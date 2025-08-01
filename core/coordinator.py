# src/core/coordinator.py

from __future__ import annotations
import threading, queue, time
from typing import Optional
from pymavlink import mavutil
from core.shared_state import armed_status

import datetime
from .settings    import Settings
from .motor       import MotorController,MotorControllerwithEthernet
from .telemetry   import TelemetryReceiver
from .logger      import DataLogger
from .measurement import MeasurementFrame
import os,sys


# Add the 'core' folder to sys.path
core_path = os.path.join(os.path.dirname(__file__), 'core')
sys.path.append(core_path)



class AppCoordinator:
    """
    Glue between GUI and backend threads with single MAVLink connection.
    """
    def __init__(self, settings: Settings):
        # single‐slot queue for the freshest MeasurementFrame
        self._frame_q: "queue.Queue[MeasurementFrame]" = queue.Queue(maxsize=1)

        # Motor controller (single connection)
        try:
            #self.motor = MotorController(settings.com_port, settings.baud)
            self.motor = MotorControllerwithEthernet(settings.stm32_ip,settings.udp_port)
            print(f"Motor controller connected on {settings.udp_port}")
        except Exception as e:
            print(f"Motor controller unavailable ({settings.udp_port}): {e}")
            print("Continuing in telemetry-only mode...")
            self.motor = None

        self.tele = TelemetryReceiver(
            bind_ip   = settings.laptop_ip,
            port      = settings.udp_port,
            dst_queue = self._frame_q
        )
        self.tele.start()
        print(f"Started UDP telemetry receiver on {settings.laptop_ip}:{settings.udp_port}")

        # throttle state for continuous mode
        self._sel_motor   = 1
        self._pwm_cached  = 1000
        self._cont_evt    = threading.Event()
        
        if self.motor:
            threading.Thread(target=self._cont_loop, daemon=True).start()

        # Armed status monitoring using motor's connection
        self.armed = False
        self._armed_lock = threading.Lock()
        
        # Start heartbeat monitoring using motor's existing connection
        if self.motor:
            self._hb_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True)
            self._hb_thread.start()

        self.logger: Optional[DataLogger] = None

    def _heartbeat_monitor(self):
        """Monitor heartbeat using motor's existing MAVLink connection"""
        # while True:
        #     try:
        #         if self.motor and self.motor.master:
        #             # Use motor's existing connection - no second connection needed
        #             msg = self.motor.master.recv_match(type="HEARTBEAT", blocking=False, timeout=0.1)
        #             if msg:
        #                 # Print raw heartbeat data for debugging
        #                 print(f"[HEARTBEAT] Raw Data:")
        #                 print(f"  Timestamp: {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        #                 print(f"  Type: {msg.type}")
        #                 print(f"  Autopilot: {msg.autopilot}")
        #                 print(f"  Base Mode: {msg.base_mode} (0b{format(msg.base_mode, '08b')})")
        #                 print(f"  Custom Mode: {msg.custom_mode}")
        #                 print(f"  System Status: {msg.system_status}")
        #                 print(f"  MAVLink Version: {msg.mavlink_version}")
                        
        #                 # Decode base mode flags
        #                 print(f"  Base Mode Flags:")
        #                 print(f"    MAV_MODE_FLAG_SAFETY_ARMED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)}")
        #                 print(f"    MAV_MODE_FLAG_MANUAL_INPUT_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_MANUAL_INPUT_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_HIL_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_HIL_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_STABILIZE_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_STABILIZE_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_GUIDED_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_GUIDED_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_AUTO_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_AUTO_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_TEST_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_TEST_ENABLED)}")
        #                 print(f"    MAV_MODE_FLAG_CUSTOM_MODE_ENABLED: {bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED)}")
                        
        #                 # Armed status extraction
        #                 new_armed = bool(msg.base_mode && mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        #                 arm_status1 = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        #                 print(f"  Extracted Armed Status: {new_armed}")
        #                 print(f"  Extracted Armed Status1: {arm_status1}")
        #                 print(f"  Extracted Armed Status2: {msg.base_mode}")

        #                 with self._armed_lock:
        #                     if new_armed != self.armed:
        #                         print(f"  *** ARMED STATUS CHANGE: {self.armed} -> {new_armed} ***")
        #                         self.armed = new_armed
        #                     else:
        #                         print(f"  Armed status unchanged: {self.armed}")
                        
        #                 print(f"  " + "="*50)
                        
        #         time.sleep(0.5)  # Slower polling to reduce interference with commands
        #     except Exception as e:
        #         print(f"Heartbeat monitoring error: {e}")
        #         time.sleep(1.0)
        return

    def get_armed_status(self) -> bool:
        """Thread-safe armed status getter"""
        with self._armed_lock:
            return self.armed

    # ------------------ Motor API ------------------

    def select_motor(self, idx: int):
        if self.motor and 1 <= idx <= 8:
            self._sel_motor = idx
            self.send_pwm_pct(0)
        else:
            print(f"Motor control unavailable - cannot select motor {idx}")

    def send_pwm_pct(self, pct: int):
        if self.motor:
            pct = max(0, min(100, pct))
            pwm = 1000 + int(pct/100*1000)
            self._pwm_cached = pwm
            self.motor.set_pwm_eth(self._sel_motor, pwm)
        else:
            print(f"Motor control unavailable - cannot send {pct}% throttle")

    def single_shot(self, pct: int, duration_ms: int):
        if self.motor:
            self.send_pwm_pct(pct)
            time.sleep(duration_ms/1000)
            self.send_pwm_pct(0)
        else:
            print(f"Motor control unavailable - cannot run single shot")

    def start_continuous(self):
        if self.motor:
            self._cont_evt.set()
            self.motor.arm()
            self.motor.set_pwm_eth(self._sel_motor, self._pwm_cached)
        else:
            print("Motor control unavailable - cannot start continuous mode")

    def stop_all(self):
        if self.motor:
            self._cont_evt.clear()
            self.motor.disarm()
            for ch in range(1,9):
                self.motor.set_pwm_eth(ch, 1000)
        else:
            print("Motor control unavailable - cannot stop motors")

    def _cont_loop(self):
        while True:
            if self._cont_evt.is_set() and self.motor:
                self.motor.set_pwm_eth(self._sel_motor, self._pwm_cached)
            time.sleep(0.1)

    # ---------------- Telemetry API ----------------

    def latest_frame(self) -> Optional[MeasurementFrame]:
        try:
            return self._frame_q.get_nowait()
        except queue.Empty:
            return None

    # ---------------- Logging API ------------------

    def start_logging(self, name_prefix: str):
        if self.logger is None:
            self.logger = DataLogger(self._frame_q, name_prefix=name_prefix)
            self.logger.start()
            print(f"[LOG] Started → {self.logger.file.name}")

    def stop_logging(self):
        if self.logger:
            self.logger.stop()
            self.logger = None

    # ---------------- Cleanup ---------------------

    def shutdown(self):
        self.stop_logging()
        self.tele.stop()
        self.stop_all()
        print("Coordinator shutdown complete")

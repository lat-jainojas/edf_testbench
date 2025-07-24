# src/core/coordinator.py

from __future__ import annotations
import threading, queue, time
from typing import Optional

from .settings    import Settings
from .motor       import MotorController
from .telemetry   import TelemetryReceiver
from .logger      import DataLogger
from .measurement import MeasurementFrame

class AppCoordinator:
    """
    Glue between GUI and backend threads (motor, UDP, logger).
    """
    def __init__(self, settings: Settings):
        # single‐slot queue for the freshest MeasurementFrame
        self._frame_q: "queue.Queue[MeasurementFrame]" = queue.Queue(maxsize=1)

        # Motor + UDP telemetry
        self.motor = MotorController(settings.com_port, settings.baud)
        self.tele  = TelemetryReceiver(
            bind_ip   = settings.stm32_ip,
            port      = settings.udp_port,
            dst_queue = self._frame_q
        )
        self.tele.start()

        # throttle state for continuous mode
        self._sel_motor   = 1
        self._pwm_cached  = 1000
        self._cont_evt    = threading.Event()
        threading.Thread(target=self._cont_loop, daemon=True).start()

        # logger (None until Record is pressed)
        self.logger: Optional[DataLogger] = None

    # ------------------ Motor API ------------------

    def select_motor(self, idx: int):
        if 1 <= idx <= 8:
            self._sel_motor = idx
            self.send_pwm_pct(0)

    def send_pwm_pct(self, pct: int):
        pct = max(0, min(100, pct))
        pwm = 1000 + int(pct/100*1000)
        self._pwm_cached = pwm
        self.motor.set_pwm(self._sel_motor, pwm)

    def single_shot(self, pct: int, duration_ms: int):
        self.send_pwm_pct(pct)
        time.sleep(duration_ms/1000)
        self.send_pwm_pct(0)

    def start_continuous(self):
        self._cont_evt.set()
        self.motor.arm()
        self.motor.set_pwm(self._sel_motor, self._pwm_cached)

    def stop_all(self):
        self._cont_evt.clear()
        self.motor.disarm()
        for ch in range(1,9):
            self.motor.set_pwm(ch, 1000)

    def _cont_loop(self):
        while True:
            if self._cont_evt.is_set():
                self.motor.set_pwm(self._sel_motor, self._pwm_cached)
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

from __future__ import annotations
import sys, time, threading, datetime as dt
from typing import List
import os,sys
import socket
import core.shared_state as globals


# Add the 'core' folder to sys.path
# core_path = os.path.join(os.path.dirname(__file__), 'core')
# sys.path.append(core_path)

# Now import the shared_state module
# import shared_state as globals
from core.shared_state import armed_status


try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None

# ─── Logging helper (from testingpix.py) ────────────────────────────────
def log(txt: str):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {txt}")

# ─── MAVLink helpers (verbatim) ─────────────────────────────────────────
def wait_heartbeat(master, timeout=10):
    log("🔌 Connecting…")
    t0 = time.time()
    while time.time() - t0 < timeout:
        hb = master.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb:
            log("✅ Heartbeat received")
            return
    sys.exit("❌ No heartbeat – check port/baud")

def wait_param_echo(master, name, target, timeout=3):
    t_end = time.time() + timeout
    while time.time() < t_end:
        m = master.recv_match(type="PARAM_VALUE", blocking=True, timeout=1)
        if not m: continue
        pid = (m.param_id.decode() 
               if isinstance(m.param_id, bytes) 
               else m.param_id)
        pid = pid.rstrip("\x00")
        if pid == name and abs(float(m.param_value) - target) < 1e-3:
            return True
    return False

def set_param(master, name, value, retries=3):
    """
    Send param_set, then if no echo do param_request_read_send + recv_match.
    """
    for r in range(1, retries+1):
        master.mav.param_set_send(master.target_system,
                                  master.target_component,
                                  name.encode(),
                                  float(value),
                                  mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        if wait_param_echo(master, name, float(value)):
            log(f"🔧 {name} → {value}")
            return True

        # fallback: request and read
        master.mav.param_request_read_send(master.target_system,
                                           master.target_component,
                                           name.encode(), -1)
        rep = master.recv_match(type="PARAM_VALUE", blocking=True, timeout=2)
        if rep:
            pid = (rep.param_id.decode() 
                   if isinstance(rep.param_id, bytes) 
                   else rep.param_id)
            pid = pid.rstrip("\x00")
            if pid == name and abs(float(rep.param_value) - float(value)) < 1e-3:
                log(f"🆗 {name} already {value} (echo skipped)")
                return True

        log(f"⚠︎ {name} not updated, retry {r}/{retries}")
    log(f"🚫 skipping {name} (no echo)")
    return False

def change_mode(master, mode, timeout=5):
    mode_id = master.mode_mapping()[mode]
    master.mav.set_mode_send(master.target_system,
                             mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                             mode_id)
    t_end = time.time() + timeout
    while time.time() < t_end:
        hb = master.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb and hb.custom_mode == mode_id:
            log(f"🎮 Mode → {mode}")
            return True
    sys.exit(f"❌ Couldn't enter {mode}")

def is_armed(hb) -> bool:
    return bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

def arm_echo(master, arm_it=True, timeout=6) -> bool:
    master.mav.command_long_send(master.target_system,
                                 master.target_component,
                                 mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                                 0, 1 if arm_it else 0, 0,0,0,0,0,0)
    t_end = time.time() + timeout
    while time.time() < t_end:
        hb = master.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb and is_armed(hb) == arm_it:
            log("✅ Armed" if arm_it else "✅ Disarmed")
            return True
    return False
# ──────────────────────────────────────────────────────────────────────────

class MotorController:
    """
    Wraps pymavlink for servo‐PWM plus arming/disarming with thread-safe heartbeat monitoring.
    """

    def __init__(self, com_port: str, baud: int):
        if mavutil is None:
            raise RuntimeError("Please `pip install pymavlink`")
        self.master = mavutil.mavlink_connection(com_port, baud=baud)
        wait_heartbeat(self.master)

        log(f"[Motor] Connected @ {com_port} {baud}")
        change_mode(self.master, "MANUAL")

        # shadow list so we can echo servo values to GUI/console
        self._shadow: List[int] = [1000]*8
        
        # Thread-safe heartbeat and armed status monitoring
        self.last_heartbeat_time = time.time()
        self.is_armed_status = False
        self.last_heartbeat = None
        self._status_lock = threading.RLock()  # Add thread safety
        self._heartbeat_thread = threading.Thread(target=self._monitor_heartbeat, daemon=True)
        self._heartbeat_thread.start()

    def _monitor_heartbeat(self):
        """Continuously monitor for heartbeat messages with proper thread safety"""
        while True:
            try:
                # Use non-blocking receive with short timeout
                hb = self.master.recv_match(type="HEARTBEAT", blocking=False, timeout=0.05)
                if hb and getattr(hb, 'type', None) != 1:
                    time.sleep(1.0)  # Wait longer on error
                    continue
                if hb:
                    with self._status_lock:  # Thread-safe update
                        self.last_heartbeat_time = time.time()
                        self.last_heartbeat = hb
                        # Extract armed status from heartbeat
                        if getattr(hb, 'base_mode', None) == 81:
                            self.is_armed_status = True
                            armed_status = True
                            print(f"Arm Status:{armed_status} ")
                        else:
                            self.is_armed_status = False
                            armed_status = False
                            print(f"Arm Status:{armed_status} ")
                        #self.is_armed_status = is_armed(hb)
                        print(f"Vehicle Status: {hb}")
                        
                
                time.sleep(0.2)  # Slower polling to reduce interference (200ms)
            except Exception as e:
                log(f"Heartbeat monitoring error: {e}")
                time.sleep(1.0)  # Wait longer on error
                continue

    def is_connected(self) -> bool:
        """Check if we've received a heartbeat within the last 3 seconds"""
        with self._status_lock:
            return (time.time() - self.last_heartbeat_time) < 3.0

    def get_armed_status(self) -> bool:
        """Get the current armed status from the most recent heartbeat"""
        with self._status_lock:
            return self.is_armed_status if self.is_connected() else False

    def arm(self):
        """Arm with status verification"""
        with self._status_lock:  # Prevent status reading during arm operation
            result = arm_echo(self.master, True)
            # Give time for status to propagate
            time.sleep(0.5)
            return result

    def disarm(self):
        """Disarm with status verification"""
        with self._status_lock:  # Prevent status reading during disarm operation
            result = arm_echo(self.master, False)
            # Give time for status to propagate
            time.sleep(0.5)
            return result

    def set_pwm(self, channel: int, pwm_us: int):
        """
        Public method: updates local shadow list, prints it,
        then sends MAV_CMD_DO_SET_SERVO.
        """
        self._shadow[channel-1] = pwm_us
        print("PWM", self._shadow)

        with self._status_lock:  # Thread-safe PWM sending
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                0,
                float(channel),
                float(pwm_us),
                0,0,0,0,0)


class MotorControllerwithEthernet: 

    def __init__(self, ip: str, port: int):
        

        # shadow list so we can echo servo values to GUI/console
        self._shadow: List[int] = [1000]*8

        self.stm32_ip = ip
        self.stm32_port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._shadow = [1000]*8  # Keep shadow for debug/local cache

        self.last_heartbeat_time = time.time()
        self.is_armed_status = False
        self.last_heartbeat = None
        # self._status_lock = threading.RLock()  # Add thread safety
        # self._heartbeat_thread = threading.Thread(target=self._monitor_heartbeat, daemon=True)
        # self._heartbeat_thread.start()



    def is_connected(self) -> bool:
        # No real connection check for UDP, always true
        return True

    def get_armed_status(self) -> bool:
        return True  # Always "true", as STM32 is always ready

    def arm(self):
        pass  # NOOP for Ethernet

    def disarm(self):
        pass  # NOOP for Ethernet

    def set_pwm_eth(self,channel: int, pwm_us: int):
        """
        Updates local list, sends pwm command over ethernet. 
        """
        self._shadow[channel-1] = pwm_us
        print("PWM", self._shadow)

        pwm = min(max(pwm_us, 1000), 2000)
        data = bytearray(3)
        data[0] = channel
        data[1] = pwm & 0xFF
        data[2] = (pwm >> 8) & 0xFF
        try:
            self.sock.sendto(data, (self.stm32_ip, self.stm32_port))
        except Exception as e:
            print(f"[EthernetController] UDP Error: {e}")




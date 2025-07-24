from __future__ import annotations
import sys, time, threading, datetime as dt
from typing import List

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
    Wraps pymavlink for servo‐PWM plus arming/disarming.
    """

    # Copy your PARAMS dictionary if you still want them:
    PARAMS = {
        'ARMING_CHECK': 0,
        'BRD_SAFETY_DEFLT': 0,
        'ARSPD_USE': 0,
        'ARMING_REQUIRE': 0,
        'COMPASS_USE': 0,
        'AHRS_GPS_USE': 0,
        'RCMAP_THROTTLE': 0,
        'RC_OPTIONS': 1,
        'EK3_Enable': 0
    }

    def __init__(self, com_port: str, baud: int):
        if mavutil is None:
            raise RuntimeError("Please `pip install pymavlink`")
        self.master = mavutil.mavlink_connection(com_port, baud=baud)
        wait_heartbeat(self.master)

        log(f"[Motor] Connected @ {com_port} {baud}")

        # Optional: write parameters exactly as in your original script.
        # Comment out the loop below if your autopilot rejects these.
        log("🔧 Writing requested parameters …")
        for k, v in self.PARAMS.items():
            set_param(self.master, k, v)

        change_mode(self.master, "MANUAL")

        # shadow list so we can echo servo values to GUI/console
        self._shadow: List[int] = [1000]*8

    def arm(self):
        arm_echo(self.master, True)

    def disarm(self):
        arm_echo(self.master, False)

    def set_pwm(self, channel: int, pwm_us: int):
        """
        Public method: updates local shadow list, prints it,
        then sends MAV_CMD_DO_SET_SERVO.
        """
        self._shadow[channel-1] = pwm_us
        print("PWM", self._shadow)   # exact echo format

        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
            0,
            float(channel),
            float(pwm_us),
            0,0,0,0,0)

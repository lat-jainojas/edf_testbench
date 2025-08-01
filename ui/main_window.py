import threading, time, queue
import dearpygui.dearpygui as dpg
import os,sys

# Add the 'core' folder to sys.path
core_path = os.path.join(os.path.dirname(__file__), 'core')
sys.path.append(core_path)

# Now import the shared_state module
from core.shared_state import armed_status

from utils.gauge         import create_gauge, update_gauge
from core.coordinator    import AppCoordinator
from core.settings       import Settings
from core.logger         import DataLogger

class MainWindow:
    _GAUGES = [
        ("V_c", "Voltage (V)",   30),
        ("I_c", "Current (A)",   20),
        ("R_c", "RPM",       20000),
        ("T_c", "Temp (°C)",    120),
        ("TQ_c", "Torque (Nm)",  50),
        ("L_c", "Load (kg)",     100),
    ]
    
    # Extended plot variables to include all individual data fields
    _PLOT_VARS = [
        "Voltage", "Current", "RPM", "Temperature", "Power", "Torque", "Load",
        "Total_Thrust", "Thrust1", "Thrust2", "Thrust3", "Thrust4", "Thrust5", "Thrust6",
        "STM32_Timestamp", "Pixhawk_Timestamp","Barometer Temp","Barometer Pressure"
    ]

    def __init__(self):
        self.coord         = None
        self._pending_pct  = 0
        self.plot_ch1      = "Voltage"
        self.plot_ch2      = "Current"
        self.hist          = {k: [] for k in ["t"] + self._PLOT_VARS}
        self._t0           = time.time()
        self.is_recording  = False
        self.data_logger   = None
        self.plot_series1  = None
        self.plot_series2  = None

        # Connection status tracking
        self.udp_connected = False
        self.serial_connected = False
        self.is_armed = False  # Track armed status for change detection
        self.last_data_time = 0
        
        # Queue for DataLogger
        self.log_queue     = queue.Queue()

        dpg.create_context()
        dpg.create_viewport(title="LAT Motor GUI", width=1400, height=950)

        # ── Main Window ─────────────────────────────────────────
        with dpg.window(label="LAT Motor Dashboard", tag="main_window", width=1400, height=950):
            with dpg.group(horizontal=True):

                # ---- LEFT PANEL ----
                with dpg.child_window(width=350, autosize_y=True):
                    dpg.add_text("Connection", bullet=True)
                    with dpg.group(horizontal=True):
                        self.com_tag  = dpg.add_input_text(label="COM Port", default_value="COM5", width=160)
                        self.baud_tag = dpg.add_input_int (label="Baud",     default_value=115200, width=160)
                    with dpg.group(horizontal=True):
                        self.ip_tag   = dpg.add_input_text(label="Laptop IP", default_value="192.168.144.100", width=160)
                        self.port_tag = dpg.add_input_int (label="UDP Port", default_value=5005,    width=160)
                    dpg.add_button(label="Connect",    callback=self._on_connect,    width=330)
                    dpg.add_button(label="Disconnect", callback=self._on_disconnect, width=330)
                    
                    # Connection Status Indicators
                    dpg.add_separator()
                    dpg.add_text("Connection Status", bullet=True)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="● UDP", tag="udp_status_btn", width=160, enabled=False)
                        dpg.add_button(label="● Serial", tag="serial_status_btn", width=160, enabled=False)

                    # Armed Status Indicator
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="● Armed Status", tag="armed_status_btn", width=330, enabled=False)

                    dpg.add_separator()

                    # Motor Controls
                    dpg.add_text("Motor Controls", bullet=True)
                    with dpg.group(horizontal=True):
                        for i in range(1,9):
                            dpg.add_button(label=f"M{i}", width=38,
                                           callback=self._on_motor, user_data=i)
                    dpg.add_separator()

                    dpg.add_button(label="Record", tag="record_button",
                                   callback=self._on_record,
                                   width=330)

                    # Throttle slider
                    dpg.add_slider_int(tag="thr_slider", label="Throttle (%)",
                                       min_value=0, max_value=100, width=330,
                                       callback=lambda s,a,u: self._cache_pct(a))
                    with dpg.group(horizontal=True):
                        dpg.add_input_int(tag="duration_box", label="Duration (ms)",
                                          default_value=500, width=200, min_value=100, step=100)
                        dpg.add_button(label="+100ms", width=60,
                                       callback=lambda:
                                           dpg.set_value("duration_box",
                                                         dpg.get_value("duration_box")+100))
                        dpg.add_button(label="-100ms", width=60,
                                       callback=lambda:
                                           dpg.set_value("duration_box",
                                                         max(100,
                                                             dpg.get_value("duration_box")-100)))
                    dpg.add_separator()

                    # Single Command
                    dpg.add_button(label="Single Command",
                                   callback=self._on_single,
                                   width=330)
                    # Continuous Command
                    dpg.add_button(label="Continuous Command",
                                   callback=self._on_continuous,
                                   width=330)
                    # Arm/Disarm Controls
                    dpg.add_button(label="Arm", callback=self._on_arm, width=330)
                    dpg.add_button(label="Disarm", callback=self._on_disarm, width=330)
                    # Melody Control - Add this new button
                    #dpg.add_button(label="🎵 Play Happy Birthday", callback=self._on_play_melody, width=330)
                    dpg.add_button(label="STOP", tag ="stop_button",callback=self._on_stop,width=330)
                    dpg.add_separator()

                    # Logging Controls
                    # dpg.add_button(label="Record", tag="record_button",
                    #                callback=self._on_record,
                    #                width=330)
                    dpg.add_button(label="Pause", tag="pause_button",
                                   callback=self._on_pause, width=330)
                    dpg.add_text("● Recording", tag="record_status",
                                 color=(255,0,0), show=False)
                    dpg.add_separator()

                    # Extended Status readouts - All UDP struct variables
                    dpg.add_text("System Data", bullet=True)
                    for tag, text in [
                        # Timestamps
                        ("stm32_timestamp_text",   "STM32 Time: 0.000 s"),
                        ("pixhawk_timestamp_text", "Pixhawk Time: 0.000 s"),
                        # Main sensors
                        ("voltage_text",     "Voltage: 0.00 V"),
                        ("current_text",     "Current: 0.00 A"),
                        ("rpm_text",         "RPM: 0"),
                        ("temperature_text", "Temp: 0.0 °C"),
                        ("power_text",       "Power: 0.00 W"),
                        ("torque_text",      "Torque: 0.00 Nm"),
                        ("load_text",        "Load: 0.00 kg"),
                        ("baro_t_text", "Baro Temp: 0.00 C"),
                        ("baro_p_text", "baro Pressure: 0 hPa"),
                        ("throttle_text",    "Throttle: 0%")
                    ]:
                        dpg.add_text(tag=tag, default_value=text)
                    
                    dpg.add_separator()
                    
                    # Individual Thrust readings
                    dpg.add_text("Thrust Data", bullet=True)
                    for tag, text in [
                        ("total_thrust_text", "Total Thrust: 0.00"),
                        ("thrust1_text",      "Thrust 1: 0.00"),
                        ("thrust2_text",      "Thrust 2: 0.00"),
                        ("thrust3_text",      "Thrust 3: 0.00"),
                        ("thrust4_text",      "Thrust 4: 0.00"),
                        ("thrust5_text",      "Thrust 5: 0.00"),
                        ("thrust6_text",      "Thrust 6: 0.00")
                    ]:
                        dpg.add_text(tag=tag, default_value=text)

                # ---- RIGHT PANEL ----
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    # Gauges
                    with dpg.group(horizontal=True):
                        for tag, lbl, rng in self._GAUGES:
                            create_gauge(tag, lbl, rng)

                    # First live plot
                    dpg.add_combo(self._PLOT_VARS, label="Plot #1",
                                  default_value=self.plot_ch1,
                                  callback=lambda s,a,u: setattr(self, "plot_ch1", a))
                    with dpg.plot(label="Live Plot #1", height=300, width=-1):
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="x_axis1")
                        with dpg.plot_axis(dpg.mvYAxis, label="Value", tag="y_axis1"):
                            self.plot_series1 = dpg.add_line_series([], [], tag="plot_series1")

                    dpg.add_separator()

                    # Plot #2
                    dpg.add_combo(self._PLOT_VARS, label="Plot #2",
                                  default_value=self.plot_ch2,
                                  callback=lambda s,a,u: setattr(self, "plot_ch2", a))
                    with dpg.plot(label="Live Plot #2", height=300, width=-1):
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="x_axis2")
                        with dpg.plot_axis(dpg.mvYAxis, label="Value", tag="y_axis2"):
                            self.plot_series2 = dpg.add_line_series([], [], tag="plot_series2")

        # Popup for log prefix
        with dpg.window(label="Log Filename Prefix",
                        modal=True, show=False,
                        tag="log_popup", width=300, height=120):
            dpg.add_text("Enter prefix:")
            self.logname_tag = dpg.add_input_text(tag="log_name_input", width=260)
            dpg.add_button(label="Start Recording",
                           callback=self._on_start_logging, width=260)
            dpg.add_button(label="Cancel",
                           callback=lambda: dpg.hide_item("log_popup"),
                           width=260)

        # Create themes for line colors
        with dpg.theme() as self.red_theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, (255, 0, 0, 255))

        with dpg.theme() as self.blue_theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 100, 255, 255))

        # Connection status themes
        with dpg.theme() as self.green_status_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 150, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 180, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))

        with dpg.theme() as self.red_status_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 0, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (180, 0, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))

        with dpg.theme() as self.gray_status_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (100, 100, 100, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (120, 120, 120, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 200, 200, 255))

        # Armed status theme (orange for armed, blue for disarmed)
        with dpg.theme() as self.armed_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (255, 140, 0, 255))  # Orange
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (255, 165, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))

        with dpg.theme() as self.disarmed_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 100, 200, 255))  # Blue
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 120, 220, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))

        # Apply default themes to status buttons
        dpg.bind_item_theme("udp_status_btn", self.gray_status_theme)
        dpg.bind_item_theme("serial_status_btn", self.gray_status_theme)
        dpg.bind_item_theme("armed_status_btn", self.gray_status_theme)

        # Apply blue theme by default to both line series
        dpg.bind_item_theme(self.plot_series1, self.blue_theme)
        dpg.bind_item_theme(self.plot_series2, self.blue_theme)

        dpg.setup_dearpygui()
        dpg.show_viewport()
        threading.Thread(target=self._updater, daemon=True).start()
        dpg.set_primary_window("main_window", True)
        dpg.start_dearpygui()
        dpg.destroy_context()

    def _update_connection_status(self):
        """Update the visual connection status indicators"""
        # Check UDP connection status
        if self.coord and self.coord.tele:
            current_time = time.time()
            if current_time - self.last_data_time < 2.0:
                self.udp_connected = True
            else:
                self.udp_connected = False
        else:
            self.udp_connected = False
        
        # Check Serial/Motor connection status
        if self.coord and self.coord.motor:
            self.serial_connected = self.coord.motor.is_connected()
            time_since_heartbeat = time.time() - self.coord.motor.last_heartbeat_time
        else:
            self.serial_connected = False
            time_since_heartbeat = float('inf')
        
        # Update UDP status button
        if self.udp_connected:
            dpg.set_item_label("udp_status_btn", "● UDP Connected")
            dpg.bind_item_theme("udp_status_btn", self.green_status_theme)
        else:
            dpg.set_item_label("udp_status_btn", "● UDP Disconnected")
            dpg.bind_item_theme("udp_status_btn", self.red_status_theme)
        
        # Update Serial status button
        if self.serial_connected:
            dpg.set_item_label("serial_status_btn", f"● Serial Connected ({time_since_heartbeat:.1f}s)")
            dpg.bind_item_theme("serial_status_btn", self.green_status_theme)
        else:
            if time_since_heartbeat == float('inf'):
                dpg.set_item_label("serial_status_btn", "● Serial Disconnected")
            else:
                dpg.set_item_label("serial_status_btn", f"● Serial Lost ({time_since_heartbeat:.1f}s ago)")
            dpg.bind_item_theme("serial_status_btn", self.red_status_theme)

    def _do_if(self, fn):
        if self.coord:
            fn(self.coord)


        # Note frequencies for required melody range
    NOTE_FREQ = {
        "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00,
        "A4": 440.00, "Bb4": 466.16, "B4": 493.88, "A4" : 440.00
    }

    def _freq_to_pwm(self, freq, f_min=261, f_max=784, pwm_min=1300, pwm_max=1600):
        """Linear mapping from frequency to PWM value"""
        freq = max(min(freq, f_max), f_min)
        return int(pwm_min + (freq - f_min) / (f_max - f_min) * (pwm_max - pwm_min))

    
    def _play_happy_birthday(self):
        """Play Happy Birthday melody through PWM signals - plays twice with correct pitch progression"""
        if not self.coord or not self.coord.motor:
            print("Motor controller not available - cannot play melody")
            return
        
        print("🎵 Starting Happy Birthday melody (2x loop)...")
        
        # Corrected melody with proper third phrase high notes
        melody = [
            # Phrase 1: "Happy Birthday to You"
            ("C4", 0.3), ("C4", 0.3), ("D4#", 0.6), ("C4", 0.6), ("F4", 0.6), ("E4", 0.9),
            # Phrase 2: "Happy Birthday to You"  
            ("C4", 0.3), ("C4", 0.3), ("D4#", 0.7), ("C4", 0.6), ("G4", 0.6), ("F4", 0.9),
            # Phrase 3: "Happy Birthdayyy toooooo You" (HIGH OCTAVE)
            ("C4", 0.3), ("C4", 0.3), ("B4", 0.7), ("A4", 0.6), ("G4", 0.6), ("F4", 0.9),
            # Phrase 4: "Happy Birthday to You" (final resolution)
            ("Bb4", 0.3), ("Bb4", 0.3), ("A4", 0.6), ("F4", 0.6), ("G4", 0.6), ("F4", 1.2), ("C4", 0.6)
        ]

        # Add the higher octave note to our frequency dictionary
        extended_notes = {
             **self.NOTE_FREQ,
             "C5": 523.25,  # High C (octave above C4)
             "D4#": 311.13  # Sharper D4 as discussed
        }

        try:
            # Play the melody twice
            for loop_num in range(1, 3):
                print(f"\n🎵 Playing loop {loop_num}/2")
                
                for i, (note, duration) in enumerate(melody, 1):
                    freq = extended_notes[note]
                    display_note = note
                    
                    pwm = self._freq_to_pwm(freq)
                    
                    print(f"Loop {loop_num} - Note {i:2d}: {display_note:4s}, Freq: {freq:6.1f} Hz, PWM: {pwm:4d} µs, Duration: {duration:.1f}s")
                    
                    # Send PWM signal to selected motor
                    self.coord.motor.set_pwm(self.coord._sel_motor, pwm)
                    time.sleep(duration)
                    
                    # Reset to rest position with short gap
                    self.coord.motor.set_pwm(self.coord._sel_motor, 1200)
                    time.sleep(0.05)
                
                # Pause between loops
                if loop_num == 1:
                    print("🎵 Brief pause between loops...")
                    time.sleep(0.5)
                    
            print("🎵 Happy Birthday melody complete (2x)!")
            
        except Exception as e:
            print(f"Error playing melody: {e}")
            # Ensure motor is reset
            if self.coord and self.coord.motor:
                self.coord.motor.set_pwm(self.coord._sel_motor, 1200)



    def _on_play_melody(self):
        """Handle melody button press"""
        if not self.coord:
            print("No coordinator available")
            return
        
        if not self.coord.motor:
            print("Motor controller not available - cannot play melody")
            return
        
        # Run melody in separate thread to avoid blocking GUI
        threading.Thread(target=self._play_happy_birthday, daemon=True).start()


    def _on_connect(self):
        s = Settings(
            com_port  = dpg.get_value(self.com_tag),
            baud      = int(dpg.get_value(self.baud_tag)),
            laptop_ip  = dpg.get_value(self.ip_tag),
            udp_port  = int(dpg.get_value(self.port_tag)),
        )
        s.save()
        
        try:
            self.coord = AppCoordinator(s)
            
            # Check connection status after initialization
            self._update_connection_status()
        except Exception as e:
            print(f"Connection failed: {e}")
            self._update_connection_status()

    def _on_arm(self):
        """Handle arm button press - uses motor.py arm() method"""
        if not self.coord:
            print("No coordinator available")
            return
        
        if not self.coord.motor:
            print("Motor controller not available - cannot arm")
            return
        
        try:
            print("Sending arm command...")
            self.coord.motor.arm()  # This calls your motor.py arm_echo() function
        except Exception as e:
            print(f"Failed to arm: {e}")

    def _on_disarm(self):
        """Handle disarm button press - uses motor.py disarm() method"""
        if not self.coord:
            print("No coordinator available") 
            return
            
        if not self.coord.motor:
            print("Motor controller not available - cannot disarm")
            return
        
        try:
            print("Sending disarm command...")
            self.coord.motor.disarm()  # This calls your motor.py arm_echo() function
        except Exception as e:
            print(f"Failed to disarm: {e}")

    def _on_stop(self):
        if self.coord:
            self.coord.stop_all()
        dpg.set_value("thr_slider", 0)

    def _on_disconnect(self):
        if self.coord:
            self.coord.shutdown()
            self.coord = None
            dpg.hide_item("record_status")
            dpg.enable_item("record_button")
            dpg.bind_item_theme(self.plot_series1, self.blue_theme)
            dpg.bind_item_theme(self.plot_series2, self.blue_theme)
        
        # Update connection status to disconnected
        self.udp_connected = False
        self.serial_connected = False
        self.is_armed = False  # Reset armed status
        self._update_connection_status()

    def _on_motor(self, sender, app_data, user_data):
        if self.coord:
            self.coord.stop_all()
            self.coord.select_motor(user_data)
        dpg.set_value("thr_slider", 0)

    def _cache_pct(self, pct: int):
        self._pending_pct = pct
        if self.coord and self.coord._cont_evt.is_set():
            self.coord.send_pwm_pct(pct)

    def _on_single(self):
        if not self.coord:
            return
        #threading.Thread(target=self._run_throttle_pattern, daemon=True).start()
        threading.Thread(
            target=lambda: self.coord.single_shot(
                self._pending_pct,
                dpg.get_value("duration_box")
            ),
            daemon=True
        ).start()

    def _on_continuous(self, sender, app_data):
        if self.coord:
            #threading.Thread(target=self._run_throttle_pattern, daemon=True).start()
            self.coord.stop_all()
            self.coord.start_continuous()
            self.coord.send_pwm_pct(self._pending_pct)

    def _on_pause(self):
        # Stop logging and change UI
        self.is_recording = False
        if self.data_logger:
            self.data_logger.stop()
            self.data_logger = None
        dpg.hide_item("record_status")
        dpg.enable_item("record_button")
        dpg.bind_item_theme(self.plot_series1, self.blue_theme)
        dpg.bind_item_theme(self.plot_series2, self.blue_theme)

    def _run_throttle_pattern(self):
        """
        Apply the pattern: 20% for 5s, 30% for 10s, 20% for 5s
        """
        pattern = [
            (20, 5.0),   # (percent, seconds)
            (30, 10.0),
            (20, 5.0),
        ]
        for pct, dur in pattern:
            self._pending_pct = pct
            if self.coord and self.coord.motor:
                self.coord.send_pwm_pct(pct)
            time.sleep(dur)
        # Optional: Return throttle to zero after pattern
        if self.coord and self.coord.motor:
            self._pending_pct = 0
            self.coord.send_pwm_pct(0)

    def _on_record(self):
        dpg.show_item("log_popup")

    def _on_start_logging(self):
        self.is_recording = True
        prefix = dpg.get_value(self.logname_tag).strip() or "log"
        dpg.hide_item("log_popup")
        
        # Create and start DataLogger with queue
        self.data_logger = DataLogger(self.log_queue, prefix)
        self.data_logger.start()
        threading.Thread(target=self._run_throttle_pattern, daemon=True).start()
        # Change plot line color to red for recording
        dpg.bind_item_theme(self.plot_series1, self.red_theme)
        dpg.bind_item_theme(self.plot_series2, self.red_theme)

        dpg.show_item("record_status")
        dpg.disable_item("record_button")

    def _on_stop_logging(self):
        self.is_recording = False
        if self.data_logger:
            self.data_logger.stop()
            self.data_logger = None
        dpg.hide_item("record_status")
        dpg.enable_item("record_button")
        dpg.bind_item_theme(self.plot_series1, self.blue_theme)
        dpg.bind_item_theme(self.plot_series2, self.blue_theme)

    def _updater(self):
        """Main update loop - handles both UI updates AND feeds logging queue"""
        while dpg.is_dearpygui_running():
        
            if not self.coord:
                time.sleep(0.05)
                continue
            
            # Get fresh data - this should NEVER be blocked
            frame = self.coord.latest_frame()
            if frame:
                self.last_data_time = time.time()  # Update last data time  
                # Feed data to logging queue if recording (non-blocking)
                # if self.is_recording and not self.log_queue.full():
                #     try:
                #         self.log_queue.put_nowait(frame)
                #     except queue.Full:
                #         pass  # Skip if queue is full, don't block UI

                if self.is_recording and not self.log_queue.full():
                    try:
                        self.log_queue.put_nowait((frame, self._pending_pct))
                    except queue.Full:
                        pass # Skip if queue is full, don't block UI

                
                # Continue with UI updates as normal
                t = time.time() - self._t0
                self.hist["t"].append(t)
                
                # Map all UDP struct fields to plot variables
                plot_data_map = {
                    "Voltage": frame.voltage,
                    "Current": frame.current,
                    "RPM": frame.rpm,
                    "Temperature": frame.temperature,
                    "Power": frame.voltage * frame.current,
                    "Torque": frame.torque,
                    "Load": frame.load,
                    "Total_Thrust": frame.thrust,  # Property that sums all thrusters
                    "Thrust1": frame.thrust1,
                    "Thrust2": frame.thrust2,
                    "Thrust3": frame.thrust3,
                    "Thrust4": frame.thrust4,
                    "Thrust5": frame.thrust5,
                    "Thrust6": frame.thrust6,
                    "STM32_Timestamp": frame.stm32_timestamp,
                    "Pixhawk_Timestamp": frame.pixhawk_timestamp,
                    "Barometer Temp": frame.baro_t,
                    "Barometer Pressure": frame.baro_p
                }
                
                # Update history for all plot variables
                for key in self._PLOT_VARS:
                    self.hist[key].append(plot_data_map[key])
                
                # Optional: Keep reasonable amount of historical data to prevent memory issues
                # Keep last 1000 points (roughly 50 seconds at 20Hz) for history
                if len(self.hist["t"]) > 1000:
                    for k in self.hist:
                        self.hist[k] = self.hist[k][-1000:]
                
                # Update plots with scrolling 5-second X-axis window
                if len(self.hist["t"]) > 0:
                    current_time = self.hist["t"][-1]
                    window_start = current_time - 5.0  # 5-second window
                    
                    try:
                        # Plot 1: Set data and configure axes
                        dpg.set_value("plot_series1", [self.hist["t"], self.hist[self.plot_ch1]])
                        dpg.set_axis_limits("x_axis1", window_start, current_time)  # Sliding X window
                        dpg.fit_axis_data("y_axis1")  # Auto-fit Y axis to visible data
                        
                        # Plot 2: Set data and configure axes
                        dpg.set_value("plot_series2", [self.hist["t"], self.hist[self.plot_ch2]])
                        dpg.set_axis_limits("x_axis2", window_start, current_time)  # Sliding X window
                        dpg.fit_axis_data("y_axis2")  # Auto-fit Y axis to visible data
                        
                    except Exception as e:
                        print(f"Plot update error: {e}")
                
                # Update gauges (using main sensor values)
                gauge_values = [frame.voltage, frame.current, frame.rpm, frame.temperature, frame.torque, frame.load]
                for (tag,_,rng), val in zip(self._GAUGES, gauge_values):
                    update_gauge(tag, val, rng)
                    
                # Update all status text displays
                dpg.set_value("stm32_timestamp_text",   f"STM32 Time: {frame.stm32_timestamp:.3f} s")
                dpg.set_value("pixhawk_timestamp_text", f"Pixhawk Time: {frame.pixhawk_timestamp:.3f} s")
                dpg.set_value("voltage_text",     f"Voltage: {frame.voltage:.2f} V")
                dpg.set_value("current_text",     f"Current: {frame.current:.2f} A")
                dpg.set_value("rpm_text",         f"RPM: {frame.rpm}")
                dpg.set_value("temperature_text", f"Temp: {frame.temperature:.1f} °C")
                dpg.set_value("power_text",       f"Power: {frame.voltage * frame.current:.2f} W")
                dpg.set_value("torque_text",      f"Torque: {frame.torque:.2f} Nm")
                dpg.set_value("load_text",        f"Load: {frame.load:.2f} kg")
                dpg.set_value("total_thrust_text", f"Total Thrust: {frame.thrust:.2f}")
                dpg.set_value("thrust1_text",     f"Thrust 1: {frame.thrust1:.2f}")
                dpg.set_value("thrust2_text",     f"Thrust 2: {frame.thrust2:.2f}")
                dpg.set_value("thrust3_text",     f"Thrust 3: {frame.thrust3:.2f}")
                dpg.set_value("thrust4_text",     f"Thrust 4: {frame.thrust4:.2f}")
                dpg.set_value("thrust5_text",     f"Thrust 5: {frame.thrust5:.2f}")
                dpg.set_value("thrust6_text",     f"Thrust 6: {frame.thrust6:.2f}")
                dpg.set_value("baro_t_text", f"Baro Temp: {frame.baro_t:.2f} C")
                dpg.set_value("baro_p_text", f"Baro Pressure: {frame.baro_p:.2f} hPa")
                
                pct = int((self.coord._pwm_cached - 1000) / 10)
                dpg.set_value("throttle_text",    f"Throttle: {pct}%")
            
            # Update arm status button based on coordinator's armed state


            # Update arm status button based on coordinator's armed state
            if self.coord and hasattr(self.coord, 'armed') and self.coord.motor:
                armed = self.coord.armed
                armed = armed_status
                #print(f"Armed status mainwindows: {armed_status}")
                if armed != self.is_armed:
                    self.is_armed = armed
                    if self.serial_connected:
                        if armed:
                            dpg.set_item_label("armed_status_btn", "● ARMED")
                            dpg.bind_item_theme("armed_status_btn", self.armed_theme)
                        else:
                            dpg.set_item_label("armed_status_btn", "● DISARMED")
                            dpg.bind_item_theme("armed_status_btn", self.disarmed_theme)
                    else:
                        dpg.set_item_label("armed_status_btn", "● Unknown Status")
                        dpg.bind_item_theme("armed_status_btn", self.gray_status_theme)
            elif self.coord and not self.coord.motor:
                # No motor controller available
                dpg.set_item_label("armed_status_btn", "● No Motor Controller")
                dpg.bind_item_theme("armed_status_btn", self.gray_status_theme)

            
            self._update_connection_status()
            
            time.sleep(0.05)

if __name__ == "__main__":
    MainWindow()

import threading, time
import dearpygui.dearpygui as dpg
from utils.gauge      import create_gauge, update_gauge
from core.coordinator import AppCoordinator
from core.settings    import Settings

class MainWindow:
    _GAUGES    = [
        ("V_c","Voltage (V)",   30),
        ("I_c","Current (A)",   20),
        ("R_c","RPM",       20000),
        ("T_c","Temp (°C)",    120),
    ]
    _PLOT_VARS = ["Voltage","Current","RPM","Thrust","Temperature","Power"]

    def __init__(self):
        self.coord         = None
        self._pending_pct  = 0
        self.plot_ch1      = "Voltage"
        self.plot_ch2      = "Current"
        self.hist          = {k: [] for k in ["t"] + self._PLOT_VARS}
        self._t0           = time.time()

        dpg.create_context()
        dpg.create_viewport(title="LAT Motor GUI", width=1400, height=850)

        with dpg.window(label="LAT Motor Dashboard",
                        tag="main_window", width=1400, height=850):
            with dpg.group(horizontal=True):

                # ---- LEFT PANEL ----
                with dpg.child_window(width=350, autosize_y=True):
                    # Connection
                    dpg.add_text("Connection", bullet=True)
                    with dpg.group(horizontal=True):
                        self.com_tag  = dpg.add_input_text(label="COM Port", default_value="COM9", width=160)
                        self.baud_tag = dpg.add_input_int (label="Baud",     default_value=115200, width=160)
                    with dpg.group(horizontal=True):
                        self.ip_tag   = dpg.add_input_text(label="STM32 IP", default_value="0.0.0.0", width=160)
                        self.port_tag = dpg.add_input_int (label="UDP Port", default_value=9000,    width=160)
                    dpg.add_button(label="Connect",    callback=self._on_connect,    width=330)
                    dpg.add_button(label="Disconnect", callback=self._on_disconnect, width=330)
                    dpg.add_separator()

                    # Motor Controls
                    dpg.add_text("Motor Controls", bullet=True)
                    with dpg.group(horizontal=True):
                        for i in range(1,9):
                            dpg.add_button(label=f"M{i}", width=38,
                                           callback=self._on_motor, user_data=i)
                    dpg.add_separator()

                    # Throttle slider (pending only)
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

                    # Single Command uses a background thread
                    dpg.add_button(label="Single Command",
                                   callback=self._on_single,
                                   width=330)
                    # Continuous Command
                    dpg.add_button(label="Continuous Command",
                                   callback=self._on_continuous,
                                   width=330)
                    # Disarm / Stop
                    dpg.add_button(label="Disarm / Stop",
                                   callback=lambda: self._do_if(lambda c: c.stop_all()),
                                   width=330)
                    dpg.add_separator()

                    # Logging Controls
                    dpg.add_button(label="Record", tag="record_button",
                                   callback=lambda: dpg.show_item("log_popup"),
                                   width=330)
                    dpg.add_button(label="Pause",  tag="pause_button",
                                   callback=self._on_pause, width=330)
                    dpg.add_text("● Recording", tag="record_status",
                                 color=(255,0,0), show=False)
                    dpg.add_separator()

                    # Status readouts
                    for tag, text in [
                        ("voltage_text",     "Voltage: 0.00 V"),
                        ("current_text",     "Current: 0.00 A"),
                        ("rpm_text",         "RPM: 0"),
                        ("thrust_text",      "Thrust: 0"),
                        ("temperature_text", "Temp: 0.0 °C"),
                        ("power_text",       "Power: 0.00 W"),
                        ("throttle_text",    "Throttle: 0%")
                    ]:
                        dpg.add_text(tag=tag, default_value=text)

                # ---- RIGHT PANEL ----
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    # Gauges
                    with dpg.group(horizontal=True):
                        for tag, lbl, rng in self._GAUGES:
                            create_gauge(tag, lbl, rng)

                    # Plot #1
                    dpg.add_combo(self._PLOT_VARS, label="Plot #1",
                                  default_value=self.plot_ch1,
                                  callback=lambda s,a,u: setattr(self, "plot_ch1", a))
                    with dpg.plot(label="Live Plot #1", height=300, width=-1):
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="x_axis1")
                        with dpg.plot_axis(dpg.mvYAxis, label="Value", tag="y_axis1"):
                            dpg.add_line_series([], [], tag="plot_series1")

                    dpg.add_separator()

                    # Plot #2
                    dpg.add_combo(self._PLOT_VARS, label="Plot #2",
                                  default_value=self.plot_ch2,
                                  callback=lambda s,a,u: setattr(self, "plot_ch2", a))
                    with dpg.plot(label="Live Plot #2", height=300, width=-1):
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)", tag="x_axis2")
                        with dpg.plot_axis(dpg.mvYAxis, label="Value", tag="y_axis2"):
                            dpg.add_line_series([], [], tag="plot_series2")

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

        dpg.setup_dearpygui()
        dpg.show_viewport()
        threading.Thread(target=self._updater, daemon=True).start()
        dpg.set_primary_window("main_window", True)
        dpg.start_dearpygui()
        dpg.destroy_context()

    def _do_if(self, fn):
        if self.coord:
            fn(self.coord)

    def _on_connect(self):
        s = Settings(
            com_port = dpg.get_value(self.com_tag),
            baud     = int(dpg.get_value(self.baud_tag)),
            stm32_ip = dpg.get_value(self.ip_tag),
            udp_port = int(dpg.get_value(self.port_tag)),
        )
        s.save()
        self.coord = AppCoordinator(s)

    def _on_disconnect(self):
        if self.coord:
            self.coord.shutdown()
            self.coord = None
            dpg.hide_item("record_status")
            dpg.enable_item("record_button")

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
        # reset and arm/disarm handled in coordinator.single_shot
        threading.Thread(
            target=lambda: self.coord.single_shot(
                self._pending_pct,
                dpg.get_value("duration_box")
            ),
            daemon=True
        ).start()

    def _on_continuous(self, sender, app_data):
        if self.coord:
            self.coord.stop_all()
            self.coord.start_continuous()
            self.coord.send_pwm_pct(self._pending_pct)

    def _on_pause(self):
        self._do_if(lambda c: c.stop_logging())
        dpg.hide_item("record_status")
        dpg.enable_item("record_button")

    def _on_start_logging(self):
        prefix = dpg.get_value(self.logname_tag).strip() or "log"
        dpg.hide_item("log_popup")
        self._do_if(lambda c: c.start_logging(prefix))
        dpg.show_item("record_status")
        dpg.disable_item("record_button")

    def _updater(self):
        while dpg.is_dearpygui_running():
            if not self.coord:
                time.sleep(0.1)
                continue
            frame = self.coord.latest_frame()
            if frame:
                t = time.time() - self._t0
                self.hist["t"].append(t)
                for key in self._PLOT_VARS:
                    val = (frame.voltage * frame.current) if key == "Power" else getattr(frame, key.lower())
                    self.hist[key].append(val)
                if len(self.hist["t"]) > 200:
                    for k in self.hist:
                        self.hist[k] = self.hist[k][-200:]
                dpg.set_value("plot_series1", [self.hist["t"], self.hist[self.plot_ch1]])
                dpg.fit_axis_data("x_axis1"); dpg.fit_axis_data("y_axis1")
                dpg.set_value("plot_series2", [self.hist["t"], self.hist[self.plot_ch2]])
                dpg.fit_axis_data("x_axis2"); dpg.fit_axis_data("y_axis2")
                for (tag,_,rng), val in zip(self._GAUGES,
                                            [frame.voltage, frame.current,
                                             frame.rpm,     frame.temperature]):
                    update_gauge(tag, val, rng)
                dpg.set_value("voltage_text",     f"Voltage: {frame.voltage:.2f} V")
                dpg.set_value("current_text",     f"Current: {frame.current:.2f} A")
                dpg.set_value("rpm_text",         f"RPM: {frame.rpm}")
                dpg.set_value("thrust_text",      f"Thrust: {frame.thrust}")
                dpg.set_value("temperature_text", f"Temp: {frame.temperature:.1f} °C")
                dpg.set_value("power_text",       f"Power: {frame.voltage * frame.current:.2f} W")
                pct = int((self.coord._pwm_cached - 1000) / 10)
                dpg.set_value("throttle_text",    f"Throttle: {pct}%")
            time.sleep(0.1)

if __name__ == "__main__":
    MainWindow()

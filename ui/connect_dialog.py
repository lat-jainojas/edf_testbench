import dearpygui.dearpygui as dpg
from core.settings import Settings


def show_connect_dialog(on_connect):
    """
    Pops modal; on *Connect* builds Settings, closes itself, then
    calls `on_connect(settings)`.
    """
    with dpg.window(label="Connect",
                    tag="connect_win",             # ⬅️  tag we can delete
                    modal=True, no_close=True,
                    width=300, height=220):

        comm  = dpg.add_input_text(label="COM",  default_value="COM9")
        baud  = dpg.add_input_int (label="Baud", default_value=115200,
                                   min_value=9600, max_value=921600)
        ip    = dpg.add_input_text(label="STM32 IP", default_value="0.0.0.0")
        port  = dpg.add_input_int (label="UDP Port", default_value=9000)

        def _ok():
            settings = Settings(
                com_port=dpg.get_value(comm),
                baud     =dpg.get_value(baud),
                stm32_ip =dpg.get_value(ip),
                udp_port =dpg.get_value(port))
            settings.save()

            dpg.delete_item("connect_win")   # ✅ close the modal
            on_connect(settings)             # 🔄 launch main window

        dpg.add_button(label="Connect", width=280, callback=_ok)

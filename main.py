import dearpygui.dearpygui as dpg
from ui.connect_dialog import show_connect_dialog
from ui.main_window   import MainWindow
from core.coordinator import AppCoordinator

def _boot(settings):
    MainWindow(AppCoordinator(settings))

def main():
    dpg.create_context()
    dpg.create_viewport(title="LAT Motor GUI", width=1300, height=860)
    show_connect_dialog(_boot)
    dpg.setup_dearpygui(); dpg.show_viewport()
    dpg.start_dearpygui(); dpg.destroy_context()

if __name__ == "__main__":
    MainWindow()

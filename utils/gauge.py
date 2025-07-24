import math, dearpygui.dearpygui as dpg

def create_gauge(tag: str, label: str, max_val: float):
    """
    Call once. Creates an empty drawlist with the given tag.
    """
    with dpg.drawlist(width=180, height=180, tag=tag):
        # draw static bezel + label once
        dpg.draw_circle((90, 90), 80, color=(80, 80, 80, 255), thickness=6)
        dpg.draw_text((60, 155), label, size=14, color=(200, 200, 200))

def update_gauge(tag: str, value: float, max_val: float):
    """
    Redraw the *needle* and numeric value. Never recreates the drawlist.
    """
    if not dpg.does_item_exist(tag):
        return                       # safeguard
    dpg.delete_item(tag, children_only=True)   # keep the drawlist itself

    # redraw static bezel
    dpg.draw_circle((90, 90), 80, color=(80, 80, 80, 255), thickness=6,
                    parent=tag)

    # needle
    pct   = max(0.0, min(1.0, value / max_val))
    angle = -0.75 * math.pi + 1.5 * math.pi * pct
    x = 90 + 70 * math.cos(angle)
    y = 90 + 70 * math.sin(angle)
    dpg.draw_line((90, 90), (x, y), color=(0, 255, 0), thickness=4,
                  parent=tag)

    # numeric text
    dpg.draw_text((70, 75), f"{value:.1f}", size=16, color=(255, 255, 255),
                  parent=tag)

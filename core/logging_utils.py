import datetime as _dt
def log(msg: str) -> None:
    """CLI log with timestamp & emoji."""
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# logger.py
from __future__ import annotations
import csv, time, datetime, pathlib, threading, queue
from .measurement import MeasurementFrame
from .logging_utils import log  # You already have this helper to log with timestamps

class DataLogger(threading.Thread):
    """
    CSV logger: start on demand, stop on demand.
    Filename = <name_prefix>_<YYYYMMDD_HHMMSS>.csv
    """
    def __init__(self,
                 in_q: "queue.Queue[MeasurementFrame]",
                 name_prefix: str,
                 folder: str | pathlib.Path = "logs"):
        super().__init__(daemon=True)
        self.q = in_q
        self.stop_evt = threading.Event()
        self.folder = pathlib.Path(folder)
        self.folder.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c for c in name_prefix if c.isalnum() or c in "-_")
        self.file = self.folder / f"{safe}_{ts}.csv"

    def run(self):
        with self.file.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_wall"] +
                            list(MeasurementFrame.__dataclass_fields__.keys()))
            while not self.stop_evt.is_set():
                try:
                    frame: MeasurementFrame = self.q.get(timeout=0.5)
                    writer.writerow([time.time(), *frame.to_tuple()])
                except queue.Empty:
                    continue

    def stop(self):
        """Stop the logger and save the file."""
        self.stop_evt.set()
        self.join()
        log(f"[LOG] Saved → {self.file.resolve()}")

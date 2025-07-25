# src/core/telemetry.py

from __future__ import annotations
import socket
import struct
import threading
import queue
from .measurement import MeasurementFrame

class TelemetryReceiver(threading.Thread):
    """
    Listens for UDP datagrams of exactly 14 float32 (56 bytes) and
    publishes the latest MeasurementFrame to a size-1 queue.
    """

    def __init__(self,
                 bind_ip: str,
                 port: int,
                 dst_queue: "queue.Queue[MeasurementFrame]"):
        """
        bind_ip   – local IP to bind; "" means all interfaces
        port      – UDP port to bind to
        dst_queue – queue where new frames will be posted (maxsize=1)
        """
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, port))

        self.q    = dst_queue
        self._fmt = MeasurementFrame._FORMAT
        self._exp = struct.calcsize(self._fmt)  # Should be 56 bytes
        self._stop = threading.Event()
        
        print(f"TelemetryReceiver: Expecting {self._exp} bytes per packet")

    def run(self):
        while not self._stop.is_set():
            try:
                pkt, addr = self.sock.recvfrom(self._exp)
            except OSError:
                break
            
            if len(pkt) != self._exp:
                print(f"Unexpected packet size: {len(pkt)} bytes. Expected {self._exp} bytes.")
                continue
                
            try:
                frame = MeasurementFrame.from_bytes(pkt)
            except ValueError as e:
                print(f"Error parsing frame: {e}")
                continue

            try:
                self.q.put_nowait(frame)
            except queue.Full:
                self.q.get_nowait()
                self.q.put_nowait(frame)

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

from __future__ import annotations
from dataclasses import dataclass, asdict
import json, pathlib

__all__ = ["Settings"]
_CFG = pathlib.Path.home() / ".lat_motor_gui.json"


@dataclass
class Settings:
    com_port:  str = ""
    baud:      int = 115200
    stm32_ip:  str = "0.0.0.0"      # bind addr for UDP recv
    udp_port:  int = 9000

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> "Settings":
        p = path or _CFG
        if p.exists():
            try:
                return cls(**json.loads(p.read_text()))
            except Exception:
                pass
        return cls()

    def save(self, path: pathlib.Path | None = None) -> None:
        (path or _CFG).write_text(json.dumps(asdict(self), indent=2))

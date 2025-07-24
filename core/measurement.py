from __future__ import annotations
from dataclasses import dataclass
import struct
from typing import ClassVar, Tuple, List

__all__ = ["MeasurementFrame"]


@dataclass(frozen=True, slots=True)
class MeasurementFrame:
    time_stm32:  float
    time_px4:    float
    time_gps:    float
    load1:       float
    load2:       float
    load3:       float
    load4:       float
    load5:       float
    load6:       float
    thrust:      float
    torque:      float
    voltage:     float
    current:     float
    rpm:         float
    temperature: float

    _FORMAT: ClassVar[str] = "<15f"             # little-endian

    @classmethod
    def from_bytes(cls, payload: bytes) -> "MeasurementFrame":
        exp = struct.calcsize(cls._FORMAT)
        if len(payload) != exp:
            raise ValueError(f"Need {exp} B, got {len(payload)} B")
        return cls(*struct.unpack(cls._FORMAT, payload))

    def to_bytes(self) -> bytes:
        return struct.pack(self._FORMAT, *self.to_tuple())

    # helpers
    def to_tuple(self) -> Tuple[float, ...]:
        return tuple(getattr(self, f.name) for f in self.__dataclass_fields__.values())

    def to_csv_row(self) -> List[str]:
        return [f"{v:.6f}" for v in self.to_tuple()]

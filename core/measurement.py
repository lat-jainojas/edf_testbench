from __future__ import annotations
from dataclasses import dataclass
import struct
from typing import ClassVar, Tuple, List

__all__ = ["MeasurementFrame"]

@dataclass(frozen=True, slots=True)
class MeasurementFrame:
    stm32_timestamp:  float  # STM32 Timestamp
    pixhawk_timestamp: float  # Pixhawk Timestamp  
    thrust1:         float   # Thrust 1
    thrust2:         float   # Thrust 2
    thrust3:         float   # Thrust 3
    thrust4:         float   # Thrust 4
    thrust5:         float   # Thrust 5
    thrust6:         float   # Thrust 6
    voltage:         float   # Voltage
    current:         float   # Current
    rpm:             float   # RPM
    temperature:     float   # Temperature
    torque:          float   # Torque
    load:            float   # Load

    _FORMAT: ClassVar[str] = "<14f"  # little-endian, 14 floats = 56 bytes

    # Combined thrust property for compatibility with existing GUI code
    @property
    def thrust(self) -> float:
        """Total thrust from all 6 thrusters"""
        return self.thrust1 + self.thrust2 + self.thrust3 + self.thrust4 + self.thrust5 + self.thrust6

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

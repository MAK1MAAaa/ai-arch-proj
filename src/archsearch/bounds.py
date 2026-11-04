"""Validated WGS84 browsing rectangles, including the antimeridian."""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BBox = tuple[float, float, float, float]
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class SpatialBounds(BaseModel):
    """A closed rectangle; west greater than east crosses the date line."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @field_validator("*", mode="before")
    @classmethod
    def reject_boolean(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("bbox坐标必须为有限数字。")
        return value

    @model_validator(mode="after")
    def validate_extent(self) -> SpatialBounds:
        if self.south >= self.north:
            raise ValueError("bbox南界必须小于北界。")
        if self.west == self.east or (self.west == 180 and self.east == -180):
            raise ValueError("bbox不能为零宽；全球经度范围请使用-180至180。")
        return self

    @classmethod
    def from_csv(cls, value: str) -> SpatialBounds:
        if not isinstance(value, str) or not 1 <= len(value) <= 200:
            raise ValueError("bbox应为west,south,east,north四个WGS84坐标。")
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4 or any(_DECIMAL.fullmatch(part) is None for part in parts):
            raise ValueError("bbox应为west,south,east,north四个十进制坐标。")
        return cls(west=float(parts[0]), south=float(parts[1]),
                   east=float(parts[2]), north=float(parts[3]))

    def as_tuple(self) -> BBox:
        return self.west, self.south, self.east, self.north

    def contains(self, point: tuple[float, float]) -> bool:
        longitude, latitude = point
        if (
            not math.isfinite(longitude) or not math.isfinite(latitude)
            or not -180 <= longitude <= 180 or not -90 <= latitude <= 90
        ):
            return False
        if not self.south <= latitude <= self.north:
            return False
        longitudes = (-180.0, 180.0) if longitude in {-180, 180} else (longitude,)
        if self.west <= self.east:
            return any(self.west <= value <= self.east for value in longitudes)
        return any(value >= self.west or value <= self.east for value in longitudes)

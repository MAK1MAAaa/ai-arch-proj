"""Validated, source-preserving records shared by search and HTTP interfaces."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PeriodEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: Literal["Name", "Location"]
    resource_uri: str
    period_id: str
    period_uri: str
    confidence: str | None = None
    association_certainty: str | None = None
    start: int | None = None
    end: int | None = None


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str
    details: str = ""
    names: list[str]
    types: list[str]
    periods: list[str]
    repr_point: tuple[float, float]
    location_precision: Literal["precise", "rough"] | None = None
    source_uri: str
    contributors: list[str]
    period_evidence: list[PeriodEvidence]

    @field_validator("repr_point")
    @classmethod
    def validate_coordinates(cls, point: tuple[float, float]) -> tuple[float, float]:
        longitude, latitude = point
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError("representative point is outside WGS84 coordinate bounds")
        return point

    @model_validator(mode="after")
    def validate_period_evidence(self) -> "Site":
        evidence_periods = {item.period_id for item in self.period_evidence}
        if "roman" not in evidence_periods or "roman" not in self.periods:
            raise ValueError("site must have a Roman Name or Location attestation")
        return self

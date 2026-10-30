"""Validated, source-preserving records shared by search and HTTP interfaces."""

import re
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

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


class SourceReference(BaseModel):
    """A source pointer and short evidence excerpt, not a copied source document."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    uri: str
    publisher: str
    license: str | None = None
    revision: str | None = None
    accessed: str | None = None
    excerpt: str = ""

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"} or not parts.netloc
            or parts.username is not None or parts.password is not None
        ):
            raise ValueError("source URI must be an HTTP(S) URL without credentials")
        return value


class HistoricalPhase(BaseModel):
    """A source-supported event or stage; precision controls automatic map navigation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    kind: Literal["construction", "use", "rebuild", "destruction", "other"]
    label: str = Field(min_length=1)
    start_year: int | None = None
    end_year: int | None = None
    precision: Literal["exact_year", "approximate_year", "range", "period"]
    sources: list[SourceReference] = Field(min_length=1)
    note: str = ""

    @field_validator("start_year", "end_year", mode="before")
    @classmethod
    def validate_year(cls, value: object) -> object:
        if value is not None and (type(value) is not int or value == 0):
            raise ValueError("phase years must be integers without a historical year zero")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "HistoricalPhase":
        if any(not source.excerpt.strip() for source in self.sources):
            raise ValueError("historical phases require nonempty source excerpts")
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.start_year > self.end_year
        ):
            raise ValueError("phase dates are reversed")
        if self.precision in {"exact_year", "approximate_year"} and (
            self.start_year is None or self.start_year != self.end_year
        ):
            raise ValueError("single-year precision requires matching, non-null endpoints")
        if self.precision == "range" and (self.start_year is None or self.end_year is None):
            raise ValueError("range precision requires both endpoints")
        return self


class ChronologyReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["not_reviewed", "reviewed", "insufficient"] = "not_reviewed"
    method: str = ""
    reviewed_at: str | None = None
    note: str = ""
    default_phase_id: str | None = None
    phases: list[HistoricalPhase] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_phases(self) -> "ChronologyReview":
        ids = [phase.id for phase in self.phases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate chronology phase identifiers")
        if self.default_phase_id is not None and self.default_phase_id not in ids:
            raise ValueError("default chronology phase does not exist")
        if self.status == "reviewed" and not self.phases:
            raise ValueError("reviewed chronology must contain a supported phase")
        if self.phases and self.default_phase_id is None:
            raise ValueError("chronology with phases must specify a default phase")
        if self.status == "insufficient" and self.phases:
            raise ValueError("insufficient chronology must preserve the unknown state")
        if self.status != "not_reviewed":
            if not self.method.strip() or self.reviewed_at is None:
                raise ValueError("completed chronology review must record its method and date")
            if date.fromisoformat(self.reviewed_at).isoformat() != self.reviewed_at:
                raise ValueError("review date must use ISO YYYY-MM-DD")
        return self


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
    source_kind: Literal["pleiades", "global"] = "pleiades"
    source_refs: list[SourceReference] = Field(default_factory=list)
    chronology: ChronologyReview = Field(default_factory=ChronologyReview)

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
        if self.source_kind == "pleiades" and (
            "roman" not in evidence_periods or "roman" not in self.periods
        ):
            raise ValueError("site must have a Roman Name or Location attestation")
        if self.source_kind == "global" and (
            re.fullmatch(r"wd:Q[1-9]\d*", self.id) is None or not self.source_refs
        ):
            raise ValueError("global sites require a namespaced Wikidata ID and source references")
        return self

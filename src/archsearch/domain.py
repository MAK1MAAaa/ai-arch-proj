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
        if self.status == "not_reviewed" and self.phases:
            raise ValueError("unreviewed chronology cannot trigger historical navigation")
        if self.status != "not_reviewed":
            if not self.method.strip() or self.reviewed_at is None:
                raise ValueError("completed chronology review must record its method and date")
            if date.fromisoformat(self.reviewed_at).isoformat() != self.reviewed_at:
                raise ValueError("review date must use ISO YYYY-MM-DD")
        return self


class Geography(BaseModel):
    """Modern source catalogue membership, independent of historical political boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    authority_id: str | None = None
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    source: SourceReference
    point_count: int = Field(default=1, ge=0)
    note: str = ""

    @field_validator("countries")
    @classmethod
    def validate_countries(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            re.fullmatch(r"[A-Z]{2}", value) is None for value in values
        ):
            raise ValueError("countries require unique source ISO alpha-2 codes")
        return values

    @field_validator("regions")
    @classmethod
    def validate_regions(cls, values: list[str]) -> list[str]:
        allowed = {
            "africa", "arab-states", "asia-pacific", "europe-north-america",
            "latin-america-caribbean",
            "antarctica",
            "nps-pacific",
        }
        if len(values) != len(set(values)) or not set(values) <= allowed:
            raise ValueError("regions require unique supported source region identifiers")
        return values


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str
    description_zh: str = ""
    details: str = ""
    names: list[str]
    types: list[str]
    periods: list[str]
    repr_point: tuple[float, float] | None
    location_precision: Literal["precise", "rough"] | None = None
    source_uri: str
    contributors: list[str]
    period_evidence: list[PeriodEvidence]
    source_kind: Literal["pleiades", "global", "unesco", "ats", "supplement"] = "pleiades"
    source_refs: list[SourceReference] = Field(default_factory=list)
    chronology: ChronologyReview = Field(default_factory=ChronologyReview)
    geography: Geography | None = None

    @field_validator("repr_point")
    @classmethod
    def validate_coordinates(cls, point: tuple[float, float] | None) -> tuple[float, float] | None:
        if point is None:
            return None
        longitude, latitude = point
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError("representative point is outside WGS84 coordinate bounds")
        return point

    @model_validator(mode="after")
    def validate_period_evidence(self) -> "Site":
        if self.source_kind not in {"ats", "supplement"} and self.repr_point is None:
            raise ValueError("existing source cohorts require a valid representative point")
        if (
            self.source_kind not in {"ats", "supplement"} and self.geography is not None
            and self.geography.point_count < 1
        ):
            raise ValueError("existing source cohorts require at least one source point")
        evidence_periods = {item.period_id for item in self.period_evidence}
        if self.source_kind == "pleiades" and (
            "roman" not in evidence_periods or "roman" not in self.periods
        ):
            raise ValueError("site must have a Roman Name or Location attestation")
        if self.source_kind == "global" and (
            re.fullmatch(r"wd:Q[1-9]\d*", self.id) is None or not self.source_refs
        ):
            raise ValueError("global sites require a namespaced Wikidata ID and source references")
        if self.source_kind == "unesco" and (
            re.fullmatch(r"whc:[1-9]\d*", self.id) is None
            or not self.source_refs or self.geography is None
        ):
            raise ValueError("UNESCO sites require authority IDs, geography and source references")
        if self.source_kind == "ats":
            if (
                re.fullmatch(r"ats:hsm:[1-9]\d*", self.id) is None
                or not self.source_refs or self.geography is None
                or self.geography.regions != ["antarctica"] or self.geography.countries
            ):
                raise ValueError("ATS records require HSM identities and country-neutral geography")
            if self.geography.point_count != (0 if self.repr_point is None else 1):
                raise ValueError("ATS point count must preserve known versus unknown location")
        if self.source_kind == "supplement":
            if (
                re.fullmatch(
                    r"(?:wd:Q[1-9]\d*|auth:[a-z][a-z0-9-]{0,39}:"
                    r"[A-Za-z0-9][A-Za-z0-9._-]{0,79})", self.id,
                ) is None
                or not self.source_refs or self.geography is None
                or not self.geography.countries or not self.geography.regions
                or self.geography.authority_id != "supplement:" + self.id
            ):
                raise ValueError("supplement sites require qualified identity and source geography")
            if self.geography.point_count != (0 if self.repr_point is None else 1):
                raise ValueError("supplement point count differs from location availability")
        return self

"""Offline catalogue browsing and source-declared modern geographic coverage."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from archsearch.config import DATA_DIR
from archsearch.domain import Site

REGION_LABELS = {
    "africa": "非洲",
    "arab-states": "阿拉伯国家",
    "asia-pacific": "亚太地区",
    "europe-north-america": "欧洲与北美",
    "latin-america-caribbean": "拉丁美洲与加勒比",
}
SOURCE_LABELS = {
    "pleiades": "Pleiades 地中海资料",
    "global": "全球策展资料",
    "unesco": "UNESCO 世界遗产名录",
}


@dataclass(frozen=True)
class CoverageRegistry:
    countries: Mapping[str, str]
    regions: Mapping[str, str]
    authority_ids: frozenset[str] = frozenset()
    source: Mapping[str, str] | None = None
    excluded_natural: int = 0


def load_registry(data_dir: Path = DATA_DIR) -> CoverageRegistry:
    """Read labels from the bundled source manifest, never from a network service."""
    path = Path(data_dir) / "catalogue_manifest.json"
    if not path.exists():
        return CoverageRegistry(countries={}, regions=REGION_LABELS)
    value = json.loads(path.read_text("utf-8"))
    countries = {row["id"]: row["label"] for row in value["countries"]}
    regions = {row["id"]: row["label"] for row in value["regions"]}
    return CoverageRegistry(
        countries=countries, regions=regions,
        authority_ids=frozenset(value.get("partition", {}).get("eligible_ids", [])),
        source=value.get("source"),
        excluded_natural=value.get("counts", {}).get("excluded_natural", 0),
    )


class CoverageFacet(BaseModel):
    id: str
    label: str
    count: int


class ChronologyCounts(BaseModel):
    reviewed: int
    insufficient: int
    not_reviewed: int


class AuthorityCoverage(BaseModel):
    dataset: str
    source_uri: str
    source_modified: str
    source_sha256: str
    license: str
    license_uri: str
    eligible_total: int
    covered: int
    missing: int
    excluded_natural: int
    note: str


class CoverageResponse(BaseModel):
    corpus_version: str
    total: int
    countries: list[CoverageFacet]
    regions: list[CoverageFacet]
    sources: list[CoverageFacet]
    chronology: ChronologyCounts
    geography_unknown: int
    country_unknown: int
    authority: AuthorityCoverage | None = None


class CataloguePoint(BaseModel):
    id: str
    title: str
    repr_point: tuple[float, float]
    countries: list[str]
    regions: list[str]
    source_kind: str
    chronology_status: str


class CatalogueResponse(BaseModel):
    corpus_version: str
    total: int
    points: list[CataloguePoint]


class SitePage(BaseModel):
    corpus_version: str
    total: int
    offset: int
    limit: int
    sites: list[Site]


def matches_geography(site: Site, country: str | None, region: str | None) -> bool:
    """Membership is the source catalogue's declaration, never a point-in-polity inference."""
    if country is not None and (site.geography is None or country not in site.geography.countries):
        return False
    if region is not None and (site.geography is None or region not in site.geography.regions):
        return False
    return True


class CatalogueIndex:
    """Immutable corpus view with stable ordering for pages, points and coverage totals."""

    def __init__(
        self, sites: Sequence[Site], corpus_version: str,
        registry: CoverageRegistry | None = None,
    ) -> None:
        self.sites = tuple(sorted(sites, key=lambda site: (site.title.casefold(), site.id)))
        self.corpus_version = corpus_version
        self.registry = registry if registry is not None else load_registry()
        self.country_counts: Counter[str] = Counter()
        self.region_counts: Counter[str] = Counter()
        self.source_counts: Counter[str] = Counter()
        self.review_counts: Counter[str] = Counter()
        self.types = {kind for site in sites for kind in site.types}
        for site in self.sites:
            if site.geography is not None:
                self.country_counts.update(site.geography.countries)
                self.region_counts.update(site.geography.regions)
            self.source_counts.update([site.source_kind])
            self.review_counts.update([site.chronology.status])

    def validate_filters(
        self, country: str | None = None, region: str | None = None,
        kind: str | None = None,
    ) -> None:
        if country is not None and country not in self.country_counts:
            raise ValueError("未知国家／地区，请从资料覆盖列表选择。")
        if region is not None and region not in self.region_counts:
            raise ValueError("未知来源区域，请从资料覆盖列表选择。")
        if kind is not None and kind not in self.types:
            raise ValueError("未知地点类型，请从类型筛选列表选择。")

    def filtered(
        self, country: str | None = None, region: str | None = None,
        kind: str | None = None,
    ) -> list[Site]:
        self.validate_filters(country, region, kind)
        return [
            site for site in self.sites
            if matches_geography(site, country, region)
            and (kind is None or kind in site.types)
        ]

    def coverage(self) -> CoverageResponse:
        def facets(counts: Counter[str], labels: Mapping[str, str]) -> list[CoverageFacet]:
            return sorted(
                [CoverageFacet(id=key, label=labels.get(key, key), count=count)
                 for key, count in counts.items()],
                key=lambda item: (item.label.casefold(), item.id),
            )

        source = self.registry.source
        authority = None
        if source is not None:
            covered = self.registry.authority_ids.intersection(
                site.geography.authority_id for site in self.sites
                if site.geography and site.geography.authority_id is not None
            )
            authority = AuthorityCoverage(
                dataset=source["dataset_id"], source_uri=source["uri"],
                source_modified=source["modified"], source_sha256=source["records_sha256"],
                license=source["license"], license_uri=source["license_uri"],
                eligible_total=len(self.registry.authority_ids), covered=len(covered),
                missing=len(self.registry.authority_ids - covered),
                excluded_natural=self.registry.excluded_natural,
                note="分母为固定版本官方文化／混合遗产名录；不代表全球所有遗址或所有国家。",
            )
        return CoverageResponse(
            corpus_version=self.corpus_version,
            total=len(self.sites),
            countries=facets(self.country_counts, self.registry.countries),
            regions=facets(self.region_counts, self.registry.regions),
            sources=facets(self.source_counts, SOURCE_LABELS),
            chronology=ChronologyCounts(
                reviewed=self.review_counts["reviewed"],
                insufficient=self.review_counts["insufficient"],
                not_reviewed=self.review_counts["not_reviewed"],
            ),
            geography_unknown=sum(site.geography is None for site in self.sites),
            country_unknown=sum(
                site.geography is None or not site.geography.countries for site in self.sites
            ),
            authority=authority,
        )

    def catalogue(
        self, country: str | None = None, region: str | None = None,
        kind: str | None = None,
    ) -> CatalogueResponse:
        selected = self.filtered(country, region, kind)
        return CatalogueResponse(
            corpus_version=self.corpus_version, total=len(selected),
            points=[CataloguePoint(
                id=site.id, title=site.title, repr_point=site.repr_point,
                countries=site.geography.countries if site.geography else [],
                regions=site.geography.regions if site.geography else [],
                source_kind=site.source_kind, chronology_status=site.chronology.status,
            ) for site in selected],
        )

    def page(
        self, offset: int = 0, limit: int = 50,
        country: str | None = None, region: str | None = None, kind: str | None = None,
    ) -> SitePage:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset必须为非负整数，limit必须为1至100的整数。")
        selected = self.filtered(country, region, kind)
        return SitePage(
            corpus_version=self.corpus_version, total=len(selected), offset=offset, limit=limit,
            sites=selected[offset:offset + limit],
        )

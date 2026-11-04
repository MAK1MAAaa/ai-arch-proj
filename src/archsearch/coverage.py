"""Offline catalogue browsing and source-declared modern geographic coverage."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from archsearch.bounds import BBox, SpatialBounds
from archsearch.config import DATA_DIR
from archsearch.domain import Site
from archsearch.spatial_data import (
    SourceGroup,
    SpatialDataError,
    WorldLocations,
    load_world_locations,
    merge_world_locations,
)
from archsearch.supplement_data import SupplementError, country_labels

REGION_LABELS = {
    "africa": "非洲",
    "arab-states": "阿拉伯国家",
    "asia-pacific": "亚太地区",
    "europe-north-america": "欧洲与北美",
    "latin-america-caribbean": "拉丁美洲与加勒比",
    "antarctica": "南极洲",
    "nps-pacific": "NPS太平洋资料分组",
}
SOURCE_LABELS = {
    "pleiades": "Pleiades 地中海资料",
    "global": "全球策展资料",
    "unesco": "UNESCO 世界遗产名录",
    "ats": "南极条约历史遗址与纪念物",
    "supplement": "文化遗址补充资料",
}

WEB_MERCATOR_MAX_LATITUDE = 85.0511287798
LocationStatus = Literal["mapped", "polar", "unknown"]


@dataclass(frozen=True)
class CoverageRegistry:
    countries: Mapping[str, str]
    regions: Mapping[str, str]
    authority_ids: frozenset[str] = frozenset()
    source: Mapping[str, str] | None = None
    excluded_natural: int = 0
    polar_ids: frozenset[str] = frozenset()
    polar_source: Mapping[str, str] | None = None
    polar_excluded_types: Mapping[str, int] = field(default_factory=dict)
    spatial: WorldLocations | None = None
    spatial_error: str | None = None


def load_registry(data_dir: Path = DATA_DIR) -> CoverageRegistry:
    """Read labels from the bundled source manifest, never from a network service."""
    path = Path(data_dir) / "catalogue_manifest.json"
    value = json.loads(path.read_text("utf-8")) if path.exists() else {}
    countries = {row["id"]: row["label"] for row in value.get("countries", [])}
    if (Path(data_dir) / "supplement_manifest.json").exists():
        additions = country_labels(Path(data_dir))
        if countries.keys() & additions.keys():
            raise SupplementError(
                "supplement labels cannot overwrite the existing country registry"
            )
        countries.update(additions)
    regions = (
        {row["id"]: row["label"] for row in value["regions"]}
        if "regions" in value else dict(REGION_LABELS)
    )
    polar_path = Path(data_dir) / "polar_manifest.json"
    polar = json.loads(polar_path.read_text("utf-8")) if polar_path.exists() else {}
    regions.update({row["id"]: row["label"] for row in polar.get("regions", [])})
    if (Path(data_dir) / "nps_pacific_manifest.json").exists():
        from archsearch.nps_data import NpsError, new_country_labels, project_region_labels

        nps_countries = new_country_labels(Path(data_dir))
        if countries.keys() & nps_countries.keys():
            raise NpsError("NPS country-or-area labels cannot replace existing source labels")
        countries.update(nps_countries)
        regions.update(project_region_labels(Path(data_dir)))
    spatial = None
    spatial_error = None
    try:
        spatial = load_world_locations(Path(data_dir))
        if (Path(data_dir) / "protection_manifest.json").exists():
            from archsearch.protection_data import ProtectionError, load_protection_locations

            try:
                spatial = merge_world_locations(
                    spatial, load_protection_locations(Path(data_dir)),
                )
            except (ProtectionError, SpatialDataError) as error:
                raise SpatialDataError(
                    f"{error} 请运行 python -m archsearch.protection_data --rebuild "
                    "修复海牙来源定位；当前统一保留原代表点，不宣称源点完整。"
                ) from error
        if (Path(data_dir) / "nps_pacific_manifest.json").exists():
            from archsearch.nps_spatial_data import load_nps_locations

            try:
                nps_locations = load_nps_locations(Path(data_dir))
                if nps_locations.points:
                    spatial = merge_world_locations(spatial, nps_locations)
            except SpatialDataError as error:
                raise SpatialDataError(
                    f"{error} 请运行 python -m archsearch.nps_spatial_data --rebuild "
                    "修复NPS来源点；当前统一保留原代表点，不宣称多来源定位完整。"
                ) from error
    except SpatialDataError as error:
        spatial = None
        spatial_error = str(error)
    return CoverageRegistry(
        countries=countries, regions=regions,
        authority_ids=frozenset(value.get("partition", {}).get("eligible_ids", [])),
        source=value.get("source"),
        excluded_natural=value.get("counts", {}).get("excluded_natural", 0),
        polar_ids=frozenset(polar.get("partition", {}).get("active_ids", [])),
        polar_source=polar.get("source"),
        polar_excluded_types=polar.get("partition", {}).get("excluded_types", {}),
        spatial=spatial, spatial_error=spatial_error,
    )


class CoverageFacet(BaseModel):
    id: str
    label: str
    count: int


class ChronologyCounts(BaseModel):
    reviewed: int
    insufficient: int
    not_reviewed: int


class LocationCounts(BaseModel):
    mapped: int
    polar: int
    unknown: int


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


class PolarAuthorityCoverage(BaseModel):
    dataset: str
    source_uri: str
    source_accessed: str
    source_sha256: str
    license: str
    license_uri: str
    eligible_total: int
    covered: int
    missing: int
    excluded_types: dict[str, int]
    note: str


class SpatialSource(BaseModel):
    name: str
    uri: str
    version: str
    license: str
    license_uri: str
    sha256: str


class SpatialSourceGroup(BaseModel):
    version: str
    source: SpatialSource
    site_ids: list[str]


class SpatialLocationCoverage(BaseModel):
    ready: bool
    reason: str | None = None
    version: str | None = None
    source: SpatialSource | None = None
    source_groups: list[SpatialSourceGroup] = Field(default_factory=list)
    records: int = 0
    points: int = 0
    distinct_points: int = 0
    duplicate_points: int = 0
    display_points: int = 0


class SourceLocationRecord(BaseModel):
    source_index: int = Field(ge=0)
    coordinate: tuple[float, float]
    name: str
    ref: str


class SiteLocationsResponse(BaseModel):
    site_id: str
    representative_point: tuple[float, float] | None
    source_points: list[tuple[float, float]]
    source_location_records: list[SourceLocationRecord]
    spatial_version: str
    source: SpatialSource | None
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
    locations: LocationCounts
    authority: AuthorityCoverage | None = None
    polar_authority: PolarAuthorityCoverage | None = None
    spatial_locations: SpatialLocationCoverage | None = None


class CataloguePoint(BaseModel):
    id: str
    title: str
    repr_point: tuple[float, float] | None
    location_status: LocationStatus
    countries: list[str]
    regions: list[str]
    source_kind: str
    chronology_status: str
    source_points: list[tuple[float, float]] = Field(default_factory=list)
    source_location_records: list[SourceLocationRecord] = Field(default_factory=list)


class CatalogueResponse(BaseModel):
    corpus_version: str
    total: int
    points: list[CataloguePoint]
    spatial_version: str | None = None


class SitePage(BaseModel):
    corpus_version: str
    total: int
    offset: int
    limit: int
    sites: list[Site]
    bbox: BBox | None = None
    spatial_match_mode: Literal["source-or-representative", "representative-only"]
    spatial_version: str | None = None


def matches_geography(site: Site, country: str | None, region: str | None) -> bool:
    """Membership is the source catalogue's declaration, never a point-in-polity inference."""
    if country is not None and (site.geography is None or country not in site.geography.countries):
        return False
    if region is not None and (site.geography is None or region not in site.geography.regions):
        return False
    return True


def location_status(site: Site) -> LocationStatus:
    """Classify map availability without clipping or inventing a source coordinate."""
    if site.repr_point is None:
        return "unknown"
    return "mapped" if abs(site.repr_point[1]) <= WEB_MERCATOR_MAX_LATITUDE else "polar"


class CatalogueIndex:
    """Immutable corpus view with stable ordering for pages, points and coverage totals."""

    def __init__(
        self, sites: Sequence[Site], corpus_version: str,
        registry: CoverageRegistry | None = None,
    ) -> None:
        self.sites = tuple(sorted(sites, key=lambda site: (site.title.casefold(), site.id)))
        self.corpus_version = corpus_version
        self.registry = registry if registry is not None else load_registry()
        self.spatial = self.registry.spatial
        self.spatial_error = self.registry.spatial_error
        if self.spatial is not None and not set(self.spatial.points).issubset(
            site.id for site in self.sites
        ):
            self.spatial = None
            self.spatial_error = "源定位记录集与当前语料身份不匹配；保留原代表点和基础检索。"
        if self.spatial is not None and self.spatial.source_groups:
            grouped = [site_id for group in self.spatial.source_groups
                       for site_id in group.site_ids]
            if (len(grouped) != len(set(grouped)) or set(grouped) != set(self.spatial.points)
                    or "+".join(group.version for group in self.spatial.source_groups)
                    != self.spatial.version):
                self.spatial = None
                self.spatial_error = "源定位分组、地点身份或组合版本不一致；保留原代表点。"
        self.country_counts: Counter[str] = Counter()
        self.region_counts: Counter[str] = Counter()
        self.source_counts: Counter[str] = Counter()
        self.review_counts: Counter[str] = Counter()
        self.location_counts: Counter[str] = Counter()
        self.types = {kind for site in sites for kind in site.types}
        for site in self.sites:
            if site.geography is not None:
                self.country_counts.update(site.geography.countries)
                self.region_counts.update(site.geography.regions)
            self.source_counts.update([site.source_kind])
            self.review_counts.update([site.chronology.status])
            self.location_counts.update([location_status(site)])

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
        polar_authority = None
        if source is not None:
            covered = self.registry.authority_ids.intersection(
                site.geography.authority_id for site in self.sites
                if site.source_kind != "ats"
                and site.geography and site.geography.authority_id is not None
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
        if self.registry.polar_source is not None:
            polar_source = self.registry.polar_source
            polar_covered = self.registry.polar_ids.intersection(
                site.id for site in self.sites if site.source_kind == "ats"
            )
            polar_authority = PolarAuthorityCoverage(
                dataset=polar_source["dataset_id"], source_uri=polar_source["uri"],
                source_accessed=polar_source["accessed"], source_sha256=polar_source["sha256"],
                license=polar_source["license"], license_uri=polar_source["license_uri"],
                eligible_total=len(self.registry.polar_ids), covered=len(polar_covered),
                missing=len(self.registry.polar_ids - polar_covered),
                excluded_types=dict(self.registry.polar_excluded_types),
                note=(
                    "分母为固定南极条约来源中的历史遗址与纪念物名录，排除其他保护区类型；"
                    "收录状态与可定位状态独立，未知位置和极区记录仍保留。"
                ),
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
            locations=LocationCounts(
                mapped=self.location_counts["mapped"], polar=self.location_counts["polar"],
                unknown=self.location_counts["unknown"],
            ),
            authority=authority,
            polar_authority=polar_authority,
            spatial_locations=self.spatial_coverage(),
        )

    def source_points(self, site_id: str) -> list[tuple[float, float]]:
        return list(self.spatial.points.get(site_id, ())) if self.spatial else []

    def source_records(self, site_id: str) -> list[SourceLocationRecord]:
        if self.spatial is None:
            return []
        return [SourceLocationRecord(
            source_index=item.source_index, coordinate=item.coordinate,
            name=item.name, ref=item.ref,
        ) for item in self.spatial.records.get(site_id, ())]

    def spatial_source(self, site_id: str | None = None) -> SpatialSource | None:
        if self.spatial is None:
            return None
        source = self.spatial.source
        if site_id is not None:
            if site_id not in self.spatial.points:
                return None
            source = next((group.source for group in self.spatial.source_groups
                           if site_id in group.site_ids), source)
        return self._spatial_source(source)

    @staticmethod
    def _spatial_source(source: Mapping[str, str]) -> SpatialSource:
        dataset_id = source.get("dataset_id", "reviewed-local-source")
        name = source.get("name") or (
            f"UNESCO DataHub {dataset_id}" if dataset_id in {"whc001", "chp001"}
            else dataset_id
        )
        return SpatialSource(
            name=name, uri=source["uri"],
            version=source["version"] if "version" in source else source["modified"],
            license=source["license"], license_uri=source["license_uri"],
            sha256=source["sha256"] if "sha256" in source else source["records_sha256"],
        )

    def spatial_source_groups(self) -> list[SpatialSourceGroup]:
        if self.spatial is None:
            return []
        groups = self.spatial.source_groups or (SourceGroup(
            self.spatial.version, self.spatial.source, tuple(sorted(self.spatial.points)),
        ),)
        return [SpatialSourceGroup(version=group.version, source=self._spatial_source(group.source),
                                   site_ids=list(group.site_ids)) for group in groups]

    def spatial_coverage(self) -> SpatialLocationCoverage | None:
        if self.spatial is None and self.spatial_error is None:
            return None
        display_points = 0
        for site in self.sites:
            positions = {
                point for point in self.source_points(site.id)
                if abs(point[1]) <= WEB_MERCATOR_MAX_LATITUDE
            }
            if site.repr_point is not None and location_status(site) == "mapped":
                positions.add(site.repr_point)
            display_points += len(positions)
        if self.spatial is None:
            return SpatialLocationCoverage(
                ready=False, reason=self.spatial_error, display_points=display_points,
            )
        points = sum(len(value) for value in self.spatial.points.values())
        distinct = sum(len(set(value)) for value in self.spatial.points.values())
        return SpatialLocationCoverage(
            ready=True, version=self.spatial.version, source=self.spatial_source(),
            source_groups=self.spatial_source_groups(),
            records=len(self.spatial.points), points=points, distinct_points=distinct,
            duplicate_points=points - distinct, display_points=display_points,
        )

    def site_locations(self, site: Site) -> SiteLocationsResponse:
        if self.spatial is None:
            raise SpatialDataError(self.spatial_error or "源定位记录集尚未准备。")
        return SiteLocationsResponse(
            site_id=site.id, representative_point=site.repr_point,
            source_points=self.source_points(site.id),
            source_location_records=self.source_records(site.id),
            spatial_version=self.spatial.version,
            source=self.spatial_source(site.id),
            note=(
                "source_points与source_location_records为所属固定来源合同中的定位记录，"
                "保留所属来源经审核的定位顺序及重合记录，不代表独立遗址数量或边界。"
                "representative_point单独保留，依据见地点详情；不以项目计算的中心补源点。"
                "仓储或标签冲突等未纳入地图的记录保留在相应来源审核资料中。"
                "国别筛选属于整体名录成员关系，不推断各点的政治归属。"
            ),
        )

    def catalogue(
        self, country: str | None = None, region: str | None = None,
        kind: str | None = None,
    ) -> CatalogueResponse:
        selected = self.filtered(country, region, kind)
        return CatalogueResponse(
            corpus_version=self.corpus_version, total=len(selected),
            spatial_version=self.spatial.version if self.spatial else None,
            points=[CataloguePoint(
                id=site.id, title=site.title, repr_point=site.repr_point,
                location_status=location_status(site),
                countries=site.geography.countries if site.geography else [],
                regions=site.geography.regions if site.geography else [],
                source_kind=site.source_kind, chronology_status=site.chronology.status,
                source_points=self.source_points(site.id),
                source_location_records=self.source_records(site.id),
            ) for site in selected],
        )

    def page(
        self, offset: int = 0, limit: int = 50,
        country: str | None = None, region: str | None = None, kind: str | None = None,
        bbox: SpatialBounds | None = None,
    ) -> SitePage:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset必须为非负整数，limit必须为1至100的整数。")
        selected = self.filtered(country, region, kind)
        if bbox is not None:
            selected = [
                site for site in selected
                if (site.repr_point is not None and bbox.contains(site.repr_point))
                or any(bbox.contains(point) for point in self.source_points(site.id))
            ]
        return SitePage(
            corpus_version=self.corpus_version, total=len(selected), offset=offset, limit=limit,
            sites=selected[offset:offset + limit],
            bbox=bbox.as_tuple() if bbox is not None else None,
            spatial_match_mode=(
                "source-or-representative" if self.spatial is not None else "representative-only"
            ),
            spatial_version=self.spatial.version if self.spatial is not None else None,
        )

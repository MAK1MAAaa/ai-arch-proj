"""Reproducible, licensed UNESCO DataHub catalogue expansion and offline validation."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from pydantic import ValidationError

from archsearch.domain import ChronologyReview, Geography, Site, SourceReference

DATA_DIR = Path(__file__).with_name("data")
CATALOGUE_VERSION = "global-v3"
DATASET_ID = "whc001"
SOURCE_URI = "https://data.unesco.org/explore/dataset/whc001/"
METADATA_URI = "https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc001"
RECORDS_URI = METADATA_URI + "/exports/json"
SOURCE_MODIFIED = "2026-11-02T07:32:31+00:00"
RECORDS_SHA256 = "7e0149d5d509e3259cf2f19d73d20a27e6d34612eb2ed7d7c35b23dd858c57a3"
METADATA_SHA256 = "dc40afdffa29d4cff9e929a68441007906dea7ad6dc71074c0367c755464d6b3"
COUNTRY_REGISTRY_SHA256 = "8436027b3e7d11ee57ad046233aa72f2e3dd67f9eee2ba1ea766f28fa2914b58"
LICENSE = "CC BY-SA 4.0"
LICENSE_URI = "https://creativecommons.org/licenses/by-sa/4.0/"
REGIONS = {
    "Africa": ("africa", "非洲"),
    "Arab States": ("arab-states", "阿拉伯国家"),
    "Asia and the Pacific": ("asia-pacific", "亚洲及太平洋"),
    "Europe and North America": ("europe-north-america", "欧洲及北美"),
    "Latin America and the Caribbean": ("latin-america-caribbean", "拉丁美洲及加勒比"),
}
EXPECTED_COUNTS = {
    "source": 1273,
    "eligible": 1033,
    "curated": 99,
    "added": 934,
    "excluded_natural": 240,
    "total": 1534,
}
SELECTION = {
    "categories": ["Cultural", "Mixed"],
    "order": "ascending numeric authority ID",
    "original_cohorts": "500 Pleiades + 100 reviewed global records unchanged",
    "duplicate_policy": "Reuse the 99 existing authority IDs; spatial scopes may overlap.",
}
GEOGRAPHY_NOTE = (
    "国家/地区与分区为UNESCO现代名录归类，不依据代表点推断历史政治归属。"
    "UNESCO分区为报告分区，不是互斥的自然洲界。"
)
POINT_RULE = (
    "采用DataHub原始几何坐标序列的首个有效定位点，不取均值或geo_point_2d质心；"
    "point_count是可用定位点记录数，不等于已独立核验的组成遗址数。"
    "系列遗产、城市和区域的代表点仅供定位，不是整体中心或边界，也不是实测发掘坐标。"
)
ARTIFACTS = ("world_sites.json", "world_geography.json")


class CatalogueError(RuntimeError):
    """A pinned source or normalized catalogue artifact does not match its contract."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.suppressed += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.suppressed = max(0, self.suppressed - 1)
        elif tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.parts.append(data)


def plain_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CatalogueError("source text must be a string or null")
    parser = _Text()
    parser.feed(value)
    return " ".join(html.unescape("".join(parser.parts)).split())


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _source_reference() -> SourceReference:
    return SourceReference(
        id="unesco-datahub:whc001",
        title="UNESCO DataHub — World Heritage List",
        uri=SOURCE_URI,
        publisher="UNESCO",
        license=LICENSE,
        revision=f"{SOURCE_MODIFIED}; sha256:{RECORDS_SHA256}",
        accessed="2026-11-04",
    )


def _wd_reference(entity: str, revision: str, excerpt: str, title: str) -> dict[str, Any]:
    return SourceReference(
        id=f"wikidata:{entity}",
        title=title,
        uri=f"https://www.wikidata.org/wiki/{entity}",
        publisher="Wikidata contributors",
        license="CC0-1.0",
        revision=revision,
        accessed="2026-11-04",
        excerpt=excerpt,
    ).model_dump(mode="json")


COORDINATE_FALLBACKS: dict[str, dict[str, Any]] = {
    "868": {
        "repr_point": [-0.7229444444444445, 45.18405555555555],
        "note": (
            "DataHub未给定位点。采用Wikidata Q2962473的地球P625代表点；"
            "其P757为868，身份与本条名录一致。该点只表示长途系列遗产的一处定位参照，"
            "不是全部法国朝圣路线的中心或边界。"
        ),
        "sources": [
            _wd_reference(
                "Q2962473",
                "2389499994",
                "P757=868; P625 claim Q2962473$dfa93b15-8a9e-4f34-a82e-2b3c87e72346: "
                "longitude=-0.7229444444444445, latitude=45.18405555555555, "
                "globe=Q2, precision=0.00002777777777777778.",
                "Wikidata — French Way of Saint James property identity and representative point",
            )
        ],
    },
    "1567": {
        "repr_point": [2.75563, 51.13696],
        "note": (
            "DataHub及Wikidata整体条目未给整体定位点。选定Wikidata明确关联的组成部分"
            "Nieuport Memorial（Q13528892）作为代表点，仅供定位，不是整体中心或边界；"
            "point_count=1只表示采用的一处定位点，不代表全体组成遗产数。"
            "父条目Q64685453的P757=1567rev、P527指向该组成部分，"
            "组成部分P361反向关联父条目，坐标来自其地球P625。"
        ),
        "sources": [
            _wd_reference(
                "Q64685453",
                "2519828379",
                "P757 claim Q64685453$6198FFF2-3D3A-45B4-B47C-71ABE3D98455=1567rev; "
                "P527 claim Q64685453$6a9a011d-43ad-874d-7853-8e1b3d366d09=Q13528892.",
                "Wikidata — Western Front serial property and explicit component relationship",
            ),
            _wd_reference(
                "Q13528892",
                "2549225853",
                "P361 claim Q13528892$5773fb02-4220-d190-c8f9-191c26a5767f=Q64685453; "
                "P625 claim Q13528892$E16BCF9F-9BEE-4E89-9E3E-A2EDBBD6780F: "
                "longitude=2.75563, latitude=51.13696, globe=Q2, precision=0.0001.",
                "Wikidata — Nieuport Memorial component representative point",
            ),
        ],
    },
}


def country_registry(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Derive labels from singleton and set membership, never positional array zipping."""
    labels: dict[str, str] = {}
    pairs: list[tuple[set[str], set[str]]] = []
    for row in rows:
        codes = row.get("iso_codes") or []
        names = row.get("states_names") or []
        if (
            not isinstance(codes, list)
            or not isinstance(names, list)
            or any(
                not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}", code) for code in codes
            )
            or any(not isinstance(name, str) or not name.strip() for name in names)
        ):
            raise CatalogueError("invalid source country membership")
        if not codes:
            continue
        if len(codes) != len(set(codes)) or len(names) != len(set(names)):
            raise CatalogueError("duplicate source country membership")
        if len(codes) != len(names):
            raise CatalogueError("country code and name membership sizes differ")
        pairs.append((set(codes), set(names)))
        if len(codes) == 1:
            if codes[0] in labels and labels[codes[0]] != names[0]:
                raise CatalogueError("conflicting singleton country label")
            labels[codes[0]] = names[0]
    while True:
        old_size = len(labels)
        for codes, names in pairs:
            unknown_codes = codes - labels.keys()
            unknown_names = names - {labels[code] for code in codes if code in labels}
            if len(unknown_codes) == len(unknown_names) == 1:
                labels[next(iter(unknown_codes))] = next(iter(unknown_names))
        if len(labels) == old_size:
            break
    if any(set(labels.get(code) for code in codes) != names for codes, names in pairs):
        raise CatalogueError("country labels cannot be independently resolved from source sets")
    return labels


def source_points(row: dict[str, Any]) -> list[tuple[float, float]]:
    feature = row.get("coordinates")
    if feature is None:
        return []
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise CatalogueError("source geographic value must be a GeoJSON Feature")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise CatalogueError("source geographic geometry is missing")
    positions: Any
    if geometry.get("type") == "Point":
        positions = [geometry.get("coordinates")]
    elif geometry.get("type") == "MultiPoint":
        positions = geometry.get("coordinates")
    else:
        raise CatalogueError("source geographic geometry must be Point or MultiPoint")
    if not isinstance(positions, list) or not positions:
        raise CatalogueError("source geographic coordinates are empty")
    result = []
    for position in positions:
        if (
            not isinstance(position, list)
            or len(position) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in position
            )
            or not -180 <= position[0] <= 180
            or not -90 <= position[1] <= 90
        ):
            raise CatalogueError("source representative coordinate is invalid WGS84")
        result.append((float(position[0]), float(position[1])))
    return result


def normalize_record(row: dict[str, Any], identifier: str | None = None) -> Site:
    """Preserve licensed source descriptions and uncertainty without deriving historical dates."""
    authority_id = row.get("id_no")
    if not isinstance(authority_id, str) or not re.fullmatch(r"[1-9]\d*", authority_id):
        raise CatalogueError("source authority ID must be a positive decimal string")
    if row.get("category") not in {"Cultural", "Mixed"}:
        raise CatalogueError("only cultural and mixed properties belong in this catalogue")
    region = row.get("region")
    if region not in REGIONS:
        raise CatalogueError("source region is unknown")
    countries = row.get("iso_codes") or []
    if not isinstance(countries, list):
        raise CatalogueError("source country membership must be an array or null")
    names = []
    for language in ("en", "zh", "fr", "es", "ar", "ru"):
        name = plain_text(row.get(f"name_{language}"))
        if name and name not in names:
            names.append(name)
    title = plain_text(row.get("name_en"))
    if not title:
        raise CatalogueError("source English title is missing")
    points = source_points(row)
    fallback = COORDINATE_FALLBACKS.get(authority_id) if not points else None
    if not points and fallback is None:
        raise CatalogueError(f"source {authority_id} has no verified representative point")
    point = points[0] if points else tuple(fallback["repr_point"]) if fallback else None
    source = _source_reference()
    notes = [GEOGRAPHY_NOTE, POINT_RULE if points else str(fallback["note"]) if fallback else ""]
    if not countries:
        designation = "; ".join(row.get("states_names") or [])
        notes.append(
            f"来源未给ISO国家/地区代码，原始标注：{designation}。保持未归类，不补推主权归属。"
        )
    geography = Geography(
        authority_id=authority_id,
        countries=sorted(countries),
        regions=[REGIONS[region][0]],
        source=source,
        point_count=len(points) if points else 1,
        note=" ".join(notes),
    )
    sources = [source]
    if fallback:
        sources.extend(SourceReference.model_validate(ref) for ref in fallback["sources"])
    return Site.model_validate(
        {
            "id": identifier or f"whc:{authority_id}",
            "source_kind": "unesco",
            "title": title,
            "names": names,
            "description": plain_text(row.get("short_description_en")),
            "description_zh": plain_text(row.get("short_description_zh")),
            "details": "",
            "types": ["historic-site"],
            "periods": [],
            "period_evidence": [],
            "repr_point": point,
            "location_precision": "rough",
            "source_uri": f"https://whc.unesco.org/en/list/{authority_id}/",
            "contributors": ["UNESCO"],
            "source_refs": sources,
            "geography": geography,
            "chronology": ChronologyReview(
                status="not_reviewed",
                method="catalogue_metadata_only",
                note=(
                    "已核对来源名录元数据；历史断代尚未独立核验，保留未知。"
                    "名录列入年份不是建造、使用或毁损年份，不用于历史地图自动跳转。"
                ),
            ),
        }
    )


def _load_sources(cache_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for filename, expected in (
        ("records.json", RECORDS_SHA256),
        ("metadata.json", METADATA_SHA256),
    ):
        if _sha256(cache_dir / filename) != expected:
            raise CatalogueError(f"pinned UNESCO DataHub source checksum differs: {filename}")
    metadata = json.loads((cache_dir / "metadata.json").read_text("utf-8"))
    defaults = metadata["metas"]["default"]
    if (
        metadata["dataset_id"] != DATASET_ID
        or defaults["license"] != LICENSE
        or defaults["license_url"] != LICENSE_URI
        or defaults["modified"] != SOURCE_MODIFIED
        or defaults["records_count"] != EXPECTED_COUNTS["source"]
    ):
        raise CatalogueError("source dataset identity, license or version differs")
    rows = json.loads((cache_dir / "records.json").read_text("utf-8"))
    if not isinstance(rows, list) or len(rows) != EXPECTED_COUNTS["source"]:
        raise CatalogueError("source record count differs from the pinned version")
    return rows, metadata


def rebuild_catalogue(cache_dir: Path, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Rebuild normalized artifacts from the explicit pinned cache; never download implicitly."""
    try:
        rows, _ = _load_sources(Path(cache_dir))
        curated_manifest = json.loads((data_dir / "global_manifest.json").read_text("utf-8"))
        curated = {
            record["authority_id"]: record["id"]
            for record in curated_manifest["records"]
            if re.fullmatch(r"[1-9]\d*", record["authority_id"])
        }
        eligible = [row for row in rows if row["category"] in {"Cultural", "Mixed"}]
        eligible.sort(key=lambda row: int(row["id_no"]))
        all_ids = {row["id_no"] for row in rows}
        eligible_ids = [row["id_no"] for row in eligible]
        if len(all_ids) != len(rows) or len(set(eligible_ids)) != len(eligible_ids):
            raise CatalogueError("source authority identifiers are duplicated")
        if not set(curated) <= set(eligible_ids):
            raise CatalogueError("curated authority IDs are absent from the licensed source")
        labels = country_registry(rows)
        sites: list[Site] = []
        geography: dict[str, Any] = {}
        for row in eligible:
            authority_id = row["id_no"]
            site = normalize_record(row)
            assert site.geography is not None
            if authority_id in curated:
                overlay = site.geography.model_copy(
                    update={
                        "note": GEOGRAPHY_NOTE
                        + "保留原策展资料的Wikidata代表点，不改为DataHub首点。"
                        "point_count记录DataHub提供的定位点记录数，这些多点尚未在此展开；"
                        "名录定位点与原策展代表点可不同，均不是实测发掘坐标或整个遗产边界。",
                    }
                )
                geography[curated[authority_id]] = overlay.model_dump(mode="json")
            else:
                geography[site.id] = site.geography.model_dump(mode="json")
                sites.append(site)
        imported_ids = [site.geography.authority_id for site in sites if site.geography]
        countries = sorted({code for item in geography.values() for code in item["countries"]})
        artifacts = {
            "world_sites.json": _json_bytes([site.model_dump(mode="json") for site in sites]),
            "world_geography.json": _json_bytes(geography),
        }
        counts = {
            "source": len(rows),
            "eligible": len(eligible),
            "curated": len(curated),
            "added": len(sites),
            "excluded_natural": len(rows) - len(eligible),
            "total": 600 + len(sites),
        }
        if counts != EXPECTED_COUNTS:
            raise CatalogueError("catalogue partition counts differ from the fixed contract")
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "corpus_version": CATALOGUE_VERSION,
            "source": {
                "dataset_id": DATASET_ID,
                "uri": SOURCE_URI,
                "api_uri": RECORDS_URI,
                "metadata_uri": METADATA_URI,
                "modified": SOURCE_MODIFIED,
                "records_sha256": RECORDS_SHA256,
                "metadata_sha256": METADATA_SHA256,
                "license": LICENSE,
                "license_uri": LICENSE_URI,
                "attribution": "UNESCO",
                "accessed": "2026-11-04",
            },
            "counts": counts,
            "selection": SELECTION,
            "partition": {
                "eligible_ids": eligible_ids,
                "curated_ids": sorted(curated, key=int),
                "added_ids": imported_ids,
                "excluded_ids": sorted(all_ids - set(eligible_ids), key=int),
                "unlocated_ids": [],
            },
            "countries": [{"id": code, "label": labels[code]} for code in countries],
            "regions": [
                {"id": slug, "label": label, "source_label": name}
                for name, (slug, label) in REGIONS.items()
            ],
            "coverage": {
                "country_count": len(countries),
                "region_counts": dict(Counter(row["regions"][0] for row in geography.values())),
                "unassigned_country_authority_ids": [
                    row["authority_id"] for row in geography.values() if not row["countries"]
                ],
                "note": (
                    "Modern source catalogue membership; not historical sovereignty "
                    "or complete global inventory."
                ),
            },
            "coordinate_processing": {
                "new_records": POINT_RULE,
                "curated_overlay": (
                    "Retain curated Wikidata points; "
                    "point_count describes DataHub source positions."
                ),
            },
            "coordinate_fallbacks": COORDINATE_FALLBACKS,
            "processing": {
                "text": (
                    "HTML-to-text and whitespace normalization; official Chinese kept; "
                    "no generated translations."
                ),
                "chronology": (
                    "New catalogue phases unreviewed; "
                    "inscription year never used as a historical stage."
                ),
                "media": "No images, videos, nomination files or full raw export redistributed.",
            },
            "files": {
                name: {"sha256": hashlib.sha256(payload).hexdigest()}
                for name, payload in artifacts.items()
            },
        }
        manifest["country_registry_sha256"] = hashlib.sha256(
            _json_bytes(manifest["countries"])
        ).hexdigest()
        for name, payload in artifacts.items():
            (data_dir / name).write_bytes(payload)
        (data_dir / "catalogue_manifest.json").write_bytes(_json_bytes(manifest))
        return manifest
    except CatalogueError:
        raise
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise CatalogueError(f"cannot rebuild licensed world catalogue: {error}") from error


def load_catalogue(curated: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Validate the full world partition and overlay source geography without replacing reviews."""
    try:
        manifest = json.loads((data_dir / "catalogue_manifest.json").read_text("utf-8"))
        if manifest["schema_version"] != 1 or manifest["corpus_version"] != CATALOGUE_VERSION:
            raise CatalogueError("world catalogue schema/version differs")
        if manifest["selection"] != SELECTION:
            raise CatalogueError("world catalogue selection differs from the fixed source contract")
        source = manifest["source"]
        if (
            source["dataset_id"] != DATASET_ID
            or source["modified"] != SOURCE_MODIFIED
            or source["uri"] != SOURCE_URI
            or source["api_uri"] != RECORDS_URI
            or source["metadata_uri"] != METADATA_URI
            or source["attribution"] != "UNESCO"
            or source["license"] != LICENSE
            or source["license_uri"] != LICENSE_URI
            or source["records_sha256"] != RECORDS_SHA256
            or source["metadata_sha256"] != METADATA_SHA256
        ):
            raise CatalogueError("world catalogue source license or fixed snapshot differs")
        if manifest["counts"] != EXPECTED_COUNTS or len(curated) != 600:
            raise CatalogueError("world catalogue counts differ from the fixed 600+934 contract")
        for filename in ARTIFACTS:
            if _sha256(data_dir / filename) != manifest["files"][filename]["sha256"]:
                raise CatalogueError(f"world catalogue checksum mismatch: {filename}")
        imported = [
            Site.model_validate(row)
            for row in json.loads((data_dir / "world_sites.json").read_text("utf-8"))
        ]
        geography = {
            key: Geography.model_validate(value)
            for key, value in json.loads(
                (data_dir / "world_geography.json").read_text("utf-8")
            ).items()
        }
        if any(item.point_count < 1 for item in geography.values()):
            raise CatalogueError("world catalogue geography requires at least one source point")
        partition = manifest["partition"]
        sets = {}
        for name in ("eligible_ids", "curated_ids", "added_ids", "excluded_ids"):
            values = partition[name]
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(value, str) or re.fullmatch(r"[1-9]\d*", value) is None
                    for value in values
                )
                or len(values) != len(set(values))
                or values != sorted(values, key=int)
            ):
                raise CatalogueError("catalogue partition IDs must be unique sorted authority IDs")
            sets[name] = set(values)
        if (
            sets["curated_ids"] & sets["added_ids"]
            or sets["eligible_ids"] != sets["curated_ids"] | sets["added_ids"]
            or sets["eligible_ids"] & sets["excluded_ids"]
            or len(sets["eligible_ids"] | sets["excluded_ids"]) != EXPECTED_COUNTS["source"]
            or len(sets["eligible_ids"]) != EXPECTED_COUNTS["eligible"]
            or len(sets["curated_ids"]) != EXPECTED_COUNTS["curated"]
            or len(sets["added_ids"]) != EXPECTED_COUNTS["added"]
            or partition["unlocated_ids"]
        ):
            raise CatalogueError("world catalogue source partition is incomplete or overlapping")
        ids = [site.id for site in imported]
        if (
            len(ids) != EXPECTED_COUNTS["added"]
            or len(set(ids)) != len(ids)
            or ids != [f"whc:{value}" for value in partition["added_ids"]]
            or set(ids) & {site.id for site in curated}
            or any(site.source_kind != "unesco" for site in imported)
        ):
            raise CatalogueError("imported catalogue identities differ or duplicate existing sites")
        if any(
            site.chronology.status != "not_reviewed" or site.chronology.phases for site in imported
        ):
            raise CatalogueError("catalogue import cannot assert reviewed historical phases")
        if len(geography) != EXPECTED_COUNTS["eligible"]:
            raise CatalogueError("geography overlay must cover the complete eligible source")
        authority_ids = [item.authority_id for item in geography.values()]
        if (
            len(set(authority_ids)) != len(authority_ids)
            or set(authority_ids) != sets["eligible_ids"]
        ):
            raise CatalogueError("geography authority coverage is incomplete or duplicated")
        curated_ids = {site.id for site in curated}
        overlay_ids = set(geography) - set(ids)
        if not overlay_ids <= curated_ids or len(overlay_ids) != EXPECTED_COUNTS["curated"]:
            raise CatalogueError("geography overlay includes unknown or missing curated identities")
        old_manifest = json.loads((data_dir / "global_manifest.json").read_text("utf-8"))
        expected_overlay = {
            row["id"]: row["authority_id"]
            for row in old_manifest["records"]
            if re.fullmatch(r"[1-9]\d*", row["authority_id"])
        }
        if set(expected_overlay) != overlay_ids or any(
            geography[key].authority_id != authority for key, authority in expected_overlay.items()
        ):
            raise CatalogueError(
                "curated authority identity bridge differs from its frozen manifest"
            )
        countries = {row["id"]: row["label"] for row in manifest["countries"]}
        if len(countries) != len(manifest["countries"]) or len(countries) != 159:
            raise CatalogueError("country label registry is incomplete or duplicated")
        country_hash = hashlib.sha256(_json_bytes(manifest["countries"])).hexdigest()
        if (
            country_hash != COUNTRY_REGISTRY_SHA256
            or manifest["country_registry_sha256"] != COUNTRY_REGISTRY_SHA256
        ):
            raise CatalogueError("country label registry differs from the frozen source mapping")
        expected_regions = {
            slug: {"id": slug, "label": label, "source_label": name}
            for name, (slug, label) in REGIONS.items()
        }
        if (
            len(manifest["regions"]) != len(expected_regions)
            or {row["id"]: row for row in manifest["regions"]} != expected_regions
        ):
            raise CatalogueError("region label registry differs from source region definitions")
        if any(code not in countries for item in geography.values() for code in item.countries):
            raise CatalogueError("geography refers to an unknown country label")
        if any(item.source != _source_reference() for item in geography.values()):
            raise CatalogueError(
                "geography source reference differs from the licensed fixed snapshot"
            )
        for site in imported:
            if site.geography != geography[site.id]:
                raise CatalogueError("imported site and external geography overlay differ")
            if site.geography.authority_id != site.id.removeprefix("whc:"):
                raise CatalogueError("site identity differs from geography authority identity")
            authority_id = site.geography.authority_id
            if site.source_uri != f"https://whc.unesco.org/en/list/{authority_id}/":
                raise CatalogueError("site source URI differs from its authority identity")
            expected_sources = [_source_reference()]
            if authority_id in COORDINATE_FALLBACKS:
                expected_sources.extend(
                    SourceReference.model_validate(reference)
                    for reference in COORDINATE_FALLBACKS[authority_id]["sources"]
                )
            if site.source_refs != expected_sources:
                raise CatalogueError(
                    "site is missing fixed dataset or coordinate source references"
                )
            if site.periods or site.period_evidence or site.types != ["historic-site"]:
                raise CatalogueError(
                    "catalogue import cannot synthesize period or place type evidence"
                )
            if site.geography.authority_id in COORDINATE_FALLBACKS:
                fallback = COORDINATE_FALLBACKS[site.geography.authority_id]
                if (
                    site.repr_point != tuple(fallback["repr_point"])
                    or site.geography.point_count != 1
                    or site.geography.note != GEOGRAPHY_NOTE + " " + fallback["note"]
                ):
                    raise CatalogueError("verified fallback representative point or scope differs")
        result = [
            site.model_copy(update={"geography": geography[site.id]})
            if site.id in geography
            else site
            for site in curated
        ] + imported
        return result
    except CatalogueError:
        raise
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise CatalogueError(
            f"cannot load local world catalogue from {data_dir}: {error}"
        ) from error


def download_sources(cache_dir: Path) -> None:
    """Explicit preparation only; reject a changed upstream instead of silently upgrading."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, uri, expected, maximum in (
        ("records.json", RECORDS_URI, RECORDS_SHA256, 64 * 1024 * 1024),
        ("metadata.json", METADATA_URI, METADATA_SHA256, 1024 * 1024),
    ):
        path = cache_dir / name
        if path.exists() and _sha256(path) == expected:
            continue
        temporary = path.with_suffix(".part")
        try:
            request = Request(uri, headers={"User-Agent": "archsearch-mvp/0.1"})
            with urlopen(request, timeout=120) as response, temporary.open("wb") as target:
                size = 0
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(block)
                    if size > maximum:
                        raise CatalogueError("UNESCO DataHub source exceeds bounded download size")
                    target.write(block)
            if _sha256(temporary) != expected:
                raise CatalogueError(
                    "UNESCO DataHub has changed from the pinned snapshot; retain the original "
                    "cache or review a deliberate source version update."
                )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--source-cache", type=Path, default=Path(".archsearch/downloads/unesco-datahub-v1")
    )
    args = parser.parse_args()
    if args.download:
        download_sources(args.source_cache)
    if args.rebuild:
        print(json.dumps(rebuild_catalogue(args.source_cache, args.data_dir)["counts"]))
    else:
        manifest = json.loads((args.data_dir / "catalogue_manifest.json").read_text("utf-8"))
        for filename in ARTIFACTS:
            if _sha256(args.data_dir / filename) != manifest["files"][filename]["sha256"]:
                raise CatalogueError(f"world catalogue checksum mismatch: {filename}")
        print(json.dumps(manifest["counts"]))


if __name__ == "__main__":
    main()

"""Pinned Antarctic Treaty HSM records with explicit unknown and polar source locations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from pydantic import ValidationError

from archsearch.catalogue_data import plain_text
from archsearch.domain import ChronologyReview, Geography, Site, SourceReference

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "ats-hsm-v1"
CORPUS_VERSION = "global-v4"
SOURCE_URI = "https://www.ats.aq/devph/en/apa-database"
QUERY_URI = "https://www.ats.aq/devphbackend/api/apa/search?lang=e"
DETAIL_API = "https://www.ats.aq/devphbackend/api/apa/{internal_id}?lang=e"
DETAIL_PAGE = "https://www.ats.aq/devph/en/apa-database/{internal_id}"
COPYRIGHT_URI = "https://www.ats.aq/e/copyright.html"
LICENSE = "CC BY 4.0"
LICENSE_URI = "https://creativecommons.org/licenses/by/4.0/"
QUERY_SHA256 = "f2e9b4132d3521731d6aa571f942a3640df410735f60ae435080d96cc9ebd694"
COPYRIGHT_SHA256 = "396f426ddb211048ca4f26c398976168e2ef343e4356328ee9babd87d0d7b7ac"
DETAIL_MAP_SHA256 = "399fd1f98e683a3282522c16daf60e72a7aa59e4ace65df09d2f7dc665a20e3e"
SITES_SHA256 = "1eb2c3d31f15c20d3e4ac3e5243ca0f40a32e730c24b859ecaa317f80bd04db3"
RECORDS_CONTRACT_SHA256 = "ac2c6c04ede214a627e5391e7ae3d6c08f404504d72a64aed5960dcb75fda972"
ACCESSED = "2026-11-04"
ABSENT_NUMBERS = (12, 13, 25, 31, 58)
ACTIVE_NUMBERS = tuple(number for number in range(1, 97) if number not in ABSENT_NUMBERS)
REGION = {"id": "antarctica", "label": "南极", "source_label": "Antarctica"}
MERCATOR_MAX_LATITUDE = 85.0511287798
EXPECTED_COUNTS = {
    "source_apa": 182,
    "selected_hsm": 91,
    "base": 1534,
    "total": 1625,
    "located": 90,
    "unknown_location": 1,
    "outside_web_mercator": 3,
}
_DMS = re.compile(
    r"\s*(\d{1,3})\s*[°º˚]\s*(?:(\d{1,2})\s*['′’]\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*[\"″”]\s*)?([NSEW])\s*",
    re.IGNORECASE,
)


class PolarDataError(RuntimeError):
    """A frozen ATS source, identity, location semantic or artifact is inconsistent."""


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _detail_pins(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {str(number) for number in ACTIVE_NUMBERS}:
        raise PolarDataError("ATS detail pins do not cover the fixed active HSM numbers")
    if any(
        not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in value.values()
    ):
        raise PolarDataError("ATS detail SHA256 values are malformed")
    if hashlib.sha256(_canonical(value)).hexdigest() != DETAIL_MAP_SHA256:
        raise PolarDataError("ATS detail pins differ from the independently verified snapshot")
    return dict(value)


def dms_coordinate(value: Any, *, latitude: bool) -> float:
    """Convert an explicit source hemisphere/DMS value without a geographic guess."""
    match = _DMS.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise PolarDataError("source DMS coordinate is missing or malformed")
    degrees = int(match[1])
    minutes = int(match[2] or 0)
    seconds = float(match[3] or 0)
    hemisphere = match[4].upper()
    maximum = 90 if latitude else 180
    allowed = {"N", "S"} if latitude else {"E", "W"}
    if (
        hemisphere not in allowed
        or minutes >= 60
        or not 0 <= seconds < 60
        or degrees > maximum
        or (degrees == maximum and (minutes or seconds))
    ):
        raise PolarDataError("source DMS coordinate is outside its valid angular range")
    result = degrees + minutes / 60 + seconds / 3600
    return -result if hemisphere in {"S", "W"} else result


def source_location(detail: dict[str, Any]) -> tuple[tuple[float, float] | None, str, str]:
    """Separate a known/approximate site reference from a last sighting of an unknown wreck."""
    number = str(detail["number"])
    location = detail.get("location") or {}
    decimal = location.get("decimal") or {}
    context = plain_text(detail.get("physicalFeaturesAndContext"))
    if number == "95":
        if "exact location is unknown" not in context.casefold():
            raise PolarDataError("HSM95 location semantics changed; source review is required")
        return (
            None,
            "unknown_last_sighting",
            (
                "遗址准确位置未知。来源[-70,-62]是最后目击参照，不是已发现的沉船坐标；"
                "该参照只在来源说明中保留，不绘制为真实遗址标记。来源原文：" + context
            ),
        )
    latitude = decimal.get("latitude")
    longitude = decimal.get("longitude")
    if latitude is None and longitude is None:
        dms = location.get("dms") or {}
        if not dms.get("latitude") and not dms.get("longitude"):
            return None, "unknown", "来源未提供可核对的定位点，保留未知，不补零坐标。"
        point = (
            dms_coordinate(dms.get("longitude"), latitude=False),
            dms_coordinate(dms.get("latitude"), latitude=True),
        )
        return (
            point,
            "dms_conversion",
            (
                f"来源十进制字段缺失，按原始DMS {dms['latitude']} / {dms['longitude']}直接换算；"
                "保留来源角度精度，不以邻近基地中心补点。"
            ),
        )
    if (
        not isinstance(longitude, (int, float))
        or not isinstance(latitude, (int, float))
        or isinstance(longitude, bool)
        or isinstance(latitude, bool)
        or not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise PolarDataError("source decimal coordinates are invalid WGS84 values")
    note = "保留来源十进制代表点及DMS，不承诺精确发掘或全部遗产范围。"
    if abs(latitude) > MERCATOR_MAX_LATITUDE:
        note += "源纬度超出Web Mercator显示范围；保留原坐标，禁止静默夹取，应使用极地/地理投影。"
    if abs(latitude) == 90:
        note += "极点经度是参照约定，不表示不同经度是不同地点；原物位置及现状仍须阅读来源。"
    return (float(longitude), float(latitude)), "decimal", note


def _reference(number: int, internal_id: int, digest: str, title: str) -> SourceReference:
    return SourceReference(
        id=f"ats:hsm:{number}:detail",
        title=f"ATS HSM {number} — {title}",
        uri=DETAIL_PAGE.format(internal_id=internal_id),
        publisher="Antarctic Treaty Secretariat",
        license=LICENSE,
        revision=f"sha256:{digest}",
        accessed=ACCESSED,
    )


def normalize_detail(detail: dict[str, Any], digest: str) -> tuple[Site, dict[str, Any]]:
    """Keep official source text and original location semantics; do not infer historical dates."""
    number_text = detail.get("number")
    if not isinstance(number_text, str) or not re.fullmatch(r"[1-9]\d*", number_text):
        raise PolarDataError("HSM number must be an explicit positive decimal source number")
    if detail.get("type", {}).get("id") != 1 or detail.get("isDeDesignated") is not False:
        raise PolarDataError("only active, formally designated HSM records may be imported")
    internal_id = detail.get("id")
    if type(internal_id) is not int or internal_id < 1:
        raise PolarDataError("ATS source internal identifier is missing")
    number = int(number_text)
    title = plain_text(detail.get("name"))
    if not title:
        raise PolarDataError("ATS HSM source title is missing")
    point, method, note = source_location(detail)
    reference = _reference(number, internal_id, digest, title)
    geography = Geography(
        authority_id=f"ats:hsm:{number}",
        countries=[],
        regions=["antarctica"],
        source=reference,
        point_count=0 if point is None else 1,
        note=(
            "来源为南极条约秘书处正式HSM名录。提议方或管理方不是国家主权归属；"
            "不按坐标、探险队国籍或历史疆域补推归属。 " + note
        ),
    )
    details = []
    for field, label in (
        ("historicalContext", "Historical context"),
        ("physicalFeaturesAndContext", "Physical features and context"),
    ):
        text = plain_text(detail.get(field))
        if text:
            details.append(f"{label}: {text}")
    site = Site(
        id=f"ats:hsm:{number}",
        title=title,
        names=[f"HSM {number}", f"HSM-{number}"],
        description=plain_text(detail.get("summary")),
        details="\n\n".join(details),
        types=["historic-site"],
        periods=[],
        repr_point=point,
        location_precision=None,
        source_uri=reference.uri,
        contributors=["Antarctic Treaty Secretariat"],
        period_evidence=[],
        source_kind="ats",
        source_refs=[reference],
        geography=geography,
        chronology=ChronologyReview(
            status="not_reviewed",
            method="official_catalogue_and_location_semantics_check",
            note=(
                "已核对官方HSM身份、原文与定位语义；历史阶段尚未独立核验。"
                "保护认定、名录采用或管理年份不视为建造/使用年代，不自动跳转历史年份。"
            ),
        ),
    )
    record = {
        "site_id": site.id,
        "hsm_number": number,
        "internal_id": internal_id,
        "detail_uri": reference.uri,
        "detail_api_uri": DETAIL_API.format(internal_id=internal_id),
        "detail_sha256": digest,
        "coordinate_method": method,
        "source_decimal": (detail.get("location") or {}).get("decimal"),
        "source_dms": (detail.get("location") or {}).get("dms"),
        "measure_refs": detail.get("designations") or [],
        "type": detail.get("hsmType"),
    }
    return site, record


def _read_pins(cache_dir: Path, data_dir: Path) -> dict[str, str]:
    cached = cache_dir / "ats-hsm-details-manifest.json"
    if cached.exists():
        return _detail_pins(json.loads(cached.read_text("utf-8"))["files"])
    manifest = json.loads((data_dir / "polar_manifest.json").read_text("utf-8"))
    return _detail_pins(manifest["source"]["details_sha256_by_hsm_number"])


def rebuild_polar(cache_dir: Path, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Rebuild the fixed 91-source cohort only from verified cached official responses."""
    try:
        cache_dir, data_dir = Path(cache_dir), Path(data_dir)
        if _sha256(cache_dir / "ats-apa-search.json") != QUERY_SHA256:
            raise PolarDataError("ATS source query snapshot SHA256 differs")
        if _sha256(cache_dir / "ats-copyright.html") != COPYRIGHT_SHA256:
            raise PolarDataError("ATS source copyright statement snapshot SHA256 differs")
        pins = _read_pins(cache_dir, data_dir)
        rows = json.loads((cache_dir / "ats-apa-search.json").read_text("utf-8"))
        if not isinstance(rows, list) or len(rows) != EXPECTED_COUNTS["source_apa"]:
            raise PolarDataError("ATS APA query count differs from its fixed snapshot")
        selected = {
            row["number"]: row
            for row in rows
            if row["type"]["id"] == 1 and row["isDeDesignated"] is False
        }
        if set(selected) != set(pins):
            raise PolarDataError("ATS active HSM source identity partition differs")
        sites: list[Site] = []
        records: list[dict[str, Any]] = []
        for number in ACTIVE_NUMBERS:
            filename = cache_dir / f"ats-hsm-{number}-detail.json"
            if _sha256(filename) != pins[str(number)]:
                raise PolarDataError(f"ATS HSM {number} detail SHA256 differs")
            detail = json.loads(filename.read_text("utf-8"))
            if detail["number"] != str(number) or detail["id"] != selected[str(number)]["id"]:
                raise PolarDataError("ATS internal ID and stable HSM number do not match")
            site, record = normalize_detail(detail, pins[str(number)])
            sites.append(site)
            records.append(record)
        unknown = [site.id for site in sites if site.repr_point is None]
        outside = [
            site.id
            for site in sites
            if site.repr_point is not None and abs(site.repr_point[1]) > MERCATOR_MAX_LATITUDE
        ]
        if unknown != ["ats:hsm:95"] or outside != ["ats:hsm:1", "ats:hsm:24", "ats:hsm:80"]:
            raise PolarDataError("ATS source location semantics or projection coverage changed")
        payload = _json_bytes([site.model_dump(mode="json") for site in sites])
        if (
            hashlib.sha256(payload).hexdigest() != SITES_SHA256
            or hashlib.sha256(_canonical(records)).hexdigest() != RECORDS_CONTRACT_SHA256
        ):
            raise PolarDataError("ATS normalization differs from the frozen normalization contract")
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "cohort_version": COHORT_VERSION,
            "corpus_version": CORPUS_VERSION,
            "source": {
                "dataset_id": "ats-hsm",
                "uri": SOURCE_URI,
                "query_uri": QUERY_URI,
                "query_method": "POST",
                "query_body": {},
                "modified": None,
                "accessed": ACCESSED,
                "sha256": QUERY_SHA256,
                "query_sha256": QUERY_SHA256,
                "license": LICENSE,
                "license_uri": LICENSE_URI,
                "attribution": "Antarctic Treaty Secretariat",
                "copyright_uri": COPYRIGHT_URI,
                "copyright_sha256": COPYRIGHT_SHA256,
                "details_sha256_by_hsm_number": pins,
            },
            "counts": EXPECTED_COUNTS,
            "regions": [REGION],
            "selection": {
                "type_id": 1,
                "type_name": "HSM",
                "is_de_designated": False,
                "order": "ascending integer HSM number",
                "media": "excluded",
            },
            "partition": {
                "active_ids": [site.id for site in sites],
                "active_numbers": list(ACTIVE_NUMBERS),
                "numbers_absent": list(ABSENT_NUMBERS),
                "excluded_types": {"ASPA": 84, "ASMA": 7},
                "unknown_location_ids": unknown,
                "outside_web_mercator_ids": outside,
            },
            "records": records,
            "processing": {
                "text": (
                    "Official English text, HTML/whitespace normalization, "
                    "no generated translations."
                ),
                "dates": (
                    "All imported stages not_reviewed; "
                    "designation dates are not construction dates."
                ),
                "location": (
                    "Keep source WGS84; HSM34 DMS conversion; "
                    "HSM95 unknown, not last-sighting marker."
                ),
                "pole": (
                    "Preserve -90 and -85.173278 source latitudes; never silently clamp projection."
                ),
                "sovereignty": (
                    "Proponents and managers are not country ownership or political boundaries."
                ),
            },
            "files": {"polar_sites.json": {"sha256": hashlib.sha256(payload).hexdigest()}},
        }
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "polar_sites.json").write_bytes(payload)
        (data_dir / "polar_manifest.json").write_bytes(_json_bytes(manifest))
        return manifest
    except PolarDataError:
        raise
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise PolarDataError(f"cannot rebuild ATS HSM cohort: {error}") from error


def load_polar(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Load an independent ATS cohort without replacing any of the fixed 1534 earlier records."""
    try:
        data_dir = Path(data_dir)
        manifest = json.loads((data_dir / "polar_manifest.json").read_text("utf-8"))
        if (
            manifest["schema_version"] != 1
            or manifest["cohort_version"] != COHORT_VERSION
            or manifest["corpus_version"] != CORPUS_VERSION
            or manifest["counts"] != EXPECTED_COUNTS
            or len(base) != EXPECTED_COUNTS["base"]
            or len({site.id for site in base}) != len(base)
        ):
            raise PolarDataError("ATS cohort version or counts differ from its fixed contract")
        source = manifest["source"]
        if (
            source["dataset_id"] != "ats-hsm"
            or source["uri"] != SOURCE_URI
            or source["query_uri"] != QUERY_URI
            or source["query_method"] != "POST"
            or source["query_body"] != {}
            or source["sha256"] != QUERY_SHA256
            or source["query_sha256"] != QUERY_SHA256
            or source["license"] != LICENSE
            or source["license_uri"] != LICENSE_URI
            or source["attribution"] != "Antarctic Treaty Secretariat"
            or source["copyright_uri"] != COPYRIGHT_URI
            or source["copyright_sha256"] != COPYRIGHT_SHA256
            or source["accessed"] != ACCESSED
            or source["modified"] is not None
        ):
            raise PolarDataError("ATS source license, authority or fixed snapshot differs")
        pins = _detail_pins(source["details_sha256_by_hsm_number"])
        if manifest["regions"] != [REGION] or manifest["selection"] != {
            "type_id": 1,
            "type_name": "HSM",
            "is_de_designated": False,
            "order": "ascending integer HSM number",
            "media": "excluded",
        }:
            raise PolarDataError("ATS selection or source-specific region contract differs")
        expected_ids = [f"ats:hsm:{number}" for number in ACTIVE_NUMBERS]
        partition = manifest["partition"]
        if partition != {
            "active_ids": expected_ids,
            "active_numbers": list(ACTIVE_NUMBERS),
            "numbers_absent": list(ABSENT_NUMBERS),
            "excluded_types": {"ASPA": 84, "ASMA": 7},
            "unknown_location_ids": ["ats:hsm:95"],
            "outside_web_mercator_ids": ["ats:hsm:1", "ats:hsm:24", "ats:hsm:80"],
        }:
            raise PolarDataError("ATS active/unknown/projection identity partitions differ")
        path = data_dir / "polar_sites.json"
        if (
            _sha256(path) != SITES_SHA256
            or manifest["files"]["polar_sites.json"]["sha256"] != SITES_SHA256
        ):
            raise PolarDataError("ATS normalized site checksum mismatch")
        sites = [Site.model_validate(row) for row in json.loads(path.read_text("utf-8"))]
        if [site.id for site in sites] != expected_ids or set(expected_ids) & {
            site.id for site in base
        }:
            raise PolarDataError("ATS site identities differ or duplicate the earlier corpus")
        records = manifest["records"]
        if len(records) != len(sites) or (
            hashlib.sha256(_canonical(records)).hexdigest() != RECORDS_CONTRACT_SHA256
        ):
            raise PolarDataError("ATS source record metadata is incomplete")
        for number, site, record in zip(ACTIVE_NUMBERS, sites, records, strict=True):
            internal_id = record["internal_id"]
            if type(internal_id) is not int or internal_id < 1:
                raise PolarDataError("ATS internal source identifier is invalid")
            expected_ref = _reference(number, internal_id, pins[str(number)], site.title)
            if (
                record["site_id"] != site.id
                or record["hsm_number"] != number
                or record["detail_sha256"] != pins[str(number)]
                or record["detail_uri"] != expected_ref.uri
                or record["detail_api_uri"] != DETAIL_API.format(internal_id=internal_id)
                or site.source_kind != "ats"
                or site.source_uri != expected_ref.uri
                or site.source_refs != [expected_ref]
                or site.types != ["historic-site"]
                or site.periods
                or site.period_evidence
                or site.chronology.status != "not_reviewed"
                or site.chronology.phases
                or site.geography is None
                or site.geography.authority_id != site.id
                or site.geography.countries
                or site.geography.regions != ["antarctica"]
                or site.geography.source != expected_ref
                or site.geography.point_count != (0 if site.repr_point is None else 1)
            ):
                raise PolarDataError(
                    "ATS record source, geography or unreviewed chronology differs"
                )
            location = {"decimal": record["source_decimal"], "dms": record["source_dms"]}
            context = site.details.split("Physical features and context: ", 1)[-1]
            expected_point, method, note = source_location(
                {
                    "number": str(number),
                    "location": location,
                    "physicalFeaturesAndContext": context,
                }
            )
            if site.repr_point != expected_point or record["coordinate_method"] != method:
                raise PolarDataError("ATS point no longer reflects its original source semantics")
            if note not in site.geography.note:
                raise PolarDataError("ATS coordinate scope note is missing or changed")
        if [site.id for site in sites if site.repr_point is None] != partition[
            "unknown_location_ids"
        ]:
            raise PolarDataError("ATS unknown positions have been silently synthesized")
        outside = [
            site.id
            for site in sites
            if site.repr_point is not None and abs(site.repr_point[1]) > MERCATOR_MAX_LATITUDE
        ]
        if outside != partition["outside_web_mercator_ids"]:
            raise PolarDataError("ATS polar source latitudes have been silently clamped")
        return list(base) + sites
    except PolarDataError:
        raise
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise PolarDataError(f"cannot load local ATS HSM cohort: {error}") from error


def _download_file(path: Path, uri: str, digest: str, *, post: bool = False) -> None:
    if path.exists() and _sha256(path) == digest:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="ats-", suffix=".part", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        request = Request(
            uri,
            data=b"{}" if post else None,
            headers={
                "User-Agent": "archsearch-mvp/0.1",
                "Content-Type": "application/json",
            },
        )
        with os.fdopen(descriptor, "wb") as target, urlopen(request, timeout=120) as response:
            size = 0
            for block in iter(lambda: response.read(65536), b""):
                size += len(block)
                if size > 2 * 1024 * 1024:
                    raise PolarDataError("ATS source exceeds its bounded download size")
                target.write(block)
        if _sha256(temporary) != digest:
            raise PolarDataError(
                "ATS source changed from the fixed snapshot; review an explicit update"
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_sources(cache_dir: Path, data_dir: Path = DATA_DIR) -> None:
    """Explicit network preparation with frozen pins; normal serving never calls this function."""
    pins = _read_pins(cache_dir, data_dir)
    _download_file(cache_dir / "ats-apa-search.json", QUERY_URI, QUERY_SHA256, post=True)
    _download_file(cache_dir / "ats-copyright.html", COPYRIGHT_URI, COPYRIGHT_SHA256)
    rows = json.loads((cache_dir / "ats-apa-search.json").read_text("utf-8"))
    internal = {row["number"]: row["id"] for row in rows if row["type"]["id"] == 1}

    def fetch(number: str) -> None:
        _download_file(
            cache_dir / f"ats-hsm-{number}-detail.json",
            DETAIL_API.format(internal_id=internal[number]),
            pins[number],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch, pins))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--source-cache", type=Path, default=Path(".archsearch/downloads/ats-hsm-v1")
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    if args.download:
        download_sources(args.source_cache, args.data_dir)
    if args.rebuild:
        print(json.dumps(rebuild_polar(args.source_cache, args.data_dir)["counts"]))
    else:
        manifest = json.loads((args.data_dir / "polar_manifest.json").read_text("utf-8"))
        if (
            _sha256(args.data_dir / "polar_sites.json")
            != manifest["files"]["polar_sites.json"]["sha256"]
        ):
            raise PolarDataError("ATS normalized site checksum mismatch")
        print(json.dumps(manifest["counts"]))


if __name__ == "__main__":
    main()

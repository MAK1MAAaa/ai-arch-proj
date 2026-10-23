"""Load the bundled corpus offline or rebuild it from a fixed Pleiades release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import tarfile
from collections import Counter
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import TypeAdapter, ValidationError

from archsearch.domain import PeriodEvidence, Site

DATA_DIR = Path(__file__).with_name("data")
DATASET_VERSION = "v4.1"
SOURCE_COMMIT = "b6a6790f71c45e4a4ef60fce296c506f28f458bf"
ARCHIVE_URL = "https://codeload.github.com/isawnyu/pleiades.datasets/tar.gz/refs/tags/v4.1"
CORPUS_SIZE = 500
BOUNDING_BOX = (-6.0, 29.0, 37.0, 46.0)
ALLOWED_TYPES = frozenset({"settlement", "villa", "port", "bath", "theatre", "archaeological-site"})
SAMPLE_PREFIX = "mvp-v1:"
_SITES_ADAPTER = TypeAdapter(list[Site])


class CorpusError(RuntimeError):
    """A local corpus artifact is absent, inconsistent, or invalid."""


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.suppressed_depth += 1
        elif tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.suppressed_depth = max(0, self.suppressed_depth - 1)
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parser = _PlainTextParser()
    parser.feed(value)
    return " ".join(html.unescape("".join(parser.parts)).split())


def _strings(values: Iterable[Any]) -> list[str]:
    return sorted({text for value in values if (text := _text(value))})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _period_id(attestation: dict[str, Any]) -> str:
    uri = attestation.get("timePeriodURI")
    if isinstance(uri, str) and uri:
        return urlsplit(uri).path.rstrip("/").rsplit("/", 1)[-1]
    return _text(attestation.get("timePeriod"))


def _evidence(place: dict[str, Any]) -> list[PeriodEvidence]:
    evidence: list[PeriodEvidence] = []
    collections: tuple[tuple[str, Literal["Name", "Location"]], ...] = (
        ("names", "Name"),
        ("locations", "Location"),
    )
    for collection, resource_type in collections:
        for resource in place.get(collection, []):
            resource_uri = resource.get("uri")
            if not isinstance(resource_uri, str) or not resource_uri.startswith(
                ("https://", "http://")
            ):
                continue
            for attestation in resource.get("attestations", []):
                period_uri = attestation.get("timePeriodURI")
                period_id = _period_id(attestation)
                if (
                    not period_id
                    or not isinstance(period_uri, str)
                    or not period_uri.startswith(("https://", "http://"))
                ):
                    continue
                evidence.append(
                    PeriodEvidence(
                        resource_type=resource_type,
                        resource_uri=resource_uri,
                        period_id=period_id,
                        period_uri=period_uri,
                        confidence=attestation.get("confidence") or None,
                        association_certainty=resource.get("associationCertainty") or None,
                        start=resource.get("start"),
                        end=resource.get("end"),
                    )
                )
    unique = {item.model_dump_json(): item for item in evidence}
    return sorted(
        unique.values(),
        key=lambda item: (item.resource_uri, item.period_uri, item.confidence or ""),
    )


def _contributors(place: dict[str, Any]) -> list[str]:
    resources = [place, *place.get("names", []), *place.get("locations", [])]
    return _strings(
        person.get("name")
        for resource in resources
        for field in ("creators", "contributors")
        for person in resource.get(field, [])
    )


def normalize_place(place: dict[str, Any], precision: str | None = None) -> Site | None:
    """Normalize one eligible place without translating or synthesizing metadata."""
    evidence = _evidence(place)
    if not any(item.period_id == "roman" for item in evidence):
        return None
    title = _text(place.get("title"))
    names = _strings(
        name.get(field)
        for name in place.get("names", [])
        for field in ("title", "attested", "romanized")
    )
    normalized_precision: Literal["precise", "rough"] | None = None
    if precision == "precise":
        normalized_precision = "precise"
    elif precision == "rough":
        normalized_precision = "rough"
    return Site(
        id=str(place["id"]),
        title=title,
        description=_text(place.get("description")),
        details=_text(place.get("details")),
        names=[name for name in names if name != title],
        types=_strings(place.get("placeTypes", [])),
        periods=sorted({item.period_id for item in evidence}),
        repr_point=place["reprPoint"],
        location_precision=normalized_precision,
        source_uri=place["uri"],
        contributors=_contributors(place),
        period_evidence=evidence,
    )


def build_document(site: Site) -> str:
    """Return the exact same English source document for lexical and dense search."""
    parts = [site.title, "; ".join(site.names), site.description, site.details]
    parts.extend(("Types: " + ", ".join(site.types), "Periods: " + ", ".join(site.periods)))
    return "\n".join(part for part in parts if part)


def load_corpus(data_dir: Path | None = None) -> list[Site]:
    """Load and verify bundled artifacts; never download data or models."""
    directory = Path(data_dir) if data_dir is not None else DATA_DIR
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise CorpusError("unsupported corpus schema version")
        if (
            manifest["source"]["version"] != DATASET_VERSION
            or manifest["source"]["commit"] != SOURCE_COMMIT
            or manifest["selection"]["bbox"] != list(BOUNDING_BOX)
            or manifest["selection"]["allowed_types"] != sorted(ALLOWED_TYPES)
        ):
            raise CorpusError("manifest does not match the configured release and selection")
        for filename in ("sites.json", "site_ids.json"):
            actual = _sha256_file(directory / filename)
            if actual != manifest["files"][filename]["sha256"]:
                raise CorpusError(f"corpus checksum mismatch: {filename}")
        sites = _SITES_ADAPTER.validate_json((directory / "sites.json").read_bytes())
        ids = json.loads((directory / "site_ids.json").read_text(encoding="utf-8"))
        if len(sites) != CORPUS_SIZE or manifest["counts"]["selected"] != CORPUS_SIZE:
            raise CorpusError(f"corpus must contain exactly {CORPUS_SIZE} sites")
        if len({site.id for site in sites}) != CORPUS_SIZE:
            raise CorpusError("corpus contains duplicate place identifiers")
        if ids != [site.id for site in sites]:
            raise CorpusError("site_ids.json does not match the corpus order")
        for site in sites:
            lon, lat = site.repr_point
            if not (
                BOUNDING_BOX[0] <= lon <= BOUNDING_BOX[2]
                and BOUNDING_BOX[1] <= lat <= BOUNDING_BOX[3]
            ):
                raise CorpusError(
                    f"site {site.id} lies outside the configured demonstration rectangle"
                )
            if not ALLOWED_TYPES.intersection(site.types):
                raise CorpusError(f"site {site.id} has no allowed archaeological place type")
        return sites
    except CorpusError:
        raise
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CorpusError(f"cannot load local corpus from {directory}: {exc}") from exc


def _archive_members(archive_path: Path) -> Iterable[tuple[str, bytes]]:
    """Read regular JSON/CSV members without extracting any archive paths."""
    with tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            path = member.name.replace("\\", "/")
            if not member.isfile() or not (
                "/data/json/" in path
                and path.endswith(".json")
                or path.endswith("/data/gis/places.csv")
            ):
                continue
            if member.size > 32 * 1024 * 1024:
                raise CorpusError(f"unexpected oversized archive member: {path}")
            source = archive.extractfile(member)
            if source is not None:
                yield path, source.read()


def rebuild_corpus(archive_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Rebuild the deterministic 500-place corpus from the fixed release archive."""
    directory = Path(output_dir) if output_dir is not None else DATA_DIR
    archive_path = Path(archive_path)
    archive_sha256 = _sha256_file(archive_path)
    baseline_path = DATA_DIR / "manifest.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if archive_sha256 != baseline["source"]["archive_sha256"]:
            raise CorpusError(
                "source archive checksum differs from the pinned Pleiades v4.1 archive"
            )
    precisions: dict[str, str] = {}
    for name, payload in _archive_members(archive_path):
        if name.endswith("/data/gis/places.csv"):
            precisions = {
                row["id"]: row["location_precision"]
                for row in csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
            }
            break
    if not precisions:
        raise CorpusError("archive has no GIS place precision table")
    counts: Counter[str] = Counter(
        {
            key: 0
            for key in (
                "total_places",
                "rejected_no_representative_point",
                "rejected_outside_bbox",
                "rejected_disallowed_type",
                "rejected_no_roman_evidence",
                "eligible",
                "selected",
                "eligible_not_selected",
            )
        }
    )
    candidates: list[tuple[str, Site]] = []
    for name, payload in _archive_members(archive_path):
        if not name.endswith(".json"):
            continue
        place = json.loads(payload)
        counts["total_places"] += 1
        point = place.get("reprPoint")
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)
        ):
            counts["rejected_no_representative_point"] += 1
            continue
        lon, lat = point
        if not (
            BOUNDING_BOX[0] <= lon <= BOUNDING_BOX[2] and BOUNDING_BOX[1] <= lat <= BOUNDING_BOX[3]
        ):
            counts["rejected_outside_bbox"] += 1
            continue
        if not ALLOWED_TYPES.intersection(place.get("placeTypes", [])):
            counts["rejected_disallowed_type"] += 1
            continue
        site = normalize_place(place, precisions.get(str(place["id"])))
        if site is None:
            counts["rejected_no_roman_evidence"] += 1
            continue
        rank = hashlib.sha256((SAMPLE_PREFIX + site.id).encode("utf-8")).hexdigest()
        candidates.append((rank, site))
    candidates.sort(key=lambda item: (item[0], item[1].id))
    sites = [site for _, site in candidates[:CORPUS_SIZE]]
    if len(sites) != CORPUS_SIZE:
        raise CorpusError(f"only {len(sites)} eligible sites; expected {CORPUS_SIZE}")
    counts.update(
        eligible=len(candidates),
        selected=len(sites),
        eligible_not_selected=len(candidates) - len(sites),
    )
    artifacts = {
        "sites.json": _json_bytes([site.model_dump(mode="json") for site in sites]),
        "site_ids.json": _json_bytes([site.id for site in sites]),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "name": "Pleiades: A Gazetteer of Past Places",
            "version": DATASET_VERSION,
            "commit": SOURCE_COMMIT,
            "release_date": "2025-05-28",
            "archive_url": ARCHIVE_URL,
            "archive_sha256": archive_sha256,
            "release_uri": "https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1",
            "license": "CC BY 3.0",
            "license_uri": "https://creativecommons.org/licenses/by/3.0/",
            "attribution": (
                "Copyright The Contributors. Pleiades, Ancient World Mapping Center "
                "and Institute for the Study of the Ancient World."
            ),
            "contributors": _strings(person for site in sites for person in site.contributors),
        },
        "selection": {
            "bbox": list(BOUNDING_BOX),
            "bbox_order": "west,south,east,north; WGS84 longitude/latitude",
            "geographic_scope": (
                "Mediterranean and surroundings demonstration rectangle; not a historical boundary"
            ),
            "allowed_types": sorted(ALLOWED_TYPES),
            "required_period": "roman",
            "period_label": "Roman, early Empire (30 BC-AD 300)",
            "period_uri": "https://pleiades.stoa.org/vocabularies/time-periods/roman",
            "period_evidence_resources": ["names", "locations"],
            "required_evidence": (
                "source resource URI and time-period URI; connections alone never qualify"
            ),
            "ranking": "ascending SHA256(UTF-8('mvp-v1:' + place_id)), then ascending place_id",
            "limit": CORPUS_SIZE,
            "processing": (
                "HTML-to-text cleanup and whitespace normalization; aliases/types/attestations "
                "preserved; no generated translations or coordinates"
            ),
            "precision_source": (
                "Pleiades v4.1 data/gis/places.csv location_precision; null if unavailable"
            ),
        },
        "counts": dict(sorted(counts.items())),
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "records": len(sites)}
            for name, payload in artifacts.items()
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in {**artifacts, "manifest.json": _json_bytes(manifest)}.items():
        temporary = directory / (name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(directory / name)
    load_corpus(directory)
    return manifest


def download_archive(destination: Path) -> Path:
    """Download the one public release archive explicitly during preparation."""
    destination = Path(destination)
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = Request(ARCHIVE_URL, headers={"User-Agent": "archsearch-mvp/0.1"})
    with urlopen(request, timeout=120) as response, temporary.open("wb") as target:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            target.write(block)
    temporary.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild", action="store_true", help="rebuild from the fixed Pleiades archive"
    )
    parser.add_argument(
        "--download", action="store_true", help="allow downloading the archive if absent"
    )
    parser.add_argument(
        "--archive", type=Path, default=Path(".archsearch/downloads/pleiades-v4.1.tar.gz")
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    arguments = parser.parse_args()
    if arguments.rebuild:
        archive = download_archive(arguments.archive) if arguments.download else arguments.archive
        manifest = rebuild_corpus(archive, arguments.data_dir)
        print(json.dumps(manifest["counts"], sort_keys=True))
    else:
        print(f"Verified {len(load_corpus(arguments.data_dir))} local Pleiades records.")


if __name__ == "__main__":
    main()

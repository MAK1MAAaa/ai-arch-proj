"""Source traceability, deterministic preparation, and offline integrity checks."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from archsearch import corpus
from archsearch.corpus import CorpusError, build_document, load_corpus, normalize_place


def example_place(identifier: str = "123") -> dict[str, Any]:
    source = f"https://pleiades.stoa.org/places/{identifier}"
    return {
        "id": identifier,
        "uri": source,
        "title": "Ancient Harbor",
        "description": "<p>A Roman <strong>harbor</strong>.</p><script>untrusted()</script>",
        "details": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "placeTypes": ["port"],
        "reprPoint": [12.0, 35.0],
        "contributors": [{"name": "An Editor"}],
        "creators": [{"name": "An Author"}],
        "names": [
            {
                "uri": source + "/portus",
                "title": "Portus",
                "romanized": "Portus",
                "attested": "PORTVS",
                "start": -30,
                "end": 300,
                "associationCertainty": "certain",
                "attestations": [
                    {
                        "timePeriod": "roman",
                        "timePeriodURI": "https://pleiades.stoa.org/vocabularies/time-periods/roman",
                        "confidence": "less-confident",
                    }
                ],
            }
        ],
        "locations": [],
        "connections": [],
    }


def copy_corpus(destination: Path) -> None:
    destination.mkdir()
    for filename in ("sites.json", "site_ids.json", "manifest.json"):
        (destination / filename).write_bytes((corpus.DATA_DIR / filename).read_bytes())


def replace_artifact(directory: Path, filename: str, value: Any) -> None:
    path = directory / filename
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_bundled_corpus_is_offline_verified_and_source_traceable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def disallow_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("load_corpus must not access the network")

    monkeypatch.setattr(corpus, "urlopen", disallow_network)
    sites = corpus.load_pleiades_corpus()
    assert len(sites) == len({site.id for site in sites}) == 500
    ranks = [hashlib.sha256(("mvp-v1:" + site.id).encode()).hexdigest() for site in sites]
    assert ranks == sorted(ranks)
    for site in sites:
        assert site.source_uri.endswith("/" + site.id)
        assert any(item.period_id == "roman" for item in site.period_evidence)
        assert corpus.ALLOWED_TYPES.intersection(site.types)
        assert all(item.resource_type in {"Name", "Location"} for item in site.period_evidence)
        assert all(item.resource_uri and item.period_uri for item in site.period_evidence)
        assert site.title in build_document(site)


def test_normalization_retains_source_metadata_without_inventing_precision() -> None:
    site = normalize_place(example_place())
    assert site is not None
    assert site.description == "A Roman harbor."
    assert site.details == "First paragraph. Second paragraph."
    assert site.names == ["PORTVS", "Portus"]
    assert site.contributors == ["An Author", "An Editor"]
    assert site.location_precision is None
    assert site.period_evidence[0].confidence == "less-confident"
    assert site.period_evidence[0].start == -30
    assert "untrusted" not in build_document(site)
    assert not build_document(site).startswith("passage:")


def test_connection_or_title_alone_cannot_establish_roman_period() -> None:
    place = example_place()
    place["connections"] = copy.deepcopy(place["names"])
    place["names"] = []
    assert normalize_place(place) is None


def test_period_selection_uses_source_uri_over_conflicting_label() -> None:
    place = example_place()
    place["names"][0]["attestations"][0]["timePeriodURI"] = (
        "https://pleiades.stoa.org/vocabularies/time-periods/classical"
    )
    assert normalize_place(place) is None


def test_checksum_detects_modified_data(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    copy_corpus(directory)
    with (directory / "sites.json").open("ab") as artifact:
        artifact.write(b" ")
    with pytest.raises(CorpusError, match="checksum mismatch"):
        load_corpus(directory)


def test_schema_detects_invalid_coordinates_even_with_updated_checksum(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    copy_corpus(directory)
    sites = json.loads((directory / "sites.json").read_text(encoding="utf-8"))
    sites[0]["repr_point"] = [12.0, 91.0]
    replace_artifact(directory, "sites.json", sites)
    with pytest.raises(CorpusError, match="WGS84"):
        load_corpus(directory)


def test_duplicate_ids_and_id_order_are_verified(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    copy_corpus(directory)
    sites = json.loads((directory / "sites.json").read_text(encoding="utf-8"))
    sites[1] = copy.deepcopy(sites[0])
    replace_artifact(directory, "sites.json", sites)
    replace_artifact(directory, "site_ids.json", [site["id"] for site in sites])
    with pytest.raises(CorpusError, match="duplicate"):
        load_corpus(directory)


def write_fixture_archive(path: Path, places: list[dict[str, Any]]) -> None:
    csv_lines = ["id,location_precision", *(f"{place['id']},rough" for place in places)]
    members = [("release/data/gis/places.csv", "\n".join(csv_lines).encode())]
    members.extend(
        (f"release/data/json/{place['id']}.json", json.dumps(place).encode()) for place in places
    )
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        symlink = tarfile.TarInfo("release/data/json/symlink.json")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "../../outside.json"
        archive.addfile(symlink)


def test_rebuild_is_deterministic_and_reports_filter_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corpus, "DATA_DIR", tmp_path / "unconfigured-baseline")
    monkeypatch.setattr(corpus, "CORPUS_SIZE", 2)
    places = [example_place(str(identifier)) for identifier in range(1, 8)]
    places[3]["reprPoint"] = None
    places[4]["reprPoint"] = [80, 35]
    places[5]["placeTypes"] = ["river"]
    places[6]["names"] = []
    first_archive = tmp_path / "first.tar.gz"
    second_archive = tmp_path / "second.tar.gz"
    write_fixture_archive(first_archive, places)
    write_fixture_archive(second_archive, list(reversed(places)))
    first = corpus.rebuild_corpus(first_archive, tmp_path / "first")
    second = corpus.rebuild_corpus(second_archive, tmp_path / "second")
    assert first["files"] == second["files"]
    assert first["counts"] == {
        "eligible": 3,
        "eligible_not_selected": 1,
        "rejected_disallowed_type": 1,
        "rejected_no_representative_point": 1,
        "rejected_no_roman_evidence": 1,
        "rejected_outside_bbox": 1,
        "selected": 2,
        "total_places": 7,
    }
    assert all(site.location_precision == "rough" for site in load_corpus(tmp_path / "first"))
    rebuilt = json.loads((tmp_path / "first" / "sites.json").read_text("utf-8"))
    assert all("chronology" not in site and "source_kind" not in site for site in rebuilt)
    assert not (tmp_path / "outside.json").exists()

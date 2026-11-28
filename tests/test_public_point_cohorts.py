"""Public point additions preserve the frozen corpus and are reachable in the API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch.api import create_app
from archsearch.corpus import CORPUS_VERSION, load_corpus, load_guyana_corpus
from archsearch.domain import Site
from archsearch.target_data import DATA_DIR, IRELAND, load_targets, rebuild_targets


@pytest.fixture(scope="module")
def sites() -> list[Site]:
    return load_corpus()


def test_irish_points_rebuild_and_preserve_the_original_corpus(
    sites: list[Site], tmp_path: Path,
) -> None:
    base = load_guyana_corpus()
    assert len(base) == 3905 and sites[:len(base)] == base
    review, points, manifest = IRELAND.filenames
    (tmp_path / review).write_bytes((DATA_DIR / review).read_bytes())
    assert rebuild_targets(base, tmp_path, cohort=IRELAND)["counts"] == {
        "added": 90, "total": 3995,
    }
    for filename in (points, manifest):
        assert (tmp_path / filename).read_bytes() == (DATA_DIR / filename).read_bytes()
    rebuilt = load_targets(base, tmp_path, cohort=IRELAND)
    assert rebuilt == sites[:3995]
    additions = rebuilt[len(base):]
    assert len({site.repr_point for site in additions}) == 90
    assert all(site.geography and site.geography.countries == ["IE"] for site in additions)
    assert all(
        site.repr_point is not None and site.location_precision is None for site in additions
    )
    assert all(
        site.chronology.status == "insufficient" and not site.chronology.phases
        for site in additions
    )
    assert {"auth:ie-nms:KE11684", "auth:ie-nms:ME00960", "auth:ie-nms:ME00980",
            "auth:ie-nms:KK01310"}.isdisjoint(site.id for site in additions)


def test_public_point_search_catalogue_and_provenance(
    sites: list[Site], tmp_path: Path,
) -> None:
    with TestClient(create_app(home=tmp_path, sites=sites)) as client:
        catalogue = client.get("/api/catalogue?country=IE").json()
        assert catalogue["corpus_version"] == CORPUS_VERSION
        assert catalogue["total"] == 92
        identifier = "auth:ie-nms:CL00184"
        point = next(row for row in catalogue["points"] if row["id"] == identifier)
        assert point["repr_point"] == [-9.054012677, 53.12691394]
        result = client.post("/api/search", json={
            "query": "Corcomroe Abbey", "mode": "bm25", "country": "IE",
        }).json()
        assert result["results"][0]["site"]["id"] == identifier
        detail = client.get("/api/sites/" + identifier)
        assert detail.headers["x-archsearch-corpus-version"] == CORPUS_VERSION
        assert detail.json()["source_refs"][0]["license"] == "CC BY 4.0"
        ireland = client.get("/api/subdivisions?country=IE").json()
        assert ireland["ready"] and not ireland["supported"]
        assert ireland["assigned"] == 0 and ireland["unassigned"] == 92

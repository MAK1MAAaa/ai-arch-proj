"""Independent source geometry labels, failures and original-ring snapshots."""

from __future__ import annotations

from pathlib import Path

from archsearch.coverage import SpatialSource
from archsearch.registered_areas import (
    LABEL,
    POLYGON_LABEL,
    AreaSourceGroup,
    RegisteredArea,
    RegisteredAreasIndex,
)


def feature(site_id: str, oid: int) -> RegisteredArea:
    return RegisteredArea(
        id=f"{site_id}:OBJECTID:{oid}", source_index=0, provider_object_id=oid,
        title="Original fixture shape", source=SpatialSource(
            name="Fixture publisher", uri="https://example.org/public/query",
            version="fixture-public-v1", sha256="a" * 64,
            license="Fixture source terms", license_uri="https://example.org/terms",
        ), rings=[[(114.0, 22.0), (114.1, 22.0), (114.0, 22.1), (114.0, 22.0)]],
    )


def test_different_geometry_sources_retain_their_own_labels_and_original_rings(
    tmp_path: Path,
) -> None:
    au, hk = feature("auth:fixture:au", 1), feature("auth:fixture:hk", 2)
    groups = [
        AreaSourceGroup("fixture-au-v1", LABEL, "Publisher registration extent.",
                        frozenset({"auth:fixture:au"}), {"auth:fixture:au": [au]}),
        AreaSourceGroup("fixture-hk-v1", POLYGON_LABEL, "Not an asserted legal boundary.",
                        frozenset({"auth:fixture:hk", "auth:fixture:without-shape"}),
                        {"auth:fixture:hk": [hk]}),
    ]
    index = RegisteredAreasIndex(tmp_path, sources=groups)
    status = index.status()
    assert status.ready and status.label == "来源公开范围"
    assert status.version == "fixture-au-v1+fixture-hk-v1"
    assert (status.sites, status.features, status.rings, status.coordinate_records) == (2, 2, 2, 8)
    assert index.response("auth:fixture:au", "corpus").label == LABEL
    response = index.response("auth:fixture:hk", "corpus")
    assert response.label == POLYGON_LABEL and "Not an asserted" in response.note
    assert response.features[0].rings == hk.rings
    response.features[0].rings[0].pop()
    hk.rings[0].pop()
    assert len(index.response("auth:fixture:hk", "corpus").features[0].rings[0]) == 4
    empty = index.response("auth:fixture:without-shape", "corpus")
    assert empty.ready and empty.features == [] and empty.label == POLYGON_LABEL


def test_failed_source_keeps_another_provider_available(tmp_path: Path) -> None:
    au = feature("auth:fixture:au", 1)
    index = RegisteredAreasIndex(tmp_path, sources=[
        AreaSourceGroup("fixture-au-v1", LABEL, "Original extent.",
                        frozenset({"auth:fixture:au"}), {"auth:fixture:au": [au]}),
        AreaSourceGroup("fixture-hk-v1", POLYGON_LABEL, "Polygon, not a legal extent.",
                        frozenset({"auth:fixture:hk"}), {}, ready=False,
                        reason="Fixed polygon cache is missing; rebuild it."),
    ])
    assert not index.status().ready and index.status().features == 1
    assert index.response("auth:fixture:au", "v").ready
    assert len(index.response("auth:fixture:au", "v").features) == 1
    failed = index.response("auth:fixture:hk", "v")
    assert not failed.ready and failed.features == [] and failed.label == POLYGON_LABEL
    assert failed.reason and "rebuild" in failed.reason
    assert failed.version == index.status().version == "fixture-au-v1"
    unrelated = index.response("auth:fixture:other-country", "v")
    assert unrelated.ready and unrelated.reason is None and unrelated.features == []
    assert unrelated.label == "来源公开范围" and "未采用" in unrelated.note


def test_conflicting_source_cannot_replace_another_providers_identity(tmp_path: Path) -> None:
    original, other = feature("auth:fixture:au", 1), feature("auth:fixture:au", 2)
    index = RegisteredAreasIndex(tmp_path, sources=[
        AreaSourceGroup("fixture-au-v1", LABEL, "Original extent.",
                        frozenset({"auth:fixture:au"}), {"auth:fixture:au": [original]}),
        AreaSourceGroup("fixture-hk-v1", POLYGON_LABEL, "Unapproved identity conflict.",
                        frozenset({"auth:fixture:au", "auth:fixture:hk"}),
                        {"auth:fixture:au": [other]}),
    ])
    assert not index.status().ready
    au = index.response("auth:fixture:au", "v")
    assert au.ready and au.features[0].provider_object_id == 1 and au.label == LABEL
    hk = index.response("auth:fixture:hk", "v")
    assert not hk.ready and hk.label == POLYGON_LABEL and hk.features == []

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

        spain = client.get("/api/catalogue?country=ES").json()
        assert spain["total"] == 69
        assert sum(point["id"].startswith("auth:es-dera:") for point in spain["points"]) == 23
        taiwan = client.get("/api/catalogue?country=TW").json()
        assert taiwan["total"] == len(taiwan["points"]) == 54
        assert all(point["id"].startswith("auth:tw-moc:") for point in taiwan["points"])
        countries = client.get("/api/coverage").json()["countries"]
        assert {"id": "TW", "label": "Taiwan", "count": 54} in countries
        detail = client.get("/api/sites/auth:tw-moc:19831228000008").json()
        assert detail["title"] == "赤嵌樓"
        assert detail["chronology"]["phases"] == []
        assert all(
            source["license"] == "Open Government Data License, version 1.0"
            for source in detail["source_refs"]
        )

        mexico = client.get("/api/catalogue?country=MX").json()
        assert mexico["total"] == 155
        assert sum(point["id"].startswith("auth:mx-sic:") for point in mexico["points"]) == 124
        vallecito = client.get("/api/sites/auth:mx-sic:1").json()
        assert vallecito["title"] == "El Vallecito"
        assert vallecito["repr_point"] == [-116.09759, 32.53888]
        assert [source["license"] for source in vallecito["source_refs"]] == [
            "SIC open data attribution terms", "CC BY 4.0",
        ]

        for country, prefix, count in (
            ("FI", "auth:fi-vark:", 11),
            ("GB", "auth:gb-cadw:", 111),
            ("TH", "auth:th-fad:", 17),
            ("GB", "auth:gb-hes-pic:", 31),
            ("PR", "auth:nps-caribbean:", 5),
            ("VI", "auth:nps-caribbean:", 2),
            ("PE", "auth:pe-mincul:", 9),
            ("IN", "auth:in-public:", 46),
            ("LK", "auth:lk-public:", 4),
            ("BD", "auth:bd-public:", 6),
            ("NP", "auth:np-public:", 2),
            ("PK", "auth:pk-public:", 5),
            ("CR", "auth:public-americas:cr-", 4),
            ("PA", "auth:public-americas:pa-", 1),
            ("CO", "auth:public-americas:co-", 4),
            ("CL", "auth:public-americas:cl-", 6),
            ("AR", "auth:public-americas:ar-", 2),
            ("NZ", "auth:nz-public:", 25),
            ("EG", "auth:eg-public:", 19),
            ("VN", "auth:vn-public:", 19),
            ("KH", "auth:kh-public:", 9),
            ("TT", "auth:tt-public:", 3),
            ("KN", "auth:kn-public:", 2),
            ("TN", "auth:tn-public:", 8),
            ("MA", "auth:ma-public:", 8),
            ("BZ", "auth:bz-public:", 8),
            ("GT", "auth:gt-public:", 8),
            ("HN", "auth:hn-public:", 5),
            ("SV", "auth:sv-public:", 4),
            ("TO", "auth:to-public:", 2),
            ("WS", "auth:ws-public:", 2),
            ("FJ", "auth:fj-public:", 2),
            ("VU", "auth:vu-public:", 2),
            ("TZ", "auth:tz-public:", 5),
            ("UG", "auth:ug-public:", 8),
            ("KE", "auth:ke-public:", 6),
            ("UY", "auth:uy-public:", 11),
            ("PY", "auth:py-public:", 5),
            ("KZ", "auth:kz-public:", 3),
            ("UZ", "auth:uz-public:", 8),
            ("GB", "auth:gb-nhle:", 29),
            ("EC", "auth:ec-public:", 2),
            ("BO", "auth:bo-public:", 3),
            ("BR", "auth:br-public:", 3),
            ("GY", "auth:gy-public:", 3),
            ("NO", "auth:no-askeladden:", 8),
        ):
            points = client.get(f"/api/catalogue?country={country}").json()["points"]
            added = [point for point in points if point["id"].startswith(prefix)]
            assert len(added) == count
            assert all(point["repr_point"] is not None for point in added)
        assert client.get("/api/sites/auth:gb-cadw:PE373").status_code == 404
        assert client.get("/api/sites/auth:fi-vark:100270").status_code == 404
        assert client.get("/api/sites/auth:gb-hes-pic:PIC077").status_code == 404
        lochleven = client.get("/api/sites/auth:gb-hes-pic:PIC030").json()
        assert lochleven["repr_point"] == [-3.3921612556552567, 56.20086363535327]
        assert lochleven["source_refs"][0]["license"] == "UK Open Government Licence v3.0"
        malindi = client.get("/api/sites/wd:Q42840468").json()
        assert malindi["repr_point"] == [40.12965, -3.22395]
        assert malindi["geography"]["countries"] == ["KE"]
        assert malindi["chronology"]["status"] == "insufficient"
        assert {"id": "PR", "label": "Puerto Rico", "count": 5} in countries
        assert {"id": "VI", "label": "United States Virgin Islands", "count": 2} in countries
        lighthouse = client.get("/api/sites/auth:nps-caribbean:81000560").json()
        assert lighthouse["repr_point"] == [-67.270805, 18.361977777777778]
        assert client.get("/api/sites/auth:nps-caribbean:97001269").status_code == 404
        tucume = client.get("/api/sites/auth:pe-mincul:350").json()
        assert tucume["title"] == "Museo de Sitio Túcume"
        assert tucume["source_refs"][1]["license"] == "CC0"
        island = client.get("/api/sites/auth:in-public:Q749108").json()
        assert island["repr_point"] == [79.23930405, 16.52031987]
        assert "水库岛" in island["description_zh"] and "迁建" in island["description_zh"]
        ritigala = client.get("/api/sites/auth:lk-public:Q126650014").json()
        assert ritigala["repr_point"] == [80.66461, 8.11834]
        assert ritigala["chronology"]["phases"] == []
        katas_raj = client.get("/api/sites/auth:pk-public:Q3629175").json()
        assert "organized pilgrimage admission" in katas_raj["details"]
        cerro = client.get("/api/sites/auth:public-americas:ar-cerro-colorado").json()
        assert cerro["repr_point"] == [-63.92931086, -30.0967002]
        assert cerro["source_refs"][0]["license"] == "IGN free reuse with attribution"
        assert client.get("/api/sites/auth:public-americas:ar-gaboto").status_code == 404
        pencarrow = client.get("/api/sites/auth:nz-public:Q2068609").json()
        assert pencarrow["repr_point"] == [174.849917, -41.35893]
        beni_hasan = client.get("/api/sites/auth:eg-public:Q817286").json()
        assert beni_hasan["repr_point"] == [30.875280555556, 27.931388888889]
        nokor = client.get("/api/sites/auth:kh-public:Q806972").json()
        assert "Banteay Prey Nokor" not in nokor["names"]
        assert client.get("/api/sites/auth:vn-public:Q10825838").status_code == 404
        king_george = client.get("/api/sites/auth:tt-public:geonames-3574520").json()
        assert king_george["repr_point"] == [-60.72697, 11.17777]
        assert client.get("/api/sites/auth:kn-public:Q41575364").status_code == 404
        bulla_regia = client.get("/api/sites/auth:tn-public:Q1004205").json()
        assert bulla_regia["repr_point"] == [8.757016, 36.558893]
        search = client.post("/api/search", json={
            "query": "Bulla Regia", "mode": "bm25", "country": "TN",
        }).json()
        assert search["results"][0]["site"]["id"] == bulla_regia["id"]
        lixus = client.get("/api/sites/auth:ma-public:Q923835").json()
        assert lixus["repr_point"] == [-6.109951512805376, 35.2002398463664]
        assert "M. Euzennat" in lixus["contributors"]
        lubaantun = client.get("/api/sites/auth:bz-public:geonames-3581772").json()
        assert lubaantun["repr_point"] == [-88.95955, 16.28203]
        cook = client.get("/api/sites/auth:to-public:cook-landing-memorial").json()
        assert cook["repr_point"] == [-175.130268, -21.192191]
        assert "CC BY-SA 4.0" in {source["license"] for source in cook["source_refs"]}
        mtoni = client.get("/api/sites/auth:tz-public:geonames-11791590").json()
        assert mtoni["repr_point"] == [39.21337, -6.13553]
        assert client.get("/api/sites/auth:tz-public:geonames-161342").status_code == 404
        olorgesailie = client.get("/api/sites/auth:ke-public:geonames-182034").json()
        assert olorgesailie["repr_point"] == [36.44602, -1.57763]
        assert client.get("/api/sites/auth:ke-public:geonames-193774").status_code == 404
        rivera = client.get("/api/sites/auth:uy-public:Q1046504").json()
        lavalleja = client.get("/api/sites/auth:uy-public:Q1046478").json()
        assert rivera["repr_point"] == [-56.20673, -34.90703]
        assert lavalleja["repr_point"] == [-56.20783333, -34.90630556]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=5441415" in ref["uri"]
            for ref in rivera["source_refs"]
        )
        manzana = client.get("/api/sites/auth:py-public:Q3300173").json()
        assert manzana["repr_point"] == [-57.638192, -25.277991]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=5433614" in ref["uri"]
            for ref in manzana["source_refs"]
        )
        otrar = client.get("/api/sites/auth:kz-public:Q956911").json()
        assert otrar["repr_point"] == [68.3029696, 42.8514829]
        assert otrar["chronology"]["status"] == "insufficient"
        ming_urik = client.get("/api/sites/auth:uz-public:Q122676365").json()
        assert ming_urik["repr_point"] == [69.28598013644901, 41.29831008865522]
        assert ming_urik["source_kind"] == "supplement"
        assert any(ref["license"] == "CC0" for ref in ming_urik["source_refs"])
        dunstanburgh = client.get("/api/sites/auth:gb-nhle:1153477").json()
        assert dunstanburgh["repr_point"] == [-1.595110996673, 55.4893096027667]
        assert any(
            ref["license"] == "UK Open Government Licence v3.0"
            and "Ordnance Survey data" in ref["excerpt"]
            for ref in dunstanburgh["source_refs"]
        )
        whalley = client.get("/api/sites/auth:gb-nhle:1362365").json()
        assert "Its interior is closed" in whalley["details"]
        parliament = client.get("/api/sites/auth:gy-public:Q7138904").json()
        assert any(
            "parliament.gov.gy/about-parliament/access-to-the-public-buildings/" in ref["uri"]
            for ref in parliament["source_refs"]
        )
        assert parliament["chronology"]["phases"] == []
        assert client.get("/api/sites/auth:br-public:Q48884405").status_code == 404
        fredriksten = client.get("/api/sites/auth:no-askeladden:122685").json()
        assert fredriksten["repr_point"] == [11.39722, 59.11981]
        assert {"NLOD 1.0", "CC0"}.issubset(ref["license"] for ref in fredriksten["source_refs"])

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
            ("IN", "auth:in-public:", 51),
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
            ("KN", "auth:kn-public:", 3),
            ("TN", "auth:tn-public:", 8),
            ("MA", "auth:ma-public:", 8),
            ("BZ", "auth:bz-public:", 8),
            ("GT", "auth:gt-public:", 8),
            ("HN", "auth:hn-public:", 5),
            ("SV", "auth:sv-public:", 4),
            ("TO", "auth:to-public:", 2),
            ("WS", "auth:ws-public:", 2),
            ("FJ", "auth:fj-public:", 3),
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
            ("BO", "auth:bo-public:", 7),
            ("AR", "auth:ar-public:", 6),
            ("BR", "auth:br-public:", 3),
            ("GY", "auth:gy-public:", 3),
            ("NO", "auth:no-askeladden:", 8),
            ("JP", "auth:jp-public:", 20),
            ("NA", "auth:na-public:", 5),
            ("BW", "auth:bw-public:", 2),
            ("ZW", "auth:zw-public:", 1),
            ("ZM", "auth:zm-public:", 2),
            ("ID", "auth:id-public:", 19),
            ("KG", "auth:kg-public:", 6),
            ("TJ", "auth:tj-public:", 2),
            ("GB", "auth:gb-dfc-hed:", 60),
            ("SN", "auth:sn-public:", 8),
            ("BJ", "auth:bj-public:", 4),
            ("TG", "auth:tg-public:", 4),
            ("GH", "auth:gh-public:", 5),
            ("NG", "auth:ng-public:", 5),
            ("PH", "auth:ph-public:", 10),
            ("MY", "auth:my-public:", 11),
            ("EE", "auth:ee-kpois:", 11),
            ("LV", "auth:lv-public:", 14),
            ("AL", "auth:al-public:", 12),
            ("MK", "auth:mk-public:", 5),
            ("OM", "auth:om-public:", 6),
            ("BH", "auth:bh-public:", 4),
            ("QA", "auth:qa-public:", 1),
            ("GE", "auth:ge-public:", 10),
            ("AM", "auth:am-public:", 10),
            ("LT", "auth:lt-kvr:", 12),
            ("DK", "auth:dk-public:", 14),
            ("MN", "auth:mn-public:", 8),
            ("PT", "auth:pt-public:", 17),
            ("MD", "auth:md-public:", 10),
            ("RO", "auth:ro-public:", 10),
            ("BM", "auth:bm-public:", 4),
            ("KY", "auth:ky-public:", 2),
            ("NU", "auth:nu-public:", 2),
            ("KR", "auth:kr-khs:", 21),
            ("BG", "auth:bg-public:", 9),
            ("RS", "auth:rs-public:", 10),
            ("RW", "auth:rw-public:", 4),
            ("LA", "auth:la-public:", 9),
            ("BT", "auth:bt-public:", 9),
            ("DZ", "auth:dz-public:", 5),
            ("SE", "auth:se-public:", 26),
            ("SE", "auth:se-raa:", 2),
            ("PL", "auth:pl-public:", 20),
            ("CV", "auth:cv-public:", 4),
            ("CM", "auth:cm-public:", 4),
            ("CO", "auth:co-public:", 6),
            ("VE", "auth:ve-public:", 4),
            ("CN", "auth:cn-public:", 10),
            ("TR", "auth:tr-public:", 13),
            ("MZ", "auth:mz-public:", 3),
            ("AO", "auth:ao-public:", 5),
            ("CZ", "auth:cz-npu:", 28),
            ("SL", "auth:sl-public:", 2),
            ("LR", "auth:lr-public:", 1),
            ("GM", "auth:gm-public:", 3),
            ("MR", "auth:mr-public:", 1),
            ("ML", "auth:ml-public:", 2),
            ("MU", "auth:mu-public:", 4),
            ("SC", "auth:sc-public:", 2),
            ("MG", "auth:mg-public:", 1),
            ("MV", "auth:mv-public:", 1),
            ("AU", "auth:au-ga2012:", 14),
            ("AU", "auth:au-public:", 3),
        ):
            points = client.get(f"/api/catalogue?country={country}").json()["points"]
            added = [point for point in points if point["id"].startswith(prefix)]
            assert len(added) == count
            assert all(point["repr_point"] is not None for point in added)
        assert client.get("/api/sites/auth:gb-cadw:PE373").status_code == 404
        assert client.get("/api/sites/auth:fi-vark:100270").status_code == 404
        assert client.get("/api/sites/auth:gb-hes-pic:PIC077").status_code == 404
        utheemu = client.get("/api/sites/auth:mv-public:utheemu-ganduvaru").json()
        assert utheemu["repr_point"] == [73.11231944444444, 6.8367305555555555]
        assert any(
            source["license"] == "CC BY-SA 4.0"
            and source["publisher"] == "Andreas Faessler via Wikimedia Commons"
            for source in utheemu["source_refs"]
        )
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
        tagajo = client.get("/api/sites/auth:jp-public:Q870867").json()
        assert tagajo["repr_point"] == [140.98833333, 38.30666667]
        assert "多賀城跡" in tagajo["names"]
        assert "reconstructed south gate" in tagajo["details"]
        assert tagajo["chronology"]["phases"] == []
        windhoek_heroes = client.get("/api/sites/auth:na-public:Q5743019").json()
        assert windhoek_heroes["repr_point"] == [17.07820278, -22.66320556]
        assert windhoek_heroes["geography"]["countries"] == ["NA"]
        harare_heroes = client.get("/api/sites/auth:zw-public:Q6973056").json()
        assert harare_heroes["geography"]["countries"] == ["ZW"]
        assert harare_heroes["repr_point"] != windhoek_heroes["repr_point"]
        leang = client.get("/api/sites/auth:id-public:Q19944351").json()
        assert leang["repr_point"] == [119.67572, -4.97922]
        assert leang["chronology"]["status"] == "insufficient"
        goa_gajah = client.get("/api/sites/auth:id-public:Q2037360").json()
        assert goa_gajah["repr_point"] == [115.286333, -8.523389]
        assert "south of the Pekerisan World Heritage component" in goa_gajah["details"]
        koshoy = client.get("/api/sites/auth:kg-public:Q2512688").json()
        assert koshoy["repr_point"] == [75.69861, 41.12372]
        assert any(
            ref["license"] == "CC BY 4.0" and "/11888204/" in ref["uri"]
            for ref in koshoy["source_refs"]
        )
        tynan = client.get("/api/sites/auth:gb-dfc-hed:ARM011-014").json()
        assert tynan["repr_point"] == [-6.82300740947656, 54.3299912169035]
        assert "现展示位置" in tynan["description_zh"]
        assert any(
            ref["publisher"] == "Historic Environment Division, Department for Communities"
            and ref["license"] == "UK Open Government Licence v3.0"
            and "Crown copyright" in ref["excerpt"]
            for ref in tynan["source_refs"]
        )
        maison_wood = client.get("/api/sites/auth:tg-public:Q3279064").json()
        assert maison_wood["repr_point"] == [1.4769309198181217, 6.203787080144058]
        assert "visitor museum" in maison_wood["details"]
        badagry = client.get("/api/sites/auth:ng-public:badagry-heritage-museum").json()
        assert badagry["repr_point"] == [2.889252, 6.412022]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=5394172" in ref["uri"]
            for ref in badagry["source_refs"]
        )
        assert client.get("/api/sites/auth:ng-public:Q107036407").status_code == 404
        tabon = client.get("/api/sites/auth:ph-public:Q477329").json()
        assert tabon["repr_point"] == [117.981, 9.27988]
        assert "appointment" in tabon["details"]
        hose = client.get("/api/sites/auth:my-public:Q131293228").json()
        assert hose["repr_point"] == [114.324739, 4.177099]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=1270866590" in ref["uri"]
            for ref in hose["source_refs"]
        )

        narva = client.get("/api/sites/auth:ee-kpois:14002").json()
        assert narva["repr_point"] == [28.20188898, 59.37551092]
        assert "CC BY 4.0" in {ref["license"] for ref in narva["source_refs"]}
        bauska = client.get("/api/sites/auth:lv-public:6166").json()
        assert bauska["repr_point"] == [24.173611111111, 56.403611111111]
        assert bauska["chronology"]["status"] == "insufficient"

        amantia = client.get("/api/sites/auth:al-public:Q454510").json()
        assert amantia["repr_point"] == [19.70013984739374, 40.379004524474105]
        assert any(
            ref["license"] == "CC BY 3.0" and ref["uri"].endswith("/481715")
            for ref in amantia["source_refs"]
        )
        sunaysilah = client.get("/api/sites/auth:om-public:GN8508062").json()
        assert sunaysilah["repr_point"] == [59.50413, 22.57939]
        assert any(
            ref["license"] == "CC BY 4.0" and "/8508062/" in ref["uri"]
            for ref in sunaysilah["source_refs"]
        )
        palace = client.get("/api/sites/auth:qa-public:Q65117843").json()
        assert palace["title"] == "Old Amiri Palace"
        assert palace["repr_point"] == [51.54830555555555, 25.287916666666668]
        garni = client.get("/api/sites/auth:am-public:Q684072").json()
        assert garni["repr_point"] == [44.73015, 40.11233]
        assert any(
            ref["license"] == "CC BY 4.0" and ref["uri"].endswith("/11336259/about.rdf")
            for ref in garni["source_refs"]
        )
        vardzia = client.get("/api/sites/auth:ge-public:Q691813").json()
        assert vardzia["chronology"]["phases"] == []

        lake_castle = client.get("/api/sites/auth:lt-kvr:29964").json()
        peninsula_castle = client.get("/api/sites/auth:lt-kvr:22719").json()
        assert lake_castle["repr_point"] == [24.93405331102181, 54.65274721961398]
        assert lake_castle["repr_point"] != peninsula_castle["repr_point"]
        assert any(
            ref["license"] == "CC BY 4.0" and "Valstybės duomenų agentūra" in ref["publisher"]
            for ref in lake_castle["source_refs"]
        )
        assert client.get("/api/sites/auth:lt-kvr:3679").status_code == 404
        assert client.get("/api/sites/auth:lt-kvr:24547").status_code == 404
        vordingborg = client.get("/api/sites/auth:dk-public:Q1014431").json()
        assert vordingborg["repr_point"] == [11.9117, 55.0069]
        manzushir = client.get("/api/sites/auth:mn-public:Q148612").json()
        assert manzushir["repr_point"] == [106.99302, 47.76363]
        assert manzushir["chronology"]["phases"] == []
        assert client.get("/api/sites/auth:mn-public:Q2368924").status_code == 404

        escoural = client.get("/api/sites/auth:pt-public:Q1127492").json()
        assert "advance public reservations" in escoural["details"]
        assert any(ref["license"] == "CC0" for ref in escoural["source_refs"])
        cave_monastery = client.get("/api/sites/auth:md-public:Q22915390").json()
        assert cave_monastery["repr_point"] == [28.96821, 47.30287]
        assert "coarse source precision" in cave_monastery["details"]
        pelisor = client.get("/api/sites/auth:ro-public:Q2561653").json()
        assert pelisor["repr_point"] == [25.53915, 45.36057]
        assert "its own ticketed route" in pelisor["details"]

        assert {"id": "BM", "label": "Bermuda", "count": 4} in countries
        assert {"id": "KY", "label": "Cayman Islands", "count": 2} in countries
        talava = client.get("/api/sites/auth:nu-public:talava-arches").json()
        assert talava["repr_point"] == [-169.87741666666668, -18.95925]
        assert any(
            ref["license"] == "Public domain" and "oldid=1100359806" in ref["uri"]
            for ref in talava["source_refs"]
        )
        cottle = client.get("/api/sites/auth:kn-public:Q5175639").json()
        assert cottle["repr_point"] == [-62.596046, 17.196505]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=238882391" in ref["uri"]
            for ref in cottle["source_refs"]
        )
        assert client.get("/api/sites/auth:ky-public:Q5471206").status_code == 404

        osan = client.get("/api/sites/auth:kr-khs:1333203940000").json()
        assert osan["repr_point"] == [128.663051, 38.08718]
        assert "public parking area" in osan["details"]
        assert any(ref["license"] and "15034324" in ref["license"]
                   for ref in osan["source_refs"])
        cheorwon = client.get("/api/sites/auth:kr-khs:4413200220000").json()
        assert cheorwon["repr_point"] == [127.20194444444445, 38.25527777777778]
        assert "public plaza" in cheorwon["details"]
        assert any(ref["license"] == "CC0" for ref in cheorwon["source_refs"])
        nicopolis = client.get("/api/sites/auth:bg-public:Q1987323").json()
        assert nicopolis["repr_point"] == [25.612232, 43.217925]
        assert "requires prior booking" in nicopolis["details"]
        assert client.get("/api/sites/auth:bg-public:Q1943549").status_code == 404
        assert client.get("/api/sites/501557").status_code == 200

        rukari = client.get("/api/sites/auth:rw-public:Q16678454").json()
        assert rukari["repr_point"] == [29.7399, -2.3603]
        assert any(
            ref["publisher"] == "Rwanda Cultural Heritage Academy" for ref in rukari["source_refs"]
        )
        assert client.get("/api/sites/auth:bi-public:Q2688645").status_code == 404
        assert client.get("/api/sites/wd:Q5564954").status_code == 200

        dam = client.get("/api/sites/auth:la-public:Q4466863").json()
        assert "street-side" in dam["details"]
        assert any(
            "/2025/06/04/" in ref["uri"] for ref in dam["source_refs"]
        )
        tashichho = client.get("/api/sites/auth:bt-public:Q1896299").json()
        assert "admitted visitor route" in tashichho["details"]
        ahmed_bey = client.get("/api/sites/auth:dz-public:geonames-11127626").json()
        assert ahmed_bey["repr_point"] == [6.61188, 36.36763]
        assert any(
            ref["license"] == "CC BY 4.0" and ref["uri"].endswith("/11127626/about.rdf")
            for ref in ahmed_bey["source_refs"]
        )
        assert client.get("/api/sites/auth:dz-public:Q524667").status_code == 404

        froso = client.get("/api/sites/auth:se-raa:f6ed31ce-2941-4171-a738-6e7edf22003d").json()
        assert froso["repr_point"] == [14.52025393, 63.17912709]
        assert any(
            ref["license"] == "CC0" and ref["publisher"] == "Riksantikvarieämbetet"
            for ref in froso["source_refs"]
        )
        rodberget = client.get("/api/sites/auth:se-public:rodbergsfortet").json()
        assert rodberget["repr_point"] == [21.6572, 65.7911]
        assert any(
            ref["license"] == "CC BY-SA 4.0" and "oldid=1386365601" in ref["uri"]
            for ref in rodberget["source_refs"]
        )

        frombork = client.get("/api/sites/auth:pl-public:Q478321").json()
        assert frombork["repr_point"] == [19.68166667, 54.35708333]
        assert any(
            ref["uri"] == "https://bilety.muzeumfrombork.pl/" for ref in frombork["source_refs"]
        )
        batoufam = client.get("/api/sites/auth:cm-public:Q30744186").json()
        assert "public forecourt" in batoufam["details"]
        assert client.get("/api/sites/auth:cv-public:Q106807076").status_code == 404

        gabo = client.get("/api/sites/auth:co-public:Q127694594").json()
        assert "reconstructed childhood house" in gabo["details"]
        assert any(ref["publisher"] == "Museo Nacional de Colombia" for ref in gabo["source_refs"])
        cumana = client.get("/api/sites/auth:ve-public:Q5558033").json()
        assert "publicly approached exterior" in cumana["details"]

        taosi = client.get("/api/sites/auth:cn-public:Q217859").json()
        assert taosi["repr_point"] == [111.49005555555556, 35.89286111111111]
        assert "coarse declared precision" in taosi["details"]
        assert client.get("/api/sites/auth:cn-public:Q1196056").status_code == 404

        kultepe = client.get("/api/sites/auth:tr-public:Q538605").json()
        assert "original historic mound" in kultepe["details"]
        assert any("site museum as closed" in ref["excerpt"] for ref in kultepe["source_refs"])

        maputo_station = client.get("/api/sites/auth:mz-public:geonames-9254055").json()
        assert maputo_station["repr_point"] == [32.56436, -25.97108]
        assert any(
            ref["publisher"] == "GeoNames" and ref["license"] == "CC BY 4.0"
            for ref in maputo_station["source_refs"]
        )
        maputo_fort = client.get("/api/sites/auth:mz-public:Q10283622").json()
        assert "reconstruction on the original" in maputo_fort["details"]

        zvikov = client.get("/api/sites/auth:cz-npu:690850").json()
        assert zvikov["repr_point"] == [14.192495033393621, 49.43898378714071]
        assert "gate can limit access" in zvikov["details"]
        assert any(
            ref["license"] == "CC BY-SA 4.0"
            and ref["publisher"] == "Geoportál památkové péče, Národní památkový ústav"
            for ref in zvikov["source_refs"]
        )

        dakar = client.get("/api/sites/auth:sn-public:geonames-10401826").json()
        assert dakar["repr_point"] == [-17.43323, 14.67565]
        assert any(
            ref["publisher"] == "GeoNames" and ref["license"] == "CC BY 4.0"
            for ref in dakar["source_refs"]
        )
        pavilion = client.get("/api/sites/auth:lr-public:Q1053549").json()
        assert "scheduled tours" in pavilion["details"]

        hemudu = client.get("/api/sites/auth:cn-public:Q11142035").json()
        assert hemudu["repr_point"] == [121.345725, 29.96259722]
        assert "designated exhibits" in hemudu["details"]
        kiln = client.get("/api/sites/auth:cn-public:Q10883697").json()
        assert kiln["repr_point"] == [103.445959, 30.400709]
        assert any(
            "Q10883697.json" in ref["uri"] and ref["license"] == "CC0"
            for ref in kiln["source_refs"]
        )

        tucuman = client.get("/api/sites/auth:ar-public:Q5364487").json()
        assert "original session hall was retained" in tucuman["details"]
        assert "reconstructed in place" in tucuman["details"]
        sarmiento = client.get("/api/sites/auth:ar-public:Q5754443").json()
        assert sarmiento["repr_point"] == [-68.528917, -31.534806]
        assert client.get("/api/sites/auth:ar-public:Q951509").status_code == 404

        stuart = client.get("/api/sites/auth:au-ga2012:NT23649").json()
        assert "December to February" in stuart["details"]
        assert any(
            ref["license"] == "CC BY 3.0 AU"
            and ref["publisher"] == "Commonwealth of Australia (Geoscience Australia)"
            for ref in stuart["source_refs"]
        )
        cossack = client.get("/api/sites/auth:au-ga2012:WA100187892").json()
        assert cossack["repr_point"] == [117.1886, -20.67833]
        assert "outdoor Heritage Trail" in cossack["details"]
        gwalia = client.get("/api/sites/auth:au-public:Q5623251").json()
        assert "Little Pink Camp" in gwalia["details"]

"""Validate shipped source memberships without external pages, models or network."""

from __future__ import annotations

import hashlib
import json

from archsearch.corpus import CORPUS_VERSION, build_document, load_corpus
from archsearch.subdivisions import SubdivisionIndex
from archsearch.supplement_data import base_contract


def test_shipped_memberships_cover_canada_without_changing_corpus() -> None:
    sites = load_corpus()
    assert base_contract(sites) == {
        "base_count": 2976,
        "base_ids_sha256": "7dfba2896df4370dc078372b735aaddc3141fcba36ef2c2135d40fa4cc0ef830",
        "base_sites_sha256": "794d50f1df00ad835a9f108eefa4543c4944296495cffceb1fe4868ee77d77e0",
    }
    documents = json.dumps([[site.id, build_document(site)] for site in sites],
                           ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(documents).hexdigest() == (
        "67d079663efd7318cbc11b5f99d8693f25def158a6571ae48c05b6c3bd168679"
    )
    index = SubdivisionIndex(sites, CORPUS_VERSION)
    assert index.ready, index.reason
    canada = {site.id for site in sites if site.geography and "CA" in site.geography.countries}
    facets = index.facets("CA", len(canada))
    assert facets.total == facets.assigned == 992 and facets.unassigned == 0
    assert len(facets.subdivisions) == 13
    assert sum(facet.count for facet in facets.subdivisions) == 993
    assert set().union(*index.members.values()) == canada
    assert {row.id for row in index.site_response("whc:1415").subdivisions} == {
        "CA:manitoba", "CA:ontario",
    }
    old_quebec = index.site_response("whc:300").memberships[0].evidence[0]
    assert old_quebec.raw_value == old_quebec.source_label == "Québec"
    assert "wd:Q3077812" in index.members["CA:nunavut"]

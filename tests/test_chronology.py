"""Historical stages preserve evidence precision independently of name attestations."""

from collections import Counter

import pytest
from pydantic import ValidationError

from archsearch.corpus import GLOBAL_ERA_QUOTAS, GLOBAL_REGION_QUOTAS, load_corpus
from archsearch.domain import ChronologyReview, HistoricalPhase, SourceReference


def phase(**changes: object) -> HistoricalPhase:
    values: dict[str, object] = {
        "id": "use-1", "kind": "use", "label": "Documented use",
        "start_year": -1, "end_year": 1, "precision": "range",
        "sources": [SourceReference(
            id="test", title="Source", uri="https://example.org/source", publisher="Test",
            excerpt="Used between 1 BCE and 1 CE.",
        )],
    }
    values.update(changes)
    return HistoricalPhase.model_validate(values)


@pytest.mark.parametrize("year", [0, True, 1.5, "117"])
def test_phase_years_do_not_coerce_invalid_historical_dates(year: object) -> None:
    with pytest.raises(ValidationError):
        phase(start_year=year)


def test_bce_ce_range_and_unbounded_period_keep_source_precision() -> None:
    assert phase().start_year == -1
    unknown = phase(start_year=None, end_year=None, precision="period")
    assert unknown.start_year is None and unknown.kind == "use"
    approximate = phase(start_year=-15, end_year=-15, precision="approximate_year")
    assert approximate.precision != "exact_year"
    with pytest.raises(ValidationError):
        phase(precision="exact_year")
    with pytest.raises(ValidationError):
        phase(start_year=2, end_year=1)


def test_review_requires_valid_default_and_real_review_method() -> None:
    with pytest.raises(ValidationError):
        ChronologyReview(status="reviewed", phases=[phase()], default_phase_id="missing")
    with pytest.raises(ValidationError):
        ChronologyReview(status="insufficient", phases=[phase()], default_phase_id="use-1")
    review = ChronologyReview(
        status="reviewed", method="Independent agent source comparison; not expert review",
        reviewed_at="2026-10-31", default_phase_id="use-1", phases=[phase()],
    )
    assert review.phases[0].kind == "use"
    with pytest.raises(ValidationError):
        phase(sources=[SourceReference(
            id="test", title="Source", uri="https://example.org/", publisher="Test",
        )])
    with pytest.raises(ValidationError):
        ChronologyReview(status="insufficient", method=" ", reviewed_at="2026-10-31")
    with pytest.raises(ValidationError):
        ChronologyReview(status="insufficient", method="checked", reviewed_at="not-a-date")
    with pytest.raises(ValidationError):
        SourceReference(
            id="test", title="Source", uri="https://:password@example.org/", publisher="T"
        )


def test_global_corpus_has_complete_audits_without_rewriting_original_attestations() -> None:
    import json

    from archsearch.corpus import DATA_DIR, load_pleiades_corpus

    sites = load_corpus()
    assert len(sites) == len({site.id for site in sites}) == 600
    original = load_pleiades_corpus()
    for old, new in zip(original, sites[:500], strict=True):
        assert old.id == new.id
        assert old.description == new.description
        assert old.details == new.details
        assert old.period_evidence == new.period_evidence
    manifest = json.loads((DATA_DIR / "global_manifest.json").read_text("utf-8"))
    assert Counter(row["region"] for row in manifest["records"]) == GLOBAL_REGION_QUOTAS
    assert Counter(row["era"] for row in manifest["records"]) == GLOBAL_ERA_QUOTAS
    for site in sites:
        assert site.chronology.status in {"reviewed", "insufficient"}
        assert site.chronology.reviewed_at and site.chronology.method
        assert site.source_refs
        if site.source_kind == "global":
            assert site.id.startswith("wd:Q") and site.chronology.phases
        for stage in site.chronology.phases:
            assert stage.sources and all(source.excerpt for source in stage.sources)

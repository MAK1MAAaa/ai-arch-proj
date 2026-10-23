"""Small source-traceable fixtures; unit tests never need model downloads."""

from __future__ import annotations

import pytest

from archsearch.domain import PeriodEvidence, Site


@pytest.fixture
def sample_sites() -> list[Site]:
    sites = []
    for identifier, title, kind in (
        ("3", "Eastern harbor", "port"),
        ("1", "Roman bath", "bath"),
        ("2", "Western harbor", "port"),
    ):
        source = f"https://pleiades.stoa.org/places/{identifier}"
        sites.append(
            Site(
                id=identifier,
                title=title,
                description=f"An ancient {kind} with surviving remains.",
                details="Excavated in the twentieth century.",
                names=[f"Alias{identifier}"],
                types=[kind],
                periods=["roman"],
                repr_point=(12.0, 35.0),
                location_precision="precise",
                source_uri=source,
                contributors=["Fixture Author"],
                period_evidence=[
                    PeriodEvidence(
                        resource_type="Name",
                        resource_uri=source + "/name",
                        period_id="roman",
                        period_uri="https://pleiades.stoa.org/vocabularies/time-periods/roman",
                    )
                ],
            )
        )
    return sites

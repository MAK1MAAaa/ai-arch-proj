"""Compile source-reviewed Mérimée overseas notices without runtime networking."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from archsearch.domain import Geography, Site, SourceReference
from archsearch.supplement_data import IdentityReview, SourceArtifact, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "merimee-overseas-v1"
CORPUS_VERSION = "global-v17"
BASE_COUNT = 3326
SOURCE_COUNT = 450
FULL_SOURCE_COUNT = 46761
DATASET_ID = "5af120e5b595087cfabcde81"
DATASET_URI = (
    "https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2"
)
METADATA_URI = f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/"
CSV_URI = "https://ministere-culture.s3.sbg.io.cloud.ovh.net/POP/merimee.csv"
LICENCE_URI = "https://www.data.gouv.fr/pages/legal/licences/etalab-2-0"
LICENCE = "Licence Ouverte / Open Licence version 2.0"
PUBLISHER = "Ministère de la Culture"
DETAILS_PREFIX = "Original source fields (French):\n"
ROSTER_FILE = "merimee_source_roster.json"
SPEC_FILE = "merimee_review.json"
SITES_FILE = "merimee_sites.json"
MANIFEST_FILE = "merimee_manifest.json"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
# Root activates these only after independent source and derivative approval.
RAW_SOURCE_SHA256 = "d83f5a3beb83221ed55169159fc0ce7c6d3dad66edca205a225cd30c136dd6ec"
METADATA_SHA256 = "d4865cdc53abbbbdcf8db24195c9711b3bab6fde3e6ad4d9f97037e423671496"
LICENCE_SHA256 = "e3abcb87edeca051d99be349976a688802f1340f8482a0290ebabea73561fcb8"
CANDIDATES_SHA256 = "9249ac20cf55e412fa0b4b0a094f6f786cdecc45eddca9de38a609133fc0cbf4"
HANDOFF_SHA256 = "0650b3de8ad0fd0e97d3c62a93ab43c851dcdac15ba6d7740a5833f93f6ae053"
INDEPENDENT_REVIEW_SHA256 = "00f82a43d6d8dd59306507ae2e9b1bf335aa0c78108dd2778834fe058d77179c"
SOURCE_FACTS_SHA256 = "f5be231ae4cd0b702cb929e7741f412c9b8ba940d0035d06050fb7d8b18f3605"
SOURCE_ROSTER_SHA256 = "a7b8e79d64bf184b870607fc83435a4f1c7fb021eb312211b56daed6962f7623"
SPEC_SHA256 = "f6b41e4368d1b31082502bf501f93e576cb6718c22a0c9e807b49480a64c9709"
SITES_SHA256 = "d0a462744555ded18bd8df628ca8200552e4ed463356189ed2ddc683de715845"
_SHA256 = r"^[0-9a-f]{64}$"
_REFERENCE = r"^PA[0-9]{8}$"
AreaCode = Literal["GP", "BL", "MF", "MQ", "RE"]
SOURCE_FIELDS = (
    "Reference",
    "Destination_actuelle_de_l_edifice",
    "Adresse_forme_index",
    "Etablissement_affectataire_de_l_edifice",
    "Autre_appellation_de_l_edifice",
    "Nature_de_la_protection",
    "Auteur_de_l_edifice",
    "Cadastre",
    "Commune_forme_index",
    "Copyright",
    "Type_de_couverture",
    "Datation_de_l_edifice",
    "Denomination_de_l_edifice",
    "Lieu_de_conservation_d_un_element_architectural_deplace",
    "Description_de_l_edifice",
    "Dimensions_normalisees_des_edicules_uniquement",
    "Date_de_Label",
    "Date_de_la_derniere_mise_a_jour",
    "Date_de_creation_de_la_notice",
    "Domaine",
    "Typologie_du_dossier",
    "Date_et_typologie_de_la_protection",
    "Departement_format_numerique",
    "Departement_en_lettres",
    "Partie_d_elevation_exterieure",
    "Source_de_l_energie_utilisee_par_l_edifice",
    "Emplacement__forme_et_structure_de_l_escalier",
    "Description_de_l_elevation_interieure",
    "etat_de_conservation",
    "Cadre_de_l_etude",
    "Genre_du_destinataire",
    "Historique",
    "Nom_du_cours_d_eau_traversant_ou_bordant_l_edifice",
    "Identifiant_Agregee",
    "COG_Insee_lors_de_la_protection",
    "Justification_attribution",
    "Justification_de_la_datation",
    "Liens_externes",
    "Lieudit",
    "Lien_vers_la_base_Archiv_MH",
    "Materiaux_du_gros_oeuvre",
    "Nom_du_redacteur",
    "Observations",
    "Precision_affectataire",
    "Partie_constituante_non_etudiee",
    "Partie_constituante",
    "Precision_sur_la_denomination",
    "Personnes_liees_a_l_edifice",
    "Typologie_de_plan",
    "Precision_de_la_localisation",
    "Precision_de_la_protection",
    "Description_de_l_iconographie",
    "Typologie_de_la_protection",
    "Precision_sur_le_statut_de_l_edifice",
    "Reference_a_un_ensemble",
    "Lien_vers_la_base_Joconde",
    "Lien_vers_la_base_Palissy",
    "References_des_parties_constituantes_etudiees",
    "Region",
    "Elements_remarquables_dans_l_edifice",
    "Remploi",
    "Renvoi_vers_une_notice_de_la_base_Merimee_ou_Palissy",
    "Indexation_iconographique_normalisee",
    "Siecle_de_campagne_secondaire_de_construction",
    "Siecle_de_la_campagne_principale_de_construction",
    "Format_abrege_du_siecle_de_construction",
    "Typologie_de_la_zone_de_protection",
    "Statut_juridique_de_l_edifice",
    "Technique_du_decor_porte_de_l_edifice",
    "Titre_editorial_de_la_notice",
    "Materiaux_de_la_couverture",
    "Couverts_ou_decouverts_du_jardin_de_l_edifice",
    "Vocable___pour_les_edifices_cultuels",
    "Typologie_du_couvrement",
    "Adresse_forme_editoriale",
    "Commune_forme_editoriale",
    "coordonnees_au_format_WGS84",
    "Producteur",
)


class MerimeeError(RuntimeError):
    """A frozen source, review, unchanged base or offline derivative differs."""


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compact_hash(value: Any) -> str:
    return _hash(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def project_id(reference: str) -> str:
    if re.fullmatch(_REFERENCE, reference) is None:
        raise ValueError("Mérimée project identity requires the exact original PA reference")
    return "auth:fr-merimee:" + reference


def parse_reference_point(literal: str) -> tuple[float, float] | None:
    """Convert the source's independently checked lat,lon order, never supply a point."""
    if literal == "":
        return None
    parts = literal.split(",")
    if len(parts) != 2 or any(not value.strip() for value in parts):
        raise ValueError("source WGS84 reference needs exactly latitude,longitude")
    latitude, longitude = map(float, parts)
    if not (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        raise ValueError("source WGS84 reference is not finite or outside coordinate bounds")
    return longitude, latitude


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceEvidence(FrozenModel):
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_binding(self) -> SourceEvidence:
        if self.source.uri != self.artifact.uri or not self.source.excerpt.strip():
            raise ValueError("evidence requires an original URI-bound nonempty excerpt")
        return self


class MerimeeApiReceipt(FrozenModel):
    api_row_compact_sha256: StrictStr = Field(pattern=_SHA256)
    array_index: StrictInt = Field(ge=0, lt=50)
    filename: StrictStr
    page_sha256: StrictStr = Field(pattern=_SHA256)
    provider_row_index_not_business_id: StrictInt = Field(ge=1)
    uri: StrictStr

    @model_validator(mode="after")
    def validate_origin(self) -> MerimeeApiReceipt:
        SourceArtifact(filename=self.filename, sha256=self.page_sha256, uri=self.uri)
        if not self.filename.startswith("api-pages/") or not self.uri.startswith(
            "https://tabular-api.data.gouv.fr/api/resources/"
            "3a52af4a-f9da-4dcc-8110-b07774dfb3bc/data/?"
        ):
            raise ValueError("API corroboration must retain the fixed official resource")
        return self


class MerimeeOriginalRecord(FrozenModel):
    original_record_index: StrictInt = Field(ge=1)
    raw_fields: dict[StrictStr, StrictStr]
    raw_fields_compact_sha256: StrictStr = Field(pattern=_SHA256)
    api_receipt: MerimeeApiReceipt

    @model_validator(mode="after")
    def validate_fields(self) -> MerimeeOriginalRecord:
        if set(self.raw_fields) != set(SOURCE_FIELDS):
            raise ValueError("every original notice must retain exactly all78 CSV fields")
        if compact_hash(self.raw_fields) != self.raw_fields_compact_sha256:
            raise ValueError("the complete original field hash differs")
        project_id(self.raw_fields["Reference"])
        if not self.raw_fields["Titre_editorial_de_la_notice"].strip():
            raise ValueError("the original editorial notice title must not be blank")
        if self.api_receipt.provider_row_index_not_business_id != self.original_record_index:
            raise ValueError("provider row index must remain provenance, separate from PA identity")
        parse_reference_point(self.raw_fields["coordonnees_au_format_WGS84"])
        return self


class MerimeeSourceRoster(FrozenModel):
    schema_version: Literal[1]
    dataset_id: Literal["5af120e5b595087cfabcde81"]
    source_artifact: SourceArtifact
    fields: list[StrictStr]
    records: list[MerimeeOriginalRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roster(self) -> MerimeeSourceRoster:
        indices = [row.original_record_index for row in self.records]
        refs = [row.raw_fields["Reference"] for row in self.records]
        if self.source_artifact.uri != CSV_URI or self.fields != list(SOURCE_FIELDS):
            raise ValueError("fixed CSV identity and original78-field order must be retained")
        if indices != sorted(set(indices)) or len(refs) != len(set(refs)):
            raise ValueError("original selected row order and unique PA identities are required")
        return self


class MerimeeDecision(FrozenModel):
    reference: StrictStr = Field(pattern=_REFERENCE)
    disposition: Literal["include", "existing", "component", "hold", "exclude"]
    qualification: Literal["immovable_cultural", "uncertain", "existing_overlap"]
    scope_kind: Literal["whole_notice_scope", "specified_parts", "composite_protected_scope"]
    supported_scope_field: StrictStr
    supported_scope_literal: StrictStr = Field(min_length=1)
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    independent_review: IdentityReview
    evidence: list[SourceEvidence] = Field(min_length=1)
    area_code: AreaCode
    point_adoption: Literal["provider_reference", "unavailable", "withheld"]

    @model_validator(mode="after")
    def validate_decision(self) -> MerimeeDecision:
        if self.supported_scope_field not in SOURCE_FIELDS or not all(
            value.strip() for value in (self.reason, self.supported_scope_literal)
        ):
            raise ValueError("a review needs literal original scope and explicit audit reason")
        if self.disposition in {"hold", "exclude"}:
            if self.target_id is not None:
                raise ValueError("held or excluded notices cannot gain public targets")
        elif not self.target_id or not self.target_id.strip():
            raise ValueError("accepted notices need their independently reviewed target")
        if self.disposition == "include" and (
            self.qualification != "immovable_cultural"
            or self.target_id != project_id(self.reference)
        ):
            raise ValueError("new notices require cultural qualification and exact PA identity")
        if self.disposition != "include" and self.point_adoption == "provider_reference":
            raise ValueError("a redirected or unadopted notice cannot supply a new reference point")
        return self


class MerimeeMetadata(FrozenModel):
    evidence: SourceEvidence
    csv_last_modified: StrictStr = Field(min_length=1)
    dataset_modified: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_origin(self) -> MerimeeMetadata:
        if self.evidence.source.uri != METADATA_URI:
            raise ValueError("metadata must retain the official dataset API origin")
        return self


class MerimeeLicence(FrozenModel):
    name: Literal["Licence Ouverte / Open Licence version 2.0"]
    uri: Literal["https://www.data.gouv.fr/pages/legal/licences/etalab-2-0"]
    attribution: StrictStr = Field(min_length=1)
    accessed: StrictStr
    evidence: SourceEvidence

    @model_validator(mode="after")
    def validate_licence(self) -> MerimeeLicence:
        if date.fromisoformat(self.accessed).isoformat() != self.accessed:
            raise ValueError("licence access date requires ISO YYYY-MM-DD")
        if self.evidence.source.uri != LICENCE_URI or any(
            value not in self.attribution for value in (DATASET_URI, LICENCE_URI, self.accessed)
        ):
            raise ValueError("attribution requires original dataset, licence and access date")
        return self


class MerimeeArea(FrozenModel):
    code: AreaCode
    name: StrictStr = Field(min_length=1)
    project_region: Literal["africa", "latin-america-caribbean"]
    source_m49_cells: list[StrictStr] = Field(min_length=15, max_length=15)
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_active_row(self) -> MerimeeArea:
        cells = self.source_m49_cells
        region = "africa" if self.code == "RE" else "latin-america-caribbean"
        hierarchy = (
            ["002", "Africa", "202", "Sub-Saharan Africa", "014", "Eastern Africa"]
            if self.code == "RE"
            else ["019", "Americas", "419", "Latin America and the Caribbean", "029", "Caribbean"]
        )
        if (
            cells[:2] != ["001", "World"]
            or cells[2:8] != hierarchy
            or cells[8] != self.name
            or cells[10] != self.code
            or self.project_region != region
        ):
            raise ValueError("country-or-area labels require the exact current active M49 row")
        return self


class MerimeeCogEvidence(FrozenModel):
    original_code: StrictStr = Field(pattern=r"^[0-9]{5}$")
    current_commune: dict[StrictStr, StrictStr] | None = None
    current_department: dict[StrictStr, StrictStr] | None = None
    current_overseas_commune: dict[StrictStr, StrictStr] | None = None
    current_overseas_area: dict[StrictStr, StrictStr] | None = None

    def area(self) -> str:
        if self.current_commune is not None and self.current_department is not None:
            if self.current_overseas_commune is not None or self.current_overseas_area is not None:
                raise ValueError("one COG token cannot mix commune and overseas join variants")
            commune, department = self.current_commune, self.current_department
            if (
                commune.get("COM") != self.original_code
                or commune.get("TYPECOM") != "COM"
                or commune.get("DEP") != department.get("DEP")
            ):
                raise ValueError("current INSEE commune-to-department exact join differs")
            code = {"971": "GP", "972": "MQ", "974": "RE"}.get(department.get("DEP", ""))
        elif self.current_overseas_commune is not None and self.current_overseas_area is not None:
            if self.current_commune is not None or self.current_department is not None:
                raise ValueError("one COG token cannot mix commune and overseas join variants")
            commune, area = self.current_overseas_commune, self.current_overseas_area
            if commune.get("COM_COMER") != self.original_code or commune.get("COMER") != area.get(
                "COMER"
            ):
                raise ValueError("current INSEE overseas commune-to-area exact join differs")
            code = {"977": "BL", "978": "MF"}.get(area.get("COMER", ""))
        else:
            raise ValueError("every COG token requires a complete original current INSEE join")
        if code is None:
            raise ValueError("COG token has no independently supported cohort statistical area")
        return code

    @model_validator(mode="after")
    def validate_join(self) -> MerimeeCogEvidence:
        self.area()
        return self


class MerimeeAreaCrosswalk(FrozenModel):
    reference: StrictStr = Field(pattern=_REFERENCE)
    source_cog_literal: StrictStr
    source_commune_literal: StrictStr
    source_region: StrictStr
    current_statistical_area: AreaCode
    current_cog_evidence: list[MerimeeCogEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_join(self) -> MerimeeAreaCrosswalk:
        if self.source_cog_literal.split(";") != [
            item.original_code for item in self.current_cog_evidence
        ] or any(
            item.area() != self.current_statistical_area for item in self.current_cog_evidence
        ):
            raise ValueError("all original COG tokens require exact same-area current joins")
        return self


class MerimeeReview(FrozenModel):
    schema_version: Literal[1]
    cohort_version: Literal["merimee-overseas-v1"]
    corpus_version: Literal["global-v17"]
    base_count: Literal[3326]
    base_ids_sha256: StrictStr = Field(pattern=_SHA256)
    base_sites_sha256: StrictStr = Field(pattern=_SHA256)
    candidates_sha256: StrictStr = Field(pattern=_SHA256)
    handoff_sha256: StrictStr = Field(pattern=_SHA256)
    independent_report_sha256: StrictStr = Field(pattern=_SHA256)
    metadata: MerimeeMetadata
    licence: MerimeeLicence
    areas: list[MerimeeArea] = Field(min_length=5, max_length=5)
    area_crosswalk: list[MerimeeAreaCrosswalk] = Field(min_length=1)
    point_axis_evidence: list[SourceEvidence] = Field(min_length=1)
    decisions: list[MerimeeDecision] = Field(min_length=1)


class MerimeeSpec(FrozenModel):
    roster: MerimeeSourceRoster
    review: MerimeeReview


def _source_facts(spec: MerimeeSpec) -> dict[str, Any]:
    return {
        "roster": spec.roster.model_dump(mode="json"),
        "review": spec.review.model_dump(
            mode="json",
            exclude={"candidates_sha256", "handoff_sha256", "independent_report_sha256"},
        ),
    }


def _artifacts(spec: MerimeeSpec) -> dict[str, SourceArtifact]:
    evidence = [spec.review.metadata.evidence, spec.review.licence.evidence]
    evidence += spec.review.point_axis_evidence
    evidence += [item for area in spec.review.areas for item in area.evidence]
    evidence += [item for decision in spec.review.decisions for item in decision.evidence]
    originals = [spec.roster.source_artifact, *(item.artifact for item in evidence)]
    originals += [
        SourceArtifact(
            filename="merimee-source-candidate/" + row.api_receipt.filename,
            sha256=row.api_receipt.page_sha256,
            uri=row.api_receipt.uri,
        )
        for row in spec.roster.records
    ]
    result: dict[str, SourceArtifact] = {}
    for artifact in originals:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise MerimeeError("one local snapshot has conflicting source URI/hash contracts")
        result[artifact.filename] = artifact
    return result


def _validate_spec(spec: MerimeeSpec) -> None:
    records = {row.raw_fields["Reference"]: row.raw_fields for row in spec.roster.records}
    decisions = {row.reference: row for row in spec.review.decisions}
    crosswalk = {row.reference: row for row in spec.review.area_crosswalk}
    areas = {row.code: row for row in spec.review.areas}
    if (
        len(records) != SOURCE_COUNT
        or len(decisions) != len(spec.review.decisions)
        or (
            set(records) != set(decisions)
            or set(crosswalk) != set(records)
            or len(crosswalk) != len(spec.review.area_crosswalk)
        )
    ):
        raise MerimeeError("all450 original notices need exactly one decision and area join")
    if set(areas) != {"GP", "BL", "MF", "MQ", "RE"}:
        raise MerimeeError("five distinct source-supported current statistical areas are required")
    for reference, fields in records.items():
        decision, mapping = decisions[reference], crosswalk[reference]
        if decision.supported_scope_literal != fields[decision.supported_scope_field]:
            raise MerimeeError("source scope must retain the entire exact selected original field")
        if (
            mapping.source_cog_literal != fields["COG_Insee_lors_de_la_protection"]
            or mapping.source_commune_literal != fields["Commune_forme_index"]
            or mapping.source_region != fields["Region"]
            or decision.area_code != mapping.current_statistical_area
        ):
            raise MerimeeError("area membership must bind each original COG/commune/region literal")
        point = parse_reference_point(fields["coordonnees_au_format_WGS84"])
        if (point is None) != (decision.point_adoption == "unavailable"):
            raise MerimeeError("missing source coordinates must remain unavailable, never zero")
        if decision.disposition == "component" and (
            decision.target_id == project_id(reference)
            or (
                decision.target_id is not None
                and decision.target_id.startswith("auth:fr-merimee:")
                and decision.target_id
                not in {
                    project_id(item.reference)
                    for item in decisions.values()
                    if item.disposition == "include"
                }
            )
        ):
            raise MerimeeError(
                "component cannot target itself, another redirect or unaccepted notice"
            )
    _artifacts(spec)


def _path(root: Path, filename: str) -> Path:
    directory = root.resolve()
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory):
        raise MerimeeError("source or derivative escapes its chosen local directory")
    return path


def _read_bounded(root: Path, filename: str) -> bytes:
    with _path(root, filename).open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise MerimeeError(f"local normalized file exceeds its bounded contract: {filename}")
    return raw


def _require_pins() -> None:
    if any(
        re.fullmatch(_SHA256, value) is None
        for value in (
            RAW_SOURCE_SHA256,
            METADATA_SHA256,
            LICENCE_SHA256,
            CANDIDATES_SHA256,
            HANDOFF_SHA256,
            INDEPENDENT_REVIEW_SHA256,
            SOURCE_FACTS_SHA256,
            SOURCE_ROSTER_SHA256,
            SPEC_SHA256,
            SITES_SHA256,
        )
    ):
        raise MerimeeError("Mérimée independent source/derivative approval pins are not configured")


def _spec(directory: Path) -> MerimeeSpec:
    _require_pins()
    roster, review = _read_bounded(directory, ROSTER_FILE), _read_bounded(directory, SPEC_FILE)
    if _hash(roster) != SOURCE_ROSTER_SHA256 or _hash(review) != SPEC_SHA256:
        raise MerimeeError("normalized Mérimée roster or review differs from independent pin")
    spec = MerimeeSpec(
        roster=MerimeeSourceRoster.model_validate_json(roster),
        review=MerimeeReview.model_validate_json(review),
    )
    if (
        spec.roster.source_artifact.sha256 != RAW_SOURCE_SHA256
        or spec.review.metadata.evidence.artifact.sha256 != METADATA_SHA256
        or spec.review.licence.evidence.artifact.sha256 != LICENCE_SHA256
        or spec.review.candidates_sha256 != CANDIDATES_SHA256
        or spec.review.handoff_sha256 != HANDOFF_SHA256
        or spec.review.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
        or _hash(_bytes(_source_facts(spec))) != SOURCE_FACTS_SHA256
    ):
        raise MerimeeError("original source receipts or complete independent source facts differ")
    _validate_spec(spec)
    return spec


def _ordered(spec: MerimeeSpec) -> list[MerimeeDecision]:
    return sorted(
        (row for row in spec.review.decisions if row.disposition == "include"),
        key=lambda row: (
            _hash((COHORT_VERSION + ":" + project_id(row.reference)).encode()),
            row.reference,
        ),
    )


def _description(fields: dict[str, str], decision: MerimeeDecision) -> str:
    keys = dict.fromkeys(
        (
            "Commune_forme_editoriale",
            "Region",
            decision.supported_scope_field,
            "Description_de_l_edifice",
            "Historique",
        )
    )
    return "\n\n".join(key + ":\n" + fields[key] for key in keys if fields[key] != "")


def compile_merimee(spec: MerimeeSpec) -> list[Site]:
    """Project reviewed literal fields; compilation alone does not activate approval pins."""
    _validate_spec(spec)
    records = {row.raw_fields["Reference"]: row.raw_fields for row in spec.roster.records}
    areas = {row.code: row for row in spec.review.areas}
    result = []
    for decision in _ordered(spec):
        fields, area = records[decision.reference], areas[decision.area_code]
        identifier = project_id(decision.reference)
        point = parse_reference_point(fields["coordonnees_au_format_WGS84"])
        if decision.point_adoption != "provider_reference":
            point = None
        notice_uri = "https://pop.culture.gouv.fr/notice/merimee/" + decision.reference
        source = SourceReference(
            id="source:fr-merimee:" + decision.reference,
            title=fields["Titre_editorial_de_la_notice"],
            uri=notice_uri,
            publisher=PUBLISHER,
            license=LICENCE,
            revision="sha256:" + spec.roster.source_artifact.sha256,
            accessed=spec.review.licence.accessed,
            excerpt=decision.supported_scope_literal,
        )
        result.append(
            Site(
                id=identifier,
                title=fields["Titre_editorial_de_la_notice"],
                description=_description(fields, decision),
                description_zh="",
                details=DETAILS_PREFIX
                + json.dumps(
                    {
                        "schema_version": 1,
                        "reference": decision.reference,
                        "scope": {
                            "kind": decision.scope_kind,
                            "source_field": decision.supported_scope_field,
                            "literal": decision.supported_scope_literal,
                        },
                        "source_record": {key: fields[key] for key in SOURCE_FIELDS},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                names=[],
                types=["historic-site"],
                periods=[],
                repr_point=point,
                location_precision=None,
                source_uri=notice_uri,
                contributors=[PUBLISHER],
                period_evidence=[],
                source_kind="supplement",
                source_refs=[
                    source,
                    spec.review.metadata.evidence.source,
                    spec.review.licence.evidence.source,
                ],
                geography=Geography(
                    authority_id="supplement:" + identifier,
                    countries=[area.code],
                    regions=[area.project_region],
                    source=area.evidence[0].source,
                    point_count=int(point is not None),
                    note=(
                        "原COG经当前INSEE与UN M49对照用于地区浏览，不表示历史政治归属。"
                        "来源包括曾受或现受保护资料；保护范围保留原文，不自动扩成完整建筑。"
                        "原WGS84点仅作来源参考，生成方法和精度未知，不等于保护边界或发掘位置。"
                        "缺点不补点；法律、保护、更新和建筑世纪字段未转成历史阶段。"
                        "开放许可仅按数据集范围署名，不延伸到链接的照片和档案材料。"
                    ),
                ),
            )
        )
    return result


def new_country_labels(directory: Path = DATA_DIR) -> dict[str, str]:
    try:
        return {area.code: area.name for area in _spec(Path(directory)).review.areas}
    except MerimeeError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise MerimeeError(
            f"cannot load frozen current statistical area labels: {error}"
        ) from error


def _manifest(spec: MerimeeSpec, payload: bytes) -> dict[str, Any]:
    additions = compile_merimee(spec)
    return {
        "schema_version": 1,
        "cohort_version": COHORT_VERSION,
        "corpus_version": CORPUS_VERSION,
        "base": {
            key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
        },
        "independent_source_review": {
            "candidates_sha256": CANDIDATES_SHA256,
            "handoff_sha256": HANDOFF_SHA256,
            "report_sha256": INDEPENDENT_REVIEW_SHA256,
            "source_facts_sha256": SOURCE_FACTS_SHA256,
        },
        "files": {
            ROSTER_FILE: {"sha256": SOURCE_ROSTER_SHA256},
            SPEC_FILE: {"sha256": SPEC_SHA256},
            SITES_FILE: {"sha256": _hash(payload)},
        },
        "counts": {
            "base": BASE_COUNT,
            "source_records": len(spec.roster.records),
            "added": len(additions),
            "total": BASE_COUNT + len(additions),
            "decisions": dict(
                sorted(Counter(d.disposition for d in spec.review.decisions).items())
            ),
            "adopted_reference_points": sum(s.repr_point is not None for s in additions),
            "missing_reference_points": sum(s.repr_point is None for s in additions),
            "new_historical_phases": 0,
            "areas": dict(sorted(Counter(d.area_code for d in _ordered(spec)).items())),
        },
        "metadata": spec.review.metadata.model_dump(mode="json"),
        "licence": spec.review.licence.model_dump(mode="json"),
        "areas": [area.model_dump(mode="json") for area in spec.review.areas],
        "decisions": [d.model_dump(mode="json") for d in spec.review.decisions],
        "source_artifacts": [
            a.model_dump(mode="json") for _, a in sorted(_artifacts(spec).items())
        ],
        "semantics": "Original PA notice scopes and all78 French fields retained. "
        "A notice may cover specified parts or have historical protection only. "
        "Current INSEE-to-M49 statistical areas are independent of source Region and publisher. "
        "Original WGS84 references have unknown method/precision; no generated centroid, "
        "geocoding, aliases, historical phases, UNESCO or current legal-status assertion. "
        "OpenLicence2 applies to original dataset fields, not automatically to linked media.",
    }


def _validate_base(base: list[Site], spec: MerimeeSpec) -> set[str]:
    expected = {
        key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
    }
    if base_contract(base) != expected:
        raise MerimeeError("Mérimée base differs from the unchanged3326 field/order contract")
    ids = {site.id for site in base}
    includes = {project_id(row.reference) for row in _ordered(spec)}
    if len(ids) != BASE_COUNT or ids & includes:
        raise MerimeeError("Mérimée base/additions contain duplicate identities")
    for decision in spec.review.decisions:
        if decision.disposition == "existing" and decision.target_id not in ids:
            raise MerimeeError("existing notice target is absent from the frozen base")
        if decision.disposition == "component" and (
            decision.target_id not in ids | includes
            or decision.target_id == project_id(decision.reference)
        ):
            raise MerimeeError("component target must be a distinct base or accepted cohort whole")
    return ids


def _output_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if path.is_symlink():
        raise MerimeeError("derivative output must remain a regular local path")
    return _path(directory, filename)


def rebuild_merimee(data_dir: Path = DATA_DIR, *, base: list[Site] | None = None) -> dict[str, Any]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base is not None:
            _validate_base(base, spec)
        payload = _bytes([site.model_dump(mode="json") for site in compile_merimee(spec)])
        if _hash(payload) != SITES_SHA256:
            raise MerimeeError("compiled Mérimée sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        sites_path = _output_path(directory, SITES_FILE)
        manifest_path = _output_path(directory, MANIFEST_FILE)
        sites_path.write_bytes(payload)
        manifest_path.write_bytes(_bytes(manifest))
        return manifest
    except MerimeeError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MerimeeError(f"cannot rebuild frozen Mérimée facts: {error}") from error


def load_merimee(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        _validate_base(base, spec)
        additions = compile_merimee(spec)
        payload = _read_bounded(directory, SITES_FILE)
        if payload != _bytes([site.model_dump(mode="json") for site in additions]) or (
            _hash(payload) != SITES_SHA256
        ):
            raise MerimeeError("Mérimée derivative differs from approved literal source facts")
        if _bytes(json.loads(_read_bounded(directory, MANIFEST_FILE))) != _bytes(
            _manifest(spec, payload)
        ):
            raise MerimeeError("Mérimée manifest differs from its frozen contract")
        return base + additions
    except MerimeeError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MerimeeError(f"cannot load frozen Mérimée facts: {error}") from error


def _verify_hash(root: Path, artifact: SourceArtifact) -> None:
    digest = hashlib.sha256()
    size = 0
    with _path(root, artifact.filename).open("rb") as stream:
        while raw := stream.read(1024 * 1024):
            size += len(raw)
            if size > MAX_SOURCE_BYTES:
                raise MerimeeError("source snapshot exceeds the bounded source contract")
            digest.update(raw)
    if digest.hexdigest() != artifact.sha256:
        raise MerimeeError(f"original source snapshot differs: {artifact.filename}")


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Stream the original full CSV and verify all selected literal fields; never fetch."""
    try:
        spec = _spec(Path(data_dir))
        artifacts = _artifacts(spec)
        for artifact in artifacts.values():
            _verify_hash(cache_dir, artifact)
        selected = {row.original_record_index: row for row in spec.roster.records}
        found: set[int] = set()
        total = 0
        with _path(cache_dir, spec.roster.source_artifact.filename).open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.DictReader(stream, delimiter="|", strict=True)
            if reader.fieldnames != list(SOURCE_FIELDS):
                raise MerimeeError("original CSV78-field header/order differs")
            for index, fields in enumerate(reader, start=1):
                total += 1
                if index in selected:
                    if fields != selected[index].raw_fields:
                        raise MerimeeError(
                            "original CSV physical record differs from frozen roster"
                        )
                    found.add(index)
        if total != FULL_SOURCE_COUNT or found != set(selected):
            raise MerimeeError("full source record count or selected physical indices differ")
        for original in spec.roster.records:
            receipt = original.api_receipt
            page = json.loads(
                _read_bounded(cache_dir, "merimee-source-candidate/" + receipt.filename)
            )
            row = page["data"][receipt.array_index]
            if (
                compact_hash(row) != receipt.api_row_compact_sha256
                or row["__id"] != original.original_record_index
                or {key: "" if row[key] is None else row[key] for key in SOURCE_FIELDS}
                != original.raw_fields
            ):
                raise MerimeeError("official API corroboration differs from original CSV fields")
        return len(artifacts)
    except MerimeeError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        RecursionError,
        csv.Error,
    ) as error:
        raise MerimeeError(f"cannot verify original Mérimée source cache: {error}") from error


def main() -> None:
    from archsearch.corpus import CorpusError, load_pre_merimee_corpus

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--verify-source-cache", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_source_cache is not None:
            print(
                json.dumps(
                    {
                        "verified_source_files": verify_source_cache(
                            args.verify_source_cache,
                            args.data_dir,
                        )
                    }
                )
            )
        if args.rebuild:
            print(
                json.dumps(
                    rebuild_merimee(
                        args.data_dir,
                        base=load_pre_merimee_corpus(args.data_dir),
                    )["counts"]
                )
            )
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild and/or --verify-source-cache")
    except (MerimeeError, CorpusError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()

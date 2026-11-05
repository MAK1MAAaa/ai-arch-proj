"""Pure, source-literal Mérimée projection shared by separately pinned cohorts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from archsearch.domain import Geography, Site, SourceReference

LICENCE = "Licence Ouverte / Open Licence version 2.0"
PUBLISHER = "Ministère de la Culture"
DETAILS_PREFIX = "Original source fields (French):\n"
_REFERENCE = r"^PA[0-9]{8}$"
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


def describe_original_fields(fields: Mapping[str, str], scope_field: str) -> str:
    keys = dict.fromkeys(
        (
            "Commune_forme_editoriale",
            "Region",
            scope_field,
            "Description_de_l_edifice",
            "Historique",
        )
    )
    return "\n\n".join(key + ":\n" + fields[key] for key in keys if fields[key] != "")


@dataclass(frozen=True)
class NoticeProjection:
    reference: str
    scope_kind: str
    scope_field: str
    scope_literal: str
    adopt_point: bool
    area_code: str
    project_region: str
    geography_source: SourceReference
    raw_source_sha256: str
    accessed: str
    metadata_source: SourceReference
    licence_source: SourceReference


def project_notice(fields: Mapping[str, str], context: NoticeProjection) -> Site:
    """Project only caller-reviewed original fields; no source or identity approval here."""
    identifier = project_id(context.reference)
    point = parse_reference_point(fields["coordonnees_au_format_WGS84"])
    if not context.adopt_point:
        point = None
    notice_uri = "https://pop.culture.gouv.fr/notice/merimee/" + context.reference
    source = SourceReference(
        id="source:fr-merimee:" + context.reference,
        title=fields["Titre_editorial_de_la_notice"],
        uri=notice_uri,
        publisher=PUBLISHER,
        license=LICENCE,
        revision="sha256:" + context.raw_source_sha256,
        accessed=context.accessed,
        excerpt=context.scope_literal,
    )
    return Site(
        id=identifier,
        title=fields["Titre_editorial_de_la_notice"],
        description=describe_original_fields(fields, context.scope_field),
        description_zh="",
        details=DETAILS_PREFIX
        + json.dumps(
            {
                "schema_version": 1,
                "reference": context.reference,
                "scope": {
                    "kind": context.scope_kind,
                    "source_field": context.scope_field,
                    "literal": context.scope_literal,
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
            context.metadata_source,
            context.licence_source,
        ],
        geography=Geography(
            authority_id="supplement:" + identifier,
            countries=[context.area_code],
            regions=[context.project_region],
            source=context.geography_source,
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

const ArchSearchResearch = (() => {
  "use strict";

  interface SearchSpec {
    query: string;
    mode: "semantic" | "bm25";
    type: string | null;
    limit: number;
    country?: string | null;
    region?: string | null;
    subdivision?: string | null;
  }

  interface ParsedLink {
    request: SearchSpec | null;
    error: string | null;
  }

  interface HistoryView {
    year: number;
    basemap: "historical" | "modern";
    boundaries: boolean;
    frame_id: string | null;
    source_version: string | null;
  }

  interface Selection {
    site: string | null;
    phase: string | null;
  }

  interface BrowseState {
    country: string | null;
    region: string | null;
    offset: number;
    visible: boolean;
    bbox?: [number, number, number, number] | null;
    spatial_match_mode?: "source-or-representative" | "representative-only";
    spatial_version?: string | null;
    subdivision?: string | null;
    subdivision_version?: string | null;
  }

  const minasSourceFields = ["processo_ano", "denominacao", "denominacao_completa", "categoria", "classe_subclasse", "municipio", "distrito", "ato_legal", "livro_de_tombo"] as const;
  type MinasSourceRecord = { record_index: number } & Record<typeof minasSourceFields[number], string>;

  function compactSourceJson(value: string): string {
    let compact = "", quoted = false, escaped = false;
    for (const character of value) {
      if (quoted) {
        compact += character;
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === '"') quoted = false;
      } else if (character === '"') {
        quoted = true;
        compact += character;
      } else if (!/[\t\n\r ]/u.test(character)) compact += character;
    }
    return compact;
  }

  function parseMinasSource(site: { id: string; details: string }): MinasSourceRecord[] | null {
    const prefix = "Original source fields (Portuguese):\n";
    if (typeof site.id !== "string" || !/^auth:br-iepha-mg:scope-[a-f0-9]{64}$/u.test(site.id)
      || typeof site.details !== "string" || !site.details.startsWith(prefix)) return null;
    try {
      const original = site.details.slice(prefix.length);
      const rows: unknown = JSON.parse(original);
      if (!Array.isArray(rows) || rows.length < 1 || rows.length > 153) return null;
      let previousIndex = 0;
      for (const row of rows) {
        if (row === null || typeof row !== "object" || Array.isArray(row)) return null;
        const record = row as Record<string, unknown>;
        if (Object.keys(record).length !== minasSourceFields.length + 1
          || !Number.isSafeInteger(record.record_index) || (record.record_index as number) <= previousIndex
          || (record.record_index as number) > 153
          || !minasSourceFields.every((field) => typeof record[field] === "string")) return null;
        previousIndex = record.record_index as number;
      }
      // Only source serialization is structured; duplicate keys or alternate encodings retain the original fallback.
      if (compactSourceJson(original) !== JSON.stringify(rows)) return null;
      return rows as MinasSourceRecord[];
    } catch {
      return null;
    }
  }

  const merimeeSourceFields = [
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
  ] as const;
  type MerimeeSourceField = typeof merimeeSourceFields[number];
  type MerimeeSourceRecord = Record<MerimeeSourceField, string>;
  type MerimeeScopeKind = "whole_notice_scope" | "specified_parts" | "composite_protected_scope";
  interface MerimeeSource {
    schema_version: 1;
    reference: string;
    scope: { kind: MerimeeScopeKind; source_field: MerimeeSourceField; literal: string };
    source_record: MerimeeSourceRecord;
  }

  function parseMerimeeSource(site: { id: string; details: string }): MerimeeSource | null {
    const prefix = "Original source fields (French):\n";
    if (typeof site.id !== "string" || typeof site.details !== "string" || !site.details.startsWith(prefix)) return null;
    const identity = /^auth:fr-merimee:(PA[0-9]{8})$/u.exec(site.id);
    if (!identity) return null;
    try {
      const original = site.details.slice(prefix.length);
      const parsed: unknown = JSON.parse(original);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
      const value = parsed as Record<string, unknown>;
      if (Object.keys(value).length !== 4 || value.schema_version !== 1 || value.reference !== identity[1]) return null;
      const record = value.source_record, scope = value.scope;
      if (record === null || typeof record !== "object" || Array.isArray(record)
        || scope === null || typeof scope !== "object" || Array.isArray(scope)) return null;
      const fields = record as Record<string, unknown>, range = scope as Record<string, unknown>;
      if (Object.keys(fields).length !== merimeeSourceFields.length || fields.Reference !== value.reference
        || !merimeeSourceFields.every((field) => typeof fields[field] === "string")) return null;
      if (Object.keys(range).length !== 3
        || typeof range.kind !== "string"
        || !["whole_notice_scope", "specified_parts", "composite_protected_scope"].includes(range.kind)
        || typeof range.source_field !== "string"
        || !merimeeSourceFields.some((field) => field === range.source_field)
        || typeof range.literal !== "string" || fields[range.source_field] !== range.literal) return null;
      // Ambiguous JSON preserves the complete original text instead of selecting one duplicate value.
      if (compactSourceJson(original) !== JSON.stringify(parsed)) return null;
      return parsed as MerimeeSource;
    } catch {
      return null;
    }
  }

  function normalizeBBox(value: unknown): [number, number, number, number] | null {
    if (value === null || value === undefined) return null;
    if (!Array.isArray(value) || value.length !== 4 || !value.every((item) => typeof item === "number" && Number.isFinite(item))) throw new Error("地图范围须为四个有限数字。");
    const [west, south, east, north] = value as number[];
    if (west < -180 || west > 180 || east < -180 || east > 180 || south < -90 || north > 90
      || south >= north || west === east || (west === 180 && east === -180)) throw new Error("地图范围经纬度越界或范围宽度／高度为零。");
    return [west, south, east, north];
  }

  function parseBBox(value: string | null): [number, number, number, number] | null {
    if (value === null) return null;
    if (value.length < 1 || value.length > 200) throw new Error("地图范围参数长度应为1至200个字符。");
    const parts = value.split(",").map((part) => part.trim());
    if (parts.length !== 4 || parts.some((part) => !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/u.test(part))) throw new Error("地图范围应为西、南、东、北四个十进制数字。");
    return normalizeBBox(parts.map(Number));
  }

  const regions = ["africa", "arab-states", "asia-pacific", "europe-north-america", "latin-america-caribbean", "antarctica", "nps-pacific"];

  function normalizeSubdivision(country: string | null | undefined, value: unknown): string | null {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value !== "string" || !/^[A-Z]{2}:[a-z0-9][a-z0-9-]{0,63}$/u.test(value)
      || !country || !value.startsWith(`${country}:`)) throw new Error("来源省区须使用所选国家／地区对应的项目标识。");
    return value;
  }

  function subdivisionVersion(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0 && value.length <= 128;
  }

  function validateSubdivisionResponse(request: Pick<SearchSpec, "country" | "subdivision">, response: { subdivision?: unknown; subdivision_version?: unknown }, expectedVersion?: string | null): string | null {
    const subdivision = normalizeSubdivision(request.country, request.subdivision);
    if (!subdivision) return null;
    if (response.subdivision !== subdivision || !subdivisionVersion(response.subdivision_version)
      || (expectedVersion !== undefined && response.subdivision_version !== expectedVersion)) throw new Error("来源省区响应的条件或资料版本不一致，未替换成功视图。");
    return response.subdivision_version;
  }

  function geography(country: string | null | undefined, region: string | null | undefined): { country: string | null; region: string | null } {
    const normalizedCountry = country || null;
    const normalizedRegion = region || null;
    if (normalizedCountry !== null && !/^[A-Z]{2}$/u.test(normalizedCountry)) throw new Error("国家／地区代码应为来源中的两位大写ISO代码。");
    if (normalizedRegion !== null && !regions.includes(normalizedRegion)) throw new Error("来源分区参数无效。");
    return { country: normalizedCountry, region: normalizedRegion };
  }

  function parseBrowse(url: URL): { state: BrowseState; error: string | null } {
    const empty = { country: null, region: null, offset: 0, visible: true, bbox: null };
    try {
      for (const name of ["browse_country", "browse_region", "browse_subdivision", "browse_offset", "points", "browse_bbox"]) {
        if (url.searchParams.getAll(name).length > 1) throw new Error(`链接中的 ${name} 参数不能重复。`);
      }
      const scope = geography(url.searchParams.get("browse_country"), url.searchParams.get("browse_region"));
      const subdivision = normalizeSubdivision(scope.country, url.searchParams.get("browse_subdivision"));
      const rawOffset = url.searchParams.get("browse_offset") ?? "0";
      const points = url.searchParams.get("points") ?? "1";
      if (!/^(?:0|[1-9]\d{0,6})$/u.test(rawOffset) || Number(rawOffset) > 1_000_000) throw new Error("目录页码无效。");
      if (points !== "0" && points !== "1") throw new Error("全库点图层参数无效。");
      return { state: { ...scope, ...(subdivision ? { subdivision } : {}), offset: Number(rawOffset), visible: points === "1", bbox: parseBBox(url.searchParams.get("browse_bbox")) }, error: null };
    } catch (error) {
      return { state: empty, error: error instanceof Error ? error.message : "目录链接无效。" };
    }
  }

  function validYear(year: number): boolean {
    return Number.isInteger(year) && year !== 0;
  }

  function automaticPhaseYear(phase: { precision: string; start_year: number | null; end_year: number | null }): number | null {
    return phase.precision === "exact_year" && phase.start_year !== null
      && validYear(phase.start_year) && phase.start_year === phase.end_year ? phase.start_year : null;
  }

  function parseView(url: URL): { view: HistoryView | null; selection: Selection; error: string | null } {
    const empty = { site: null, phase: null };
    const parameters = url.searchParams;
    const names = ["year", "basemap", "boundaries", "site", "phase"];
    try {
      for (const name of names) {
        if (parameters.getAll(name).length > 1) throw new Error(`链接中的 ${name} 参数不能重复。`);
      }
      const rawYear = parameters.get("year");
      const basemap = parameters.get("basemap") ?? "historical";
      const boundaries = parameters.get("boundaries") ?? "1";
      if (basemap !== "historical" && basemap !== "modern") throw new Error("链接中的 basemap 无效。");
      if (boundaries !== "0" && boundaries !== "1") throw new Error("链接中的 boundaries 无效。");
      if (rawYear !== null && (!/^-?[1-9]\d*$/u.test(rawYear) || !validYear(Number(rawYear))
        || Number(rawYear) < -3400 || Number(rawYear) > 2024)) throw new Error("链接年份应为公元前3400至公元2024年，不能为0。");
      const site = parameters.get("site");
      const phase = parameters.get("phase");
      if (site !== null && !/^(?:[1-9]\d*|wd:Q[1-9]\d*|whc:[1-9]\d*|ats:hsm:[1-9]\d*|auth:[a-z][a-z0-9-]{0,39}:[A-Za-z0-9][A-Za-z0-9._-]{0,79})$/u.test(site)) throw new Error("链接中的 site 无效。");
      if (phase !== null && (!site || !phase || phase.length > 160 || /[\u0000-\u001f\u007f]/u.test(phase))) throw new Error("链接中的 phase 无效或缺少 site。");
      const hasView = ["year", "basemap", "boundaries"].some((name) => parameters.has(name));
      return { view: hasView ? { year: rawYear === null ? 117 : Number(rawYear), basemap, boundaries: boundaries === "1", frame_id: null, source_version: null } : null, selection: { site, phase }, error: null };
    } catch (error) {
      return { view: null, selection: empty, error: error instanceof Error ? error.message : "地图链接无效。" };
    }
  }

  interface SearchResponse<T> {
    query: string;
    mode: "semantic" | "bm25";
    corpus_version: string;
    elapsed_ms: number;
    total_candidates: number;
    results: T[];
    subdivision?: string | null;
    subdivision_version?: string | null;
  }

  const parameterNames = ["q", "mode", "type", "limit", "country", "region", "subdivision"] as const;

  function normalizeRequest(request: SearchSpec): SearchSpec {
    const query = request.query.trim();
    if (!query || Array.from(query).length > 500) {
      throw new Error("链接中的 q 必须包含 1 至 500 个字符。");
    }
    if (request.mode !== "semantic" && request.mode !== "bm25") {
      throw new Error("链接中的 mode 仅支持 semantic 或 bm25。");
    }
    if (request.limit !== 10 && request.limit !== 20 && request.limit !== 50) {
      throw new Error("链接中的 limit 仅支持 10、20 或 50。");
    }
    const type = request.type === "" ? null : request.type;
    if (type !== null && (Array.from(type).length > 128 || /[\u0000-\u001f\u007f-\u009f]/u.test(type))) {
      throw new Error("链接中的 type 必须是不超过 128 个字符且不含控制字符的类型 ID。");
    }
    const scope = geography(request.country, request.region);
    const subdivision = normalizeSubdivision(scope.country, request.subdivision);
    return { query, mode: request.mode, type, limit: request.limit,
      ...(scope.country ? { country: scope.country } : {}), ...(scope.region ? { region: scope.region } : {}), ...(subdivision ? { subdivision } : {}) };
  }

  function parseLink(url: URL): ParsedLink {
    const parameters = url.searchParams;
    if (!parameterNames.some((name) => parameters.has(name))) return { request: null, error: null };
    for (const name of parameterNames) {
      if (parameters.getAll(name).length > 1) {
        return { request: null, error: `链接中的 ${name} 参数不能重复。` };
      }
    }
    for (const name of ["country", "region", "subdivision"]) {
      if (parameters.has(name) && parameters.get(name) === "") return { request: null, error: `链接中的 ${name} 不能是空筛选值。` };
    }
    const mode = parameters.get("mode") ?? "semantic";
    if (mode !== "semantic" && mode !== "bm25") {
      return { request: null, error: "链接中的 mode 仅支持 semantic 或 bm25。" };
    }
    const limit = parameters.get("limit") ?? "10";
    if (limit !== "10" && limit !== "20" && limit !== "50") {
      return { request: null, error: "链接中的 limit 仅支持 10、20 或 50。" };
    }
    try {
      const request = normalizeRequest({
        query: parameters.get("q") ?? "",
        mode,
        type: parameters.get("type"),
        limit: Number(limit),
        country: parameters.get("country"), region: parameters.get("region"),
        subdivision: parameters.get("subdivision"),
      });
      return { request, error: null };
    } catch (error) {
      return { request: null, error: error instanceof Error ? error.message : "检索链接参数无效。" };
    }
  }

  function buildLink(base: URL, request: SearchSpec | null, view: HistoryView | null = null, selection: Selection = { site: null, phase: null }, browse: BrowseState | null = null): string {
    const normalized = request ? normalizeRequest(request) : null;
    if (base.protocol !== "http:" && base.protocol !== "https:") {
      throw new Error("检索链接仅支持 HTTP 或 HTTPS 页面。");
    }
    const url = new URL(base.origin);
    url.pathname = base.pathname;
    if (normalized) {
      url.searchParams.set("q", normalized.query);
      url.searchParams.set("mode", normalized.mode);
      url.searchParams.set("type", normalized.type ?? "");
      url.searchParams.set("limit", String(normalized.limit));
      if (normalized.country) url.searchParams.set("country", normalized.country);
      if (normalized.region) url.searchParams.set("region", normalized.region);
      if (normalized.subdivision) url.searchParams.set("subdivision", normalized.subdivision);
    }
    if (view) {
      if (!validYear(view.year) || view.year < -3400 || view.year > 2024) throw new Error("地图年份无效。");
      url.searchParams.set("year", String(view.year));
      url.searchParams.set("basemap", view.basemap);
      url.searchParams.set("boundaries", view.boundaries ? "1" : "0");
    }
    if (selection.site) url.searchParams.set("site", selection.site);
    if (selection.site && selection.phase) url.searchParams.set("phase", selection.phase);
    if (browse) {
      const scope = geography(browse.country, browse.region);
      const subdivision = normalizeSubdivision(scope.country, browse.subdivision);
      const bbox = normalizeBBox(browse.bbox);
      if (!Number.isInteger(browse.offset) || browse.offset < 0 || browse.offset > 1_000_000) throw new Error("目录页码无效。");
      url.searchParams.set("browse_country", scope.country ?? "");
      url.searchParams.set("browse_region", scope.region ?? "");
      if (subdivision) url.searchParams.set("browse_subdivision", subdivision);
      if (browse.offset) url.searchParams.set("browse_offset", String(browse.offset));
      if (!browse.visible) url.searchParams.set("points", "0");
      if (bbox !== null) url.searchParams.set("browse_bbox", bbox.join(","));
    }
    return url.href;
  }

  interface SpatialSnapshot {
    metadata: unknown;
    selected: {
      site_id: string;
      representative_point: [number, number] | null;
      source_points: [number, number][];
      records: { source_index: number; coordinate: [number, number]; name: string; ref: string }[];
      source?: { name: string; uri: string; version: string; license: string; license_uri: string; sha256: string } | null;
    } | null;
  }

  type RegisteredAreasSnapshot = NonNullable<ReturnType<ReturnType<typeof ArchSearchRegisteredAreas.create>["getSnapshot"]>>;

  function createExport<T>(request: SearchSpec, response: SearchResponse<T>, exportedAt: string, map: HistoryView | null = null, selection: Selection = { site: null, phase: null }, selectedSite: unknown = null, browse: BrowseState | null = null, spatial: SpatialSnapshot | null = null, registeredAreas: RegisteredAreasSnapshot | null = null, currentCorpusVersion: string | null = response.corpus_version, currentRegisteredAreasVersion: string | null = registeredAreas?.version ?? null) {
    const normalized = normalizeRequest(request);
    if (normalized.query !== response.query || normalized.mode !== response.mode) {
      throw new Error("导出请求必须与成功响应的查询和检索方式一致。");
    }
    validateSubdivisionResponse(normalized, response);
    if (browse?.subdivision && !subdivisionVersion(browse.subdivision_version)) throw new Error("尚未成功应用的来源省区不能加入目录导出。");
    if (browse) normalizeSubdivision(browse.country, browse.subdivision);
    const selectedMatches = selectedSite !== null && typeof selectedSite === "object" && "id" in selectedSite && selectedSite.id === selection.site;
    const areas = registeredAreas?.displayed === true && selectedMatches && selection.site === registeredAreas.site_id
      && registeredAreas.corpus_version === response.corpus_version && registeredAreas.corpus_version === currentCorpusVersion && registeredAreas.version === currentRegisteredAreasVersion
      ? { ...ArchSearchRegisteredAreas.parseAreas(registeredAreas, registeredAreas.site_id, currentCorpusVersion, currentRegisteredAreasVersion), displayed: true as const } : null;
    if (areas && (!areas.ready || areas.features.length === 0)) throw new Error("未实际显示的登记范围不能加入导出。");
    return {
      schema_version: 2,
      exported_at: exportedAt,
      request: normalized,
      response,
      map: map ? { ...map } : null,
      selection: { ...selection },
      selected_site: selectedSite,
      spatial: spatial === null ? null : JSON.parse(JSON.stringify(spatial)) as SpatialSnapshot,
      registered_areas: areas,
      browse: browse ? { ...browse, bbox: normalizeBBox(browse.bbox) } : null,
      sources: [
        { name: "Pleiades", version: "v4.1", license: "CC BY 3.0", uri: "https://pleiades.stoa.org/" },
        { name: "UNESCO World Heritage descriptions", license: "CC BY-SA 3.0 IGO", uri: "https://whc.unesco.org/en/disclaimer/", note: "Individual record references retain attribution and revisions; other linked documents retain their own rights." },
        { name: "UNESCO DataHub World Heritage List", license: "CC BY-SA 4.0", uri: "https://data.unesco.org/explore/dataset/whc001/", note: "Frozen cultural and mixed catalogue, HTML-to-text processing; individual records retain snapshot hashes and attribution. No images redistributed." },
        { name: "Antarctic Treaty Secretariat — Historic Sites and Monuments", license: "CC BY 4.0", uri: "https://www.ats.aq/devph/en/apa-database", note: "Frozen active HSM records. Unknown true locations remain null; polar coordinates retain their original values. Proposing parties do not establish sovereignty." },
        { name: "Wikidata", license: "CC0", uri: "https://www.wikidata.org/wiki/Wikidata:Licensing" },
        { name: "Country cultural supplement", version: "country-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SUPPLEMENT-LICENSE.md", note: "Wikidata structured fields CC0; authority excerpts retain individual rights. Proposed heritage is not relabelled as protected or inscribed. Three records lack verified public digital coordinates. No new historical phases inferred." },
        { name: "Regional cultural supplement", version: "regional-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/REGIONAL-LICENSE.md", note: "Source-reviewed cultural places in sparse northern, island and interior regions. Original site coordinates are separate from museum display locations. Source qualification and country association do not establish historical dates or sovereignty. No new historical phases inferred." },
        { name: "South America cultural supplement", version: "southamerica-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SOUTHAMERICA-LICENSE.md", note: "Source-reviewed cultural places in six South American countries. Public representative coordinates retain source limits; absent or conflicting coordinates remain null. Wikidata English short descriptions and separately attributed Chinese translations are CC0. Identity review does not establish historical stages or a complete regional inventory." },
        { name: "Africa cultural supplement", version: "africa-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/AFRICA-LICENSE.md", note: "Five source-reviewed cultural identities from State Party tentative submissions, not World Heritage inscriptions or a complete African inventory. Wikidata metadata is CC0; authority excerpts retain individual rights. Unadopted representative coordinates remain null; no new historical phases are inferred." },
        { name: "Pacific and interior cultural supplement", version: "pacific-interior-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/PACIFIC-LICENSE.md", note: "Seven independently source-reviewed cultural identities from Pacific registers and African archaeological research. An address-restricted place remains unmapped; unadopted or conflicting representative coordinates remain null. Tentative submissions are not World Heritage inscriptions. No listing, excavation or publication year becomes a historical phase." },
        { name: "NPS Pacific register supplement", version: "nps-pacific-v1", license: "NPS government structured metadata; other source rights retained", uri: "https://www.nps.gov/aboutus/disclaimer.htm", note: "Project grouping of seven source State labels, not a UNESCO region or sovereignty classification. Government metadata does not relicense third-party nomination text, photos or attachments. Viewer text, feature edits and newer downloads have separate version clocks. Source points may be generated reference positions; restricted locations remain unmapped. No registration or publication date becomes a site phase." },
        { name: "Canadian Federal Heritage Designations historic-place supplement", version: "canada-dfhd-v1", license: "Open Government Licence - Canada; Wikidata structured claims CC0", license_uri: "https://open.canada.ca/en/open-government-licence-canada", uri: "https://open.canada.ca/data/en/dataset/49d5ba7d-d860-40d9-9183-892979e4acbe", note: "Parks Canada / Government of Canada. Contains information licensed under the Open Government Licence – Canada. Released NHS identities, original narrative and province fields retain their source version. Adopted public reference points retain separate source statements and roles; no generated centroids or ancient footprints. Commemorative-reason or plaque review notices are separate from project identity approval and chronology. Other webpages and third-party materials retain their own rights." },
        { name: "Source-associated province, district, municipality and commune memberships", version: "source-subdivisions-v5", license: "Mixed rights — DFHD fields OGL-Canada; CSDI custom terms; Iepha-MG fields CC BY 4.0; Mérimée fields Open Licence 2.0; other webpages retain individual rights", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SUBDIVISIONS-LICENSE.md", note: "Only the986 DFHD objects' province fields use Open Government Licence – Canada. CRHP and Parks Canada short location facts retain webpage rights. Canadian whole-object provinces and aliases are unchanged. Hong Kong districts associate source features with an explicitly reviewed whole and do not assert that every shape belongs to that district. CSDI Terms apply to those original fields, not all AMO contents. Version5 retains Iepha-MG original-record municipio values and adds reviewed Mérimée original-record Commune_forme_editoriale values in GP, BL, MF, MQ and RE to global-v17. Compound locality values stay intact; record-to-composite associations do not assert whole-object jurisdiction. Project label IDs are not statutory administrative IDs. Each request/response and browse retains its actual successful version. No coordinate geocoding, inferred parent membership, borders or historical phases." },
        { name: "Iepha-MG protected cultural registration scopes", version: "minas-tombados-v1", license: "CC BY 4.0", license_uri: "https://creativecommons.org/licenses/by/4.0/", uri: "https://dados.mg.gov.br/dataset/bens-tombados", accessed: "2026-11-05", note: "Instituto Estadual do Patrimônio Histórico e Artístico de Minas Gerais, via dados.mg.gov.br; fixed original Portuguese registration fields, grouped by exact process and complete designation after independent source review. Project scope IDs are derived identities, not legal registration numbers. Original process, legal-act and book fields are retained without interpreting them as construction or use dates. The source has no coordinates; representative points and precision remain null. Original municipality values support record-associated browsing without geocoding or asserting a complete regional inventory. Linked documents and photographs are not redistributed." },
        { name: "Mérimée overseas protected-notice scopes", version: "merimee-overseas-v1", license: "Licence Ouverte / Open Licence version 2.0", license_uri: "https://www.data.gouv.fr/pages/legal/licences/etalab-2-0", uri: "https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2", accessed: "2026-11-05", source_updated: "2026-10-29T02:16:04+00:00", processed: "2026-11-05", note: "Ministère de la Culture, Immeubles protégés au titre des Monuments Historiques, via data.gouv.fr; source updated on2026-10-29T02:16:04+00:00, accessed and processed on2026-11-05. Original French notice fields and protection-scope text retain source qualification: the catalogue includes formerly or currently protected records, without asserting current legal status. Partial protection is not expanded to a whole estate; notice references and record-associated Commune values are not statutory parcels or jurisdiction boundaries. The project uses reviewed published WGS84 points only as reference positions, without a whole-centre or precision claim; the provider did not state point-generation method or precision. Missing points stay null. Original protection dates do not create historical phases. Processing retains original fields and separately reviewed modern area associations; it does not translate names or fabricate historical facts. The dataset licence does not automatically cover linked photographs or third-party contents." },
        { name: "Australian National Heritage List public spatial database", version: "australia-nhl-v1", license: "CC BY 3.0 Australia", license_uri: "https://creativecommons.org/licenses/by/3.0/au/", uri: "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/National_Heritage_List/FeatureServer/0", note: "Public factual register fields and provider registered ranges only. Modern heritage registration is not an ancient footprint, political boundary, access permission or a representative point. Individual feature source URIs, versions, hashes and licences remain with registered_areas; linked third-party materials retain their own rights." },
        { name: "Hong Kong monument source facts and CSDI polygons", version: "hong-kong-monuments-v1", license: "CSDI Portal Terms and Conditions of Use; separate AMO short-fact and linked-content rights", uri: "https://portal.csdi.gov.hk/csdi-webpage/doc/TNC", note: "Data from the Government of the Hong Kong Special Administrative Region, CSDI Portal and Antiquities and Monuments Office; their intellectual property rights are acknowledged. Original January2026 CSDI attributes/polygons and later October2026 official whole-object facts retain separate source dates. Source polygons are not asserted legal or ancient boundaries and never create representative points. AMO introductions, photos and other third-party contents have no blanket CSDI licence." },
        { name: "Singapore NHB Monuments (GEOJSON)", version: "singapore-monuments-v1", license: "Singapore Open Data Licence version 1.0", license_uri: "https://data.gov.sg/open-data-licence", uri: "https://data.gov.sg/datasets/d_b29c230ec6b609e29ed42f71ca9a8767/view", accessed: "2026-11-05", note: "Contains information from Monuments (GEOJSON), National Heritage Board, accessed on2026-11-05 via data.gov.sg, made available under the Singapore Open Data Licence version1.0. Original licensed descriptions and provider Point coordinates retain their source fields and release clocks. The project uses the original provider Point as a reference position and makes no whole-centre or precision claim; the provider did not state the point-generation method or precision. It is not an excavation or legal-boundary assertion. Feature updates and protection dates are not historical phases. The licence does not automatically cover linked webpages, images or third-party rights." },
        { name: "UNESCO Hague cultural properties", version: "protection-supplement-v1", license: "CC BY-SA 4.0", uri: "https://data.unesco.org/explore/dataset/chp001/", note: "Reviewed cultural places from a fixed protection register; source rows and component locations are not new-site counts. Source protection years do not establish historical phases. Unresolved or storage-only locations remain in the source audit and are not mapped as archaeological places." },
        { name: "Cliopatria", version: map?.source_version ?? null, license: "CC BY 4.0", uri: "https://github.com/Seshat-Global-History-Databank/cliopatria", note: "Historical polity approximations; valid source intervals, no interpolation or point-based political attribution." },
        { name: "Natural Earth", license: "Public domain", uri: "https://www.naturalearthdata.com/about/terms-of-use/", note: "Modern natural-geography reference; no ancient coastline reconstruction." },
        { name: "OpenStreetMap contributors", license: "ODbL", uri: "https://www.openstreetmap.org/copyright", displayed: map?.basemap === "modern" },
      ],
      source: {
        name: "Pleiades: A Gazetteer of Past Places",
        version: "v4.1",
        uri: "https://pleiades.stoa.org/",
        release_uri: "https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1",
        commit: "b6a6790f71c45e4a4ef60fce296c506f28f458bf",
        license: "CC BY 3.0",
        license_uri: "https://creativecommons.org/licenses/by/3.0/",
        attribution: "Copyright The Contributors. Pleiades, Ancient World Mapping Center and Institute for the Study of the Ancient World.",
      },
      provenance: {
        processing: "来源资料经 HTML 转纯文本和空白规范化；别名、类型、分期证据、原文出处和贡献者随结果保留，未生成历史事实或补造坐标。",
        scope: "保留原有策展资料、固定文化／混合名录与南极历史资料，另有逐条核验的国家文化补充；资格来源可能是预备名录、国家文保或考古研究，不一概表示正式世界遗产。不是全世界所有遗址清单。response为成功检索快照，selected_site可为独立目录选择，没有虚构排名或分数。",
        coordinates: "repr_point 为 WGS84 [经度, 纬度] 代表点，用于地图定位；不等同于实测发掘坐标，location_precision 不承诺米级精度。",
        scores: "检索分数不是相关概率，不同检索方式的分数不可直接比较；本导出不包含人工相关性判断或评测指标。",
        periods: "分期来自名称或位置记录的来源关联；不等同于建造年代或连续使用证明，start/end 保留原始记录时间范围。",
        chronology: "历史阶段独立记录事件类型、精度、证据和代理核验方式；区间或时期不证明连续存在，未标成人工专家确认。",
        map: "map保存最后成功显示的年份与疆域版本；null表示尚无成功地图快照，待加载或失败年份不冒充已显示年份。",
        locations: "repr_point为null表示本记录无可用代表点：可能真实位置不明，也可能尚未取得可信公开数字坐标，来源说明保留区别；不等于零坐标。有效极区坐标超出Web Mercator时使用独立极区示意，不截断或伪造纬度。极区底图为现代自然地理参照，不生成历史国界。",
        source_points: "spatial保留最后成功目录的组合源点版本、source_groups对应的来源／版本／许可与地点身份，以及独立选中资料经审核纳入地图的定位序列、重复记录与来源标签。原代表点单独保存；多个定位记录不增加遗址条目数或承诺发掘精度。世界遗产原始序列保持不变；海牙名录排除的仓储、标签冲突等原记录仍保留在来源审计中，不混作考古原址点。",
        registered_areas: "registered_areas只保存当前实际显示、且与选中资料和当前语料/检索版本一致的来源范围；label区分现代遗产登记范围与来源古迹多边形，后者不承诺法定边界。null表示未显示或上下文不匹配。保留原WGS84闭环与来源版本/许可，不推内外环、代表点、古址轮廓、准入或点计数。范围显隐不写入分享链接，重新打开后仍须主动点击查看。",
        browse: "browse保存成功应用的独立目录条件；bbox为[西,南,东,北]闭区间，西大于东表示跨日期变更线，仅筛目录和全库点层，不改变request中的检索语义。spatial_match_mode及spatial_version记录当时的来源点匹配能力；representative-only可能遗漏无代表点落入框内的组成地点。选中资料纳入地图的来源序列完整导出；海牙名录未纳入地图的保护设施仍留在冻结来源审计中。",
        subdivisions: "加拿大采用整体省区原字段；香港采用有明确整体／要素关联的来源要素地区；巴西Iepha-MG采用原登记行municipio全文值；Mérimée采用原记录Commune_forme_editoriale全文值，多地值不自动拆分。来源要素／原记录关联不表示整体或全部组成部分都属于该地区，不由坐标、省界或历史政权推断。request/response与browse各保存其独立成功条件；subdivision_version为各自实际应用的来源索引版本，未成功的待选条件不冒充已显示范围。",
      },
    };
  }

  return { parseLink, parseView, parseBrowse, buildLink, createExport, validYear, automaticPhaseYear, normalizeBBox, parseBBox, normalizeSubdivision, validateSubdivisionResponse, parseMinasSource, minasSourceFields, parseMerimeeSource, merimeeSourceFields };
})();

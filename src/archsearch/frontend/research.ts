const ArchSearchResearch = (() => {
  "use strict";

  interface SearchSpec {
    query: string;
    mode: "semantic" | "bm25";
    type: string | null;
    limit: number;
    country?: string | null;
    region?: string | null;
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

  const regions = ["africa", "arab-states", "asia-pacific", "europe-north-america", "latin-america-caribbean", "antarctica"];

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
      for (const name of ["browse_country", "browse_region", "browse_offset", "points", "browse_bbox"]) {
        if (url.searchParams.getAll(name).length > 1) throw new Error(`链接中的 ${name} 参数不能重复。`);
      }
      const scope = geography(url.searchParams.get("browse_country"), url.searchParams.get("browse_region"));
      const rawOffset = url.searchParams.get("browse_offset") ?? "0";
      const points = url.searchParams.get("points") ?? "1";
      if (!/^(?:0|[1-9]\d{0,6})$/u.test(rawOffset) || Number(rawOffset) > 1_000_000) throw new Error("目录页码无效。");
      if (points !== "0" && points !== "1") throw new Error("全库点图层参数无效。");
      return { state: { ...scope, offset: Number(rawOffset), visible: points === "1", bbox: parseBBox(url.searchParams.get("browse_bbox")) }, error: null };
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
  }

  const parameterNames = ["q", "mode", "type", "limit", "country", "region"] as const;

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
    return { query, mode: request.mode, type, limit: request.limit,
      ...(scope.country ? { country: scope.country } : {}), ...(scope.region ? { region: scope.region } : {}) };
  }

  function parseLink(url: URL): ParsedLink {
    const parameters = url.searchParams;
    if (!parameterNames.some((name) => parameters.has(name))) return { request: null, error: null };
    for (const name of parameterNames) {
      if (parameters.getAll(name).length > 1) {
        return { request: null, error: `链接中的 ${name} 参数不能重复。` };
      }
    }
    for (const name of ["country", "region"]) {
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
      const bbox = normalizeBBox(browse.bbox);
      if (!Number.isInteger(browse.offset) || browse.offset < 0 || browse.offset > 1_000_000) throw new Error("目录页码无效。");
      url.searchParams.set("browse_country", scope.country ?? "");
      url.searchParams.set("browse_region", scope.region ?? "");
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

  function createExport<T>(request: SearchSpec, response: SearchResponse<T>, exportedAt: string, map: HistoryView | null = null, selection: Selection = { site: null, phase: null }, selectedSite: unknown = null, browse: BrowseState | null = null, spatial: SpatialSnapshot | null = null) {
    const normalized = normalizeRequest(request);
    if (normalized.query !== response.query || normalized.mode !== response.mode) {
      throw new Error("导出请求必须与成功响应的查询和检索方式一致。");
    }
    return {
      schema_version: 2,
      exported_at: exportedAt,
      request: normalized,
      response,
      map: map ? { ...map } : null,
      selection: { ...selection },
      selected_site: selectedSite,
      spatial: spatial === null ? null : JSON.parse(JSON.stringify(spatial)) as SpatialSnapshot,
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
        browse: "browse保存成功应用的独立目录条件；bbox为[西,南,东,北]闭区间，西大于东表示跨日期变更线，仅筛目录和全库点层，不改变request中的检索语义。spatial_match_mode及spatial_version记录当时的来源点匹配能力；representative-only可能遗漏无代表点落入框内的组成地点。选中资料纳入地图的来源序列完整导出；海牙名录未纳入地图的保护设施仍留在冻结来源审计中。",
      },
    };
  }

  return { parseLink, parseView, parseBrowse, buildLink, createExport, validYear, automaticPhaseYear, normalizeBBox, parseBBox };
})();

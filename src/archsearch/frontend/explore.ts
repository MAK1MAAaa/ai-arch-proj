const ArchSearchExplore = (() => {
  "use strict";

  interface State {
    country: string | null;
    region: string | null;
    offset: number;
    visible: boolean;
  }

  interface Point {
    id: string;
    title: string;
    repr_point: [number, number];
    countries: string[];
    regions: string[];
    source_kind: string;
    chronology_status: "reviewed" | "insufficient" | "not_reviewed";
  }

  interface Facet { id: string; label: string; count: number }
  interface Coverage {
    corpus_version: string; total: number; countries: Facet[]; regions: Facet[]; sources: Facet[];
    chronology: { reviewed: number; insufficient: number; not_reviewed: number };
    geography_unknown: number; country_unknown: number;
    authority: Authority | null;
  }
  interface Authority {
    dataset: string; source_uri: string; source_modified: string; source_sha256: string;
    license: string; license_uri: string; eligible_total: number; covered: number; missing: number;
    excluded_natural: number; note: string;
  }
  interface Catalogue { corpus_version: string; total: number; points: Point[] }
  interface Page { corpus_version: string; total: number; offset: number; limit: number; sites: Point[] }
  interface Options {
    map: L.Map | null;
    onSelect(id: string, opener: HTMLElement): void;
    onFilterChange?(state: State): void;
    onStateChange?(state: State): void;
    onCommittedState?(state: State): void;
    onFeedback?(message: string): void;
  }

  const pageSize = 50;
  const regionLabels: Readonly<Record<string, string>> = {
    "africa": "非洲",
    "arab-states": "阿拉伯国家",
    "asia-pacific": "亚太地区",
    "europe-north-america": "欧洲和北美洲",
    "latin-america-caribbean": "拉丁美洲和加勒比地区",
  };
  const sourceLabels: Readonly<Record<string, string>> = {
    pleiades: "Pleiades 罗马资料", global: "已策展全球资料", unesco: "世界遗产名录",
  };
  const chronologyLabels: Readonly<Record<Point["chronology_status"], string>> = {
    reviewed: "已有来源支持的阶段", insufficient: "已核验，断代未确定", not_reviewed: "断代尚未核验",
  };

  function normalizeState(value: Partial<State>): State {
    const country = value.country ?? null;
    const region = value.region ?? null;
    const offset = value.offset ?? 0;
    const visible = value.visible ?? true;
    if (country !== null && (typeof country !== "string" || !/^[A-Z]{2}$/u.test(country))) throw new Error("目录国家／地区代码应为来源中的大写双字母代码。");
    if (region !== null && (typeof region !== "string" || !Object.hasOwn(regionLabels, region))) throw new Error("目录分区代码不在来源分区中。");
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > 1_000_000) throw new Error("目录起始位置应为0至1000000的整数。");
    if (typeof visible !== "boolean") throw new Error("目录点位开关无效。");
    return { country, region, offset, visible };
  }

  function matches(point: Pick<Point, "countries" | "regions">, state: Pick<State, "country" | "region">): boolean {
    return (state.country === null || point.countries.includes(state.country))
      && (state.region === null || point.regions.includes(state.region));
  }

  function coordinate(value: unknown): value is [number, number] {
    return Array.isArray(value) && value.length === 2
      && typeof value[0] === "number" && Number.isFinite(value[0]) && value[0] >= -180 && value[0] <= 180
      && typeof value[1] === "number" && Number.isFinite(value[1]) && value[1] >= -90 && value[1] <= 90;
  }

  function displayCoordinates(value: [number, number]): L.LatLngTuple[] {
    return [-360, 0, 360].map((offset) => [value[1], value[0] + offset]);
  }

  function record(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function text(value: unknown): value is string { return typeof value === "string" && Boolean(value.trim()); }
  function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
  function version(value: unknown): value is string { return text(value) && value.length <= 128; }

  function countryLabel(facet: Facet): string {
    try {
      const translated = new Intl.DisplayNames(["zh-CN"], { type: "region" }).of(facet.id);
      if (translated && translated !== facet.id) return `${translated}（${facet.id}）`;
    } catch { /* Keep the source label when locale display names are unavailable. */ }
    return `${facet.label}（${facet.id}）`;
  }

  function httpUrl(value: unknown): string {
    if (!text(value)) throw new Error("覆盖统计来源链接缺失。");
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error("覆盖统计来源链接无效。");
    return url.href;
  }

  function parseAuthority(value: unknown): Authority | null {
    if (value === null || value === undefined) return null;
    if (!record(value) || !text(value.dataset) || !text(value.source_modified) || !text(value.source_sha256)
      || !/^[a-f0-9]{64}$/u.test(value.source_sha256) || !text(value.license) || typeof value.note !== "string"
      || !count(value.eligible_total) || !count(value.covered) || !count(value.missing) || !count(value.excluded_natural)
      || value.covered + value.missing !== value.eligible_total) throw new Error("官方名录覆盖分母或来源元数据无效。");
    return { dataset: value.dataset, source_uri: httpUrl(value.source_uri), source_modified: value.source_modified,
      source_sha256: value.source_sha256, license: value.license, license_uri: httpUrl(value.license_uri),
      eligible_total: value.eligible_total, covered: value.covered, missing: value.missing, excluded_natural: value.excluded_natural, note: value.note };
  }

  function facets(value: unknown, kind: "country" | "region" | "source"): Facet[] {
    if (!Array.isArray(value)) throw new Error("覆盖统计缺少来源分组。");
    const seen = new Set<string>();
    return value.map((item: unknown) => {
      if (!record(item) || !text(item.id) || !text(item.label) || !count(item.count) || seen.has(item.id)
        || (kind === "country" && !/^[A-Z]{2}$/u.test(item.id)) || (kind === "region" && !Object.hasOwn(regionLabels, item.id))) throw new Error("覆盖统计分组格式无效。");
      seen.add(item.id);
      return { id: item.id, label: item.label, count: item.count };
    });
  }

  function parseCoverage(value: unknown): Coverage {
    if (!record(value) || !version(value.corpus_version) || !count(value.total) || !record(value.chronology)
      || !count(value.chronology.reviewed) || !count(value.chronology.insufficient) || !count(value.chronology.not_reviewed)
      || !count(value.geography_unknown) || !count(value.country_unknown)) throw new Error("覆盖统计格式无效。");
    const result: Coverage = {
      corpus_version: value.corpus_version, total: value.total, countries: facets(value.countries, "country"),
      regions: facets(value.regions, "region"), sources: facets(value.sources, "source"),
      chronology: { reviewed: value.chronology.reviewed, insufficient: value.chronology.insufficient, not_reviewed: value.chronology.not_reviewed },
      geography_unknown: value.geography_unknown, country_unknown: value.country_unknown,
      authority: parseAuthority(value.authority),
    };
    if (Object.values(result.chronology).reduce((sum, amount) => sum + amount, 0) !== result.total
      || result.sources.reduce((sum, item) => sum + item.count, 0) !== result.total
      || result.country_unknown > result.total || result.geography_unknown > result.total) throw new Error("覆盖统计总数不一致。");
    return result;
  }

  function stringArray(value: unknown, kind: "country" | "region"): string[] {
    if (!Array.isArray(value) || value.some((item: unknown) => typeof item !== "string"
      || (kind === "country" ? !/^[A-Z]{2}$/u.test(item) : !Object.hasOwn(regionLabels, item)))
      || new Set(value).size !== value.length) throw new Error("目录来源地域标签无效。");
    return value as string[];
  }

  function parsePoint(value: unknown, fullSite = false): Point {
    if (!record(value) || !text(value.id) || !/^(?:[1-9]\d*|wd:Q[1-9]\d*|whc:[1-9]\d*)$/u.test(value.id)
      || !text(value.title) || !coordinate(value.repr_point) || !text(value.source_kind)) throw new Error("目录地点编号、标题或代表点无效。");
    const geography = fullSite ? record(value.geography) ? value.geography : { countries: [], regions: [] } : value;
    const status = fullSite ? record(value.chronology) ? value.chronology.status : undefined : value.chronology_status;
    if (status !== "reviewed" && status !== "insufficient" && status !== "not_reviewed") throw new Error("目录断代核验状态无效。");
    return { id: value.id, title: value.title, repr_point: [...value.repr_point], countries: stringArray(geography.countries, "country"),
      regions: stringArray(geography.regions, "region"), source_kind: value.source_kind, chronology_status: status };
  }

  function parseCatalogue(value: unknown, coverage: Coverage): Catalogue {
    if (!record(value) || value.corpus_version !== coverage.corpus_version || value.total !== coverage.total
      || !Array.isArray(value.points) || value.points.length !== coverage.total) throw new Error("全库点目录与覆盖统计版本或总数不一致。");
    const points = value.points.map((item: unknown) => parsePoint(item));
    if (new Set(points.map((item) => item.id)).size !== points.length
      || points.some((item) => item.countries.some((id) => !coverage.countries.some((facet) => facet.id === id))
        || item.regions.some((id) => !coverage.regions.some((facet) => facet.id === id)))) throw new Error("全库点目录存在重复编号或未登记地域标签。");
    return { corpus_version: coverage.corpus_version, total: coverage.total, points };
  }

  function parsePage(value: unknown, catalogue: Catalogue, state: State): Page {
    const points = catalogue.points.filter((point) => matches(point, state));
    if (!record(value) || value.corpus_version !== catalogue.corpus_version || value.total !== points.length
      || value.offset !== state.offset || value.limit !== pageSize || !Array.isArray(value.sites)
      || value.sites.length !== Math.min(pageSize, Math.max(0, points.length - state.offset))) throw new Error("目录分页与点位范围或版本不一致。");
    const sites = value.sites.map((item: unknown) => parsePoint(item, true));
    const byId = new Map(points.map((point) => [point.id, point]));
    if (new Set(sites.map((site) => site.id)).size !== sites.length || sites.some((site, index) => {
      const point = byId.get(site.id);
      return site.id !== points[state.offset + index]?.id || !point || JSON.stringify(point) !== JSON.stringify(site);
    })) throw new Error("目录分页与点位来源记录不一致。");
    return { corpus_version: catalogue.corpus_version, total: points.length, offset: state.offset, limit: pageSize, sites };
  }

  function create({ map, onSelect, onFilterChange, onStateChange, onCommittedState, onFeedback }: Options) {
    const get = <T extends HTMLElement>(id: string): T => {
      const node = document.getElementById(id);
      if (!node) throw new Error(`目录组件缺少 ${id}。`);
      return node as T;
    };
    const ui = {
      panel: get("explore-panel"), summary: get("explore-summary"), country: get<HTMLSelectElement>("explore-country"),
      authority: get("explore-authority"),
      region: get<HTMLSelectElement>("explore-region"), clear: get<HTMLButtonElement>("explore-clear"),
      points: get<HTMLInputElement>("explore-points"), fit: get<HTMLButtonElement>("explore-fit"),
      count: get("explore-count"), list: get<HTMLOListElement>("explore-list"),
      previous: get<HTMLButtonElement>("explore-previous"), next: get<HTMLButtonElement>("explore-next"),
      page: get("explore-page"), feedback: get("explore-feedback"), retry: get<HTMLButtonElement>("explore-retry"),
      limit: get("explore-limit-note"),
    };
    const limitNote = ui.limit.textContent ?? "";
    let desired = normalizeState({});
    let applied: State | null = null;
    let coverage: Coverage | null = null;
    let catalogue: Catalogue | null = null;
    let page: Page | null = null;
    let controller: AbortController | null = null;
    let sequence = 0;
    let loading = false;
    let failed = false;
    let layer: L.LayerGroup | null = null;
    let markers = new Map<string, L.CircleMarker[]>();
    let selectedId: string | null = null;
    const buttons = new Map<string, HTMLButtonElement>();
    let renderer: L.Canvas | null = null;
    if (map && typeof L !== "undefined") {
      const pane = map.getPane("catalogue-points") ?? map.createPane("catalogue-points");
      pane.style.zIndex = "450";
      renderer = L.canvas({ pane: "catalogue-points", padding: 0.5 });
    }

    function feedback(message: string, error = false): void {
      failed = error;
      ui.panel.classList.toggle("has-error", error);
      ui.feedback.textContent = message;
      ui.retry.hidden = !error;
      onFeedback?.(message);
    }

    function getCommittedState(): State | null {
      return applied ? { ...applied, visible: desired.visible } : null;
    }

    function committed(): void {
      const state = getCommittedState();
      if (state) onCommittedState?.(state);
    }

    function renderAuthority(): void {
      const source = coverage?.authority;
      ui.authority.hidden = source === null || source === undefined;
      if (!source) { ui.authority.replaceChildren(); return; }
      const summary = element("span", undefined, `当前官方文化／混合名录 ${source.covered.toLocaleString("zh-CN")} / ${source.eligible_total.toLocaleString("zh-CN")} 条已覆盖`);
      const link = element("a", undefined, "UNESCO 官方来源"); link.href = source.source_uri;
      link.target = "_blank"; link.rel = "noopener noreferrer";
      const license = element("a", undefined, source.license); license.href = source.license_uri;
      license.target = "_blank"; license.rel = "noopener noreferrer";
      const note = element("span", "explore-authority-note", `来源更新：${source.source_modified.split("T")[0]} · ${source.missing} 条待覆盖 · ${source.excluded_natural} 条纯自然遗产不在本语料范围。`);
      note.title = `${source.dataset}\nSHA256: ${source.source_sha256}\n${source.note}`;
      ui.authority.replaceChildren(summary, link, license, note);
    }

    function renderControls(): void {
      ui.panel.setAttribute("aria-busy", String(loading));
      ui.country.disabled = coverage === null;
      ui.region.disabled = coverage === null;
      ui.clear.disabled = desired.country === null && desired.region === null && desired.offset === 0;
      ui.points.checked = desired.visible;
      ui.points.disabled = !map || !catalogue;
      ui.fit.disabled = !map || !catalogue || catalogue.points.filter((point) => matches(point, applied ?? desired)).length === 0;
      ui.previous.disabled = loading || page === null || page.offset === 0;
      ui.previous.textContent = page && page.offset >= page.total && page.total > 0 ? "回到首页" : "上一页";
      ui.next.disabled = loading || page === null || page.offset + page.limit >= page.total;
      ui.retry.disabled = loading;
      if (layer && map) {
        if (desired.visible && !map.hasLayer(layer)) layer.addTo(map);
        else if (!desired.visible && map.hasLayer(layer)) map.removeLayer(layer);
      }
    }

    function renderOptions(): void {
      if (!coverage) return;
      const populate = (select: HTMLSelectElement, values: Facet[], label: string, selected: string | null, isRegion = false): void => {
        const all = element("option", undefined, label); all.value = "";
        const options = values.map((item) => {
          const option = element("option", undefined, `${isRegion ? regionLabels[item.id] : countryLabel(item)} · ${item.count}`);
          option.title = item.label;
          option.value = item.id; return option;
        });
        if (selected !== null && !values.some((item) => item.id === selected)) {
          const missing = element("option", undefined, `${selected}（当前来源无此标签）`);
          missing.value = selected; missing.disabled = true; options.push(missing);
        }
        select.replaceChildren(all, ...options); select.value = selected ?? "";
      };
      populate(ui.country, coverage.countries, "全部国家／地区", desired.country);
      populate(ui.region, coverage.regions, "全部来源分区", desired.region, true);
    }

    function select(id: string | null): void {
      selectedId = id;
      for (const [pointId, button] of buttons) button.setAttribute("aria-pressed", String(pointId === id));
      for (const [pointId, copies] of markers) for (const marker of copies) {
        const active = pointId === id;
        marker.setRadius(active ? 5 : 3.2);
        marker.setStyle({ color: active ? "#813d29" : "#586f60", fillColor: active ? "#a55339" : "#66745b", fillOpacity: active ? 0.95 : 0.5, weight: active ? 1.5 : 0.7 });
      }
    }

    function buildLayer(points: Point[]): { layer: L.LayerGroup | null; markers: Map<string, L.CircleMarker[]> } {
      const nextMarkers = new Map<string, L.CircleMarker[]>();
      if (!map || !renderer || typeof L === "undefined") return { layer: null, markers: nextMarkers };
      const next = L.layerGroup();
      for (const point of points) {
        const copies = displayCoordinates(point.repr_point).map((location) => {
          const marker = L.circleMarker(location, { pane: "catalogue-points", renderer: renderer ?? undefined, radius: 3.2,
            color: "#586f60", fillColor: "#66745b", fillOpacity: 0.5, weight: 0.7 });
          marker.bindTooltip(() => element("span", undefined, point.title), { direction: "top", offset: [0, -4] });
          marker.on("click", () => onSelect(point.id, map.getContainer()));
          marker.addTo(next); return marker;
        });
        nextMarkers.set(point.id, copies);
      }
      return { layer: next, markers: nextMarkers };
    }

    function renderPage(): void {
      if (!coverage || !page || !applied) return;
      const focused = ui.list.contains(document.activeElement);
      buttons.clear();
      const countryLabels = new Map(coverage.countries.map((item) => [item.id, countryLabel(item)]));
      const nodes = page.sites.map((site) => {
        const item = element("li"); const button = element("button", "explore-item"); button.type = "button";
        button.dataset.siteId = site.id;
        button.setAttribute("aria-pressed", String(site.id === selectedId));
        const title = site.title.trim().toLowerCase() === "untitled" ? `未命名地点 · #${site.id}` : site.title;
        button.setAttribute("aria-label", `${title}，打开目录资料，不属于检索排名`);
        const countries = site.countries.length ? site.countries.map((id) => countryLabels.get(id) ?? id).join(" · ") : "国家／地区未标注";
        button.append(element("span", "explore-item-title", title), element("span", "explore-item-meta", countries),
          element("span", "explore-item-meta", `${sourceLabels[site.source_kind] ?? site.source_kind} · ${chronologyLabels[site.chronology_status]}`));
        button.addEventListener("click", () => onSelect(site.id, button));
        buttons.set(site.id, button); item.append(button); return item;
      });
      if (!nodes.length) nodes.push(element("li", "explore-empty", page.total === 0 ? "所选国家／地区与分区组合暂无资料，可清除地域后继续浏览。" : "此目录位置超出当前筛选范围，可用上一页返回首页。"));
      ui.list.replaceChildren(...nodes);
      ui.list.scrollTop = 0;
      ui.count.textContent = `${page.total.toLocaleString("zh-CN")} 条符合地域条件`;
      const start = page.sites.length ? page.offset + 1 : 0;
      const end = page.offset + page.sites.length;
      ui.page.textContent = `${page.sites.length ? `第 ${start}—${end} 条` : "本页无资料"} / 共 ${page.total.toLocaleString("zh-CN")} 条 · 按来源标题排序，无相关性分数`;
      if (focused) ui.page.focus({ preventScroll: true });
    }

    async function json(path: string, signal: AbortSignal): Promise<unknown> {
      const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
      const value: unknown = await response.json();
      if (!response.ok) throw new Error(record(value) && typeof value.detail === "string" ? value.detail : `目录请求失败（HTTP ${response.status}）。`);
      return value;
    }

    async function request(refresh: boolean): Promise<void> {
      controller?.abort(); const current = ++sequence;
      const abort = new AbortController(); controller = abort;
      const wanted = { ...desired };
      const parameters = new URLSearchParams({ offset: String(wanted.offset), limit: String(pageSize) });
      if (wanted.country) parameters.set("country", wanted.country);
      if (wanted.region) parameters.set("region", wanted.region);
      loading = true;
      feedback(page ? "正在更新目录；列表与全库点位保留上次成功范围，检索排名和年份不变。" : "正在读取本地全库点位与覆盖统计。");
      renderControls();
      let pendingLayer: L.LayerGroup | null = null;
      try {
        const reload = refresh || !coverage || !catalogue;
        const [coverageRaw, catalogueRaw, pageRaw] = await Promise.all([
          reload ? json("/api/coverage", abort.signal) : Promise.resolve(null),
          reload ? json("/api/catalogue", abort.signal) : Promise.resolve(null),
          json(`/api/sites?${parameters}`, abort.signal),
        ]);
        if (abort.signal.aborted || current !== sequence) return;
        const nextCoverage = reload ? parseCoverage(coverageRaw) : coverage;
        if (!nextCoverage) throw new Error("覆盖统计尚未准备。");
        if ((wanted.country && !nextCoverage.countries.some((item) => item.id === wanted.country))
          || (wanted.region && !nextCoverage.regions.some((item) => item.id === wanted.region))) throw new Error("所选地域标签不在当前资料版本中，未放宽筛选。");
        const nextCatalogue = reload ? parseCatalogue(catalogueRaw, nextCoverage) : catalogue;
        if (!nextCatalogue) throw new Error("全库点位尚未准备。");
        const nextPage = parsePage(pageRaw, nextCatalogue, wanted);
        const replacePoints = nextCatalogue !== catalogue || !applied || applied.country !== wanted.country || applied.region !== wanted.region;
        const next = replacePoints ? buildLayer(nextCatalogue.points.filter((point) => matches(point, wanted))) : { layer, markers };
        pendingLayer = replacePoints ? next.layer : null;
        if (abort.signal.aborted || current !== sequence) return;
        if (replacePoints) {
          if (next.layer && desired.visible && map) next.layer.addTo(map);
          if (layer && map && map.hasLayer(layer)) map.removeLayer(layer);
        }
        coverage = nextCoverage; catalogue = nextCatalogue; page = nextPage; applied = { ...wanted };
        layer = next.layer; markers = next.markers;
        ui.summary.textContent = `${coverage.total.toLocaleString("zh-CN")} 条资料 · ${coverage.countries.length} 个国家／地区 · ${coverage.regions.length} 个来源分区`;
        ui.limit.textContent = `${limitNote} 当前 ${coverage.country_unknown.toLocaleString("zh-CN")} 条未标注国家／地区；${coverage.chronology.not_reviewed.toLocaleString("zh-CN")} 条断代尚未核验。`;
        renderAuthority(); renderOptions(); renderPage();
        if (selectedId !== null) select(selectedId);
        feedback(`当前地域范围 ${page.total.toLocaleString("zh-CN")} 条资料。${map ? "小圆点为全库资料，编号标记为检索候选。" : "地图组件不可用，可使用目录列表。"}`);
        committed();
      } catch (error) {
        if (abort.signal.aborted || current !== sequence) return;
        if (pendingLayer && map?.hasLayer(pendingLayer)) map.removeLayer(pendingLayer);
        if (layer && desired.visible && map && !map.hasLayer(layer)) layer.addTo(map);
        abort.abort();
        feedback(`${error instanceof Error ? error.message : "目录加载失败。"}${page ? " 保留上次成功目录与点位。" : " 可重试本地目录；基础检索仍独立可用。"}`, true);
        throw error;
      } finally {
        if (current === sequence) { loading = false; controller = null; renderControls(); }
      }
    }

    function load(): Promise<void> { return request(true); }

    async function setState(value: Partial<State>, options: { notify?: boolean } = {}): Promise<void> {
      let next: State;
      try { next = normalizeState({ ...desired, ...value }); }
      catch (error) { feedback(error instanceof Error ? error.message : "目录条件无效。", true); throw error; }
      const filterChanged = next.country !== desired.country || next.region !== desired.region;
      const pageChanged = next.offset !== desired.offset;
      const visibilityChanged = next.visible !== desired.visible;
      const changed = filterChanged || pageChanged || next.visible !== desired.visible;
      desired = next;
      renderOptions(); renderControls();
      if (options.notify && changed) {
        if (filterChanged) onFilterChange?.({ ...desired });
        onStateChange?.({ ...desired });
      }
      if (filterChanged || pageChanged || !catalogue) await request(false);
      else if (visibilityChanged) committed();
    }

    ui.country.addEventListener("change", () => { void setState({ country: ui.country.value || null, offset: 0 }, { notify: true }).catch(() => undefined); });
    ui.region.addEventListener("change", () => { void setState({ region: ui.region.value || null, offset: 0 }, { notify: true }).catch(() => undefined); });
    ui.clear.addEventListener("click", () => { void setState({ country: null, region: null, offset: 0 }, { notify: true }).catch(() => undefined); });
    ui.points.addEventListener("change", () => { void setState({ visible: ui.points.checked }, { notify: true }).catch(() => undefined); });
    ui.previous.addEventListener("click", () => { void setState({ offset: page && page.offset >= page.total ? 0 : Math.max(0, desired.offset - pageSize) }, { notify: true }).catch(() => undefined); });
    ui.next.addEventListener("click", () => { if (page && page.offset + page.limit < page.total) void setState({ offset: page.offset + page.limit }, { notify: true }).catch(() => undefined); });
    ui.retry.addEventListener("click", () => { void load().catch(() => undefined); });
    ui.fit.addEventListener("click", () => {
      if (!map || !catalogue) return;
      const points = catalogue.points.filter((point) => matches(point, applied ?? desired)).map((point): L.LatLngTuple => [point.repr_point[1], point.repr_point[0]]);
      if (points.length) map.fitBounds(L.latLngBounds(ArchSearchMapView.wrapCoordinates(points)), { padding: [40, 40], maxZoom: 9, animate: false });
    });
    renderControls();
    return { load, getState: (): State => ({ ...desired }), getCommittedState, setState, select,
      getPoint: (id: string): [number, number] | null => {
        const point = catalogue?.points.find((item) => item.id === id);
        return point ? [...point.repr_point] : null;
      },
    };
  }

  return { create, normalizeState, matches, coordinate, displayCoordinates, parseCoverage, parseCatalogue, parsePage };
})();

(() => {
  "use strict";

  type SearchMode = "semantic" | "bm25";

  interface PeriodEvidence {
    resource_type: "Name" | "Location";
    resource_uri: string;
    period_id: string;
    period_uri: string;
    confidence: string | null;
    association_certainty: string | null;
    start: number | null;
    end: number | null;
  }

  interface Site {
    id: string;
    title: string;
    description: string;
    details: string;
    names: string[];
    types: string[];
    periods: string[];
    repr_point: [number, number];
    location_precision: "precise" | "rough" | null;
    source_uri: string;
    contributors: string[];
    period_evidence: PeriodEvidence[];
  }

  interface SearchResult {
    site: Site;
    score: number;
    matched_fields: string[];
  }

  interface SearchRequest {
    query: string;
    mode: SearchMode;
    type: string | null;
    limit: number;
  }

  interface SearchResponse {
    results: SearchResult[];
    mode: SearchMode;
    query: string;
    elapsed_ms: number;
    corpus_version: string;
    total_candidates: number;
  }

  interface SearchContext {
    type: string | null;
    limit: number;
  }

  interface StatusResponse {
    status: string;
    corpus: { count: number; version: string; period: string };
    semantic: { ready: boolean; reason: string | null; model: string; revision: string };
  }

  interface Facet {
    id: string;
    label: string;
    count: number;
  }

  interface FacetResponse {
    types: Facet[];
  }

  interface ApplicationState {
    corpusReady: boolean;
    semanticReady: boolean;
    statusLoaded: boolean;
    searching: boolean;
    hasSearched: boolean;
    displayedMode: SearchMode | null;
    results: SearchResult[];
    selectedId: string | null;
    typeLabels: Map<string, string>;
    searchController: AbortController | null;
    detailController: AbortController | null;
    searchSequence: number;
    map: L.Map | null;
    tiles: L.TileLayer | null;
    markerLayer: L.LayerGroup | null;
    markers: Map<string, L.Marker>;
  }

  function byId<T extends HTMLElement>(id: string, expected: new () => T): T {
    const node = document.getElementById(id);
    if (!(node instanceof expected)) throw new Error(`页面元素不存在或类型错误：${id}`);
    return node;
  }
  const ui = {
    form: byId("search-form", HTMLFormElement), query: byId("query", HTMLInputElement), searchButton: byId("search-button", HTMLButtonElement),
    buttonLabel: byId("search-button-label", HTMLSpanElement), typeFilter: byId("type-filter", HTMLSelectElement),
    limitFilter: byId("limit-filter", HTMLSelectElement), modeExplanation: byId("mode-explanation", HTMLParagraphElement),
    preparationNote: byId("preparation-note", HTMLDivElement), preparationReason: byId("preparation-reason", HTMLParagraphElement),
    requestError: byId("request-error", HTMLDivElement), announcement: byId("announcement", HTMLParagraphElement),
    statusDot: byId("status-dot", HTMLSpanElement), runtimeLabel: byId("runtime-label", HTMLSpanElement),
    corpusCount: byId("corpus-count", HTMLElement), corpusPeriod: byId("corpus-period", HTMLParagraphElement),
    resultsPanel: byId("results-panel", HTMLDivElement), resultCount: byId("result-count", HTMLSpanElement),
    resultSummary: byId("result-summary", HTMLParagraphElement), activeMode: byId("active-mode", HTMLSpanElement),
    resultContext: byId("result-context", HTMLParagraphElement), exampleHint: byId("example-hint", HTMLParagraphElement),
    list: byId("results-list", HTMLOListElement), empty: byId("results-empty", HTMLDivElement), emptyTitle: byId("empty-title", HTMLHeadingElement),
    emptyDescription: byId("empty-description", HTMLParagraphElement), loading: byId("loading-state", HTMLDivElement),
    detailPanel: byId("detail-panel", HTMLElement), detailContent: byId("detail-content", HTMLDivElement),
    tileWarning: byId("tile-warning", HTMLDivElement), tileWarningText: byId("tile-warning-text", HTMLSpanElement),
    mapEmptyLabel: byId("map-empty-label", HTMLDivElement),
  };

  const state: ApplicationState = {
    corpusReady: false, semanticReady: false, statusLoaded: false, searching: false,
    hasSearched: false, displayedMode: null, results: [], selectedId: null, typeLabels: new Map(),
    searchController: null, detailController: null, searchSequence: 0,
    map: null, tiles: null, markerLayer: null, markers: new Map(),
  };

  const fieldLabels: Readonly<Record<string, string>> = {
    title: "地点名称", names: "别名", description: "原始描述", types: "地点类型",
    periods: "原始时期", details: "原始补充记录", search_text: "检索文本",
  };

  const primaryTypeLabels: Readonly<Record<string, string>> = {
    settlement: "聚落", villa: "别墅庄园", port: "港口", bath: "浴场", theatre: "剧场", "archaeological-site": "考古遗址",
  };

  const confidenceLabels: Readonly<Record<string, string>> = {
    confident: "较有把握", "less-confident": "把握较低",
    "confident-inferred": "较有把握，基于推断、无同时代证据", "less-confident-inferred": "把握较低，基于推断、无同时代证据",
  };

  const certaintyLabels: Readonly<Record<string, string>> = {
    certain: "确定", "less-certain": "确定性较低", uncertain: "不确定",
  };

  function element<K extends keyof HTMLElementTagNameMap>(
    tag: K, className?: string | null, text?: unknown,
  ): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function strings(values: unknown): string[] {
    return Array.isArray(values)
      ? values.filter((value: unknown): value is string => typeof value === "string" && Boolean(value.trim()))
      : [];
  }

  function labelFromId(value: unknown): string {
    if (typeof value !== "string") return "未提供";
    const tail = value.replace(/\/$/, "").split(/[\/#]/).pop() || value;
    return tail.replace(/[_-]/g, " ") || value;
  }

  function typeLabel(value: string): string {
    return state.typeLabels.get(value) || primaryTypeLabels[value] || labelFromId(value);
  }

  function sourceLabel(value: string | null, labels: Readonly<Record<string, string>>): string {
    if (!value) return "原始资料未提供";
    return labels[value] ? `${labels[value]}（${value}）` : value;
  }

  function periodLabel(value: string): string {
    return value === "roman" ? "罗马早期帝国（roman）" : value;
  }

  function displayTitle(site: Site): string {
    return !site.title.trim() || site.title.trim().toLowerCase() === "untitled"
      ? `未命名地点 · #${site.id}` : site.title;
  }

  function hasSourceText(value: string): boolean {
    return Boolean(value.trim()) && !["none", "null"].includes(value.trim().toLowerCase());
  }

  function sourceExcerpt(site: Site): { label: string; text: string } {
    if (site.description.startsWith("An ancient place, cited:") && hasSourceText(site.details)) {
      return { label: "目录补充原文", text: site.details };
    }
    if (hasSourceText(site.description)) return { label: "来源描述原文", text: site.description };
    if (hasSourceText(site.details)) return { label: "补充记录原文", text: site.details };
    return { label: "原文状态", text: "当前导出未提供描述，请打开详情核验来源记录。" };
  }

  function sourceYear(value: number | null): string {
    if (value === null || !Number.isFinite(value)) return "未提供";
    if (value === 0) return "原始值 0（未转换纪年）";
    return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
  }

  function currentMode(): SearchMode {
    const value = ui.form.querySelector<HTMLInputElement>('input[name="mode"]:checked')?.value;
    if (value !== "semantic" && value !== "bm25") throw new Error("页面检索方式无效。");
    return value;
  }

  function announce(message: string): void {
    ui.announcement.textContent = message;
  }

  function showError(message: string): void {
    ui.requestError.textContent = message;
    ui.requestError.hidden = !message;
  }

  function safeLink(value: unknown, label: string, className?: string): HTMLAnchorElement | HTMLSpanElement {
    try {
      if (typeof value !== "string") throw new Error("invalid URL");
      const url = new URL(value);
      if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("invalid protocol");
      const link = element("a", className, label);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch {
      return element("span", "muted", `${label}（链接未提供）`);
    }
  }

  function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : typeof error === "string" ? error : "未知错误";
  }

  function isAbortError(error: unknown): boolean {
    return error instanceof Error && error.name === "AbortError";
  }

  async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    const response = await fetch(path, { ...options, headers });
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new Error(`服务返回了无法读取的响应（HTTP ${response.status}）。`);
    }
    if (!response.ok) {
      let detail: unknown = isRecord(data) ? data.detail || data.message : undefined;
      if (Array.isArray(detail)) {
        detail = detail.map((item: unknown) => isRecord(item) && typeof item.msg === "string" ? item.msg : "请求参数无效").join("；");
      }
      if (isRecord(detail)) detail = detail.message || detail.reason;
      throw new Error(typeof detail === "string" ? detail : `请求未完成（HTTP ${response.status}）。`);
    }
    return data as T;
  }

  function updateSearchAvailability(): void {
    const mode = currentMode();
    const available = state.corpusReady && (mode === "bm25" || state.semanticReady);
    ui.searchButton.disabled = !available;
    ui.buttonLabel.textContent = state.searching ? "检索中" : "开始检索";
    ui.activeMode.textContent = (state.displayedMode || mode) === "semantic" ? "SEMANTIC" : "BM25";
    ui.preparationNote.hidden = mode !== "semantic" || !state.statusLoaded || state.semanticReady;
    ui.modeExplanation.textContent = mode === "semantic"
      ? "用中文描述研究问题，在英文原文中寻找语义相近的资料；排序分数不是相关概率，仍需核验原文。"
      : "按原文字词匹配，建议输入英文关键词或古地名；不会自动翻译或扩展同义词，零命中不代表没有相关资料。";
    ui.exampleHint.textContent = mode === "semantic"
      ? "中文问题示例；选择后会同步切换到对应地点类型。"
      : "英文原词示例；选择后会同步切换到对应地点类型。";
    document.querySelectorAll<HTMLButtonElement>("[data-query-zh]").forEach((button) => {
      const query = mode === "semantic" ? button.dataset.queryZh : button.dataset.queryEn;
      const label = button.querySelector<HTMLSpanElement>(".example-label");
      if (label) label.textContent = mode === "semantic" ? button.dataset.label || query || "示例" : query || "示例";
      button.disabled = !available || ui.typeFilter.disabled || !Array.from(ui.typeFilter.options).some((option) => option.value === button.dataset.type);
      button.setAttribute("aria-label", `检索示例：${query || ""}；类型：${typeLabel(button.dataset.type || "")}`);
      button.lang = mode === "semantic" ? "zh-CN" : "en";
    });
  }

  async function loadStatus(): Promise<void> {
    const refreshButton = byId("refresh-status", HTMLButtonElement);
    refreshButton.disabled = true;
    ui.runtimeLabel.textContent = "检查本地服务";
    try {
      const status = await api<StatusResponse>("/api/status");
      state.statusLoaded = true;
      state.corpusReady = Number(status.corpus?.count) > 0;
      state.semanticReady = status.semantic?.ready === true;
      ui.corpusCount.textContent = Number(status.corpus?.count || 0).toLocaleString("zh-CN");
      if (status.corpus?.period) ui.corpusPeriod.textContent = status.corpus.period;
      ui.statusDot.className = `status-dot ${state.semanticReady ? "is-ready" : "is-warning"}`;
      ui.runtimeLabel.textContent = state.semanticReady ? "本地检索已就绪" : state.corpusReady ? "关键词检索可用" : "等待资料准备";
      const reason = typeof status.semantic?.reason === "string" ? status.semantic.reason : "";
      ui.preparationReason.textContent = `${reason ? `${reason}。` : ""}请按 README 完成本地模型与索引准备，然后点击右上角刷新运行状态。`;
      if (!state.corpusReady) {
        showError("本地资料集尚未准备。请先按 README 导入演示资料，再刷新运行状态。");
      } else {
        showError("");
      }
      announce(state.semanticReady ? "本地语义检索已就绪。" : "本地模型尚未就绪，可以选择关键词基线。");
    } catch (error) {
      state.statusLoaded = true;
      state.semanticReady = false;
      ui.statusDot.className = "status-dot is-warning";
      ui.runtimeLabel.textContent = "服务连接失败";
      ui.preparationReason.textContent = "无法确认本地模型状态。请检查服务是否启动，再点击右上角刷新运行状态。";
      showError(`运行状态检查失败：${errorMessage(error)}`);
    } finally {
      refreshButton.disabled = false;
      updateSearchAvailability();
    }
  }

  async function loadFacets(): Promise<void> {
    try {
      const facets = await api<FacetResponse>("/api/facets");
      for (const item of facets.types || []) {
        if (typeof item.id !== "string") continue;
        const label = typeof item.label === "string" ? item.label : labelFromId(item.id);
        state.typeLabels.set(item.id, label);
        const option = element("option", null, `${label} (${Number(item.count) || 0})`);
        option.value = item.id;
        ui.typeFilter.append(option);
      }
    } catch {
      ui.typeFilter.disabled = true;
      ui.typeFilter.options[0].textContent = "类型暂不可用";
    } finally {
      updateSearchAvailability();
    }
  }

  function point(site: Site): L.LatLngTuple | null {
    const coordinate = site.repr_point;
    if (!Array.isArray(coordinate) || coordinate.length !== 2) return null;
    const [lon, lat] = coordinate;
    return Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90
      ? [lat, lon] : null;
  }

  function coordinateLabel(site: Site): string {
    const coordinate = point(site);
    if (!coordinate) return "无可用代表点";
    const [lat, lon] = coordinate;
    return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? "N" : "S"} / ${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? "E" : "W"}`;
  }

  function initializeMap(): void {
    if (typeof L === "undefined") {
      byId("map", HTMLDivElement).append(element("div", "map-unavailable", "地图组件未能加载。你仍可检索并阅读候选资料的原文与坐标。"));
      byId("fit-map", HTMLButtonElement).disabled = true;
      return;
    }
    state.map = L.map("map", { zoomControl: false, minZoom: 3, maxZoom: 18, worldCopyJump: true }).setView([37.2, 17.4], 4);
    L.control.zoom({ position: "bottomleft" }).addTo(state.map);
    state.map.attributionControl?.setPrefix(false);
    state.tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
    }).addTo(state.map);
    state.tiles.on("tileerror", () => {
      ui.tileWarning.hidden = false;
      ui.tileWarningText.textContent = "部分底图未能加载；检索结果与遗址标记仍可使用。";
    });
    state.markerLayer = L.layerGroup().addTo(state.map);
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => state.map?.invalidateSize({ pan: false })).observe(byId("map", HTMLDivElement));
    }
  }

  function fitMap(): void {
    if (!state.map) return;
    const coordinates = state.results.map((result) => point(result.site)).filter((coordinate): coordinate is L.LatLngTuple => coordinate !== null);
    if (coordinates.length === 0) {
      state.map.setView([37.2, 17.4], 4);
    } else {
      state.map.fitBounds(L.latLngBounds(coordinates), { padding: [46, 55], maxZoom: 9, animate: false });
    }
  }

  function renderMarkers(): void {
    if (!state.map || !state.markerLayer) return;
    state.markerLayer.clearLayers();
    state.markers.clear();
    for (const [index, result] of state.results.entries()) {
      const coordinate = point(result.site);
      if (!coordinate) continue;
      const markerContent = element("span", "site-marker", index + 1);
      markerContent.setAttribute("aria-hidden", "true");
      const marker = L.marker(coordinate, {
        icon: L.divIcon({ className: "site-marker-icon", html: markerContent, iconSize: [30, 30], iconAnchor: [15, 15] }),
        title: displayTitle(result.site),
        keyboard: true,
      }).addTo(state.markerLayer);
      marker.bindTooltip(element("span", null, displayTitle(result.site)), { direction: "top", offset: [0, -13] });
      marker.on("click", () => selectSite(String(result.site.id), { fromMap: true }));
      const icon = marker.getElement();
      if (icon) {
        icon.setAttribute("aria-label", `候选 ${index + 1}：${displayTitle(result.site)}，打开资料详情`);
        icon.setAttribute("aria-pressed", "false");
        icon.addEventListener("keydown", (event) => {
          if (event.key === " ") { event.preventDefault(); marker.fire("click"); }
        });
      }
      state.markers.set(String(result.site.id), marker);
    }
    ui.mapEmptyLabel.hidden = state.results.length > 0;
    fitMap();
  }

  function scoreLabel(score: number, mode: SearchMode): string {
    if (!Number.isFinite(score)) return "未提供分数";
    return mode === "semantic" ? `语义分数 ${score.toFixed(3)}` : `BM25 ${score.toFixed(2)}`;
  }

  function renderResults(data: SearchResponse, context: SearchContext): void {
    closeDetail(false);
    state.results = Array.isArray(data.results) ? data.results : [];
    state.selectedId = null;
    state.hasSearched = true;
    state.displayedMode = data.mode;
    ui.list.replaceChildren();
    ui.resultCount.textContent = String(state.results.length).padStart(2, "0");
    ui.activeMode.textContent = data.mode === "bm25" ? "BM25" : "SEMANTIC";
    const elapsed = Number.isFinite(data.elapsed_ms) ? `${Math.round(data.elapsed_ms)} ms` : "耗时未提供";
    const candidates = Number.isFinite(data.total_candidates)
      ? data.mode === "semantic" ? `在当前范围的 ${data.total_candidates} 条资料中，` : `${data.total_candidates} 条资料有字词匹配，`
      : "";
    ui.resultSummary.textContent = `${candidates}展示 ${state.results.length} 条 · ${elapsed}`;
    ui.resultContext.textContent = `本次查询：“${data.query}” · ${data.mode === "semantic" ? "语义检索" : "关键词基线"} · ${context.type ? typeLabel(context.type) : "全部类型"} · 最多 ${context.limit} 条 · Pleiades ${data.corpus_version}`;
    ui.resultContext.hidden = false;
    ui.empty.hidden = state.results.length > 0;
    if (state.results.length === 0) {
      ui.emptyTitle.textContent = "没有找到候选资料";
      ui.emptyDescription.textContent = data.mode === "bm25"
        ? "尝试英文关键词或古地名，放宽类型筛选；也可切换语义检索使用中文研究问题。"
        : "尝试调整问题或放宽类型筛选。当前资料只覆盖地中海周边的演示子集。";
    }
    for (const [index, result] of state.results.entries()) {
      const site = result.site;
      const item = element("li", "result-item");
      const card = element("button", "result-card");
      card.type = "button";
      card.dataset.siteId = String(site.id);
      card.setAttribute("aria-pressed", "false");
      card.setAttribute("aria-label", `候选 ${index + 1}：${displayTitle(site)}，查看地图与原始证据`);
      const top = element("div", "result-topline");
      top.append(element("span", "result-rank", String(index + 1).padStart(2, "0")));
      const titleArea = element("div");
      titleArea.append(element("h3", "result-title", displayTitle(site)));
      titleArea.append(element("p", "result-type", strings(site.types).map(typeLabel).join(" · ") || "地点类型未提供"));
      top.append(titleArea, element("span", "result-arrow", "↗"));
      const excerpt = sourceExcerpt(site);
      const description = element("p", "result-description", excerpt.text);
      description.lang = excerpt.label === "原文状态" ? "zh-CN" : "en";
      const metadata = element("div", "result-metadata");
      metadata.append(element("span", "result-coordinate", coordinateLabel(site)), element("span", "result-score", scoreLabel(result.score, data.mode)));
      card.append(top, element("p", "result-excerpt-label", excerpt.label), description, metadata);
      card.addEventListener("click", () => selectSite(String(site.id)));
      item.append(card);
      ui.list.append(item);
    }
    renderMarkers();
    announce(`检索完成，返回 ${state.results.length} 条候选资料。${data.mode === "semantic" ? "相似度分数并非相关概率，请核验来源。" : ""}`);
  }

  function setLoading(value: boolean): void {
    state.searching = value;
    ui.resultsPanel.setAttribute("aria-busy", String(value));
    ui.form.classList.toggle("is-searching", value);
    ui.loading.hidden = !value || state.results.length > 0;
    if (value && state.results.length === 0) ui.empty.hidden = true;
    if (!value) ui.empty.hidden = state.results.length > 0;
    updateSearchAvailability();
  }

  async function search(event?: Event): Promise<void> {
    if (event) event.preventDefault();
    const query = ui.query.value.trim();
    if (!query) { ui.query.focus(); return; }
    const mode = currentMode();
    const context: SearchContext = { type: ui.typeFilter.value || null, limit: Number(ui.limitFilter.value) };
    state.searchController?.abort();
    const sequence = ++state.searchSequence;
    if (!state.corpusReady || (mode === "semantic" && !state.semanticReady)) {
      setLoading(false);
      announce("当前检索方式尚未就绪，请查看准备指引，或选择关键词基线。");
      return;
    }
    const controller = new AbortController();
    state.searchController = controller;
    showError("");
    setLoading(true);
    announce("正在检索本地资料。");
    try {
      const data = await api<SearchResponse>("/api/search", {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, mode, ...context } satisfies SearchRequest),
      });
      if (sequence !== state.searchSequence) return;
      renderResults(data, context);
    } catch (error) {
      if (isAbortError(error) || sequence !== state.searchSequence) return;
      const retained = state.results.length ? "已保留上次结果。" : "请检查本地服务后重试。";
      showError(`本次检索未完成：${errorMessage(error)} ${retained}`);
      announce("本次检索失败，请查看错误说明。");
      if (!state.results.length) {
        ui.emptyTitle.textContent = "本次检索未完成";
        ui.emptyDescription.textContent = "上方保留了错误说明。检查本地模型与服务后，可以重试或选择关键词基线。";
      }
    } finally {
      if (sequence === state.searchSequence) setLoading(false);
    }
  }

  function detailSection(title: string, content: string | Node): HTMLElement {
    const section = element("section", "detail-section");
    section.append(element("h4", null, title));
    if (typeof content === "string") section.append(element("p", null, content));
    else section.append(content);
    return section;
  }

  function fact(label: string, value: string): HTMLDivElement {
    const row = element("div", "detail-fact");
    row.append(element("dt", null, label), element("dd", null, value));
    return row;
  }

  function evidenceList(evidence: PeriodEvidence[]): HTMLDivElement {
    const list = element("div");
    for (const item of evidence) {
      const row = element("div", "evidence-item");
      const resource = item.resource_type === "Name" ? "名称记录" : "位置记录";
      row.append(element("p", null, `${resource} · ${periodLabel(item.period_id)}`));
      row.append(element("p", "evidence-meta", `分期标注把握：${sourceLabel(item.confidence, confidenceLabels)}`));
      row.append(element("p", "evidence-meta", `记录与地点的关联：${sourceLabel(item.association_certainty, certaintyLabels)}`));
      row.append(element("p", "evidence-meta", `原始记录时间范围：${sourceYear(item.start)} — ${sourceYear(item.end)}`));
      const links = element("div", "evidence-links");
      links.append(safeLink(item.resource_uri, "原始记录 ↗"), safeLink(item.period_uri, "时期定义 ↗"));
      row.append(links);
      list.append(row);
    }
    return list;
  }

  function renderDetail(site: Site, matchedFields: string[] = []): void {
    const title = element("h3", null, displayTitle(site));
    title.id = "detail-title";
    const sourceId = element("p", "detail-id", `PLEIADES / ${site.id}`);
    const description = element("p", "detail-description", hasSourceText(site.description) ? site.description : "当前导出未提供描述。");
    description.lang = hasSourceText(site.description) ? "en" : "zh-CN";
    const nodes: Node[] = [title, sourceId];
    if (displayTitle(site) !== site.title) {
      nodes.push(element("p", "detail-source-title", `来源标题原文：${site.title || "未提供"}`));
    }
    nodes.push(element("p", "detail-note", "来源原文保留原语言；以下内容未经自动翻译或历史补写。"), description);
    const details = element("p", null, hasSourceText(site.details)
      ? site.details : `当前导出未提供补充内容${site.details.trim() ? `（原始值：${site.details}）` : ""}。`);
    if (hasSourceText(site.details)) details.lang = "en";
    nodes.push(detailSection("原始补充记录", details));
    nodes.push(detailSection("名称与别名", strings(site.names).join(" · ") || "原始资料未提供其他名称。"));
    nodes.push(detailSection("来源类型标签", strings(site.types).map((value) => primaryTypeLabels[value]
      ? `${typeLabel(value)}（${value}）` : value).join(" · ") || "原始资料未提供类型。"));
    const periods = detailSection("原始时期标签", strings(site.periods).map(periodLabel).join(" · ") || "原始资料未提供时期标签。");
    periods.append(element("p", "detail-note", "标签来自名称或位置记录；多个时期标签不能证明地点持续使用，也不能直接视为建造年代。"));
    nodes.push(periods);
    const facts = element("dl");
    facts.append(fact("代表点", coordinateLabel(site)), fact("原始精度", sourceLabel(site.location_precision, { precise: "精确", rough: "概略" })));
    const space = detailSection("空间信息 · WGS84", facts);
    space.append(element("p", "detail-note", "精度按来源标签展示，不承诺米级误差；代表点不等同于实测发掘坐标。"));
    if (site.location_precision === "rough") {
      space.append(element("p", "detail-note", "rough 表示应在某个范围内寻找地点；代表点可能只是该范围的中心。"));
    }
    nodes.push(space);
    const fields = strings(matchedFields).map((field) => fieldLabels[field] || field);
    const matches = detailSection("原文字词匹配字段", fields.join(" · ") || "未发现查询与原文字段的字词重叠。");
    matches.append(element("p", "detail-note", "仅展示字词重叠，不解释语义模型的排序依据；中文问题仍可能检索到英文候选。"));
    nodes.push(matches);
    const evidence = Array.isArray(site.period_evidence) ? site.period_evidence : [];
    if (evidence.length) {
      const roman = evidence.filter((item) => item.period_id === "roman");
      const other = evidence.filter((item) => item.period_id !== "roman");
      const section = detailSection("入选分期依据", element("p", "evidence-summary", `名称或位置记录中有 ${roman.length} 条 roman 分期关联。`));
      section.append(element("p", "detail-note", "本语料以 roman（前30—公元300年）筛选。下方起止年份属于整条原始记录，可能跨越多个分期，不是该分期的起止或遗址的确切断代。"));
      section.append(evidenceList(roman));
      if (other.length) {
        const more = element("details", "evidence-more");
        more.append(element("summary", null, `查看其他时期关联（${other.length} 条）`), evidenceList(other));
        section.append(more);
      }
      nodes.push(section);
    } else {
      nodes.push(detailSection("时期证据与来源", "原始资料未提供可展示的时期证据。"));
    }
    nodes.push(detailSection("资料贡献者", strings(site.contributors).join(" · ") || "当前导出未提供贡献者信息，请在原始来源中核验。"));
    nodes.push(detailSection("来源与许可", "Pleiades v4.1 · CC BY 3.0。引用时请保留地点编号、原始链接与贡献者信息。"));
    nodes.push(safeLink(site.source_uri, "在 Pleiades 查看原始资料 ↗", "detail-source-link"));
    ui.detailContent.replaceChildren(...nodes);
  }

  async function selectSite(id: string, { fromMap = false }: { fromMap?: boolean } = {}): Promise<void> {
    const result = state.results.find((item) => String(item.site.id) === id);
    if (!result) return;
    state.selectedId = id;
    for (const card of Array.from(ui.list.querySelectorAll<HTMLButtonElement>(".result-card"))) {
      const selected = card.dataset.siteId === id;
      card.classList.toggle("is-selected", selected);
      card.setAttribute("aria-pressed", String(selected));
      if (selected && fromMap) {
        card.focus({ preventScroll: true });
        const listBounds = ui.list.getBoundingClientRect();
        const cardBounds = card.getBoundingClientRect();
        if (cardBounds.top < listBounds.top) ui.list.scrollTop -= listBounds.top - cardBounds.top;
        else if (cardBounds.bottom > listBounds.bottom) ui.list.scrollTop += cardBounds.bottom - listBounds.bottom;
      }
    }
    for (const [markerId, marker] of state.markers) {
      const selected = markerId === id;
      marker.getElement()?.classList.toggle("is-selected", selected);
      marker.getElement()?.setAttribute("aria-pressed", String(selected));
      marker.setZIndexOffset(selected ? 1000 : 0);
    }
    const coordinate = point(result.site);
    if (state.map && coordinate) {
      state.map.panTo(coordinate, { animate: false });
      // Keep the selected point visible to the left of the source drawer.
      if (byId("map", HTMLDivElement).clientWidth > 500) state.map.panBy([150, 0], { animate: false });
    }
    ui.detailPanel.hidden = false;
    renderDetail(result.site, result.matched_fields);
    announce(`已选择 ${displayTitle(result.site)}，原始资料详情已展开。`);
    state.detailController?.abort();
    const controller = new AbortController();
    state.detailController = controller;
    try {
      const site = await api<Site>(`/api/sites/${encodeURIComponent(id)}`, { signal: controller.signal });
      if (state.selectedId === id && !controller.signal.aborted) renderDetail(site, result.matched_fields);
    } catch (error) {
      if (isAbortError(error) || state.selectedId !== id) return;
      ui.detailContent.append(element("p", "detail-loading", "详情刷新失败，当前显示检索时返回的原始资料。"));
    }
  }

  function closeDetail(returnFocus = true): void {
    state.detailController?.abort();
    ui.detailPanel.hidden = true;
    if (returnFocus && state.selectedId !== null) {
      const card = Array.from(ui.list.querySelectorAll<HTMLButtonElement>(".result-card")).find((item) => item.dataset.siteId === state.selectedId);
      card?.focus({ preventScroll: true });
    }
  }

  function applyChangedFilter(): void {
    updateSearchAvailability();
    if ((state.hasSearched || state.searching) && ui.query.value.trim()) search();
  }

  ui.form.addEventListener("submit", search);
  ui.form.querySelectorAll<HTMLInputElement>('input[name="mode"]').forEach((radio) => radio.addEventListener("change", applyChangedFilter));
  ui.typeFilter.addEventListener("change", applyChangedFilter);
  ui.limitFilter.addEventListener("change", applyChangedFilter);
  document.querySelectorAll<HTMLButtonElement>("[data-query-zh]").forEach((button) => {
    button.addEventListener("click", () => {
      ui.query.value = (currentMode() === "semantic" ? button.dataset.queryZh : button.dataset.queryEn) || "";
      const type = button.dataset.type || "";
      ui.typeFilter.value = Array.from(ui.typeFilter.options).some((option) => option.value === type) ? type : "";
      ui.query.focus();
      search();
    });
  });
  byId("refresh-status", HTMLButtonElement).addEventListener("click", loadStatus);
  byId("fit-map", HTMLButtonElement).addEventListener("click", () => { closeDetail(false); fitMap(); });
  byId("retry-tiles", HTMLButtonElement).addEventListener("click", () => {
    ui.tileWarning.hidden = true;
    state.tiles?.redraw();
  });
  byId("close-detail", HTMLButtonElement).addEventListener("click", () => closeDetail());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !ui.detailPanel.hidden) closeDetail();
  });

  initializeMap();
  updateSearchAvailability();
  Promise.allSettled([loadStatus(), loadFacets()]);
})();

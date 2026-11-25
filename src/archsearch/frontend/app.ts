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
    description_zh?: string;
    details: string;
    names: string[];
    types: string[];
    periods: string[];
    repr_point: [number, number] | null;
    location_precision: "precise" | "rough" | null;
    source_uri: string;
    contributors: string[];
    period_evidence: PeriodEvidence[];
    source_kind: "pleiades" | "global" | "unesco" | "ats" | "supplement";
    geography?: { authority_id: string | null; countries: string[]; regions: string[]; point_count: number; note: string; source: SourceReference } | null;
    source_refs: SourceReference[];
    chronology: {
      status: "not_reviewed" | "reviewed" | "insufficient";
      method: string;
      reviewed_at: string | null;
      note: string;
      default_phase_id: string | null;
      phases: HistoricalPhase[];
    };
  }

  interface SourceReference {
    id: string; title: string; uri: string; publisher: string;
    license: string | null; revision: string | null; excerpt: string;
  }

  interface HistoricalPhase {
    id: string; kind: "construction" | "use" | "rebuild" | "destruction" | "other";
    label: string; precision: "exact_year" | "approximate_year" | "range" | "period";
    start_year: number | null; end_year: number | null; note: string; sources: SourceReference[];
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
    country?: string | null;
    region?: string | null;
    subdivision?: string | null;
    enhance?: boolean;
    llm_revision?: number;
  }

  interface SearchResponse {
    results: SearchResult[];
    mode: SearchMode;
    query: string;
    elapsed_ms: number;
    corpus_version: string;
    total_candidates: number;
    subdivision?: string | null;
    subdivision_version?: string | null;
    enhancement?: ReturnType<typeof ArchSearchResearch.validateEnhancement>;
  }

  interface SearchContext {
    type: string | null;
    limit: number;
    country?: string | null;
    region?: string | null;
    subdivision?: string | null;
    enhance?: boolean;
    llm_revision?: number;
  }

  interface CompletedSearch {
    request: SearchRequest;
    response: SearchResponse;
    link: string;
  }

  interface StatusResponse {
    status: string;
    corpus: { count: number; version: string; period: string };
    semantic: { ready: boolean; reason: string | null; model: string; revision: string };
    history?: Parameters<ReturnType<typeof ArchSearchHistory.create>["configure"]>[0];
    registered_areas?: { ready: boolean; reason: string | null; version: string | null } | null;
    subdivisions?: { ready: boolean; reason: string | null; version: string | null } | null;
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
    selectedSite: Site | null;
    selectionMarker: L.Marker | null;
    completedSearch: CompletedSearch | null;
    restoringLink: boolean;
    detailOpener: HTMLElement | null;
    typeLabels: Map<string, string>;
    searchController: AbortController | null;
    detailController: AbortController | null;
    searchSequence: number;
    activeSearch: SearchRequest | null;
    failedSearch: SearchRequest | null;
    searchFeedback: string | null;
    statusError: string | null;
    facetError: string | null;
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
    corpusCount: byId("corpus-count", HTMLElement), corpusPeriod: byId("corpus-period", HTMLElement),
    coverage: byId("workspace-coverage", HTMLElement),
    resultsPanel: byId("results-panel", HTMLDivElement), resultCount: byId("result-count", HTMLSpanElement),
    resultSummary: byId("result-summary", HTMLParagraphElement), activeMode: byId("active-mode", HTMLSpanElement),
    resultContext: byId("result-context", HTMLParagraphElement), exampleHint: byId("example-hint", HTMLParagraphElement),
    enhancementNote: byId("llm-result-note", HTMLElement), enhancementSummary: byId("llm-result-summary", HTMLParagraphElement),
    enhancementQueries: byId("llm-result-query-list", HTMLOListElement),
    resultTools: byId("result-tools", HTMLDivElement), copyLink: byId("copy-search-link", HTMLButtonElement),
    exportResults: byId("export-results", HTMLButtonElement), toolsFeedback: byId("result-tools-feedback", HTMLParagraphElement),
    shareLinkPanel: byId("share-link-panel", HTMLDivElement), shareLink: byId("share-link", HTMLInputElement),
    list: byId("results-list", HTMLOListElement), empty: byId("results-empty", HTMLDivElement), emptyTitle: byId("empty-title", HTMLHeadingElement),
    emptyDescription: byId("empty-description", HTMLParagraphElement), loading: byId("loading-state", HTMLDivElement),
    detailPanel: byId("detail-panel", HTMLElement), detailContent: byId("detail-content", HTMLDivElement),
    detailDialog: byId("detail-dialog", HTMLDialogElement),
    exportSiteEvidence: byId("export-site-evidence", HTMLButtonElement),
    siteExportFeedback: byId("site-export-feedback", HTMLParagraphElement),
    openSelectedDetail: byId("open-selected-detail", HTMLButtonElement),
    tileWarning: byId("tile-warning", HTMLDivElement), tileWarningText: byId("tile-warning-text", HTMLSpanElement),
    mapEmptyLabel: byId("map-empty-label", HTMLDivElement), viewportCount: byId("viewport-count", HTMLElement),
    clearType: byId("clear-type", HTMLButtonElement), emptyClearType: byId("empty-clear-type", HTMLButtonElement),
    searchProgress: byId("search-progress", HTMLDivElement), progressLabel: byId("search-progress-label", HTMLParagraphElement),
    cancelSearch: byId("cancel-search", HTMLButtonElement), retryPanel: byId("retry-panel", HTMLDivElement),
    retrySearch: byId("retry-search", HTMLButtonElement), serviceError: byId("service-error", HTMLDivElement),
    selectionSummary: byId("selection-summary", HTMLParagraphElement), selectionActions: byId("selection-actions", HTMLDivElement),
    previousResult: byId("previous-result", HTMLButtonElement),
    nextResult: byId("next-result", HTMLButtonElement), locateSelected: byId("locate-selected", HTMLButtonElement),
  };

  const state: ApplicationState = {
    corpusReady: false, semanticReady: false, statusLoaded: false, searching: false,
    hasSearched: false, displayedMode: null, results: [], selectedId: null, selectedSite: null, selectionMarker: null, typeLabels: new Map(),
    completedSearch: null, restoringLink: false, detailOpener: null,
    searchController: null, detailController: null, searchSequence: 0,
    activeSearch: null, failedSearch: null, searchFeedback: null, statusError: null, facetError: null,
    map: null, tiles: null, markerLayer: null, markers: new Map(),
  };

  const initialUrl = new URL(window.location.href);
  const initialLink = ArchSearchResearch.parseLink(initialUrl);
  const initialView = ArchSearchResearch.parseView(initialUrl);
  const initialComparison = ArchSearchResearch.parseComparison(initialUrl);
  let pendingLink: SearchRequest | null = initialView.error || initialComparison.error ? null : initialLink.request;
  let unresolvedSearchLink: SearchRequest | null = pendingLink;
  let restoringSearchController: AbortController | null = null;
  let linkError: string | null = initialLink.error ?? initialView.error ?? initialComparison.error;
  let invalidLink = linkError !== null;
  let pendingSelectionRestore = !invalidLink && initialView.selection.site !== null;
  let currentLink = window.location.href;
  let runtimeRefresh: Promise<void> | null = null;
  let mapView: ReturnType<typeof ArchSearchMapView.create> | null = null;
  let registeredAreas: ReturnType<typeof ArchSearchRegisteredAreas.create> | null = null;
  let currentCorpusVersion: string | null = null;
  let coverageSummary: { version: string; countries: number; regions: number } | null = null;
  let verifiedDetail: { site: Site; corpusVersion: string } | null = null;
  let currentRegisteredAreasVersion: string | null = null;
  let historyView: ReturnType<typeof ArchSearchHistory.create> | null = null;
  let selectedPhaseId: string | null = null;
  let restoringView = true;
  let initialStatePending = true;
  let llmView: ReturnType<typeof ArchSearchLlm.create> | null = null;
  let historicalMap: L.Map | null = null;
  let mapComparison: ReturnType<typeof ArchSearchComparison.create> | null = null;
  let modernBoundaries: ReturnType<typeof ArchSearchModernBoundaries.create> | null = null;

  const fieldLabels: Readonly<Record<string, string>> = {
    title: "地点名称", names: "别名", description: "原始描述", description_zh: "中文描述／译文", source_refs: "来源资格片段", types: "地点类型",
    periods: "原始时期", details: "原始补充记录", search_text: "检索文本",
  };

  const primaryTypeLabels: Readonly<Record<string, string>> = {
    settlement: "聚落", villa: "别墅庄园", port: "港口", bath: "浴场", theatre: "剧场", "archaeological-site": "考古遗址", "historic-site": "历史遗址",
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

  function chineseDescriptionLabel(site: Site): string {
    return ArchSearchResearch.descriptionLabel(site, "zh");
  }

  function sourceExcerpt(site: Site): { label: string; text: string; lang?: string; structured?: boolean } {
    const merimee = ArchSearchResearch.parseMerimeeSource(site);
    if (merimee) {
      const source = merimee.source_record;
      return { label: "来源 Commune · 原记录范围（完整原文见详情）", text: `${source.Commune_forme_editoriale}\n${merimee.scope.literal}`, lang: "fr" };
    }
    const minas = ArchSearchResearch.parseMinasSource(site);
    if (minas) {
      const classes = [...new Set(minas.map((row) => row.classe_subclasse))];
      const municipalities = [...new Set(minas.map((row) => row.municipio))];
      return { label: "原登记分类 · 来源行市镇", text: `${classes.join(" / ")}\n${municipalities.join(" / ")}`, lang: "pt-BR", structured: true };
    }
    if (site.description_zh && hasSourceText(site.description_zh)) return { label: chineseDescriptionLabel(site), text: site.description_zh };
    if (site.description.startsWith("An ancient place, cited:") && hasSourceText(site.details)) {
      return { label: "目录补充原文", text: site.details };
    }
    if (hasSourceText(site.description)) return { label: ArchSearchResearch.descriptionLabel(site, "en"), text: site.description };
    if (site.source_kind === "supplement" && hasSourceText(site.details)) return { label: "来源结构化信息", text: site.details };
    if (hasSourceText(site.details)) return { label: "补充记录原文", text: site.details };
    return { label: "原文状态", text: "当前导出未提供描述，请打开详情核验来源记录。" };
  }

  function sourceYear(value: number | null): string {
    if (value === null || !Number.isFinite(value)) return "未提供";
    if (value === 0) return "原始值 0（未转换纪年）";
    return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
  }

  function currentMode(): SearchMode {
    return "semantic";
  }

  function announce(message: string): void {
    ui.announcement.textContent = message;
  }

  function focusWithinView(target: HTMLElement): void {
    const destination = target.closest("[hidden]") ? byId("workspace-toggle-sidebar", HTMLButtonElement) : target;
    if (destination.tabIndex < 0) destination.tabIndex = -1;
    destination.focus({ preventScroll: true });
    const bounds = destination.getBoundingClientRect();
    if (bounds.top < 0 || bounds.bottom > window.innerHeight) {
      destination.scrollIntoView({ block: "nearest", behavior: "instant" });
    }
  }

  function showError(message: string): void {
    ui.requestError.textContent = message;
    ui.requestError.hidden = !message;
  }

  function renderServiceError(): void {
    const message = [state.statusError, state.facetError].filter(Boolean).join(" ");
    ui.serviceError.textContent = message;
    ui.serviceError.hidden = !message;
  }

  function formRequest(): SearchRequest {
    return {
      query: ui.query.value.trim(), mode: currentMode(), type: ui.typeFilter.value || null,
      limit: Number(ui.limitFilter.value), ...llmView?.requestOptions(),
    };
  }

  function sameRequest(left: SearchRequest, right: SearchRequest): boolean {
    return left.query === right.query && left.mode === right.mode && left.type === right.type && left.limit === right.limit
      && (left.country ?? null) === (right.country ?? null) && (left.region ?? null) === (right.region ?? null)
      && (left.subdivision ?? null) === (right.subdivision ?? null)
      && (left.enhance === true) === (right.enhance === true)
      && (!left.enhance || left.llm_revision === right.llm_revision);
  }

  function modeAvailable(mode: SearchMode): boolean {
    return !state.restoringLink && state.corpusReady && mode === "semantic" && state.semanticReady;
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

  async function readApi<T>(path: string, options: RequestInit = {}): Promise<{ data: T; headers: Headers }> {
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    const response = await fetch(path, { ...options, headers });
    let data: unknown;
    try {
      data = await response.json();
    } catch (error) {
      if (isAbortError(error)) throw error;
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
    return { data: data as T, headers: response.headers };
  }

  async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
    return (await readApi<T>(path, options)).data;
  }

  function updateSearchAvailability(): void {
    const available = modeAvailable("semantic");
    const enhancementReady = !llmView?.enabled() || llmView.ready();
    const samePending = state.searching && state.activeSearch !== null && sameRequest(state.activeSearch, formRequest());
    ui.searchButton.disabled = !available || !enhancementReady || samePending;
    ui.buttonLabel.textContent = state.searching ? samePending ? "检索中" : "更新检索" : "开始检索";
    ui.cancelSearch.disabled = !state.searching;
    ui.cancelSearch.hidden = !state.searching;
    ui.searchProgress.hidden = !state.searching && !state.searchFeedback;
    if (state.searching) {
      const status = state.activeSearch?.enhance ? "正在扩展查询并检索本地资料。" : "正在检索本地资料。";
      const model = "首次语义检索可能需要加载本地模型。";
      const retained = state.completedSearch ? "上次结果仍可查看。" : "";
      ui.progressLabel.textContent = status + model + retained;
    } else ui.progressLabel.textContent = state.searchFeedback ?? "";
    ui.retryPanel.hidden = state.failedSearch === null;
    ui.retrySearch.disabled = state.failedSearch === null || state.searching || !modeAvailable(state.failedSearch.mode)
      || (state.failedSearch.enhance === true && !llmView?.ready());
    ui.retrySearch.title = state.failedSearch ? `恢复并重试：${state.failedSearch.query}` : "";
    ui.clearType.disabled = !ui.typeFilter.value || ui.typeFilter.disabled;
    ui.emptyClearType.hidden = !state.hasSearched || state.results.length > 0 || !ui.typeFilter.value || state.searching || ui.typeFilter.disabled;
    ui.activeMode.textContent = state.completedSearch?.response.enhancement?.applied ? "LLM · RRF" : "SEMANTIC";
    ui.preparationNote.hidden = !state.statusLoaded || state.semanticReady;
    ui.modeExplanation.textContent = "用中文描述问题，专名可保留原文，在多语种源资料中寻找相近候选；排序分数不是相关概率，仍需核验来源。";
    ui.exampleHint.textContent = "中文问题示例，专名可保留原文；示例同步地点类型并开始检索。";
    document.querySelectorAll<HTMLButtonElement>("[data-query-zh]").forEach((button) => {
      const query = button.dataset.queryZh;
      const label = button.querySelector<HTMLSpanElement>(".example-label");
      if (label) label.textContent = button.dataset.label || query || "示例";
      button.disabled = !available || !enhancementReady || ui.typeFilter.disabled || !Array.from(ui.typeFilter.options).some((option) => option.value === button.dataset.type);
      button.setAttribute("aria-label", `检索示例：${query || ""}；类型：${typeLabel(button.dataset.type || "")}`);
      button.lang = "zh-CN";
    });
    ArchSearchWorkspace.refreshSearchSummary();
  }

  function updateScopeHeader(): void {
    ui.coverage.textContent = coverageSummary && coverageSummary.version === currentCorpusVersion
      ? `${coverageSummary.countries} 个国家／地区 · ${coverageSummary.regions} 个资料分组`
      : "全球文化遗址 · 覆盖统计加载中";
    ui.coverage.title = currentCorpusVersion ? `当前语料 ${currentCorpusVersion}；来源覆盖不代表全球完整清单。` : "正在核对本地语料版本。";
  }

  async function loadCoverageSummary(): Promise<void> {
    try {
      const data = await api<{ corpus_version?: unknown; countries?: unknown[]; regions?: unknown[] }>("/api/coverage");
      if (typeof data.corpus_version === "string" && Array.isArray(data.countries) && Array.isArray(data.regions)) {
        coverageSummary = { version: data.corpus_version, countries: data.countries.length, regions: data.regions.length };
        updateScopeHeader();
      }
    } catch { /* Coverage metadata is optional in the header summary. */ }
  }

  async function loadStatus(): Promise<void> {
    ui.runtimeLabel.textContent = "检查本地服务";
    try {
      const status = await api<StatusResponse>("/api/status");
      historyView?.configure(status.history);
      if (restoringView) {
        restoringView = false;
        if (initialView.view) {
          historyView?.setBasemap(initialView.view.basemap, "site");
          historyView?.setBoundaries(initialView.view.boundaries, "site");
          historyView?.setYear(initialView.view.year, "site");
        }
      }
      state.statusLoaded = true;
      state.corpusReady = Number(status.corpus?.count) > 0;
      currentCorpusVersion = typeof status.corpus?.version === "string" ? status.corpus.version : null;
      currentRegisteredAreasVersion = status.registered_areas?.version ?? null;
      registeredAreas?.setCorpusVersion(currentCorpusVersion, currentRegisteredAreasVersion);
      state.semanticReady = status.semantic?.ready === true;
      ui.corpusCount.textContent = Number(status.corpus?.count || 0).toLocaleString("zh-CN");
      if (status.corpus?.period) ui.corpusPeriod.textContent = status.corpus.period;
      updateScopeHeader();
      ui.statusDot.className = `status-dot ${state.semanticReady ? "is-ready" : "is-warning"}`;
      ui.runtimeLabel.textContent = state.semanticReady ? "本地语义检索就绪" : state.corpusReady ? "语义模型待准备" : "等待资料准备";
      const reason = typeof status.semantic?.reason === "string" ? status.semantic.reason : "";
      ui.preparationReason.textContent = `${reason ? `${reason}。` : ""}请按 README 完成本地模型与索引准备，然后点击右上角刷新运行状态。`;
      state.statusError = state.corpusReady ? null : "本地资料集尚未准备。请先按 README 导入资料，再刷新运行状态。";
      announce(state.semanticReady ? "本地语义检索已就绪。" : "本地语义模型尚未就绪，请按 README 准备。");
    } catch (error) {
      state.statusLoaded = true;
      state.semanticReady = false;
      ui.statusDot.className = "status-dot is-warning";
      ui.runtimeLabel.textContent = "服务连接失败";
      ui.preparationReason.textContent = "无法确认本地模型状态。请检查服务是否启动，再点击右上角刷新运行状态。";
      state.statusError = `运行状态检查失败：${errorMessage(error)}`;
    } finally {
      renderServiceError();
      updateSearchAvailability();
      updateSiteExportControl();
    }
  }

  async function loadFacets(): Promise<void> {
    try {
      const facets = await api<FacetResponse>("/api/facets");
      if (!Array.isArray(facets.types) || !facets.types.length) throw new Error("服务未返回可用的类型列表。");
      const selected = ui.typeFilter.value;
      const previousLabel = selected ? typeLabel(selected) : "";
      const labels = new Map<string, string>();
      const options = [element("option", null, "全部类型")];
      options[0].value = "";
      for (const item of facets.types || []) {
        if (typeof item.id !== "string") continue;
        const label = typeof item.label === "string" ? item.label : labelFromId(item.id);
        if (labels.has(item.id)) continue;
        labels.set(item.id, label);
        const option = element("option", null, `${label} (${Number(item.count) || 0})`);
        option.value = item.id;
        options.push(option);
      }
      if (!labels.size) throw new Error("类型列表无效。");
      state.typeLabels = labels;
      state.facetError = null;
      if (selected && !labels.has(selected)) {
        const missing = element("option", null, `${previousLabel}（当前不可用）`);
        missing.value = selected;
        missing.disabled = true;
        options.push(missing);
        state.facetError = "当前选择的类型已不可用。请改选类型或明确清除筛选后检索。";
      }
      ui.typeFilter.replaceChildren(...options);
      ui.typeFilter.value = selected;
      ui.typeFilter.disabled = false;
    } catch (error) {
      const retained = state.typeLabels.size > 0;
      ui.typeFilter.disabled = !retained;
      if (!retained) ui.typeFilter.options[0].textContent = "类型暂不可用";
      state.facetError = `类型列表加载失败：${errorMessage(error)} ${retained ? "保留已加载的类型；可再次刷新。" : "可手动检索全部类型，或点击右上角刷新重试。"}`;
    } finally {
      renderServiceError();
      updateSearchAvailability();
    }
  }

  function refreshRuntime(): Promise<void> {
    if (runtimeRefresh) return runtimeRefresh;
    const refreshButton = byId("refresh-status", HTMLButtonElement);
    refreshButton.disabled = true;
    const job = Promise.allSettled([loadStatus(), loadFacets(), loadCoverageSummary(), llmView?.load()]).then(() => undefined).finally(() => {
      runtimeRefresh = null;
      refreshButton.disabled = false;
    });
    runtimeRefresh = job;
    return job;
  }

  function sourcePoint(site: Site): L.LatLngTuple | null {
    const coordinate = site.repr_point;
    if (!Array.isArray(coordinate) || coordinate.length !== 2) return null;
    const [lon, lat] = coordinate;
    return Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90
      ? [lat, lon] : null;
  }

  function point(site: Site): L.LatLngTuple | null {
    return ArchSearchMapView.locationStatus(site.repr_point) === "mapped" ? sourcePoint(site) : null;
  }

  function coordinateLabel(site: Site): string {
    const coordinate = sourcePoint(site);
    if (!coordinate) return site.source_kind === "ats" ? "来源真实位置未知" : "当前资料无可核代表点";
    const [lat, lon] = coordinate;
    return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? "N" : "S"} / ${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? "E" : "W"}`;
  }

  function initializeMap(): void {
    if (typeof L === "undefined") {
      byId("map", HTMLDivElement).append(element("div", "map-unavailable", "地图组件未能加载。你仍可检索并阅读候选资料的原文与坐标。"));
      byId("history-map", HTMLDivElement).append(element("div", "map-unavailable", "历史地图组件未能加载；年代证据与原文仍可查阅。"));
      byId("fit-map", HTMLButtonElement).disabled = true;
      return;
    }
    state.map = L.map("map", { zoomControl: false, zoomAnimation: false, inertia: false, minZoom: 1, maxZoom: 9, worldCopyJump: true }).setView([20, 0], 1);
    historicalMap = L.map("history-map", { zoomControl: false, zoomAnimation: false, inertia: false, minZoom: 1, maxZoom: 9, worldCopyJump: true }).setView([20, 0], 1);
    L.control.zoom({ position: "bottomleft" }).addTo(historicalMap);
    historicalMap.attributionControl?.setPrefix(false);
    L.control.zoom({ position: "bottomleft" }).addTo(state.map);
    state.map.attributionControl?.setPrefix(false);
    state.tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      keepBuffer: 4,
      updateInterval: 250,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
    }).addTo(state.map);
    state.markerLayer = L.layerGroup().addTo(state.map);
    state.map.on("moveend", () => {
      const marker = state.selectionMarker;
      const center = state.map?.getCenter().lng;
      if (marker && center !== undefined) {
        const location = marker.getLatLng();
        marker.setLatLng([location.lat, ArchSearchMapView.wrapLongitude(location.lng, center)]);
      }
    });
  }

  function fitMap(): void {
    if (!state.map) return;
    if (mapComparison) { mapComparison.fitCandidates(); return; }
    const coordinates = state.results.map((result) => point(result.site)).filter((coordinate): coordinate is L.LatLngTuple => coordinate !== null);
    if (coordinates.length === 0) {
      state.map.setView([20, 0], 1);
    } else {
      state.map.fitBounds(L.latLngBounds(ArchSearchMapView.wrapCoordinates(coordinates)), { padding: [35, 35], maxZoom: 4, animate: false });
    }
  }

  function selectedResult(): SearchResult | undefined {
    return state.results.find((result) => result.site.id === state.selectedId);
  }

  function currentSelectedSite(): Site | null {
    return state.selectedSite?.id === state.selectedId ? state.selectedSite : selectedResult()?.site ?? null;
  }

  function exportableDetail(): { site: Site; corpusVersion: string } | null {
    return verifiedDetail?.site.id === state.selectedId && verifiedDetail.corpusVersion === currentCorpusVersion ? verifiedDetail : null;
  }

  function setSiteExportFeedback(message: string): void {
    ui.siteExportFeedback.textContent = message;
    ui.siteExportFeedback.hidden = !message;
  }

  function updateSiteExportControl(): void {
    const wasDisabled = ui.exportSiteEvidence.disabled;
    ui.exportSiteEvidence.disabled = exportableDetail() === null;
    if (verifiedDetail && currentCorpusVersion === null) {
      setSiteExportFeedback("工作区语料版本尚未确认。请刷新运行状态后再试。");
    } else if (verifiedDetail && verifiedDetail.corpusVersion !== currentCorpusVersion) {
      setSiteExportFeedback("语料版本已变化。请刷新页面后重新核对资料。");
    } else if (wasDisabled && !ui.exportSiteEvidence.disabled) {
      setSiteExportFeedback("");
    }
  }

  function resetSiteExport(): void {
    verifiedDetail = null;
    setSiteExportFeedback("");
    updateSiteExportControl();
  }

  function updateSelectionControls(): void {
    const index = state.results.findIndex((result) => result.site.id === state.selectedId);
    const selected = currentSelectedSite();
    ui.selectionSummary.textContent = selected
      ? index >= 0 ? `第 ${index + 1} / ${state.results.length} 条 · ${displayTitle(selected)}` : `已选遗址 · ${displayTitle(selected)}`
      : state.results.length ? `${state.results.length} 条候选，可逐条浏览或选择地图标记。` : "选择候选，查看地图与原始资料。";
    ui.selectionSummary.title = ui.selectionSummary.textContent;
    const hideActions = state.results.length === 0 && selected === null;
    const actionsOwnedFocus = ui.selectionActions.contains(document.activeElement);
    ui.selectionActions.hidden = hideActions;
    if (hideActions && actionsOwnedFocus) {
      ui.selectionSummary.tabIndex = -1;
      ui.selectionSummary.focus({ preventScroll: true });
    }
    ui.previousResult.disabled = index <= 0;
    ui.nextResult.disabled = !state.results.length || index >= state.results.length - 1;
    ui.nextResult.textContent = index < 0 ? "查看首条" : "下一条";
    const polar = selected && ArchSearchMapView.locationStatus(selected.repr_point) === "polar";
    ui.locateSelected.textContent = polar ? "查看极区位置" : "定位选中";
    ui.locateSelected.disabled = !selected || sourcePoint(selected) === null || (!state.map && !polar);
    ui.openSelectedDetail.disabled = selected === null;
    ui.locateSelected.title = selected && sourcePoint(selected) === null ? "当前资料无可核代表点，不添加遗址地图标记。" : "";
  }

  function positionSelectedSite(site: Site): void {
    const coordinate = point(site);
    if (!state.map || !coordinate) return;
    coordinate[1] = ArchSearchMapView.wrapLongitude(coordinate[1], state.map.getCenter().lng);
    state.map.stop();
    state.map.invalidateSize({ pan: true, animate: false });
    state.map.setView(coordinate, 4, { animate: false });
  }

  function updateComparisonSelection(site: Site, focus: boolean): void {
    const review = site.chronology;
    const phase = review?.phases.find((item) => item.id === selectedPhaseId) ?? review?.phases.find((item) => item.id === review.default_phase_id) ?? null;
    historyView?.setSelectionContext({ title: displayTitle(site), precision: phase?.precision ?? null,
      start_year: phase?.start_year ?? null, end_year: phase?.end_year ?? null });
    mapComparison?.setSelection({ id: site.id, title: displayTitle(site), repr_point: site.repr_point,
      status: review?.status ?? "not_reviewed", phase }, focus);
  }

  function browseResult(direction: -1 | 1): void {
    const index = state.results.findIndex((result) => result.site.id === state.selectedId);
    const target = index < 0 ? direction === 1 ? 0 : -1 : index + direction;
    const result = state.results[target];
    if (result) selectSite(result.site.id);
  }

  function locateCurrentSite(): void {
    const site = currentSelectedSite();
    if (!site) return;
    if (ArchSearchMapView.locationStatus(site.repr_point) === "polar") {
      closeDetail(false);
      announce(`该遗址坐标超出主地图 Web Mercator 投影范围（${coordinateLabel(site)}），主地图不夹取纬度。`);
      return;
    }
    if (!state.map || !point(site)) return;
    closeDetail(false);
    ArchSearchWorkspace.revealMaps();
    positionSelectedSite(site);
    updateComparisonSelection(site, true);
    const marker = state.markers.get(site.id) ?? state.selectionMarker;
    marker?.openTooltip();
    byId("map-comparison", HTMLDivElement).scrollIntoView({ block: "start", behavior: "instant" });
    marker?.getElement()?.focus({ preventScroll: true });
    announce(`已在地图定位 ${displayTitle(site)}。可按 Enter 或空格重新打开详情。`);
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
        autoPanOnFocus: false,
      }).addTo(state.markerLayer);
      marker.bindTooltip(element("span", null, displayTitle(result.site)), { direction: "top", offset: [0, -13] });
      marker.on("click", () => selectSite(String(result.site.id), { fromMap: true, showDetail: true }));
      const icon = marker.getElement();
      if (icon) {
        icon.setAttribute("aria-label", `候选 ${index + 1}：${displayTitle(result.site)}，打开资料详情`);
        icon.setAttribute("aria-pressed", "false");
        icon.addEventListener("keydown", (event) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            event.stopPropagation();
            marker.fire("click");
          }
        });
      }
      state.markers.set(String(result.site.id), marker);
    }
    mapComparison?.setCandidates(state.results.map((result, index) => ({ id: result.site.id, title: displayTitle(result.site), repr_point: result.site.repr_point, rank: index + 1 })), false);
    ui.mapEmptyLabel.hidden = true;
    fitMap();
  }

  function scoreLabel(score: number, _mode: SearchMode, fused = false): string {
    if (!Number.isFinite(score)) return "未提供分数";
    return fused ? `RRF 分数 ${score.toFixed(5)}` : `语义分数 ${score.toFixed(3)}`;
  }

  function renderResults(data: SearchResponse, context: SearchContext): void {
    const previousFocus = document.activeElement;
    const removedFocus = ui.list.contains(previousFocus) || ui.detailPanel.contains(previousFocus)
      || Array.from(state.markers.values()).some((marker) => marker.getElement()?.contains(previousFocus));
    const request: SearchRequest = { query: data.query, mode: data.mode, ...context };
    const link = ArchSearchResearch.buildLink(new URL(window.location.href), request);
    closeDetail(false);
    historyView?.setSelectionContext(null);
    registeredAreas?.clear();
    state.results = Array.isArray(data.results) ? data.results : [];
    state.selectedId = null;
    state.selectedSite = null;
    resetSiteExport();
    state.selectionMarker?.remove();
    state.selectionMarker = null;
    mapComparison?.setSelection(null);
    selectedPhaseId = null;
    state.hasSearched = true;
    state.displayedMode = data.mode;
    ui.list.replaceChildren();
    ui.resultCount.textContent = String(state.results.length).padStart(2, "0");
    ArchSearchWorkspace.setSearchResultCount(state.results.length);
    ui.activeMode.textContent = data.enhancement?.applied ? "LLM · RRF" : "SEMANTIC";
    ui.enhancementNote.hidden = !data.enhancement;
    ui.enhancementQueries.replaceChildren();
    if (data.enhancement) {
      const enhanced = data.enhancement;
      ui.enhancementSummary.textContent = enhanced.applied
        ? `本次使用 ${enhanced.provider === "ollama" ? "Ollama" : "API"} · ${enhanced.model} 扩展查询，以 RRF 融合排名；增强耗时 ${Math.round(enhanced.elapsed_ms)} ms。改写不是来源证据。`
        : `增强失败，已按原查询检索。尝试模型：${enhanced.model}。${enhanced.reason || "模型未完成查询改写。"}`;
      enhanced.queries.forEach((query) => { ui.enhancementQueries.append(element("li", null, query)); });
    } else ui.enhancementSummary.textContent = "";
    const elapsed = Number.isFinite(data.elapsed_ms) ? `${Math.round(data.elapsed_ms)} ms` : "耗时未提供";
    const candidates = Number.isFinite(data.total_candidates)
      ? data.enhancement?.applied ? `合并原查询与改写后，在 ${data.total_candidates} 条候选资料中，`
        : `在当前范围的 ${data.total_candidates} 条资料中，`
      : "";
    ui.resultSummary.textContent = `${candidates}展示 ${state.results.length} 条 · ${elapsed}`;
    ui.resultContext.textContent = `本次查询：“${data.query}” · 语义检索 · ${context.type ? typeLabel(context.type) : "全部类型"} · 最多 ${context.limit} 条 · 语料 ${data.corpus_version}`;
    ui.resultContext.hidden = false;
    ui.empty.hidden = state.results.length > 0;
    if (state.results.length === 0) {
      ui.emptyTitle.textContent = "没有找到候选资料";
      ui.emptyDescription.textContent = "尝试调整问题或放宽类型筛选。当前语料为地中海罗马资料与全球历史遗址的策展样本。";
    }
    const viewCandidates: Parameters<ReturnType<typeof ArchSearchMapView.create>["setCandidates"]>[0] = [];
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
      if (excerpt.structured) description.classList.add("result-source-fields");
      description.lang = excerpt.lang ?? (excerpt.label === "原文状态" || excerpt.label.startsWith("中文") ? "zh-CN" : "en");
      if (excerpt.lang === "fr" || excerpt.lang === "pt-BR") titleArea.querySelector("h3")!.lang = excerpt.lang;
      const metadata = element("div", "result-metadata");
      metadata.append(element("span", "result-coordinate", coordinateLabel(site)), element("span", "result-score", scoreLabel(result.score, data.mode, data.enhancement?.applied === true)));
      const viewHint = element("span", "result-view-hint");
      viewHint.hidden = true;
      card.append(top, element("p", "result-excerpt-label", excerpt.label), description, metadata, viewHint);
      card.addEventListener("click", () => selectSite(String(site.id), { opener: card }));
      const actions = element("div", "result-actions");
      const detail = element("button", "result-detail-button", "资料详情");
      detail.type = "button";
      detail.setAttribute("aria-label", `查看 ${displayTitle(site)} 的资料详情`);
      detail.addEventListener("click", () => { void selectSite(String(site.id), { opener: detail, showDetail: true }); });
      actions.append(detail);
      item.append(card, actions);
      ui.list.append(item);
      viewCandidates.push({ id: String(site.id), rank: index + 1, title: displayTitle(site), card, marker: null,
        hint: viewHint, locationStatus: ArchSearchMapView.locationStatus(site.repr_point) });
    }
    renderMarkers();
    for (const candidate of viewCandidates) {
      candidate.marker = state.markers.get(candidate.id) || null;
      const historical = mapComparison?.getMarker(candidate.id);
      if (historical) candidate.additionalMarkers = [historical];
    }
    mapView?.setCandidates(viewCandidates);
    updateSelectionControls();
    state.completedSearch = { request, response: data, link };
    if (unresolvedSearchLink && sameRequest(unresolvedSearchLink, request)) unresolvedSearchLink = null;
    saveViewLink();
    ui.resultTools.hidden = false;
    ArchSearchWorkspace.activateResults({ focus: false });
    ui.copyLink.disabled = false;
    ui.toolsFeedback.textContent = "";
    ui.shareLinkPanel.hidden = true;
    ui.shareLink.value = state.completedSearch.link;
    if (removedFocus || (previousFocus instanceof HTMLButtonElement && previousFocus.disabled
      && [ui.previousResult, ui.nextResult, ui.locateSelected].includes(previousFocus))) {
      focusWithinView(ui.resultSummary);
    }
    announce(`检索完成，返回 ${state.results.length} 条候选资料。相似度分数并非相关概率，请核验来源。`);
  }

  async function copySearchLink(): Promise<void> {
    saveViewLink();
    const copiedLink = currentLink;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(copiedLink);
      if (currentLink !== copiedLink) return;
      ui.shareLinkPanel.hidden = true;
      ui.toolsFeedback.textContent = "已复制研究视图链接。复查时需要能访问同一服务。";
    } catch {
      if (currentLink !== copiedLink) return;
      ui.shareLink.value = copiedLink;
      ui.shareLinkPanel.hidden = false;
      ui.toolsFeedback.textContent = "未能自动复制。链接已选中，可按 Ctrl+C 或 Command+C 手动复制。";
      ui.shareLink.focus();
      ui.shareLink.select();
    }
  }

  function downloadJson(filename: string, report: object): void {
    const download = element("a");
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" }));
    try {
      download.href = objectUrl;
      download.download = filename;
      download.hidden = true;
      document.body.append(download);
      download.click();
    } finally {
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }
  }

  function exportSearchResults(): void {
    const completed = state.completedSearch;
    if (!completed) return;
    try {
      const exportedAt = new Date().toISOString();
      const map = historyView?.getView() ?? null;
      const areas = registeredAreas?.getSnapshot() ?? null;
      const evidence = ArchSearchResearch.selectSearchExportEvidence({
        search: completed.response, selection: { site: state.selectedId, phase: selectedPhaseId },
        displayedSite: currentSelectedSite(), verifiedDetail,
        catalogue: null,
      });
      const report = ArchSearchResearch.createExport(completed.request, completed.response, exportedAt, map,
        evidence.selection, evidence.selectedSite, evidence.browse, evidence.spatial, areas, currentCorpusVersion,
        currentRegisteredAreasVersion, mapComparison?.snapshot(map) ?? null);
      downloadJson(`archsearch-${completed.request.mode}-${exportedAt.replace(/[:.]/g, "-")}.json`, report);
      const omitted: string[] = [];
      if (evidence.selectionStatus === "omitted") omitted.push("选中遗址资料");
      else if (evidence.phaseOmitted) omitted.push("选中阶段");
      if (areas && !report.registered_areas) omitted.push("登记范围");
      ui.toolsFeedback.textContent = [
        `已生成 ${completed.response.results.length} 条检索结果的 JSON 文件。`,
        ...(evidence.selectionStatus === "ranked" ? ["遗址附录采用检索时的记录。"] : []),
        ...(omitted.length ? [`已省略无法确认同版来源的${omitted.join("、")}。`] : []),
      ].join(" ");
    } catch {
      ui.toolsFeedback.textContent = "结果文件未能生成，请重试或检查浏览器的下载设置。";
    }
  }

  function exportSiteEvidence(): void {
    const evidence = exportableDetail();
    if (!evidence) return;
    try {
      const { site, corpusVersion } = evidence;
      const exportedAt = new Date().toISOString();
      const map = historyView?.getView() ?? null;
      const report = ArchSearchResearch.createSiteExport({
        exportedAt, corpusVersion, selection: { site: site.id, phase: selectedPhaseId }, selectedSite: site,
        map, comparison: mapComparison?.snapshot(map) ?? null, browse: null,
        spatial: null, registeredAreas: registeredAreas?.getSnapshot() ?? null,
        registeredAreasVersion: currentRegisteredAreasVersion,
      });
      const filenameId = site.id.replace(/[^a-zA-Z0-9_-]/g, "-");
      downloadJson(`archsearch-site-${filenameId}-${exportedAt.replace(/[:.]/g, "-")}.json`, report);
      setSiteExportFeedback("已生成资料 JSON，包含来源、年代证据和实际显示的地图状态。");
    } catch (error) {
      setSiteExportFeedback(`资料文件未能生成。${errorMessage(error)}`);
    }
  }

  function cancelLinkRestore(): void {
    pendingLink = null;
    unresolvedSearchLink = null;
    linkError = null;
    invalidLink = false;
    pendingSelectionRestore = false;
    state.restoringLink = false;
    if (restoringSearchController && restoringSearchController === state.searchController) cancelCurrentSearch();
    updateSearchAvailability();
  }

  function prepareLinkedSearch(request: SearchRequest): boolean {
    if (request.mode !== "semantic") {
      showError("当前网页仅支持语义检索，已移除关键词基线；请改用语义检索重新查询。");
      return false;
    }
    if (request.type && (ui.typeFilter.disabled || !Array.from(ui.typeFilter.options).some((option) => option.value === request.type))) {
      showError("链接中的地点类型无法确认。请检查类型是否有效，或重新选择后手动检索；本次未自动扩大检索范围。");
      return false;
    }
    ui.typeFilter.value = request.type || "";
    llmView?.setRequested(request.enhance === true);
    if (request.enhance) {
      const config = llmView?.getConfig();
      if (!config?.model) {
        showError("LLM 增强链接已恢复；请先在模型设置中获取并应用模型，再主动检索。本次未改成基础检索。");
        llmView?.showSettings();
        return false;
      }
      request.llm_revision = config.revision;
    }
    if (!state.corpusReady || !state.semanticReady) {
      showError("链接中的检索条件已恢复；当前服务或语义模型尚未就绪。请查看运行状态，准备后手动检索。");
      return false;
    }
    return true;
  }

  async function finishLinkRestore(): Promise<void> {
    const request = pendingLink;
    pendingLink = null;
    state.restoringLink = false;
    const actionVersion = historyView?.actionVersion() ?? 0;

    if (linkError) {
      showError(`分享链接未能恢复：${linkError}`);
      linkError = null;
      pendingSelectionRestore = false;
    } else if (request && prepareLinkedSearch(request)) {
      const search = runSearch(request);
      restoringSearchController = state.searchController;
      try {
        await search;
      } finally {
        restoringSearchController = null;
      }
    }
    updateSearchAvailability();

    if (pendingSelectionRestore && initialView.selection.site
      && (historyView?.actionVersion() ?? 0) === actionVersion) {
      await selectSite(initialView.selection.site, {
        phaseId: initialView.selection.phase,
        preserveYear: initialView.view !== null || actionVersion > 0,
        restoring: true,
      });
    }
    pendingSelectionRestore = false;
    saveViewLink();
  }

  function setLoading(value: boolean, reason?: "cancelled"): void {
    const focusWasInProgress = !value && ui.searchProgress.contains(document.activeElement);
    state.searching = value;
    ui.resultsPanel.setAttribute("aria-busy", String(value));
    ui.form.classList.toggle("is-searching", value);
    ui.loading.hidden = !value || state.results.length > 0;
    if (value && state.results.length === 0) ui.empty.hidden = true;
    if (!value) ui.empty.hidden = state.results.length > 0;
    updateSearchAvailability();
    if (!focusWasInProgress) return;
    if (reason === "cancelled") focusWithinView(ui.query);
    else if (!ui.retrySearch.disabled) focusWithinView(ui.retrySearch);
    else if (!ui.requestError.hidden) focusWithinView(ui.requestError);
    else if (!ui.searchProgress.hidden) focusWithinView(ui.progressLabel);
    else focusWithinView(ui.resultSummary);
  }

  async function search(event?: Event): Promise<void> {
    exampleIntent.invalidate();
    if (event) event.preventDefault();
    cancelLinkRestore();
    mapComparison?.noteInteraction();
    const request = formRequest();
    if (!request.query) {
      if (state.searching) cancelCurrentSearch();
      ui.query.focus();
      return;
    }
    await runSearch(request);
  }

  function invalidateSearch(): void {
    ++state.searchSequence;
    state.searchController?.abort();
    state.searchController = null;
    state.activeSearch = null;
  }

  function cancelCurrentSearch(): void {
    if (!state.searching) return;
    invalidateSearch();
    state.failedSearch = null;
    state.searchFeedback = state.completedSearch ? "已取消本次等待，保留上次结果与地图。" : "已取消本次等待，可以调整问题后重新检索。";
    showError("");
    if (!state.completedSearch) {
      ui.emptyTitle.textContent = "本次检索已取消";
      ui.emptyDescription.textContent = "调整研究问题后可重新检索；取消只停止等待，不会清除已有资料。";
    }
    setLoading(false, "cancelled");
    announce(state.searchFeedback);
  }

  async function runSearch(request: SearchRequest): Promise<void> {
    ArchSearchWorkspace.activateResults({ focus: false });
    if (state.searching && state.activeSearch && sameRequest(state.activeSearch, request)) return;
    invalidateSearch();
    const sequence = state.searchSequence;
    state.failedSearch = null;
    state.searchFeedback = null;
    showError("");
    if (!modeAvailable(request.mode)) {
      state.searchFeedback = "当前检索方式尚未就绪，请查看准备指引或手动选择可用方式。";
      setLoading(false);
      announce(state.searchFeedback);
      return;
    }
    if (request.enhance === true) {
      const config = llmView?.getConfig();
      if (!config?.model || request.llm_revision !== config.revision) {
        showError(config?.model ? "模型配置已经改变，请按当前已应用模型重新发起检索；没有改写原失败请求。" : "请先获取并应用模型，再开启 LLM 增强；当前请求未改成基础检索。");
        llmView?.showSettings(); setLoading(false); return;
      }
    }
    if (request.type && !state.typeLabels.has(request.type)) {
      showError("当前类型无法确认。请刷新类型列表、改选类型或明确清除筛选后检索。");
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    state.searchController = controller;
    state.activeSearch = { ...request };
    const focusProgress = document.activeElement === ui.searchButton || document.activeElement === ui.retrySearch;
    setLoading(true);
    if (focusProgress) {
      focusWithinView(ui.progressLabel);
    }
    announce(ui.progressLabel.textContent ?? "");
    try {
      const data = await api<SearchResponse>("/api/search", {
        method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (sequence !== state.searchSequence) return;
      if (data.query !== request.query || data.mode !== request.mode) throw new Error("检索响应与本次查询或方式不一致，保留原成功结果。");
      const enhancement = ArchSearchResearch.validateEnhancement(request, data.enhancement);
      if (enhancement) data.enhancement = enhancement;
      renderResults(data, { type: request.type, limit: request.limit, country: request.country, region: request.region,
        ...(request.subdivision ? { subdivision: request.subdivision } : {}),
        ...(request.enhance ? { enhance: true, llm_revision: request.llm_revision } : {}) });
    } catch (error) {
      if (isAbortError(error) || sequence !== state.searchSequence) return;
      state.failedSearch = { ...request };
      const retained = state.completedSearch ? "已保留上次结果与地图。" : "请检查本地服务后重试。";
      showError(`本次检索未完成：${errorMessage(error)} ${retained}`);
      announce("本次检索失败，请查看错误说明。");
      if (!state.completedSearch) {
        ui.emptyTitle.textContent = "本次检索未完成";
        ui.emptyDescription.textContent = "上方保留了错误说明。检查本地语义模型与服务后可点击重试。";
      }
    } finally {
      if (sequence === state.searchSequence) {
        state.searchController = null;
        state.activeSearch = null;
        setLoading(false);
      }
    }
  }

  function retryFailedSearch(): void {
    const request = state.failedSearch;
    if (!request || state.searching || request.mode !== "semantic") return;
    if (request.type && !state.typeLabels.has(request.type)) {
      showError("上次失败请求的类型已不可用，未放宽原条件。请刷新类型或重新选择后检索。");
      return;
    }
    ui.query.value = request.query;
    ui.typeFilter.value = request.type || "";
    ui.limitFilter.value = String(request.limit);
    llmView?.setRequested(request.enhance === true);
    void runSearch(request);
  }

  function clearTypeFilter(): void {
    const returnFocus = document.activeElement === ui.clearType || document.activeElement === ui.emptyClearType;
    ui.typeFilter.value = "";
    applyChangedFilter();
    if (returnFocus) {
      if (state.searching) {
        focusWithinView(ui.progressLabel);
      } else focusWithinView(ui.query);
    }
  }

  function detailSection(title: string, content: string | Node, className = "detail-section"): HTMLElement {
    const section = element("section", className);
    section.append(element("h4", null, title));
    if (typeof content === "string") section.append(element("p", null, content));
    else section.append(content);
    return section;
  }

  function chipList(values: string[], fallback: string): HTMLElement {
    if (!values.length) return element("p", "detail-empty-text", fallback);
    const list = element("ul", "detail-chips");
    for (const value of values) list.append(element("li", "detail-chip", value));
    return list;
  }

  function fact(label: string, value: string): HTMLDivElement {
    const row = element("div", "detail-fact");
    row.append(element("dt", null, label), element("dd", null, value));
    return row;
  }

  function evidenceList(evidence: PeriodEvidence[]): HTMLDivElement {
    const list = element("div", "evidence-list");
    for (const item of evidence) {
      const row = element("article", "evidence-item");
      const resource = item.resource_type === "Name" ? "名称记录" : "位置记录";
      row.append(element("p", "evidence-title", `${resource} · ${periodLabel(item.period_id)}`));
      const meta = element("dl", "evidence-meta-grid");
      meta.append(
        fact("分期标注把握", sourceLabel(item.confidence, confidenceLabels)),
        fact("记录与地点关联", sourceLabel(item.association_certainty, certaintyLabels)),
        fact("原始记录时间", `${sourceYear(item.start)} — ${sourceYear(item.end)}`),
      );
      const links = element("div", "evidence-links");
      links.append(safeLink(item.resource_uri, "原始记录 ↗"), safeLink(item.period_uri, "时期定义 ↗"));
      row.append(meta, links);
      list.append(row);
    }
    return list;
  }

  function saveViewLink(): void {
    ui.exportResults.disabled = state.completedSearch === null;
    if (initialStatePending || invalidLink || pendingSelectionRestore || unresolvedSearchLink) return;
    const link = ArchSearchResearch.buildLink(new URL(window.location.href), state.completedSearch?.request ?? null,
      historyView?.getView() ?? null, { site: state.selectedId, phase: selectedPhaseId }, null, mapComparison?.state() ?? null);
    currentLink = link;
    if (state.completedSearch && state.completedSearch.link !== link) state.completedSearch = { ...state.completedSearch, link };
    ui.shareLink.value = link;
    ui.resultTools.hidden = !state.completedSearch && !state.selectedSite && historyView?.getView() == null;
    ui.copyLink.disabled = false;
    try { window.history.replaceState(null, "", link); } catch { /* Copy remains available. */ }
  }

  function phaseContent(site: Site): HTMLElement {
    const review = site.chronology;
    const content = element("div", "chronology-content");
    if (!review) { content.append(element("p", null, "当前资料尚无断代核验记录。")); return content; }
    const reviewLabel = {
      reviewed: "已有来源支持的阶段", insufficient: "已核验，断代未确定", not_reviewed: "断代尚未核验",
    };
    const header = element("div", "chronology-header");
    header.append(element("span", `chronology-status-badge is-${review.status}`, reviewLabel[review.status]));
    if (review.reviewed_at) header.append(element("span", "chronology-reviewed-at", `核验日期 ${review.reviewed_at}`));
    const audit = element("details", "chronology-audit");
    audit.append(element("summary", null, "核验方式"), element("p", "detail-note", review.method));
    header.append(audit);
    content.append(header);
    if (review.note) content.append(element("p", "chronology-lead", review.note));
    if (!review.phases.length) return content;
    const kinds = { construction: "建造", use: "使用", rebuild: "改建", destruction: "毁损", other: "其他事件" };
    const precision = { exact_year: "明确单年", approximate_year: "约略年份", range: "区间年代", period: "时期描述" };
    content.append(element("p", "detail-note", "年代仅依据来源自动联动。区间、约略或未知年代保留最后成功背景，不提供任意年或手选时间点；各阶段不视为连续生命周期。"));
    const phaseList = element("div", "phase-list");
    for (const phase of review.phases) {
      const current = phase.id === (selectedPhaseId ?? review.default_phase_id);
      const section = element("section", current ? "phase-record is-current" : "phase-record");
      const phaseHeader = element("div", "phase-header");
      const phaseMain = element("div", "phase-header-main");
      phaseMain.append(element("span", "phase-kind-badge", kinds[phase.kind]), element("h5", null, phase.label));
      if (current) phaseMain.append(element("span", "phase-current-badge", "当前资料阶段"));
      const dates = phase.start_year === null && phase.end_year === null ? "来源未给出可换算的年份" : phase.start_year === phase.end_year
        ? sourceYear(phase.start_year) : `${sourceYear(phase.start_year)} — ${sourceYear(phase.end_year)}`;
      phaseHeader.append(phaseMain, element("span", "phase-dates", `${precision[phase.precision]} · ${dates}`));
      section.append(phaseHeader);
      if (phase.note) section.append(element("p", "detail-note", phase.note));
      if (phase.sources.length) {
        const sources = element("div", "phase-sources");
        for (const source of phase.sources) {
          const card = element("div", "phase-source-card");
          const evidence = element("blockquote", "phase-evidence", source.excerpt);
          evidence.lang = "en";
          card.append(
            evidence,
            safeLink(source.uri, source.title, "phase-source-link"),
            element("p", "phase-source-meta", `${source.publisher} · ${source.license ?? "许可见原始来源"} · ${source.revision ?? "版本未提供"}`),
          );
          sources.append(card);
        }
        section.append(sources);
      }
      phaseList.append(section);
    }
    content.append(phaseList);
    return content;
  }

  function followPhase(phase: HistoricalPhase): void {
    const year = ArchSearchResearch.automaticPhaseYear(phase);
    if (year !== null) historyView?.setYear(year, "site", { selectionOwned: true });
    else historyView?.retainBackground("所选阶段仅有区间或约略年代，历史图保留最后成功背景，不推定单年。");
    const site = currentSelectedSite();
    if (site) updateComparisonSelection(site, false);
  }

  function minasSourceContent(rows: NonNullable<ReturnType<typeof ArchSearchResearch.parseMinasSource>>): HTMLElement {
    const content = element("div", "minas-source-records");
    const labels: Record<typeof ArchSearchResearch.minasSourceFields[number], string> = {
      processo_ano: "原登记案号／年份字段",
      denominacao: "原登记简称（不作为整体别名）",
      denominacao_completa: "原登记完整名称",
      categoria: "原登记类别代码",
      classe_subclasse: "原登记分类／子类",
      municipio: "原来源行市镇（全文保留）",
      distrito: "原来源行地区字段",
      ato_legal: "原法律文书字段",
      livro_de_tombo: "原登记簿字段",
    };
    content.append(element("p", "detail-note", `${rows.length} 条来源行对应当前同一登记整体，来源行数不作为遗址数量。字段名称为界面说明，葡萄牙语原值完整保留；登记、法律和簿册字段不转换成建造或使用年代。`));
    if (rows.some((row) => ArchSearchResearch.minasSourceFields.some((field) => row[field] === "0"))) {
      content.append(element("p", "detail-note minas-zero-note", "原值“0”按原文保留。数据字典的通用缺失值标记与登记簿字段的具体说明存在歧义，此处不统一解释为缺失、年份或保护状态。"));
    }
    for (const row of rows) {
      const record = element("section", "minas-source-record");
      record.append(element("h5", "minas-record-heading", `来源行 ${row.record_index}`));
      const fields = element("dl", "minas-source-fields");
      for (const key of ArchSearchResearch.minasSourceFields) {
        const group = element("div");
        group.append(element("dt", null, `${labels[key]} · ${key}`));
        const value = element("dd", null, row[key]);
        value.lang = "pt-BR";
        if (row[key] === "") {
          const empty = element("span", "minas-empty-value", "原值为空字符串");
          empty.lang = "zh-CN";
          value.append(empty);
        }
        group.append(value);
        fields.append(group);
      }
      record.append(fields);
      content.append(record);
    }
    return content;
  }

  function merimeeSourceContent(site: Site, source: NonNullable<ReturnType<typeof ArchSearchResearch.parseMerimeeSource>>): HTMLElement {
    const content = element("div", "merimee-source");
    const record = source.source_record;
    content.append(element("p", "detail-note", "名录包括曾受或现受保护的记录；下列内容保留来源表述，不据此判断当前法律状态。保护限定部分与完整建筑、庄园或街区不能直接等同，保护文书日期也不作为历史阶段。"));
    const scope = element("section", "merimee-protection");
    scope.append(element("h5", null, "原文保护范围 · Precision_de_la_protection"));
    const protection = element("p", "merimee-protection-text", record.Precision_de_la_protection || "原字段为空字符串；请核对下方范围依据与官方来源。");
    protection.lang = record.Precision_de_la_protection ? "fr" : "zh-CN";
    scope.append(protection);
    if (source.scope.source_field !== "Precision_de_la_protection") {
      scope.append(element("h5", null, `范围依据原字段 · ${source.scope.source_field}`));
      const literal = element("p", "merimee-protection-text", source.scope.literal || "原字段为空字符串");
      literal.lang = source.scope.literal ? "fr" : "zh-CN";
      scope.append(literal);
    }
    if (record.Observations !== "" && source.scope.source_field !== "Observations") {
      scope.append(element("h5", null, "保护说明／变更原文 · Observations"));
      const observations = element("p", "merimee-protection-text", record.Observations);
      observations.lang = "fr";
      scope.append(observations);
    }
    content.append(scope);
    const fields = element("dl", "merimee-source-fields");
    const selectedFields = [
      ["Reference", "原名录记录编号（不作为法定地块身份）"],
      ["Typologie_de_la_protection", "原保护类型字段"],
      ["Date_et_typologie_de_la_protection", "原保护日期／类型字段（非历史阶段）"],
      ["Commune_forme_editoriale", "来源 Commune（全文保留）"],
      ["Region", "来源原 Region"],
      ["coordonnees_au_format_WGS84", "原 WGS84 坐标字段"],
    ] as const;
    for (const [key, label] of selectedFields) {
      const group = element("div");
      group.append(element("dt", null, `${label} · ${key}`));
      const value = element("dd", null, record[key] || "原值为空字符串");
      value.lang = record[key] ? "fr" : "zh-CN";
      if (!record[key]) value.classList.add("merimee-empty-value");
      group.append(value); fields.append(group);
    }
    content.append(fields,
      element("p", "detail-note", "原 Region 与项目的现代国家／地区关联分别保留；来源 Commune 全串不拆分，也不据此认定整体全部位于该分区。"),
      element("p", "detail-note", "项目仅在有已核公开坐标时采用来源点作参考位置，不将其视为整体中心；来源未说明点的生成方法与定位精度。原坐标为空时保留缺失，不用地址、行政中心或零坐标补点。"));
    const contextFields = ["Description_de_l_edifice", "Historique"] as const;
    if (contextFields.some((key) => record[key] !== "")) {
      const context = element("details", "merimee-prose");
      context.append(element("summary", null, "阅读来源的法文描述与历史原文"));
      for (const key of contextFields) {
        if (record[key] === "") continue;
        context.append(element("h5", null, key === "Historique" ? "来源历史原文 · Historique" : "来源建筑描述 · Description_de_l_edifice"));
        const paragraph = element("p", "merimee-protection-text", record[key]);
        paragraph.lang = "fr";
        context.append(paragraph);
      }
      content.append(context);
    }
    const original = element("details", "merimee-original");
    original.dataset.siteId = site.id;
    const previous = ui.detailContent.querySelector<HTMLDetailsElement>(".merimee-original");
    original.open = previous?.dataset.siteId === site.id && previous.open;
    original.append(element("summary", null, "展开完整原始记录（78 个字段）"));
    const raw = element("pre", "merimee-raw", site.details);
    raw.lang = "fr";
    original.append(raw); content.append(original);
    return content;
  }

  function renderDetail(site: Site, matchedFields: string[] = []): void {
    const focusWasInContent = ui.detailContent.contains(document.activeElement);
    const minas = ArchSearchResearch.parseMinasSource(site);
    const merimee = ArchSearchResearch.parseMerimeeSource(site);
    const sourceNames = {
      pleiades: "PLEIADES", global: "CURATED", unesco: "UNESCO DATAHUB", ats: "ATS HSM", supplement: "CULTURAL SUPPLEMENT",
    } as const;
    const reviewStatus = site.chronology?.status ?? "not_reviewed";
    const reviewBadges = {
      reviewed: "已有来源阶段", insufficient: "断代未确定", not_reviewed: "尚未核验",
    } as const;
    const hero = element("header", "detail-hero");
    const badges = element("div", "detail-badges");
    badges.append(
      element("span", "detail-badge is-source", sourceNames[site.source_kind] ?? "SOURCE"),
      element("code", "detail-id-chip", site.id),
      element("span", `detail-badge is-chronology is-${reviewStatus}`, reviewBadges[reviewStatus]),
    );
    const title = element("h3", null, displayTitle(site));
    title.id = "detail-title";
    if (minas) title.lang = "pt-BR";
    else if (merimee) title.lang = "fr";
    hero.append(badges, title);
    if (displayTitle(site) !== site.title) {
      hero.append(element("p", "detail-source-title", `来源标题原文：${site.title || "未提供"}`));
    }
    const phases = site.chronology?.phases ?? [];
    const activePhase = phases.find((phase) => phase.id === (selectedPhaseId ?? site.chronology?.default_phase_id)) ?? null;
    const quickDate = activePhase && (activePhase.start_year !== null || activePhase.end_year !== null)
      ? activePhase.start_year === activePhase.end_year ? sourceYear(activePhase.start_year) : `${sourceYear(activePhase.start_year)} — ${sourceYear(activePhase.end_year)}`
      : reviewBadges[reviewStatus];
    const quickFacts = element("dl", "detail-quick-facts");
    quickFacts.append(
      fact("代表坐标", coordinateLabel(site)),
      fact("断代阶段", quickDate),
      fact("地点类型", strings(site.types).slice(0, 3).map(typeLabel).join(" · ") || "未提供"),
    );
    if (site.geography) {
      const regionSummary = site.source_kind === "ats"
        ? "南极洲（不作主权归属标注）"
        : site.geography.countries.join(" · ") || site.geography.regions.join(" · ") || "来源未明确";
      quickFacts.append(fact("来源地区", regionSummary));
    }
    hero.append(quickFacts);
    const editorial = site.source_kind === "supplement" && !site.id.startsWith("wd:") && !site.id.startsWith("auth:sg-nhb:") && !minas && !merimee;
    hero.append(element("p", "detail-hero-note", minas ? "以下为葡萄牙语原登记字段；未生成历史摘要或中文别名。" : merimee ? "以下为法文原名录记录与保护范围；未生成历史摘要或中文别名。" : editorial ? "描述和摘要依据所列来源整理，不冒充官方原文；逐条原文见来源摘录，历史阶段另据证据核验。" : "来源原文保留原语言；未生成历史摘要。"));

    const nodes: Node[] = [hero];

    const showOriginalDesc = !merimee && (!minas || hasSourceText(site.description));
    const showChineseDesc = Boolean(site.description_zh && hasSourceText(site.description_zh));
    if (showOriginalDesc || showChineseDesc) {
      const overview = element("section", "detail-section detail-overview");
      const buildBlock = (heading: string, textValue: string, lang: string): HTMLElement => {
        const block = element("div", "detail-lang-block");
        block.append(element("h4", null, heading));
        const body = element("p", "detail-description", textValue);
        body.lang = lang;
        block.append(body);
        return block;
      };
      const container = showOriginalDesc && showChineseDesc ? element("div", "detail-bilingual") : overview;
      if (showChineseDesc) container.append(buildBlock(chineseDescriptionLabel(site), site.description_zh!, "zh-CN"));
      if (showOriginalDesc) {
        const descText = hasSourceText(site.description) ? site.description : "当前导出未提供描述。";
        const descLang = hasSourceText(site.description) ? (minas ? "pt-BR" : "en") : "zh-CN";
        const descTitle = editorial ? ArchSearchResearch.descriptionLabel(site, "en") : "来源描述原文";
        container.append(buildBlock(descTitle, descText, descLang));
      }
      if (container !== overview) overview.append(container);
      nodes.push(overview);
    }

    const details = merimee ? merimeeSourceContent(site, merimee) : minas ? minasSourceContent(minas) : element("p", null, hasSourceText(site.details)
      ? site.details : `当前导出未提供补充内容${site.details.trim() ? `（原始值：${site.details}）` : ""}。`);
    if (!minas && !merimee && hasSourceText(site.details)) details.lang = site.id.startsWith("auth:fr-merimee:") ? "fr" : "en";
    const sourceSection = detailSection(site.source_kind === "supplement" ? "来源结构化信息与范围说明" : "原始补充记录", details, "detail-section detail-card");
    if (merimee) nodes.push(sourceSection);
    nodes.push(detailSection("年代证据与地图联动", phaseContent(site), "detail-section detail-card"));
    if (!merimee) nodes.push(sourceSection);

    const metaGrid = element("div", "detail-meta-grid");
    const facts = element("dl", "detail-facts");
    facts.append(fact("代表点", coordinateLabel(site)), fact(site.source_kind === "pleiades" ? "原始精度" : "定位精度分类", sourceLabel(site.location_precision, { precise: "精确", rough: "概略" })));
    const space = detailSection("空间信息 · WGS84", facts, "detail-section detail-meta-card");
    space.append(element("p", "detail-note", "精度按来源标签展示，不承诺米级误差；代表点不等同于实测发掘坐标。"));
    const positionStatus = ArchSearchMapView.locationStatus(site.repr_point);
    if (positionStatus === "polar") {
      space.append(element("p", "detail-note", "原坐标超出主地图Web Mercator投影范围；主地图不夹取纬度。"));
    } else if (positionStatus === "unknown") {
      space.append(element("p", "detail-note", site.source_kind === "supplement"
        ? "本记录未采用可信公开代表点，不以近邻、行政中心或零坐标替代。来源公开范围如有提供，会按其来源类型单独列出；多边形不补成代表点，也不表示原址实际未知。"
        : "来源未给出已知的遗址真实位置，不绘制遗址标记；如有最后目击参照，仅保留在来源说明中。"));
    }
    if (site.location_precision === "rough") {
      space.append(element("p", "detail-note", "rough 表示应在某个范围内寻找地点；代表点可能只是该范围的中心。"));
    }
    metaGrid.append(space);

    if (site.geography) {
      const geography = site.geography;
      const geoFacts = element("dl", "detail-facts");
      geoFacts.append(
        fact("国家／地区", site.source_kind === "ats" ? "不作主权归属标注" : geography.countries.join(" · ") || "来源未明确"),
        fact("分区", geography.regions.map((region) => region === "antarctica" ? "南极洲（独立区域分类）" : region).join(" · ") || "来源未提供"),
      );
      const scope = detailSection("来源名录中的国家／地区与分区", geoFacts, "detail-section detail-meta-card");
      scope.append(element("p", "detail-note", geography.note),
        element("p", "detail-note", `名录可用定位点记录：${geography.point_count}。${geography.point_count ? "可定位时只展示一个代表点，不表示全部组成地点。" : "未采用可用代表点，不绘制遗址标记；来源公开范围如有提供另列。"}此处是来源名录标签，不代表历史政治归属。`),
        safeLink(geography.source.uri, geography.source.title, "detail-inline-link"));
      metaGrid.append(scope);
    }

    metaGrid.append(detailSection("名称与别名", chipList(strings(site.names), "原始资料未提供其他名称。"), "detail-section detail-meta-card"));
    metaGrid.append(detailSection("来源类型标签", chipList(strings(site.types).map((value) => primaryTypeLabels[value]
      ? `${typeLabel(value)}（${value}）` : value), "原始资料未提供类型。"), "detail-section detail-meta-card"));

    const periods = detailSection("原始时期标签", chipList(strings(site.periods).map(periodLabel), "原始资料未提供时期标签。"), "detail-section detail-meta-card");
    periods.append(element("p", "detail-note", "标签来自名称或位置记录；多个时期标签不能证明地点持续使用，也不能直接视为建造年代。"));
    metaGrid.append(periods);

    const fields = strings(matchedFields).map((field) => fieldLabels[field] || field);
    if (state.results.some((result) => result.site.id === site.id)) {
      const matches = detailSection("字词片段匹配字段", chipList(fields, "未发现查询与检索字段的字词片段重叠。"), "detail-section detail-meta-card");
      matches.append(element("p", "detail-note", "仅展示成功检索的字词重叠，不解释语义模型的排序依据；中文问题仍可能检索到英文候选。"));
      metaGrid.append(matches);
    } else metaGrid.append(detailSection("选择方式", "通过研究链接直接打开；未附带本次语义检索排序分数。", "detail-section detail-meta-card"));

    metaGrid.append(detailSection("资料贡献者", chipList(strings(site.contributors), "当前导出未提供贡献者信息，请在原始来源中核验。"), "detail-section detail-meta-card"));
    nodes.push(metaGrid);

    if (registeredAreas) nodes.push(registeredAreas.element);

    const evidence = Array.isArray(site.period_evidence) ? site.period_evidence : [];
    if (evidence.length) {
      const roman = evidence.filter((item) => item.period_id === "roman");
      const other = evidence.filter((item) => item.period_id !== "roman");
      const section = detailSection("入选分期依据", element("p", "evidence-summary", `名称或位置记录中有 ${roman.length} 条 roman 分期关联。`), "detail-section detail-card");
      section.append(element("p", "detail-note", "本语料以 roman（前30—公元300年）筛选。下方起止年份属于整条原始记录，可能跨越多个分期，不是该分期的起止或遗址的确切断代。"));
      section.append(evidenceList(roman));
      if (other.length) {
        const more = element("details", "evidence-more");
        more.append(element("summary", null, `查看其他时期关联（${other.length} 条）`), evidenceList(other));
        section.append(more);
      }
      nodes.push(section);
    } else {
      nodes.push(detailSection("时期证据与来源", "原始资料未提供可展示的时期证据。", "detail-section detail-card"));
    }

    const sources = element("div", "detail-sources-list");
    for (const source of site.source_refs ?? []) {
      const card = element("article", "detail-source-card");
      card.append(
        safeLink(source.uri, source.title, "detail-source-card-link"),
        element("p", "detail-source-meta", `${source.publisher} · ${source.license ?? "许可见原始来源"} · ${source.revision ?? "版本未提供"}`),
      );
      if (site.source_kind === "supplement" && source.excerpt.trim()) {
        const excerpt = element("blockquote", "detail-source-excerpt", source.excerpt);
        excerpt.lang = "en";
        card.append(excerpt);
      }
      sources.append(card);
    }
    nodes.push(detailSection("来源与许可", sources, "detail-section detail-card"));

    const footer = element("footer", "detail-footer");
    footer.append(
      element("p", "detail-note", "引用时保留地点编号、原始链接、版本与贡献者；不同来源遵循各自许可。"),
      safeLink(site.source_uri, "查看原始资料 ↗", "detail-source-link"),
    );
    nodes.push(footer);

    ui.detailContent.replaceChildren(...nodes);
    if (focusWasInContent && !ui.detailPanel.hidden) ui.detailPanel.focus({ preventScroll: true });
  }

  function markSelection(id: string): void {
    for (const card of Array.from(ui.list.querySelectorAll<HTMLButtonElement>(".result-card"))) {
      const selected = card.dataset.siteId === id;
      card.classList.toggle("is-selected", selected);
      card.setAttribute("aria-pressed", String(selected));
      if (selected) {
        const scrollPanel = document.getElementById("workspace-results-view");
        if (!scrollPanel || scrollPanel.closest("[hidden]")) continue;
        const listBounds = scrollPanel.getBoundingClientRect();
        const cardBounds = card.getBoundingClientRect();
        if (cardBounds.top < listBounds.top) scrollPanel.scrollTop -= listBounds.top - cardBounds.top;
        else if (cardBounds.bottom > listBounds.bottom) scrollPanel.scrollTop += cardBounds.bottom - listBounds.bottom;
      }
    }
    for (const [markerId, marker] of state.markers) {
      const selected = markerId === id;
      marker.getElement()?.classList.toggle("is-selected", selected);
      marker.getElement()?.setAttribute("aria-pressed", String(selected));
      marker.setZIndexOffset(selected ? 1000 : 0);
    }
  }

  function presentSelection(site: Site, matchedFields: string[], fresh: boolean, moveMap = true): void {
    state.selectedSite = site;
    const previousIcon = state.selectionMarker?.getElement();
    const markerOpenedDetail = previousIcon !== undefined && state.detailOpener === previousIcon;
    state.selectionMarker?.remove();
    state.selectionMarker = null;
    const coordinate = point(site);
    if (!state.markers.has(site.id) && state.map && coordinate) {
      coordinate[1] = ArchSearchMapView.wrapLongitude(coordinate[1], state.map.getCenter().lng);
      const content = element("span", "site-marker is-selected", "选");
      content.setAttribute("aria-hidden", "true");
      const marker = L.marker(coordinate, {
        icon: L.divIcon({ className: "site-marker-icon is-selected", html: content, iconSize: [30, 30], iconAnchor: [15, 15] }),
        keyboard: true, autoPanOnFocus: false, title: displayTitle(site), zIndexOffset: 2000,
      }).addTo(state.map);
      marker.bindTooltip(element("span", null, displayTitle(site)));
      marker.on("click", () => { void selectSite(site.id, { opener: marker.getElement() ?? null, showDetail: true }); });
      const icon = marker.getElement();
      if (markerOpenedDetail) state.detailOpener = icon ?? null;
      icon?.setAttribute("aria-label", `已选遗址：${displayTitle(site)}，打开资料详情`);
      icon?.addEventListener("keydown", (event) => {
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault(); event.stopPropagation(); marker.fire("click");
        }
      });
      state.selectionMarker = marker;
    }
    renderDetail(site, matchedFields);
    registeredAreas?.select(site.id, displayTitle(site));
    updateComparisonSelection(site, fresh && moveMap);
    updateSelectionControls();
    if (fresh) {
      ui.detailDialog.scrollTop = 0;
      ui.detailPanel.scrollTop = 0;
      if (moveMap) {
        positionSelectedSite(site);
      }
      const rank = state.results.findIndex((item) => item.site.id === site.id);
      announce(`${rank < 0 ? "已选择遗址" : `已选择第 ${rank + 1} / ${state.results.length} 条`}：${displayTitle(site)}，可打开资料详情核验来源。`);
    }
    saveViewLink();
  }

  async function selectSite(id: string, {
    fromMap = false, preserveYear = false, phaseId = null, opener = null, restoring = false, moveMap = true, showDetail = false,
  }: { fromMap?: boolean; preserveYear?: boolean; phaseId?: string | null; opener?: HTMLElement | null; restoring?: boolean; moveMap?: boolean; showDetail?: boolean } = {}): Promise<void> {
    closeDetail(false);
    if (restoring && (initialComparison.state.modern_view !== null || initialComparison.state.history_view !== null
      || (mapComparison?.actionVersion() ?? 0) > 0)) moveMap = false;
    if (!restoring) { cancelLinkRestore(); mapComparison?.noteInteraction(); }
    if (!restoring) historyView?.retainBackground("正在核对所选资料年代，保留最后成功历史背景。");
    const result = state.results.find((item) => item.site.id === id);
    const known = result?.site ?? (state.selectedSite?.id === id ? state.selectedSite : null);
    state.detailOpener = opener ?? (fromMap
      ? state.markers.get(id)?.getElement() ?? null
      : Array.from(ui.list.querySelectorAll<HTMLButtonElement>(".result-card")).find((card) => card.dataset.siteId === id) ?? null);
    state.detailController?.abort();
    const controller = new AbortController();
    state.detailController = controller;
    const userVersion = historyView?.actionVersion() ?? 0;
    const cameraVersion = mapComparison?.actionVersion() ?? 0;
    state.selectedId = id;
    state.selectedSite = known;
    resetSiteExport();
    selectedPhaseId = null;
    markSelection(id);
    registeredAreas?.select(id, known ? displayTitle(known) : id);
    const canLocateImmediately = known ? point(known) !== null : opener?.dataset.locationStatus === "mapped";
    if (!showDetail && moveMap && !restoring && canLocateImmediately) ArchSearchWorkspace.revealMaps();
    let initialPhase: HistoricalPhase | undefined;
    const choosePhase = (site: Site): void => {
      const phases = site.chronology?.phases ?? [];
      if (phaseId !== null && !phases.some((phase) => phase.id === phaseId)) {
        showError("链接中的阶段已失效；现展示遗址默认阶段，保留地图年份，请核对语料版本。");
        preserveYear = true;
      }
      selectedPhaseId = phases.some((phase) => phase.id === phaseId) ? phaseId : site.chronology?.default_phase_id ?? null;
      initialPhase = phases.find((phase) => phase.id === selectedPhaseId);
      if (initialPhase && !preserveYear && (historyView?.actionVersion() ?? 0) === userVersion) followPhase(initialPhase);
      else if (!initialPhase && !preserveYear) historyView?.retainBackground("所选资料没有已核验的明确年份；历史图保留最后成功背景。");
    };
    if (known) {
      choosePhase(known);
      presentSelection(known, result?.matched_fields ?? [], true, moveMap);
      if (!showDetail && moveMap && !restoring) {
        if (window.matchMedia("(max-width: 780px)").matches) byId("map-comparison", HTMLDivElement).scrollIntoView({ block: "start", behavior: "instant" });
        (state.markers.get(id) ?? state.selectionMarker)?.getElement()?.focus({ preventScroll: true });
      }
    } else {
      mapComparison?.setSelection(null);
      historyView?.setSelectionContext({ title: id, precision: "loading", start_year: null, end_year: null });
      state.selectionMarker?.remove(); state.selectionMarker = null;
      const loadingTitle = element("h3", null, "正在读取来源资料");
      loadingTitle.id = "detail-title";
      ui.detailContent.replaceChildren(loadingTitle, element("p", "detail-note", id), ...(registeredAreas ? [registeredAreas.element] : []));
      updateSelectionControls();
    }
    if (showDetail) ArchSearchWorkspace.openDetail(state.detailOpener);
    const phaseAtRequest = selectedPhaseId;
    try {
      const { data: site, headers } = await readApi<Site>(`/api/sites/${encodeURIComponent(id)}`, { signal: controller.signal });
      if (state.detailController !== controller || state.selectedId !== id || controller.signal.aborted) return;
      if (!isRecord(site) || site.id !== id) throw new Error("详情返回的遗址编号与当前选择不一致。");
      if (!known || JSON.stringify(site) !== JSON.stringify(known)) {
        if (!known) choosePhase(site);
        else if (selectedPhaseId === phaseAtRequest) {
          selectedPhaseId = site.chronology?.phases.some((phase) => phase.id === selectedPhaseId) ? selectedPhaseId : site.chronology?.default_phase_id ?? null;
          const phase = site.chronology?.phases.find((item) => item.id === selectedPhaseId);
          if (!initialPhase && phase && !preserveYear && (historyView?.actionVersion() ?? 0) === userVersion) followPhase(phase);
        }
        const untouched = (mapComparison?.actionVersion() ?? 0) === cameraVersion && (historyView?.actionVersion() ?? 0) === userVersion;
        presentSelection(site, result?.matched_fields ?? [], !known && untouched, moveMap && untouched);
      }
      const corpusVersion = headers.get("X-ArchSearch-Corpus-Version");
      if (corpusVersion) verifiedDetail = { site, corpusVersion };
      else setSiteExportFeedback("未能确认资料语料版本。请重启本地服务并重新打开资料。");
      updateSiteExportControl();
    } catch (error) {
      if (isAbortError(error) || controller.signal.aborted || state.detailController !== controller || state.selectedId !== id) return;
      registeredAreas?.clear();
      setSiteExportFeedback("完整资料未能读取。重新选择遗址后可再试导出。");
      if (known) ui.detailContent.append(element("p", "detail-loading", "详情刷新失败，当前显示检索时返回的原始资料。"));
      else {
        state.selectedId = null; state.selectedSite = null; selectedPhaseId = null;
        historyView?.setSelectionContext(null);
        mapComparison?.setSelection(null);
        const failedTitle = element("h3", null, "资料未能读取");
        failedTitle.id = "detail-title";
        ui.detailContent.replaceChildren(failedTitle, element("p", "detail-note", errorMessage(error)));
        showError(`遗址资料未能恢复：${errorMessage(error)}。地图与检索快照保持不变。`);
        if (restoring) invalidLink = true;
        updateSelectionControls();
        saveViewLink();
      }
    } finally {
      if (state.detailController === controller && restoring) { pendingSelectionRestore = false; saveViewLink(); }
    }
  }

  function closeDetail(returnFocus = true): void {
    ArchSearchWorkspace.closeDetail({ restoreFocus: returnFocus });
  }

  function openCurrentDetail(): void {
    const site = currentSelectedSite();
    if (!site) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : ui.openSelectedDetail;
    renderDetail(site, selectedResult()?.matched_fields ?? []);
    registeredAreas?.select(site.id, displayTitle(site));
    ArchSearchWorkspace.openDetail(opener);
  }

  function applyChangedFilter(): void {
    exampleIntent.invalidate();
    cancelLinkRestore();
    updateSearchAvailability();
    if (!ui.query.value.trim() && state.searching) cancelCurrentSearch();
    else if ((state.hasSearched || state.searching) && ui.query.value.trim()) search();
  }

  const exampleIntent = ArchSearchResearch.createExampleIntent();
  ui.form.addEventListener("submit", search);
  ui.form.addEventListener("input", (event) => {
    exampleIntent.invalidate();
    if (event.target === ui.query && !state.searching) state.searchFeedback = null;
    cancelLinkRestore();
    if (event.target === ui.query && !ui.query.value.trim() && state.searching) cancelCurrentSearch();
  });
  byId("llm-enhance", HTMLInputElement).addEventListener("change", () => {
    exampleIntent.invalidate();
    cancelLinkRestore();
  });
  ui.typeFilter.addEventListener("change", applyChangedFilter);
  ui.limitFilter.addEventListener("change", applyChangedFilter);
  document.querySelectorAll<HTMLButtonElement>("[data-query-zh]").forEach((button) => {
    button.addEventListener("click", () => {
      exampleIntent.invalidate();
      ui.query.value = button.dataset.queryZh || "";
      const type = button.dataset.type || "";
      ui.typeFilter.value = Array.from(ui.typeFilter.options).some((option) => option.value === type) ? type : "";
      updateSearchAvailability();
      const examplesMenu = document.getElementById("workspace-examples");
      if (examplesMenu instanceof HTMLDetailsElement) examplesMenu.open = false;
      ui.query.focus();
      void search();
    });
  });
  byId("refresh-status", HTMLButtonElement).addEventListener("click", refreshRuntime);
  byId("fit-map", HTMLButtonElement).addEventListener("click", () => { mapComparison?.noteInteraction(); closeDetail(false); ArchSearchWorkspace.revealMaps(); fitMap(); });
  byId("retry-tiles", HTMLButtonElement).addEventListener("click", () => {
    mapComparison?.setModernBasemap("osm");
  });
  ui.copyLink.addEventListener("click", copySearchLink);
  ui.exportResults.addEventListener("click", exportSearchResults);
  ui.exportSiteEvidence.addEventListener("click", exportSiteEvidence);
  ui.clearType.addEventListener("click", clearTypeFilter);
  ui.emptyClearType.addEventListener("click", clearTypeFilter);
  ui.cancelSearch.addEventListener("click", cancelCurrentSearch);
  ui.retrySearch.addEventListener("click", retryFailedSearch);
  ui.previousResult.addEventListener("click", () => browseResult(-1));
  ui.nextResult.addEventListener("click", () => browseResult(1));
  ui.locateSelected.addEventListener("click", locateCurrentSite);
  ui.openSelectedDetail.addEventListener("click", openCurrentDetail);
  window.addEventListener("archsearch:detailclose", () => {
    ui.detailPanel.hidden = true;
  });
  window.addEventListener("archsearch:workspacechange", () => {
    mapComparison?.invalidateSizes();
  });

  if (pendingLink) {
    state.restoringLink = true;
    ui.query.value = pendingLink.query;
    ui.limitFilter.value = String(pendingLink.limit);
  }
  llmView = ArchSearchLlm.create({ onChange: () => { updateSearchAvailability(); } });
  llmView.setRequested(pendingLink?.enhance === true);
  initializeMap();
  modernBoundaries = ArchSearchModernBoundaries.create({ map: state.map, onStatus: (status) => {
    const label = byId("modern-boundaries-status", HTMLElement);
    label.textContent = status.message;
    label.dataset.state = status.state;
    const alert = byId("modern-boundaries-alert", HTMLElement);
    alert.hidden = status.state !== "error" && status.state !== "unavailable";
    alert.textContent = alert.hidden ? "" : status.message;
    const retry = byId("modern-boundaries-retry", HTMLButtonElement);
    const retryOwnedFocus = document.activeElement === retry;
    retry.hidden = status.state !== "error";
    retry.disabled = status.state === "loading";
    if (retryOwnedFocus && retry.hidden) {
      const target = alert.hidden ? byId("modern-map-title", HTMLElement) : alert;
      target.tabIndex = -1; target.focus({ preventScroll: true });
    }
  } });
  byId("modern-boundaries-retry", HTMLButtonElement).addEventListener("click", () => { void modernBoundaries?.retry(); });
  mapComparison = ArchSearchComparison.create({
    modern: state.map, historical: historicalMap, tiles: state.tiles, initial: initialComparison.state,
    onSelect: (id, opener, options) => { void selectSite(id, { fromMap: true, opener, moveMap: options?.moveMap ?? true, showDetail: options?.moveMap !== false }); },
    onChanged: saveViewLink,
    onEvidence: openCurrentDetail,
  });
  historyView = ArchSearchHistory.create({
    map: historicalMap, tiles: null, fixedHistorical: true, automaticOnly: true, sharedRenderer: mapComparison.getHistoricalRenderer(),
    onCommittedView: saveViewLink,
    onUserAction: () => {
      restoringView = false;
      if (invalidLink) { invalidLink = false; linkError = null; }
    },
  });
  mapView = ArchSearchMapView.create({ map: state.map, countLabel: ui.viewportCount, scopeLabel: "现代图范围内" });
  registeredAreas = ArchSearchRegisteredAreas.create({
    map: state.map,
    onShow: () => {
      closeDetail(false);
      if (window.matchMedia("(max-width: 780px)").matches) {
        byId("registered-areas-show", HTMLButtonElement).scrollIntoView({ block: "nearest", behavior: "instant" });
        byId("map", HTMLDivElement).scrollIntoView({ block: "start", behavior: "instant" });
      }
    },
    onVisibilityChange: (visible) => { ui.detailPanel.classList.toggle("is-viewing-registered-area", visible); },
    getPadding: () => {
      return { topLeft: [24, 24], bottomRight: [24, 24] };
    },
  });
  ui.mapEmptyLabel.hidden = true;
  registeredAreas.setCorpusVersion(currentCorpusVersion, currentRegisteredAreasVersion);
  updateSelectionControls();
  updateSearchAvailability();
  refreshRuntime().then(finishLinkRestore).finally(() => { mapComparison?.restoreInitialViews(); initialStatePending = false; saveViewLink(); });
})();

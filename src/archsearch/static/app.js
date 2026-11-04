"use strict";
(() => {
    "use strict";
    function byId(id, expected) {
        const node = document.getElementById(id);
        if (!(node instanceof expected))
            throw new Error(`页面元素不存在或类型错误：${id}`);
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
        resultTools: byId("result-tools", HTMLDivElement), copyLink: byId("copy-search-link", HTMLButtonElement),
        exportResults: byId("export-results", HTMLButtonElement), toolsFeedback: byId("result-tools-feedback", HTMLParagraphElement),
        shareLinkPanel: byId("share-link-panel", HTMLDivElement), shareLink: byId("share-link", HTMLInputElement),
        list: byId("results-list", HTMLOListElement), empty: byId("results-empty", HTMLDivElement), emptyTitle: byId("empty-title", HTMLHeadingElement),
        emptyDescription: byId("empty-description", HTMLParagraphElement), loading: byId("loading-state", HTMLDivElement),
        detailPanel: byId("detail-panel", HTMLElement), detailContent: byId("detail-content", HTMLDivElement),
        tileWarning: byId("tile-warning", HTMLDivElement), tileWarningText: byId("tile-warning-text", HTMLSpanElement),
        mapEmptyLabel: byId("map-empty-label", HTMLDivElement), viewportCount: byId("viewport-count", HTMLElement),
        clearType: byId("clear-type", HTMLButtonElement), emptyClearType: byId("empty-clear-type", HTMLButtonElement),
        searchProgress: byId("search-progress", HTMLDivElement), progressLabel: byId("search-progress-label", HTMLParagraphElement),
        cancelSearch: byId("cancel-search", HTMLButtonElement), retryPanel: byId("retry-panel", HTMLDivElement),
        retrySearch: byId("retry-search", HTMLButtonElement), serviceError: byId("service-error", HTMLDivElement),
        selectionSummary: byId("selection-summary", HTMLParagraphElement), previousResult: byId("previous-result", HTMLButtonElement),
        nextResult: byId("next-result", HTMLButtonElement), locateSelected: byId("locate-selected", HTMLButtonElement),
    };
    const state = {
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
    const initialBrowse = ArchSearchResearch.parseBrowse(initialUrl);
    const nonBoundsUrl = new URL(initialUrl);
    nonBoundsUrl.searchParams.delete("browse_bbox");
    const initialNonBoundsBrowse = ArchSearchResearch.parseBrowse(nonBoundsUrl);
    let boundsRestoreError = null;
    try {
        if (initialUrl.searchParams.getAll("browse_bbox").length > 1)
            throw new Error("链接中的 browse_bbox 参数不能重复。");
        ArchSearchResearch.parseBBox(initialUrl.searchParams.get("browse_bbox"));
    }
    catch (error) {
        boundsRestoreError = error instanceof Error ? error.message : "地图范围无效。";
    }
    let pendingLink = initialView.error || initialNonBoundsBrowse.error ? null : initialLink.request;
    let unresolvedSearchLink = pendingLink;
    let linkError = initialLink.error ?? initialView.error ?? initialNonBoundsBrowse.error;
    let invalidLink = linkError !== null;
    let pendingSelectionRestore = !invalidLink && initialView.selection.site !== null;
    let currentLink = window.location.href;
    let runtimeRefresh = null;
    let mapView = null;
    let historyView = null;
    let explore = null;
    let polarView = null;
    let selectedPhaseId = null;
    let restoringView = true;
    let autoPositionedSelection = false;
    let positioningMap = false;
    let browseRestored = false;
    let browseRestoreError = null;
    let initialStatePending = true;
    const fieldLabels = {
        title: "地点名称", names: "别名", description: "原始描述", description_zh: "中文描述／译文", source_refs: "来源资格片段", types: "地点类型",
        periods: "原始时期", details: "原始补充记录", search_text: "检索文本",
    };
    const primaryTypeLabels = {
        settlement: "聚落", villa: "别墅庄园", port: "港口", bath: "浴场", theatre: "剧场", "archaeological-site": "考古遗址", "historic-site": "历史遗址",
    };
    const confidenceLabels = {
        confident: "较有把握", "less-confident": "把握较低",
        "confident-inferred": "较有把握，基于推断、无同时代证据", "less-confident-inferred": "把握较低，基于推断、无同时代证据",
    };
    const certaintyLabels = {
        certain: "确定", "less-certain": "确定性较低", uncertain: "不确定",
    };
    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className)
            node.className = className;
        if (text !== undefined && text !== null)
            node.textContent = String(text);
        return node;
    }
    function strings(values) {
        return Array.isArray(values)
            ? values.filter((value) => typeof value === "string" && Boolean(value.trim()))
            : [];
    }
    function labelFromId(value) {
        if (typeof value !== "string")
            return "未提供";
        const tail = value.replace(/\/$/, "").split(/[\/#]/).pop() || value;
        return tail.replace(/[_-]/g, " ") || value;
    }
    function typeLabel(value) {
        return state.typeLabels.get(value) || primaryTypeLabels[value] || labelFromId(value);
    }
    function sourceLabel(value, labels) {
        if (!value)
            return "原始资料未提供";
        return labels[value] ? `${labels[value]}（${value}）` : value;
    }
    function periodLabel(value) {
        return value === "roman" ? "罗马早期帝国（roman）" : value;
    }
    function displayTitle(site) {
        return !site.title.trim() || site.title.trim().toLowerCase() === "untitled"
            ? `未命名地点 · #${site.id}` : site.title;
    }
    function hasSourceText(value) {
        return Boolean(value.trim()) && !["none", "null"].includes(value.trim().toLowerCase());
    }
    function chineseDescriptionLabel(site) {
        return site.source_refs?.some((source) => source.id === `translation:wikidata:${site.id.slice(3)}`)
            ? "中文译文（据 Wikidata 英文）" : "中文来源描述";
    }
    function sourceExcerpt(site) {
        if (site.description_zh && hasSourceText(site.description_zh))
            return { label: chineseDescriptionLabel(site), text: site.description_zh };
        if (site.description.startsWith("An ancient place, cited:") && hasSourceText(site.details)) {
            return { label: "目录补充原文", text: site.details };
        }
        if (hasSourceText(site.description))
            return { label: site.source_kind === "supplement" && site.id.startsWith("wd:") ? "Wikidata 来源描述" : "来源描述原文", text: site.description };
        if (site.source_kind === "supplement" && hasSourceText(site.details))
            return { label: "来源结构化信息", text: site.details };
        if (hasSourceText(site.details))
            return { label: "补充记录原文", text: site.details };
        return { label: "原文状态", text: "当前导出未提供描述，请打开详情核验来源记录。" };
    }
    function sourceYear(value) {
        if (value === null || !Number.isFinite(value))
            return "未提供";
        if (value === 0)
            return "原始值 0（未转换纪年）";
        return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
    }
    function currentMode() {
        const value = ui.form.querySelector('input[name="mode"]:checked')?.value;
        if (value !== "semantic" && value !== "bm25")
            throw new Error("页面检索方式无效。");
        return value;
    }
    function announce(message) {
        ui.announcement.textContent = message;
    }
    function focusWithinView(target) {
        if (target.tabIndex < 0)
            target.tabIndex = -1;
        target.focus({ preventScroll: true });
        const bounds = target.getBoundingClientRect();
        if (bounds.top < 0 || bounds.bottom > window.innerHeight) {
            target.scrollIntoView({ block: "nearest", behavior: "instant" });
        }
    }
    function showError(message) {
        ui.requestError.textContent = message;
        ui.requestError.hidden = !message;
    }
    function renderServiceError() {
        const message = [state.statusError, state.facetError].filter(Boolean).join(" ");
        ui.serviceError.textContent = message;
        ui.serviceError.hidden = !message;
    }
    function formRequest() {
        const scope = explore?.getState();
        return { query: ui.query.value.trim(), mode: currentMode(), type: ui.typeFilter.value || null,
            limit: Number(ui.limitFilter.value), country: scope?.country ?? null, region: scope?.region ?? null };
    }
    function sameRequest(left, right) {
        return left.query === right.query && left.mode === right.mode && left.type === right.type && left.limit === right.limit
            && (left.country ?? null) === (right.country ?? null) && (left.region ?? null) === (right.region ?? null);
    }
    function modeAvailable(mode) {
        return !state.restoringLink && state.corpusReady && (mode === "bm25" || state.semanticReady);
    }
    function safeLink(value, label, className) {
        try {
            if (typeof value !== "string")
                throw new Error("invalid URL");
            const url = new URL(value);
            if (url.protocol !== "https:" && url.protocol !== "http:")
                throw new Error("invalid protocol");
            const link = element("a", className, label);
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            return link;
        }
        catch {
            return element("span", "muted", `${label}（链接未提供）`);
        }
    }
    function isRecord(value) {
        return typeof value === "object" && value !== null && !Array.isArray(value);
    }
    function errorMessage(error) {
        return error instanceof Error ? error.message : typeof error === "string" ? error : "未知错误";
    }
    function isAbortError(error) {
        return error instanceof Error && error.name === "AbortError";
    }
    async function api(path, options = {}) {
        const headers = new Headers(options.headers);
        headers.set("Accept", "application/json");
        const response = await fetch(path, { ...options, headers });
        let data;
        try {
            data = await response.json();
        }
        catch (error) {
            if (isAbortError(error))
                throw error;
            throw new Error(`服务返回了无法读取的响应（HTTP ${response.status}）。`);
        }
        if (!response.ok) {
            let detail = isRecord(data) ? data.detail || data.message : undefined;
            if (Array.isArray(detail)) {
                detail = detail.map((item) => isRecord(item) && typeof item.msg === "string" ? item.msg : "请求参数无效").join("；");
            }
            if (isRecord(detail))
                detail = detail.message || detail.reason;
            throw new Error(typeof detail === "string" ? detail : `请求未完成（HTTP ${response.status}）。`);
        }
        return data;
    }
    function updateSearchAvailability() {
        const mode = currentMode();
        const available = modeAvailable(mode);
        const samePending = state.searching && state.activeSearch !== null && sameRequest(state.activeSearch, formRequest());
        ui.searchButton.disabled = !available || samePending;
        ui.buttonLabel.textContent = state.searching ? samePending ? "检索中" : "更新检索" : "开始检索";
        ui.cancelSearch.disabled = !state.searching;
        ui.cancelSearch.hidden = !state.searching;
        ui.searchProgress.hidden = !state.searching && !state.searchFeedback;
        ui.progressLabel.textContent = state.searching
            ? state.completedSearch ? "正在更新，列表与地图仍保留上次检索结果。" : "正在检索本地资料。"
            : state.searchFeedback || "";
        ui.retryPanel.hidden = state.failedSearch === null;
        ui.retrySearch.disabled = state.failedSearch === null || state.searching || !modeAvailable(state.failedSearch.mode);
        ui.retrySearch.title = state.failedSearch ? `恢复并重试：${state.failedSearch.query}` : "";
        ui.clearType.disabled = !ui.typeFilter.value || ui.typeFilter.disabled;
        ui.emptyClearType.hidden = !state.hasSearched || state.results.length > 0 || !ui.typeFilter.value || state.searching || ui.typeFilter.disabled;
        ui.activeMode.textContent = (state.displayedMode || mode) === "semantic" ? "SEMANTIC" : "BM25";
        ui.preparationNote.hidden = mode !== "semantic" || !state.statusLoaded || state.semanticReady;
        ui.modeExplanation.textContent = mode === "semantic"
            ? "用中文描述问题，专名可保留原文，在多语种源资料中寻找相近候选；排序分数不是相关概率，仍需核验来源。"
            : "匹配资料原词和已有中文描述；中文按相邻双字片段匹配，建议输入两个字以上。不会实时翻译或扩展同义词，部分片段重叠也可能命中。";
        ui.exampleHint.textContent = mode === "semantic"
            ? "中文问题示例，专名可保留原文；选择后会同步切换到对应地点类型。"
            : "英文原词示例；选择后会同步切换到对应地点类型。";
        document.querySelectorAll("[data-query-zh]").forEach((button) => {
            const query = mode === "semantic" ? button.dataset.queryZh : button.dataset.queryEn;
            const label = button.querySelector(".example-label");
            if (label)
                label.textContent = mode === "semantic" ? button.dataset.label || query || "示例" : query || "示例";
            button.disabled = !available || ui.typeFilter.disabled || !Array.from(ui.typeFilter.options).some((option) => option.value === button.dataset.type);
            button.setAttribute("aria-label", `检索示例：${query || ""}；类型：${typeLabel(button.dataset.type || "")}`);
            button.lang = mode === "semantic" ? "zh-CN" : "en";
        });
    }
    async function loadStatus() {
        ui.runtimeLabel.textContent = "检查本地服务";
        try {
            const status = await api("/api/status");
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
            state.semanticReady = status.semantic?.ready === true;
            ui.corpusCount.textContent = Number(status.corpus?.count || 0).toLocaleString("zh-CN");
            if (status.corpus?.period)
                ui.corpusPeriod.textContent = status.corpus.period;
            ui.statusDot.className = `status-dot ${state.semanticReady ? "is-ready" : "is-warning"}`;
            ui.runtimeLabel.textContent = state.semanticReady ? "本地检索已就绪" : state.corpusReady ? "关键词检索可用" : "等待资料准备";
            const reason = typeof status.semantic?.reason === "string" ? status.semantic.reason : "";
            ui.preparationReason.textContent = `${reason ? `${reason}。` : ""}请按 README 完成本地模型与索引准备，然后点击右上角刷新运行状态。`;
            state.statusError = state.corpusReady ? null : "本地资料集尚未准备。请先按 README 导入资料，再刷新运行状态。";
            announce(state.semanticReady ? "本地语义检索已就绪。" : "本地模型尚未就绪，可以选择关键词基线。");
        }
        catch (error) {
            state.statusLoaded = true;
            state.semanticReady = false;
            ui.statusDot.className = "status-dot is-warning";
            ui.runtimeLabel.textContent = "服务连接失败";
            ui.preparationReason.textContent = "无法确认本地模型状态。请检查服务是否启动，再点击右上角刷新运行状态。";
            state.statusError = `运行状态检查失败：${errorMessage(error)}`;
        }
        finally {
            renderServiceError();
            updateSearchAvailability();
        }
    }
    async function loadFacets() {
        try {
            const facets = await api("/api/facets");
            if (!Array.isArray(facets.types) || !facets.types.length)
                throw new Error("服务未返回可用的类型列表。");
            const selected = ui.typeFilter.value;
            const previousLabel = selected ? typeLabel(selected) : "";
            const labels = new Map();
            const options = [element("option", null, "全部类型")];
            options[0].value = "";
            for (const item of facets.types || []) {
                if (typeof item.id !== "string")
                    continue;
                const label = typeof item.label === "string" ? item.label : labelFromId(item.id);
                if (labels.has(item.id))
                    continue;
                labels.set(item.id, label);
                const option = element("option", null, `${label} (${Number(item.count) || 0})`);
                option.value = item.id;
                options.push(option);
            }
            if (!labels.size)
                throw new Error("类型列表无效。");
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
        }
        catch (error) {
            const retained = state.typeLabels.size > 0;
            ui.typeFilter.disabled = !retained;
            if (!retained)
                ui.typeFilter.options[0].textContent = "类型暂不可用";
            state.facetError = `类型列表加载失败：${errorMessage(error)} ${retained ? "保留已加载的类型；可再次刷新。" : "可手动检索全部类型，或点击右上角刷新重试。"}`;
        }
        finally {
            renderServiceError();
            updateSearchAvailability();
        }
    }
    function refreshRuntime() {
        if (runtimeRefresh)
            return runtimeRefresh;
        const refreshButton = byId("refresh-status", HTMLButtonElement);
        refreshButton.disabled = true;
        runtimeRefresh = Promise.allSettled([loadStatus(), loadFacets(), explore?.load()]).then(async (loaded) => {
            if (!browseRestored && !invalidLink && boundsRestoreError === null) {
                browseRestored = true;
                const explicit = ["browse_country", "browse_region", "browse_offset", "points", "browse_bbox"].some((name) => initialUrl.searchParams.has(name));
                const browse = explicit ? initialBrowse.state : { ...initialBrowse.state,
                    country: initialLink.request?.country ?? null, region: initialLink.request?.region ?? null };
                if (loaded[2].status === "rejected" && !browse.country && !browse.region && !browse.bbox && browse.offset === 0)
                    return;
                try {
                    await explore?.setState(browse);
                }
                catch (error) {
                    invalidLink = true;
                    linkError = `目录条件无法恢复：${errorMessage(error)}`;
                    browseRestoreError = linkError;
                }
            }
        }).finally(() => {
            runtimeRefresh = null;
            refreshButton.disabled = false;
        });
        return runtimeRefresh;
    }
    function sourcePoint(site) {
        const coordinate = site.repr_point;
        if (!Array.isArray(coordinate) || coordinate.length !== 2)
            return null;
        const [lon, lat] = coordinate;
        return Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90
            ? [lat, lon] : null;
    }
    function point(site) {
        return ArchSearchMapView.locationStatus(site.repr_point) === "mapped" ? sourcePoint(site) : null;
    }
    function coordinateLabel(site) {
        const coordinate = sourcePoint(site);
        if (!coordinate)
            return site.source_kind === "ats" ? "来源真实位置未知" : "当前资料无可核代表点";
        const [lat, lon] = coordinate;
        return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? "N" : "S"} / ${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? "E" : "W"}`;
    }
    function initializeMap() {
        if (typeof L === "undefined") {
            byId("map", HTMLDivElement).append(element("div", "map-unavailable", "地图组件未能加载。你仍可检索并阅读候选资料的原文与坐标。"));
            byId("fit-map", HTMLButtonElement).disabled = true;
            return;
        }
        state.map = L.map("map", { zoomControl: false, minZoom: 1, maxZoom: 18, worldCopyJump: true }).setView([20, 0], 1);
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
        state.map.on("movestart zoomstart", () => {
            if (!positioningMap)
                autoPositionedSelection = false;
        });
        state.map.on("moveend", () => {
            const marker = state.selectionMarker;
            const center = state.map?.getCenter().lng;
            if (marker && center !== undefined) {
                const location = marker.getLatLng();
                marker.setLatLng([location.lat, ArchSearchMapView.wrapLongitude(location.lng, center)]);
            }
        });
        if (typeof ResizeObserver !== "undefined") {
            new ResizeObserver(() => {
                state.map?.invalidateSize({ pan: false });
                const selected = currentSelectedSite();
                if (autoPositionedSelection && selected && !ui.detailPanel.hidden)
                    positionSelectedSite(selected);
            }).observe(byId("map", HTMLDivElement));
        }
    }
    function fitMap() {
        if (!state.map)
            return;
        autoPositionedSelection = false;
        const coordinates = state.results.map((result) => point(result.site)).filter((coordinate) => coordinate !== null);
        if (coordinates.length === 0) {
            state.map.setView([20, 0], 1);
        }
        else {
            state.map.fitBounds(L.latLngBounds(ArchSearchMapView.wrapCoordinates(coordinates)), { padding: [46, 55], maxZoom: 9, animate: false });
        }
    }
    function selectedResult() {
        return state.results.find((result) => result.site.id === state.selectedId);
    }
    function currentSelectedSite() {
        return state.selectedSite?.id === state.selectedId ? state.selectedSite : selectedResult()?.site ?? null;
    }
    function updateSelectionControls() {
        const index = state.results.findIndex((result) => result.site.id === state.selectedId);
        const selected = currentSelectedSite();
        ui.selectionSummary.textContent = selected
            ? index >= 0 ? `第 ${index + 1} / ${state.results.length} 条 · ${displayTitle(selected)}` : `全库目录 · ${displayTitle(selected)}`
            : state.results.length ? `${state.results.length} 条候选，可逐条浏览或选择地图标记。` : "选择候选，查看地图与原始资料。";
        ui.selectionSummary.title = ui.selectionSummary.textContent;
        ui.previousResult.disabled = index <= 0;
        ui.nextResult.disabled = !state.results.length || index >= state.results.length - 1;
        ui.nextResult.textContent = index < 0 ? "查看首条" : "下一条";
        const polar = selected && ArchSearchMapView.locationStatus(selected.repr_point) === "polar";
        ui.locateSelected.textContent = polar ? "查看极区位置" : "定位选中";
        ui.locateSelected.disabled = !selected || sourcePoint(selected) === null || (!state.map && !polar);
        ui.locateSelected.title = selected && sourcePoint(selected) === null ? "当前资料无可核代表点，不添加遗址地图标记。" : "";
    }
    function positionSelectedSite(site) {
        const coordinate = point(site);
        autoPositionedSelection = false;
        if (!state.map || !coordinate)
            return;
        coordinate[1] = ArchSearchMapView.wrapLongitude(coordinate[1], state.map.getCenter().lng);
        positioningMap = true;
        try {
            state.map.stop();
            state.map.invalidateSize({ pan: false });
            state.map.panTo(coordinate, { animate: false });
            if (!ui.detailPanel.hidden) {
                const mapBounds = byId("map", HTMLDivElement).getBoundingClientRect();
                const detailBounds = ui.detailPanel.getBoundingClientRect();
                const coveredWidth = Math.max(0, Math.min(mapBounds.right, detailBounds.right) - Math.max(mapBounds.left, detailBounds.left));
                if (mapBounds.width - coveredWidth >= 64)
                    state.map.panBy([coveredWidth / 2, 0], { animate: false });
            }
            autoPositionedSelection = true;
        }
        finally {
            positioningMap = false;
        }
    }
    function browseResult(direction) {
        const index = state.results.findIndex((result) => result.site.id === state.selectedId);
        const target = index < 0 ? direction === 1 ? 0 : -1 : index + direction;
        const result = state.results[target];
        if (result)
            selectSite(result.site.id);
    }
    function locateCurrentSite() {
        const site = currentSelectedSite();
        if (!site)
            return;
        if (ArchSearchMapView.locationStatus(site.repr_point) === "polar") {
            closeDetail(false);
            if (polarView?.locate(site.id))
                announce(`已在独立极区示意定位 ${displayTitle(site)}，主地图不夹取原始纬度。`);
            else
                announce("极区定位暂未就绪，已保留来源详情中的原始坐标。请刷新资料目录后重试。");
            return;
        }
        if (!state.map || !point(site))
            return;
        closeDetail(false);
        positionSelectedSite(site);
        const marker = state.markers.get(site.id) ?? state.selectionMarker;
        marker?.openTooltip();
        if (window.matchMedia("(max-width: 780px)").matches)
            byId("map", HTMLDivElement).scrollIntoView({ block: "center", behavior: "instant" });
        marker?.getElement()?.focus({ preventScroll: true });
        announce(`已在地图定位 ${displayTitle(site)}。可按 Enter 或空格重新打开详情。`);
    }
    function renderMarkers() {
        if (!state.map || !state.markerLayer)
            return;
        state.markerLayer.clearLayers();
        state.markers.clear();
        for (const [index, result] of state.results.entries()) {
            const coordinate = point(result.site);
            if (!coordinate)
                continue;
            const markerContent = element("span", "site-marker", index + 1);
            markerContent.setAttribute("aria-hidden", "true");
            const marker = L.marker(coordinate, {
                icon: L.divIcon({ className: "site-marker-icon", html: markerContent, iconSize: [30, 30], iconAnchor: [15, 15] }),
                title: displayTitle(result.site),
                keyboard: true,
                autoPanOnFocus: false,
            }).addTo(state.markerLayer);
            marker.bindTooltip(element("span", null, displayTitle(result.site)), { direction: "top", offset: [0, -13] });
            marker.on("click", () => selectSite(String(result.site.id), { fromMap: true }));
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
        ui.mapEmptyLabel.hidden = state.results.length > 0 || explore !== null;
        fitMap();
    }
    function scoreLabel(score, mode) {
        if (!Number.isFinite(score))
            return "未提供分数";
        return mode === "semantic" ? `语义分数 ${score.toFixed(3)}` : `BM25 ${score.toFixed(2)}`;
    }
    function renderResults(data, context) {
        const previousFocus = document.activeElement;
        const removedFocus = ui.list.contains(previousFocus) || ui.detailPanel.contains(previousFocus)
            || Array.from(state.markers.values()).some((marker) => marker.getElement()?.contains(previousFocus));
        const request = { query: data.query, mode: data.mode, ...context };
        const link = ArchSearchResearch.buildLink(new URL(window.location.href), request);
        closeDetail(false);
        state.results = Array.isArray(data.results) ? data.results : [];
        state.selectedId = null;
        state.selectedSite = null;
        state.selectionMarker?.remove();
        state.selectionMarker = null;
        explore?.select(null);
        polarView?.select(null);
        selectedPhaseId = null;
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
        ui.resultContext.textContent = `本次查询：“${data.query}” · ${data.mode === "semantic" ? "语义检索" : "关键词基线"} · ${context.type ? typeLabel(context.type) : "全部类型"}${context.country ? ` · 国家／地区 ${context.country}` : ""}${context.region ? ` · 来源分区 ${context.region}` : ""} · 最多 ${context.limit} 条 · 语料 ${data.corpus_version}`;
        ui.resultContext.hidden = false;
        ui.empty.hidden = state.results.length > 0;
        if (state.results.length === 0) {
            ui.emptyTitle.textContent = "没有找到候选资料";
            ui.emptyDescription.textContent = data.mode === "bm25"
                ? "尝试英文关键词或古地名，放宽类型筛选；也可切换语义检索使用中文研究问题。"
                : "尝试调整问题或放宽类型筛选。当前语料为地中海罗马资料与全球历史遗址的策展样本。";
        }
        const viewCandidates = [];
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
            description.lang = excerpt.label === "原文状态" || excerpt.label.startsWith("中文") ? "zh-CN" : "en";
            const metadata = element("div", "result-metadata");
            metadata.append(element("span", "result-coordinate", coordinateLabel(site)), element("span", "result-score", scoreLabel(result.score, data.mode)));
            const viewHint = element("span", "result-view-hint");
            viewHint.hidden = true;
            card.append(top, element("p", "result-excerpt-label", excerpt.label), description, metadata, viewHint);
            card.addEventListener("click", () => selectSite(String(site.id)));
            item.append(card);
            ui.list.append(item);
            viewCandidates.push({ id: String(site.id), rank: index + 1, title: displayTitle(site), card, marker: null,
                hint: viewHint, locationStatus: ArchSearchMapView.locationStatus(site.repr_point) });
        }
        renderMarkers();
        for (const candidate of viewCandidates)
            candidate.marker = state.markers.get(candidate.id) || null;
        mapView?.setCandidates(viewCandidates);
        updateSelectionControls();
        state.completedSearch = { request, response: data, link };
        if (unresolvedSearchLink && sameRequest(unresolvedSearchLink, request))
            unresolvedSearchLink = null;
        saveViewLink();
        ui.resultTools.hidden = false;
        ui.copyLink.disabled = boundsRestoreError !== null;
        ui.exportResults.disabled = boundsRestoreError !== null;
        ui.toolsFeedback.textContent = "";
        ui.shareLinkPanel.hidden = true;
        ui.shareLink.value = boundsRestoreError !== null ? currentLink : state.completedSearch.link;
        if (boundsRestoreError !== null)
            ui.toolsFeedback.textContent = "地图范围恢复失败；先明确清除或重新捕获范围，再复制或导出研究视图。";
        if (removedFocus || (previousFocus instanceof HTMLButtonElement && previousFocus.disabled
            && [ui.previousResult, ui.nextResult, ui.locateSelected].includes(previousFocus))) {
            focusWithinView(ui.resultSummary);
        }
        announce(`检索完成，返回 ${state.results.length} 条候选资料。${data.mode === "semantic" ? "相似度分数并非相关概率，请核验来源。" : ""}`);
    }
    async function copySearchLink() {
        if (boundsRestoreError !== null) {
            ui.toolsFeedback.textContent = "地图范围尚未恢复；先明确清除或重新捕获范围，再复制或导出研究视图。原链接仍保留在地址栏。";
            return;
        }
        saveViewLink();
        const copiedLink = currentLink;
        try {
            if (!navigator.clipboard?.writeText)
                throw new Error("Clipboard unavailable");
            await navigator.clipboard.writeText(copiedLink);
            if (currentLink !== copiedLink)
                return;
            ui.shareLinkPanel.hidden = true;
            ui.toolsFeedback.textContent = "已复制研究视图链接。复查时需要能访问同一服务。";
        }
        catch {
            if (currentLink !== copiedLink)
                return;
            ui.shareLink.value = copiedLink;
            ui.shareLinkPanel.hidden = false;
            ui.toolsFeedback.textContent = "未能自动复制。链接已选中，可按 Ctrl+C 或 Command+C 手动复制。";
            ui.shareLink.focus();
            ui.shareLink.select();
        }
    }
    function exportSearchResults() {
        const completed = state.completedSearch;
        if (!completed)
            return;
        if (boundsRestoreError !== null) {
            ui.toolsFeedback.textContent = "地图范围尚未恢复；先明确清除或重新捕获范围，再复制或导出研究视图。";
            return;
        }
        if (state.selectedId && !currentSelectedSite()) {
            ui.toolsFeedback.textContent = "请等待选中遗址资料读取完成，再导出完整来源附录。";
            return;
        }
        let objectUrl = null;
        const download = element("a");
        try {
            const exportedAt = new Date().toISOString();
            const report = ArchSearchResearch.createExport(completed.request, completed.response, exportedAt, historyView?.getView() ?? null, { site: state.selectedId, phase: selectedPhaseId }, currentSelectedSite(), explore?.getCommittedState() ?? null, { metadata: explore?.getSpatialMetadata() ?? null, selected: state.selectedSite ? {
                    site_id: state.selectedSite.id, representative_point: state.selectedSite.repr_point,
                    source_points: explore?.getSourcePoints(state.selectedSite.id) ?? [],
                    records: explore?.getSourceLocationRecords(state.selectedSite.id) ?? [],
                } : null });
            objectUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" }));
            download.href = objectUrl;
            download.download = `archsearch-${completed.request.mode}-${exportedAt.replace(/[:.]/g, "-")}.json`;
            download.hidden = true;
            document.body.append(download);
            download.click();
            ui.toolsFeedback.textContent = `已生成 ${completed.response.results.length} 条结果的 JSON 文件，包含原文、检索条件、分数与来源。`;
        }
        catch {
            ui.toolsFeedback.textContent = "结果文件未能生成，请重试或检查浏览器的下载设置。";
        }
        finally {
            download.remove();
            if (objectUrl !== null) {
                const disposableUrl = objectUrl;
                window.setTimeout(() => URL.revokeObjectURL(disposableUrl), 1000);
            }
        }
    }
    function cancelLinkRestore() {
        pendingLink = null;
        unresolvedSearchLink = null;
        linkError = null;
        browseRestoreError = null;
        invalidLink = false;
        pendingSelectionRestore = false;
        state.restoringLink = false;
        updateSearchAvailability();
    }
    async function finishLinkRestore() {
        const request = pendingLink;
        pendingLink = null;
        state.restoringLink = false;
        if (linkError) {
            showError(`分享链接未能恢复：${linkError}`);
            linkError = null;
            if (browseRestoreError && !request && pendingSelectionRestore && initialView.selection.site) {
                await selectSite(initialView.selection.site, {
                    phaseId: initialView.selection.phase,
                    preserveYear: initialView.view !== null || (historyView?.actionVersion() ?? 0) > 0,
                    restoring: true,
                });
            }
            pendingSelectionRestore = false;
            updateSearchAvailability();
            return;
        }
        if (!request) {
            updateSearchAvailability();
            if (pendingSelectionRestore && initialView.selection.site)
                await selectSite(initialView.selection.site, {
                    phaseId: initialView.selection.phase,
                    preserveYear: initialView.view !== null || (historyView?.actionVersion() ?? 0) > 0,
                    restoring: true,
                });
            pendingSelectionRestore = false;
            saveViewLink();
            return;
        }
        if (request.type && (ui.typeFilter.disabled || !Array.from(ui.typeFilter.options).some((option) => option.value === request.type))) {
            showError("链接中的地点类型无法确认。请检查类型是否有效，或重新选择后手动检索；本次未自动扩大检索范围。");
            updateSearchAvailability();
            return;
        }
        ui.typeFilter.value = request.type || "";
        updateSearchAvailability();
        if (!state.corpusReady || (request.mode === "semantic" && !state.semanticReady)) {
            showError("链接中的检索条件已恢复；当前服务或所选模型尚未就绪。请查看运行状态，准备后手动检索。");
            return;
        }
        const actionVersion = historyView?.actionVersion() ?? 0;
        await runSearch(request);
        if (pendingSelectionRestore && initialView.selection.site && state.completedSearch && sameRequest(state.completedSearch.request, request)
            && (historyView?.actionVersion() ?? 0) === actionVersion) {
            await selectSite(initialView.selection.site, {
                phaseId: initialView.selection.phase,
                preserveYear: initialView.view !== null || (historyView?.actionVersion() ?? 0) > 0,
                restoring: true,
            });
        }
        pendingSelectionRestore = false;
        saveViewLink();
    }
    function setLoading(value) {
        const focusWasInProgress = !value && ui.searchProgress.contains(document.activeElement);
        state.searching = value;
        ui.resultsPanel.setAttribute("aria-busy", String(value));
        ui.form.classList.toggle("is-searching", value);
        ui.loading.hidden = !value || state.results.length > 0;
        if (value && state.results.length === 0)
            ui.empty.hidden = true;
        if (!value)
            ui.empty.hidden = state.results.length > 0;
        updateSearchAvailability();
        if (focusWasInProgress) {
            if (!ui.searchProgress.hidden) {
                focusWithinView(ui.progressLabel);
            }
            else if (state.failedSearch) {
                if (!ui.retrySearch.disabled)
                    focusWithinView(ui.retrySearch);
                else
                    focusWithinView(ui.requestError);
            }
            else {
                focusWithinView(ui.resultSummary);
            }
        }
    }
    async function search(event) {
        if (event)
            event.preventDefault();
        cancelLinkRestore();
        const request = formRequest();
        if (!request.query) {
            if (state.searching)
                cancelCurrentSearch();
            ui.query.focus();
            return;
        }
        await runSearch(request);
    }
    function invalidateSearch() {
        ++state.searchSequence;
        state.searchController?.abort();
        state.searchController = null;
        state.activeSearch = null;
    }
    function cancelCurrentSearch() {
        if (!state.searching)
            return;
        invalidateSearch();
        state.failedSearch = null;
        state.searchFeedback = state.completedSearch ? "已取消本次检索，保留上次结果与地图。" : "已取消本次检索，可调整问题后重新提交。";
        showError("");
        if (!state.completedSearch) {
            ui.emptyTitle.textContent = "本次检索已取消";
            ui.emptyDescription.textContent = "调整研究问题后可重新检索；取消只停止等待，不会清除已有资料。";
        }
        setLoading(false);
        announce(state.searchFeedback);
    }
    async function runSearch(request) {
        if (state.searching && state.activeSearch && sameRequest(state.activeSearch, request))
            return;
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
        announce("正在检索本地资料。");
        try {
            const data = await api("/api/search", {
                method: "POST", signal: controller.signal,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(request),
            });
            if (sequence !== state.searchSequence)
                return;
            renderResults(data, { type: request.type, limit: request.limit, country: request.country, region: request.region });
        }
        catch (error) {
            if (isAbortError(error) || sequence !== state.searchSequence)
                return;
            state.failedSearch = { ...request };
            const retained = state.completedSearch ? "已保留上次结果与地图。" : "请检查本地服务后重试。";
            showError(`本次检索未完成：${errorMessage(error)} ${retained}`);
            announce("本次检索失败，请查看错误说明。");
            if (!state.completedSearch) {
                ui.emptyTitle.textContent = "本次检索未完成";
                ui.emptyDescription.textContent = "上方保留了错误说明。检查本地模型与服务后，可以重试或选择关键词基线。";
            }
        }
        finally {
            if (sequence === state.searchSequence) {
                state.searchController = null;
                state.activeSearch = null;
                setLoading(false);
            }
        }
    }
    function retryFailedSearch() {
        const request = state.failedSearch;
        if (!request || state.searching)
            return;
        if (request.type && !state.typeLabels.has(request.type)) {
            showError("上次失败请求的类型已不可用，未放宽原条件。请刷新类型或重新选择后检索。");
            return;
        }
        ui.query.value = request.query;
        ui.typeFilter.value = request.type || "";
        ui.limitFilter.value = String(request.limit);
        ui.form.querySelectorAll('input[name="mode"]').forEach((radio) => { radio.checked = radio.value === request.mode; });
        void runSearch(request);
    }
    function clearTypeFilter() {
        const returnFocus = document.activeElement === ui.clearType || document.activeElement === ui.emptyClearType;
        ui.typeFilter.value = "";
        applyChangedFilter();
        if (returnFocus) {
            if (!ui.searchProgress.hidden) {
                focusWithinView(ui.progressLabel);
            }
            else
                focusWithinView(ui.query);
        }
    }
    function detailSection(title, content) {
        const section = element("section", "detail-section");
        section.append(element("h4", null, title));
        if (typeof content === "string")
            section.append(element("p", null, content));
        else
            section.append(content);
        return section;
    }
    function fact(label, value) {
        const row = element("div", "detail-fact");
        row.append(element("dt", null, label), element("dd", null, value));
        return row;
    }
    function evidenceList(evidence) {
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
    function saveViewLink() {
        if (initialStatePending || invalidLink || boundsRestoreError !== null || pendingSelectionRestore || unresolvedSearchLink)
            return;
        const link = ArchSearchResearch.buildLink(new URL(window.location.href), state.completedSearch?.request ?? null, historyView?.getView() ?? null, { site: state.selectedId, phase: selectedPhaseId }, explore?.getCommittedState() ?? null);
        currentLink = link;
        if (state.completedSearch && state.completedSearch.link !== link)
            state.completedSearch = { ...state.completedSearch, link };
        ui.shareLink.value = link;
        ui.resultTools.hidden = !state.completedSearch && !state.selectedSite && historyView?.getView() == null
            && explore?.getCommittedState() == null;
        ui.copyLink.disabled = false;
        ui.exportResults.disabled = state.completedSearch === null || (state.selectedId !== null && currentSelectedSite() === null);
        try {
            window.history.replaceState(null, "", link);
        }
        catch { /* Copy remains available. */ }
    }
    function phaseContent(site) {
        const review = site.chronology;
        const content = element("div", "chronology-content");
        if (!review) {
            content.append(element("p", null, "当前资料尚无断代核验记录。"));
            return content;
        }
        const reviewLabel = {
            reviewed: "已有来源支持的阶段", insufficient: "已核验，断代未确定", not_reviewed: "断代尚未核验",
        };
        content.append(element("p", "detail-note", `${reviewLabel[review.status]}${review.reviewed_at ? ` · ${review.reviewed_at}` : ""}`));
        content.append(element("p", null, review.note));
        const audit = element("details");
        audit.append(element("summary", null, "查看核验方式"), element("p", "detail-note", review.method));
        content.append(audit);
        if (!review.phases.length)
            return content;
        const label = element("label", "phase-label", "历史阶段");
        label.htmlFor = "site-phase";
        const select = element("select", "phase-select");
        select.id = "site-phase";
        const kinds = { construction: "建造", use: "使用", rebuild: "改建", destruction: "毁损", other: "其他事件" };
        for (const phase of review.phases) {
            const option = element("option", null, `${kinds[phase.kind]} · ${phase.label}`);
            option.value = phase.id;
            select.append(option);
        }
        const phase = review.phases.find((item) => item.id === selectedPhaseId) ?? review.phases.find((item) => item.id === review.default_phase_id);
        if (!phase) {
            content.append(element("p", null, "默认阶段缺失，请核对语料；地图年份保持原样。"));
            return content;
        }
        select.value = phase.id;
        const precision = { exact_year: "明确单年", approximate_year: "约略年份", range: "区间年代", period: "时期描述" };
        const dates = phase.start_year === null && phase.end_year === null ? "来源未给出可换算的年份" : phase.start_year === phase.end_year
            ? sourceYear(phase.start_year) : `${sourceYear(phase.start_year)} — ${sourceYear(phase.end_year)}`;
        content.append(label, select, element("p", "phase-dates", `${precision[phase.precision]} · ${dates}`));
        if (phase.note)
            content.append(element("p", "detail-note", phase.note));
        content.append(element("p", "detail-note", "阶段属于所列事件；不补齐时期缺口，不按代表点认定历史政治归属。"));
        if (phase.precision !== "exact_year") {
            content.append(element("p", null, "此阶段不自动切换地图。请结合原文选择要观察的年份。"));
            const yearLabel = element("label", "phase-label", "观察年份（负数表示公元前）");
            yearLabel.htmlFor = "phase-year";
            const input = element("input", "phase-year");
            input.id = "phase-year";
            input.type = "number";
            input.step = "1";
            if (phase.start_year !== null)
                input.min = String(phase.start_year);
            if (phase.end_year !== null)
                input.max = String(phase.end_year);
            const current = historyView?.getView()?.year;
            input.value = current !== undefined && (phase.start_year === null || current >= phase.start_year) && (phase.end_year === null || current <= phase.end_year)
                ? String(current) : phase.start_year !== null ? String(phase.start_year) : "";
            const jump = element("button", "interaction-button", "按此年份查看");
            jump.type = "button";
            const feedback = element("p", "detail-note");
            feedback.setAttribute("role", "status");
            const applyYear = () => {
                const year = Number(input.value);
                if (!input.value.trim() || !ArchSearchResearch.validYear(year)
                    || (phase.start_year !== null && year < phase.start_year) || (phase.end_year !== null && year > phase.end_year)) {
                    feedback.textContent = "请输入阶段范围内的整数年份，历史纪年没有0年。";
                    return;
                }
                feedback.textContent = year < -3400 || year > 2024 ? "该年份无可用疆域数据；保留最后成功地图。" : "正在切换历史地图。";
                historyView?.setYear(year, "user");
            };
            jump.addEventListener("click", applyYear);
            input.addEventListener("keydown", (event) => { if (event.key === "Enter") {
                event.preventDefault();
                applyYear();
            } });
            content.append(yearLabel, input, jump, feedback);
        }
        else {
            content.append(element("p", "detail-note", "明确单年阶段在主动选择时切换地图；之后可独立调整地图年份。"));
        }
        for (const source of phase.sources) {
            const evidence = element("blockquote", "phase-evidence", source.excerpt);
            evidence.lang = "en";
            content.append(evidence, safeLink(source.uri, source.title), element("p", "detail-note", `${source.publisher} · ${source.license ?? "许可见原始来源"} · ${source.revision ?? "版本未提供"}`));
        }
        select.addEventListener("change", () => {
            selectedPhaseId = select.value;
            renderDetail(site, selectedResult()?.matched_fields ?? []);
            const selected = review.phases.find((item) => item.id === selectedPhaseId);
            if (selected)
                followPhase(selected);
            ui.detailContent.querySelector("#site-phase")?.focus({ preventScroll: true });
            saveViewLink();
        });
        return content;
    }
    function followPhase(phase) {
        const year = ArchSearchResearch.automaticPhaseYear(phase);
        if (year !== null)
            historyView?.setYear(year, "site");
    }
    function sourceLocationsSection(site) {
        const points = explore?.getSourcePoints(site.id) ?? [];
        const metadata = explore?.getSpatialMetadata();
        if (!points.length) {
            if (!metadata || !site.geography?.authority_id || !/^[1-9]\d*$/u.test(site.geography.authority_id))
                return null;
            const section = detailSection("来源组成定位记录", metadata.ready
                ? "固定名录未提供源定位记录；原代表点来自独立证据，不插入DataHub源数组。"
                : "源定位数据尚未就绪，当前保留原代表点，不补造源点。请按全库定位状态的准备指引修复。");
            section.id = "site-source-locations";
            return section;
        }
        const records = explore?.getSourceLocationRecords(site.id) ?? [];
        const section = detailSection("来源组成定位记录", `${points.length} 条来源记录。它们属于同一遗产条目，不作为新增遗址计数，也不表示已逐点独立核验。`);
        section.id = "site-source-locations";
        section.append(element("p", "detail-note", "原代表点保持不变；全库点层另展示源定位记录，同一遗产的重合圆点可合并显示。名称与编号仅为来源标签，不作为唯一身份或精确发掘位置。"));
        const details = element("details", "evidence-more");
        details.append(element("summary", null, "查看完整原始顺序、名称与坐标"));
        const list = element("ol", "source-location-list");
        list.tabIndex = 0;
        list.setAttribute("aria-label", "按原始顺序排列的来源定位记录，可滚动阅读");
        for (const [index, point] of points.entries()) {
            const record = records[index];
            const row = element("li", "evidence-item");
            row.dataset.sourceIndex = String(index);
            row.append(element("p", null, record?.name || `来源定位记录 ${index + 1}`));
            const [longitude, latitude] = point;
            row.append(element("p", "detail-note", `原序号 ${index + 1}${record?.ref ? ` · 来源编号 ${record.ref}` : ""} · WGS84 [${longitude}, ${latitude}]`));
            list.append(row);
        }
        details.append(list);
        section.append(details);
        if (metadata?.source)
            section.append(safeLink(metadata.source.uri, `${metadata.source.name} · ${metadata.source.license}`));
        return section;
    }
    function renderDetail(site, matchedFields = []) {
        const focusWasInContent = ui.detailContent.contains(document.activeElement);
        const title = element("h3", null, displayTitle(site));
        title.id = "detail-title";
        const sourceId = element("p", "detail-id", `${{ pleiades: "PLEIADES", global: "CURATED", unesco: "UNESCO DATAHUB", ats: "ATS HSM", supplement: "CULTURAL SUPPLEMENT" }[site.source_kind] ?? "SOURCE"} / ${site.id}`);
        const description = element("p", "detail-description", hasSourceText(site.description) ? site.description : "当前导出未提供描述。");
        description.lang = hasSourceText(site.description) ? "en" : "zh-CN";
        const nodes = [title, sourceId];
        if (displayTitle(site) !== site.title) {
            nodes.push(element("p", "detail-source-title", `来源标题原文：${site.title || "未提供"}`));
        }
        nodes.push(element("p", "detail-note", "来源原文保留原语言；未生成历史摘要。"), description);
        if (site.description_zh && hasSourceText(site.description_zh)) {
            const chinese = element("p", "detail-description", site.description_zh);
            chinese.lang = "zh-CN";
            nodes.push(detailSection(chineseDescriptionLabel(site), chinese));
        }
        nodes.push(detailSection("年代证据与地图联动", phaseContent(site)));
        const details = element("p", null, hasSourceText(site.details)
            ? site.details : `当前导出未提供补充内容${site.details.trim() ? `（原始值：${site.details}）` : ""}。`);
        if (hasSourceText(site.details))
            details.lang = "en";
        nodes.push(detailSection(site.source_kind === "supplement" ? "来源结构化信息与范围说明" : "原始补充记录", details));
        nodes.push(detailSection("名称与别名", strings(site.names).join(" · ") || "原始资料未提供其他名称。"));
        nodes.push(detailSection("来源类型标签", strings(site.types).map((value) => primaryTypeLabels[value]
            ? `${typeLabel(value)}（${value}）` : value).join(" · ") || "原始资料未提供类型。"));
        const periods = detailSection("原始时期标签", strings(site.periods).map(periodLabel).join(" · ") || "原始资料未提供时期标签。");
        periods.append(element("p", "detail-note", "标签来自名称或位置记录；多个时期标签不能证明地点持续使用，也不能直接视为建造年代。"));
        nodes.push(periods);
        const facts = element("dl");
        facts.append(fact("代表点", coordinateLabel(site)), fact(site.source_kind === "pleiades" ? "原始精度" : "定位精度分类", sourceLabel(site.location_precision, { precise: "精确", rough: "概略" })));
        const space = detailSection("空间信息 · WGS84", facts);
        space.append(element("p", "detail-note", "精度按来源标签展示，不承诺米级误差；代表点不等同于实测发掘坐标。"));
        const positionStatus = ArchSearchMapView.locationStatus(site.repr_point);
        if (positionStatus === "polar") {
            space.append(element("p", "detail-note", "原坐标超出主地图Web Mercator投影范围；主地图不夹取纬度，请使用“查看极区位置”。极区定位为独立现代自然地理示意。"));
        }
        else if (positionStatus === "unknown") {
            space.append(element("p", "detail-note", site.source_kind === "supplement"
                ? "文化对象身份已核对，但本记录尚未取得可信公开数字坐标；不以近邻、行政中心或零坐标替代，不绘制遗址标记。"
                : "来源未给出已知的遗址真实位置，不绘制遗址标记；如有最后目击参照，仅保留在来源说明中。"));
        }
        if (site.location_precision === "rough") {
            space.append(element("p", "detail-note", "rough 表示应在某个范围内寻找地点；代表点可能只是该范围的中心。"));
        }
        nodes.push(space);
        const sourceLocations = sourceLocationsSection(site);
        if (sourceLocations)
            nodes.push(sourceLocations);
        if (site.geography) {
            const geography = site.geography;
            const scope = detailSection("来源名录中的国家／地区与分区", `国家／地区：${site.source_kind === "ats" ? "不作主权归属标注" : geography.countries.join(" · ") || "来源未明确"}；分区：${geography.regions.map((region) => region === "antarctica" ? "南极洲（独立区域分类）" : region).join(" · ") || "来源未提供"}。`);
            scope.append(element("p", "detail-note", geography.note), element("p", "detail-note", `名录可用定位点记录：${geography.point_count}。${geography.point_count ? "可定位时只展示一个代表点，不表示全部组成地点。" : "没有可用真实定位点，不绘制遗址标记。"}此处是来源名录标签，不代表历史政治归属。`), safeLink(geography.source.uri, geography.source.title));
            nodes.push(scope);
        }
        const fields = strings(matchedFields).map((field) => fieldLabels[field] || field);
        if (state.results.some((result) => result.site.id === site.id)) {
            const matches = detailSection("字词片段匹配字段", fields.join(" · ") || "未发现查询与检索字段的字词片段重叠。");
            matches.append(element("p", "detail-note", "仅展示成功检索的字词重叠，不解释语义模型的排序依据；中文问题仍可能检索到英文候选。"));
            nodes.push(matches);
        }
        else
            nodes.push(detailSection("选择方式", "从全库目录直接选择；此处没有附加检索分数或排名，不将目录选择解释为查询命中。"));
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
        }
        else {
            nodes.push(detailSection("时期证据与来源", "原始资料未提供可展示的时期证据。"));
        }
        nodes.push(detailSection("资料贡献者", strings(site.contributors).join(" · ") || "当前导出未提供贡献者信息，请在原始来源中核验。"));
        const sources = element("div");
        for (const source of site.source_refs ?? []) {
            sources.append(safeLink(source.uri, source.title), element("p", "detail-note", `${source.publisher} · ${source.license ?? "许可见原始来源"} · ${source.revision ?? "版本未提供"}`));
            if (site.source_kind === "supplement" && source.excerpt.trim()) {
                sources.append(element("p", "detail-source-excerpt", source.excerpt));
            }
        }
        sources.append(element("p", "detail-note", "引用时保留地点编号、原始链接、版本与贡献者；不同来源遵循各自许可。"));
        nodes.push(detailSection("来源与许可", sources));
        nodes.push(safeLink(site.source_uri, "查看原始资料 ↗", "detail-source-link"));
        ui.detailContent.replaceChildren(...nodes);
        if (focusWasInContent && !ui.detailPanel.hidden)
            ui.detailPanel.focus({ preventScroll: true });
    }
    function markSelection(id) {
        for (const card of Array.from(ui.list.querySelectorAll(".result-card"))) {
            const selected = card.dataset.siteId === id;
            card.classList.toggle("is-selected", selected);
            card.setAttribute("aria-pressed", String(selected));
            if (selected) {
                const listBounds = ui.list.getBoundingClientRect();
                const cardBounds = card.getBoundingClientRect();
                if (cardBounds.top < listBounds.top)
                    ui.list.scrollTop -= listBounds.top - cardBounds.top;
                else if (cardBounds.bottom > listBounds.bottom)
                    ui.list.scrollTop += cardBounds.bottom - listBounds.bottom;
            }
        }
        for (const [markerId, marker] of state.markers) {
            const selected = markerId === id;
            marker.getElement()?.classList.toggle("is-selected", selected);
            marker.getElement()?.setAttribute("aria-pressed", String(selected));
            marker.setZIndexOffset(selected ? 1000 : 0);
        }
        explore?.select(id);
        polarView?.select(id);
    }
    function presentSelection(site, matchedFields, fresh, moveMap = true) {
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
            marker.on("click", () => { void selectSite(site.id, { opener: marker.getElement() ?? null }); });
            const icon = marker.getElement();
            if (markerOpenedDetail)
                state.detailOpener = icon ?? null;
            icon?.setAttribute("aria-label", `全库选中：${displayTitle(site)}，打开资料详情`);
            icon?.addEventListener("keydown", (event) => {
                if (event.key === " " || event.key === "Enter") {
                    event.preventDefault();
                    event.stopPropagation();
                    marker.fire("click");
                }
            });
            state.selectionMarker = marker;
        }
        renderDetail(site, matchedFields);
        if (site.source_kind === "ats")
            polarView?.ensureSite({
                id: site.id, title: displayTitle(site), repr_point: site.repr_point,
                location_status: ArchSearchMapView.locationStatus(site.repr_point),
                regions: site.geography?.regions ?? [], source_kind: site.source_kind,
            });
        polarView?.select(site.id);
        updateSelectionControls();
        if (fresh) {
            ui.detailPanel.scrollTop = 0;
            ui.detailPanel.focus({ preventScroll: true });
            if (moveMap)
                positionSelectedSite(site);
            else
                autoPositionedSelection = false;
            if (window.matchMedia("(max-width: 780px)").matches)
                ui.detailPanel.scrollIntoView({ block: "start", behavior: "instant" });
            const rank = state.results.findIndex((item) => item.site.id === site.id);
            announce(`${rank < 0 ? "已选择全库目录地点" : `已选择第 ${rank + 1} / ${state.results.length} 条`}：${displayTitle(site)}，原始资料详情已展开。`);
        }
        saveViewLink();
    }
    async function selectSite(id, { fromMap = false, preserveYear = false, phaseId = null, opener = null, restoring = false, moveMap = true, } = {}) {
        if (!restoring)
            cancelLinkRestore();
        const result = state.results.find((item) => item.site.id === id);
        const known = result?.site ?? (state.selectedSite?.id === id ? state.selectedSite : null);
        state.detailOpener = opener ?? (fromMap
            ? state.markers.get(id)?.getElement() ?? null
            : Array.from(ui.list.querySelectorAll(".result-card")).find((card) => card.dataset.siteId === id) ?? null);
        state.detailController?.abort();
        const controller = new AbortController();
        state.detailController = controller;
        const userVersion = historyView?.actionVersion() ?? 0;
        state.selectedId = id;
        state.selectedSite = known;
        ui.exportResults.disabled = boundsRestoreError !== null || state.completedSearch === null || known === null;
        selectedPhaseId = null;
        markSelection(id);
        ui.detailPanel.hidden = false;
        let initialPhase;
        const choosePhase = (site) => {
            const phases = site.chronology?.phases ?? [];
            if (phaseId !== null && !phases.some((phase) => phase.id === phaseId)) {
                showError("链接中的阶段已失效；现展示遗址默认阶段，保留地图年份，请核对语料版本。");
                preserveYear = true;
            }
            selectedPhaseId = phases.some((phase) => phase.id === phaseId) ? phaseId : site.chronology?.default_phase_id ?? null;
            initialPhase = phases.find((phase) => phase.id === selectedPhaseId);
            if (initialPhase && !preserveYear && (historyView?.actionVersion() ?? 0) === userVersion)
                followPhase(initialPhase);
        };
        if (known) {
            choosePhase(known);
            presentSelection(known, result?.matched_fields ?? [], true, moveMap);
        }
        else {
            state.selectionMarker?.remove();
            state.selectionMarker = null;
            ui.detailContent.replaceChildren(element("h3", null, "正在读取来源资料"), element("p", "detail-note", id));
            ui.detailPanel.focus({ preventScroll: true });
            updateSelectionControls();
        }
        const phaseAtRequest = selectedPhaseId;
        try {
            const site = await api(`/api/sites/${encodeURIComponent(id)}`, { signal: controller.signal });
            if (state.detailController !== controller || state.selectedId !== id || controller.signal.aborted)
                return;
            if (!known || JSON.stringify(site) !== JSON.stringify(known)) {
                if (!known)
                    choosePhase(site);
                else if (selectedPhaseId === phaseAtRequest) {
                    selectedPhaseId = site.chronology?.phases.some((phase) => phase.id === selectedPhaseId) ? selectedPhaseId : site.chronology?.default_phase_id ?? null;
                    const phase = site.chronology?.phases.find((item) => item.id === selectedPhaseId);
                    if (!initialPhase && phase && !preserveYear && (historyView?.actionVersion() ?? 0) === userVersion)
                        followPhase(phase);
                }
                presentSelection(site, result?.matched_fields ?? [], !known, moveMap);
            }
        }
        catch (error) {
            if (isAbortError(error) || controller.signal.aborted || state.detailController !== controller || state.selectedId !== id)
                return;
            if (known)
                ui.detailContent.append(element("p", "detail-loading", "详情刷新失败，当前显示检索时返回的原始资料。"));
            else {
                state.selectedId = null;
                state.selectedSite = null;
                selectedPhaseId = null;
                explore?.select(null);
                polarView?.select(null);
                ui.detailContent.replaceChildren(element("h3", null, "资料未能读取"), element("p", "detail-note", errorMessage(error)));
                showError(`遗址资料未能恢复：${errorMessage(error)}。地图与检索快照保持不变。`);
                if (restoring) {
                    invalidLink = true;
                    browseRestoreError = null;
                }
                updateSelectionControls();
                saveViewLink();
            }
        }
        finally {
            if (state.detailController === controller && restoring) {
                pendingSelectionRestore = false;
                saveViewLink();
            }
        }
    }
    function closeDetail(returnFocus = true) {
        state.detailController?.abort();
        ui.detailPanel.hidden = true;
        if (state.selectedId && !currentSelectedSite()) {
            state.selectedId = null;
            selectedPhaseId = null;
            pendingSelectionRestore = false;
            explore?.select(null);
            polarView?.select(null);
            updateSelectionControls();
            saveViewLink();
        }
        if (returnFocus) {
            const opener = state.detailOpener;
            if (opener?.isConnected && opener.getClientRects().length > 0 && !opener.closest("details:not([open])")) {
                opener.focus({ preventScroll: true });
                if (window.matchMedia("(max-width: 780px)").matches)
                    opener.scrollIntoView({ block: "nearest", behavior: "instant" });
            }
            else
                focusWithinView(ui.selectionSummary);
        }
        state.detailOpener = null;
    }
    function applyChangedFilter() {
        cancelLinkRestore();
        updateSearchAvailability();
        if (!ui.query.value.trim() && state.searching)
            cancelCurrentSearch();
        else if ((state.hasSearched || state.searching) && ui.query.value.trim())
            search();
    }
    ui.form.addEventListener("submit", search);
    ui.form.addEventListener("input", (event) => {
        cancelLinkRestore();
        if (event.target === ui.query && !ui.query.value.trim() && state.searching)
            cancelCurrentSearch();
    });
    ui.form.querySelectorAll('input[name="mode"]').forEach((radio) => radio.addEventListener("change", applyChangedFilter));
    ui.typeFilter.addEventListener("change", applyChangedFilter);
    ui.limitFilter.addEventListener("change", applyChangedFilter);
    document.querySelectorAll("[data-query-zh]").forEach((button) => {
        button.addEventListener("click", () => {
            ui.query.value = (currentMode() === "semantic" ? button.dataset.queryZh : button.dataset.queryEn) || "";
            const type = button.dataset.type || "";
            ui.typeFilter.value = Array.from(ui.typeFilter.options).some((option) => option.value === type) ? type : "";
            ui.query.focus();
            search();
        });
    });
    byId("refresh-status", HTMLButtonElement).addEventListener("click", refreshRuntime);
    byId("fit-map", HTMLButtonElement).addEventListener("click", () => { closeDetail(false); fitMap(); });
    byId("retry-tiles", HTMLButtonElement).addEventListener("click", () => {
        ui.tileWarning.hidden = true;
        state.tiles?.redraw();
    });
    byId("close-detail", HTMLButtonElement).addEventListener("click", () => closeDetail());
    ui.copyLink.addEventListener("click", copySearchLink);
    ui.exportResults.addEventListener("click", exportSearchResults);
    ui.clearType.addEventListener("click", clearTypeFilter);
    ui.emptyClearType.addEventListener("click", clearTypeFilter);
    ui.cancelSearch.addEventListener("click", cancelCurrentSearch);
    ui.retrySearch.addEventListener("click", retryFailedSearch);
    ui.previousResult.addEventListener("click", () => browseResult(-1));
    ui.nextResult.addEventListener("click", () => browseResult(1));
    ui.locateSelected.addEventListener("click", locateCurrentSite);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !ui.detailPanel.hidden)
            closeDetail();
    });
    if (pendingLink) {
        state.restoringLink = true;
        ui.query.value = pendingLink.query;
        ui.limitFilter.value = String(pendingLink.limit);
        ui.form.querySelectorAll('input[name="mode"]').forEach((radio) => { radio.checked = radio.value === pendingLink?.mode; });
    }
    initializeMap();
    historyView = ArchSearchHistory.create({
        map: state.map, tiles: state.tiles,
        onCommittedView: () => { if (historyView?.getView()?.basemap !== "modern")
            ui.tileWarning.hidden = true; saveViewLink(); },
        onUserAction: () => {
            restoringView = false;
            if (invalidLink) {
                invalidLink = false;
                linkError = null;
            }
        },
    });
    polarView = ArchSearchPolarView.create({ onSelect: (id, opener) => { void selectSite(id, { opener, moveMap: false }); } });
    explore = ArchSearchExplore.create({
        map: state.map,
        initialBoundsError: boundsRestoreError,
        initialState: boundsRestoreError !== null ? initialNonBoundsBrowse.state : undefined,
        onBoundsAction: () => { boundsRestoreError = null; browseRestored = true; },
        onSelect: (id, opener, options) => { void selectSite(id, { opener, moveMap: options?.moveMap ?? true }); },
        onFilterChange: () => {
            cancelLinkRestore();
            updateSearchAvailability();
            announce("目录筛选已更新；下一次检索将使用当前地区，已显示排名保持原条件。");
        },
        onStateChange: () => { browseRestored = true; invalidLink = false; pendingSelectionRestore = false; saveViewLink(); },
        onCommittedState: () => {
            if (browseRestoreError) {
                if (ui.requestError.textContent === `分享链接未能恢复：${browseRestoreError}`)
                    showError("");
                browseRestoreError = null;
                invalidLink = false;
                linkError = null;
            }
            saveViewLink();
        },
        onCatalogue: (points) => {
            polarView?.setSites(points);
            const selected = currentSelectedSite();
            if (selected && !ui.detailPanel.hidden) {
                const previous = document.getElementById("site-source-locations");
                const section = sourceLocationsSection(selected);
                const active = document.activeElement;
                const ownedFocus = previous?.contains(active) ?? false;
                const oldDetails = previous?.querySelector("details");
                const oldList = previous?.querySelector("ol");
                const previousScroll = oldList?.scrollTop ?? 0;
                if (previous && section) {
                    const details = section.querySelector("details");
                    if (details && oldDetails)
                        details.open = oldDetails.open;
                    previous.replaceWith(section);
                    const list = section.querySelector("ol");
                    if (list && oldList)
                        list.scrollTop = previousScroll;
                }
                else if (section)
                    ui.detailContent.append(section);
                else
                    previous?.remove();
                if (ownedFocus)
                    focusWithinView(active === oldList
                        ? section?.querySelector("ol") ?? ui.detailPanel
                        : section?.querySelector("summary") ?? ui.detailPanel);
            }
        },
        onFeedback: () => { ui.mapEmptyLabel.hidden = true; },
    });
    mapView = ArchSearchMapView.create({ map: state.map, countLabel: ui.viewportCount });
    updateSelectionControls();
    updateSearchAvailability();
    refreshRuntime().then(finishLinkRestore).finally(() => { initialStatePending = false; saveViewLink(); });
})();
//# sourceMappingURL=app.js.map
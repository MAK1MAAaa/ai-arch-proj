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
        list: byId("results-list", HTMLOListElement), empty: byId("results-empty", HTMLDivElement), emptyTitle: byId("empty-title", HTMLHeadingElement),
        emptyDescription: byId("empty-description", HTMLParagraphElement), loading: byId("loading-state", HTMLDivElement),
        detailPanel: byId("detail-panel", HTMLElement), detailContent: byId("detail-content", HTMLDivElement),
        tileWarning: byId("tile-warning", HTMLDivElement), tileWarningText: byId("tile-warning-text", HTMLSpanElement),
        mapEmptyLabel: byId("map-empty-label", HTMLDivElement),
    };
    const state = {
        corpusReady: false, semanticReady: false, statusLoaded: false, searching: false,
        hasSearched: false, displayedMode: null, results: [], selectedId: null, typeLabels: new Map(),
        searchController: null, detailController: null, searchSequence: 0,
        map: null, tiles: null, markerLayer: null, markers: new Map(),
    };
    const fieldLabels = {
        title: "地点名称", names: "别名", description: "原始描述", types: "地点类型",
        periods: "原始时期", details: "原始补充记录", search_text: "检索文本",
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
        return state.typeLabels.get(value) || labelFromId(value);
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
    function showError(message) {
        ui.requestError.textContent = message;
        ui.requestError.hidden = !message;
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
        catch {
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
        const available = state.corpusReady && (mode === "bm25" || state.semanticReady);
        ui.searchButton.disabled = !available;
        ui.buttonLabel.textContent = state.searching ? "检索中" : "开始检索";
        ui.activeMode.textContent = (state.displayedMode || mode) === "semantic" ? "SEMANTIC" : "BM25";
        ui.preparationNote.hidden = mode !== "semantic" || !state.statusLoaded || state.semanticReady;
        ui.modeExplanation.textContent = mode === "semantic"
            ? "多语言向量模型支持中文查询；返回的是相近候选，分数并非相关概率。"
            : "关键词基线按原文字词匹配；英文与古地名更适合，中文零命中不代表资料中没有相关地点。";
    }
    async function loadStatus() {
        const refreshButton = byId("refresh-status", HTMLButtonElement);
        refreshButton.disabled = true;
        ui.runtimeLabel.textContent = "检查本地服务";
        try {
            const status = await api("/api/status");
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
            if (!state.corpusReady) {
                showError("本地资料集尚未准备。请先按 README 导入演示资料，再刷新运行状态。");
            }
            else {
                showError("");
            }
            announce(state.semanticReady ? "本地语义检索已就绪。" : "本地模型尚未就绪，可以选择关键词基线。");
        }
        catch (error) {
            state.statusLoaded = true;
            state.semanticReady = false;
            ui.statusDot.className = "status-dot is-warning";
            ui.runtimeLabel.textContent = "服务连接失败";
            ui.preparationReason.textContent = "无法确认本地模型状态。请检查服务是否启动，再点击右上角刷新运行状态。";
            showError(`运行状态检查失败：${errorMessage(error)}`);
        }
        finally {
            refreshButton.disabled = false;
            updateSearchAvailability();
        }
    }
    async function loadFacets() {
        try {
            const facets = await api("/api/facets");
            for (const item of facets.types || []) {
                if (typeof item.id !== "string")
                    continue;
                const label = typeof item.label === "string" ? item.label : labelFromId(item.id);
                state.typeLabels.set(item.id, label);
                const option = element("option", null, `${label} (${Number(item.count) || 0})`);
                option.value = item.id;
                ui.typeFilter.append(option);
            }
        }
        catch {
            ui.typeFilter.disabled = true;
            ui.typeFilter.options[0].textContent = "类型暂不可用";
        }
    }
    function point(site) {
        const coordinate = site.repr_point;
        if (!Array.isArray(coordinate) || coordinate.length !== 2)
            return null;
        const [lon, lat] = coordinate;
        return Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90
            ? [lat, lon] : null;
    }
    function coordinateLabel(site) {
        const coordinate = point(site);
        if (!coordinate)
            return "无可用代表点";
        const [lat, lon] = coordinate;
        return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? "N" : "S"} / ${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? "E" : "W"}`;
    }
    function initializeMap() {
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
    function fitMap() {
        if (!state.map)
            return;
        const coordinates = state.results.map((result) => point(result.site)).filter((coordinate) => coordinate !== null);
        if (coordinates.length === 0) {
            state.map.setView([37.2, 17.4], 4);
        }
        else {
            state.map.fitBounds(L.latLngBounds(coordinates), { padding: [46, 55], maxZoom: 9, animate: false });
        }
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
                title: result.site.title,
                keyboard: true,
            }).addTo(state.markerLayer);
            marker.bindTooltip(element("span", null, result.site.title), { direction: "top", offset: [0, -13] });
            marker.on("click", () => selectSite(String(result.site.id), { fromMap: true }));
            const icon = marker.getElement();
            if (icon) {
                icon.setAttribute("aria-label", `候选 ${index + 1}：${result.site.title}，打开资料详情`);
                icon.setAttribute("aria-pressed", "false");
                icon.addEventListener("keydown", (event) => {
                    if (event.key === " ") {
                        event.preventDefault();
                        marker.fire("click");
                    }
                });
            }
            state.markers.set(String(result.site.id), marker);
        }
        ui.mapEmptyLabel.hidden = state.results.length > 0;
        fitMap();
    }
    function scoreLabel(score, mode) {
        if (!Number.isFinite(score))
            return "未提供分数";
        return mode === "semantic" ? `相似度 ${score.toFixed(3)}` : `BM25 ${score.toFixed(2)}`;
    }
    function renderResults(data) {
        closeDetail(false);
        state.results = Array.isArray(data.results) ? data.results : [];
        state.selectedId = null;
        state.hasSearched = true;
        state.displayedMode = data.mode;
        ui.list.replaceChildren();
        ui.resultCount.textContent = String(state.results.length).padStart(2, "0");
        ui.activeMode.textContent = data.mode === "bm25" ? "BM25" : "SEMANTIC";
        const elapsed = Number.isFinite(data.elapsed_ms) ? `${Math.round(data.elapsed_ms)} ms` : "耗时未提供";
        const candidates = Number.isFinite(data.total_candidates) ? ` / ${data.total_candidates} 条候选` : "";
        ui.resultSummary.textContent = `${state.results.length} 条返回结果${candidates} · ${elapsed}`;
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
            card.setAttribute("aria-label", `候选 ${index + 1}：${site.title}，查看地图与原始证据`);
            const top = element("div", "result-topline");
            top.append(element("span", "result-rank", String(index + 1).padStart(2, "0")));
            const titleArea = element("div");
            titleArea.append(element("h3", "result-title", site.title || "未命名地点"));
            titleArea.append(element("p", "result-type", strings(site.types).map(typeLabel).join(" · ") || "地点类型未提供"));
            top.append(titleArea, element("span", "result-arrow", "↗"));
            const description = element("p", "result-description", site.description || "原始资料未提供描述，请查看来源记录。");
            description.lang = "en";
            const metadata = element("div", "result-metadata");
            metadata.append(element("span", "result-coordinate", coordinateLabel(site)), element("span", "result-score", scoreLabel(result.score, data.mode)));
            card.append(top, description, metadata);
            card.addEventListener("click", () => selectSite(String(site.id)));
            item.append(card);
            ui.list.append(item);
        }
        renderMarkers();
        announce(`检索完成，返回 ${state.results.length} 条候选资料。${data.mode === "semantic" ? "相似度分数并非相关概率，请核验来源。" : ""}`);
    }
    function setLoading(value) {
        state.searching = value;
        ui.resultsPanel.setAttribute("aria-busy", String(value));
        ui.form.classList.toggle("is-searching", value);
        ui.loading.hidden = !value || state.results.length > 0;
        if (value && state.results.length === 0)
            ui.empty.hidden = true;
        if (!value)
            ui.empty.hidden = state.results.length > 0;
        updateSearchAvailability();
    }
    async function search(event) {
        if (event)
            event.preventDefault();
        const query = ui.query.value.trim();
        if (!query) {
            ui.query.focus();
            return;
        }
        const mode = currentMode();
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
            const data = await api("/api/search", {
                method: "POST", signal: controller.signal,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, mode, type: ui.typeFilter.value || null, limit: Number(ui.limitFilter.value) }),
            });
            if (sequence !== state.searchSequence)
                return;
            renderResults(data);
        }
        catch (error) {
            if (isAbortError(error) || sequence !== state.searchSequence)
                return;
            const retained = state.results.length ? "已保留上次结果。" : "请检查本地服务后重试。";
            showError(`本次检索未完成：${errorMessage(error)} ${retained}`);
            announce("本次检索失败，请查看错误说明。");
            if (!state.results.length) {
                ui.emptyTitle.textContent = "本次检索未完成";
                ui.emptyDescription.textContent = "上方保留了错误说明。检查本地模型与服务后，可以重试或选择关键词基线。";
            }
        }
        finally {
            if (sequence === state.searchSequence)
                setLoading(false);
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
    function renderDetail(site, matchedFields = []) {
        const title = element("h3", null, site.title || "未命名地点");
        title.id = "detail-title";
        const sourceId = element("p", "detail-id", `PLEIADES / ${site.id}`);
        const description = element("p", "detail-description", site.description || "原始资料未提供描述。");
        description.lang = "en";
        const nodes = [title, sourceId, description];
        if (typeof site.details === "string" && site.details.trim()) {
            nodes.push(detailSection("原始补充记录", site.details));
        }
        nodes.push(detailSection("名称与别名", strings(site.names).join(" · ") || "原始资料未提供其他名称。"));
        nodes.push(detailSection("地点类型", strings(site.types).map(typeLabel).join(" · ") || "原始资料未提供类型。"));
        nodes.push(detailSection("原始时期记载", strings(site.periods).map(labelFromId).join(" · ") || "原始资料未提供时期标签。"));
        const facts = element("dl");
        facts.append(fact("代表点", coordinateLabel(site)), fact("位置精度", site.location_precision || "原始资料未提供精度信息"));
        nodes.push(detailSection("空间信息", facts));
        const fields = strings(matchedFields).map((field) => fieldLabels[field] || field);
        if (fields.length)
            nodes.push(detailSection("检索涉及字段", fields.join(" · ")));
        const evidence = Array.isArray(site.period_evidence) ? site.period_evidence : [];
        if (evidence.length) {
            const list = element("div");
            for (const item of evidence) {
                const row = element("div", "evidence-item");
                const resource = item.resource_type === "Name" ? "名称记录" : item.resource_type === "Location" ? "位置记录" : "原始记录";
                row.append(element("p", null, `${resource} · ${labelFromId(item.period_id || item.period_uri || "时期未提供")}`));
                const metadata = [];
                if (item.confidence !== null && item.confidence !== undefined)
                    metadata.push(`原始置信信息：${item.confidence}`);
                if (item.association_certainty !== null && item.association_certainty !== undefined)
                    metadata.push(`关联确定性：${item.association_certainty}`);
                if (item.start !== null && item.start !== undefined)
                    metadata.push(`起始：${item.start}`);
                if (item.end !== null && item.end !== undefined)
                    metadata.push(`结束：${item.end}`);
                if (metadata.length)
                    row.append(element("p", "evidence-meta", metadata.join(" · ")));
                const links = element("div", "evidence-links");
                links.append(safeLink(item.resource_uri, "原始记录 ↗"), safeLink(item.period_uri, "时期定义 ↗"));
                row.append(links);
                list.append(row);
            }
            nodes.push(detailSection("时期证据与来源", list));
        }
        else {
            nodes.push(detailSection("时期证据与来源", "原始资料未提供可展示的时期证据。"));
        }
        nodes.push(detailSection("资料贡献者", strings(site.contributors).join(" · ") || "当前导出未提供贡献者信息，请在原始来源中核验。"));
        nodes.push(safeLink(site.source_uri, "在 Pleiades 查看原始资料 ↗", "detail-source-link"));
        ui.detailContent.replaceChildren(...nodes);
    }
    async function selectSite(id, { fromMap = false } = {}) {
        const result = state.results.find((item) => String(item.site.id) === id);
        if (!result)
            return;
        state.selectedId = id;
        for (const card of Array.from(ui.list.querySelectorAll(".result-card"))) {
            const selected = card.dataset.siteId === id;
            card.classList.toggle("is-selected", selected);
            card.setAttribute("aria-pressed", String(selected));
            if (selected && fromMap) {
                card.focus({ preventScroll: true });
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
        const coordinate = point(result.site);
        if (state.map && coordinate) {
            state.map.panTo(coordinate, { animate: false });
            // Keep the selected point visible to the left of the source drawer.
            if (byId("map", HTMLDivElement).clientWidth > 500)
                state.map.panBy([150, 0], { animate: false });
        }
        ui.detailPanel.hidden = false;
        renderDetail(result.site, result.matched_fields);
        announce(`已选择 ${result.site.title}，原始资料详情已展开。`);
        state.detailController?.abort();
        const controller = new AbortController();
        state.detailController = controller;
        try {
            const site = await api(`/api/sites/${encodeURIComponent(id)}`, { signal: controller.signal });
            if (state.selectedId === id && !controller.signal.aborted)
                renderDetail(site, result.matched_fields);
        }
        catch (error) {
            if (isAbortError(error) || state.selectedId !== id)
                return;
            ui.detailContent.append(element("p", "detail-loading", "详情刷新失败，当前显示检索时返回的原始资料。"));
        }
    }
    function closeDetail(returnFocus = true) {
        state.detailController?.abort();
        ui.detailPanel.hidden = true;
        if (returnFocus && state.selectedId !== null) {
            const card = Array.from(ui.list.querySelectorAll(".result-card")).find((item) => item.dataset.siteId === state.selectedId);
            card?.focus({ preventScroll: true });
        }
    }
    function applyChangedFilter() {
        updateSearchAvailability();
        if ((state.hasSearched || state.searching) && ui.query.value.trim())
            search();
    }
    ui.form.addEventListener("submit", search);
    ui.form.querySelectorAll('input[name="mode"]').forEach((radio) => radio.addEventListener("change", applyChangedFilter));
    ui.typeFilter.addEventListener("change", applyChangedFilter);
    ui.limitFilter.addEventListener("change", applyChangedFilter);
    document.querySelectorAll("[data-query]").forEach((button) => {
        button.addEventListener("click", () => {
            ui.query.value = button.dataset.query || "";
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
        if (event.key === "Escape" && !ui.detailPanel.hidden)
            closeDetail();
    });
    initializeMap();
    updateSearchAvailability();
    Promise.allSettled([loadStatus(), loadFacets()]);
})();
//# sourceMappingURL=app.js.map
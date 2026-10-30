"use strict";
const ArchSearchHistory = (() => {
    "use strict";
    const minimumYear = -3400;
    const maximumYear = 2024;
    const palette = ["#8b603e", "#687457", "#496d77", "#93616b", "#8d783d", "#70617f"];
    function isValidYear(year) {
        return Number.isInteger(year) && year !== 0 && year >= minimumYear && year <= maximumYear;
    }
    function yearToStep(year) {
        if (!isValidYear(year))
            throw new Error("年份必须在公元前 3400 年至公元 2024 年之间，且没有公元 0 年。");
        return year < 0 ? year : year - 1;
    }
    function stepToYear(step) {
        if (!Number.isInteger(step))
            throw new Error("年份刻度无效。");
        const year = step < 0 ? step : step + 1;
        if (!isValidYear(year))
            throw new Error("年份刻度超出资料范围。");
        return year;
    }
    function formatYear(year) {
        return year < 0 ? `公元前 ${Math.abs(year)} 年` : `公元 ${year} 年`;
    }
    function frameTargets(year, changes, minimum = minimumYear) {
        const starts = [...new Set([minimum, ...changes.filter(isValidYear)])].sort((left, right) => left - right);
        let index = 0;
        while (index + 1 < starts.length && starts[index + 1] <= year)
            index++;
        return { previous: starts[index - 1] ?? null, next: starts[index + 1] ?? null };
    }
    function colorForName(name) {
        let hash = 2166136261;
        for (const character of name)
            hash = Math.imul(hash ^ (character.codePointAt(0) ?? 0), 16777619);
        return palette[(hash >>> 0) % palette.length];
    }
    function worldCopies(value) {
        if (!record(value) || !Array.isArray(value.features))
            throw new Error("地图资料格式无效。");
        const originals = value.features;
        const shift = (coordinates, offset) => {
            if (!Array.isArray(coordinates))
                return coordinates;
            if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number")
                return [coordinates[0] + offset, ...coordinates.slice(1)];
            return coordinates.map((item) => shift(item, offset));
        };
        const features = [-360, 0, 360].flatMap((offset) => originals.map((feature) => {
            if (!record(feature) || !record(feature.geometry))
                throw new Error("地图几何格式无效。");
            return { ...feature, geometry: { ...feature.geometry, coordinates: shift(feature.geometry.coordinates, offset) } };
        }));
        return { ...value, type: "FeatureCollection", features };
    }
    function record(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function text(value, fallback = "来源未提供") {
        return typeof value === "string" && value.trim() ? value : typeof value === "number" && Number.isFinite(value) ? String(value) : fallback;
    }
    function element(tag, content) {
        const node = document.createElement(tag);
        if (content !== undefined)
            node.textContent = content;
        return node;
    }
    function safeSource(value, label) {
        if (typeof value === "string") {
            try {
                const url = new URL(value);
                if (url.protocol === "https:" || url.protocol === "http:") {
                    const link = element("a", label);
                    link.href = url.href;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    return link;
                }
            }
            catch { /* A source without a usable URL remains plain text. */ }
        }
        return element("span", label);
    }
    function sourceYear(value) {
        if (value === 0)
            return "原值 0（查询中按公元前 1 年处理）";
        return typeof value === "number" && Number.isInteger(value) ? formatYear(value) : text(value);
    }
    function popup(properties, source) {
        const content = element("div");
        content.className = "history-popup";
        content.append(element("strong", text(properties.Name, "未命名历史政权")));
        content.append(element("p", `来源范围：${sourceYear(properties.FromYear)} — ${sourceYear(properties.ToYear)}`));
        if (typeof properties.Type === "string" && properties.Type)
            content.append(element("p", `来源类型：${properties.Type}`));
        if (properties.composite === true)
            content.append(element("p", "复合政体边界以虚线显示，不填色；组成关系与范围须回到来源核验。"));
        content.append(element("p", "历史边界是来源中的重建记录，可能存在概略范围、争议与不确定性。"));
        const links = element("p");
        links.append(safeSource(properties.Wikipedia, "维基百科来源"), document.createTextNode(" · "), safeSource(source.uri, text(source.name, "Cliopatria")));
        content.append(links);
        content.append(element("p", `${text(source.version, "版本未提供")} · ${text(source.license, "许可未提供")}`));
        return content;
    }
    function validGeometry(value) {
        if (!record(value) || !Array.isArray(value.coordinates))
            return false;
        const ring = (points) => Array.isArray(points) && points.length >= 4
            && points.every((point) => Array.isArray(point) && point.length >= 2
                && typeof point[0] === "number" && Number.isFinite(point[0]) && Math.abs(point[0]) <= 180
                && typeof point[1] === "number" && Number.isFinite(point[1]) && Math.abs(point[1]) <= 90)
            && JSON.stringify(points[0]) === JSON.stringify(points[points.length - 1]);
        const polygon = (rings) => Array.isArray(rings) && rings.length > 0 && rings.every(ring);
        return value.type === "Polygon" ? polygon(value.coordinates)
            : value.type === "MultiPolygon" && value.coordinates.length > 0 && value.coordinates.every(polygon);
    }
    function validateCollection(value) {
        if (!record(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features)
            || value.features.some((feature) => !record(feature) || feature.type !== "Feature" || !validGeometry(feature.geometry))) {
            throw new Error("地图资料格式无效，未替换当前视图。");
        }
    }
    function parseFrame(value, year, expectedVersion) {
        validateCollection(value);
        const metadata = value.metadata;
        if (!record(metadata) || metadata.year !== year || !isValidYear(Number(metadata.valid_from))
            || !isValidYear(Number(metadata.valid_to)) || typeof metadata.valid_from !== "number" || typeof metadata.valid_to !== "number"
            || metadata.valid_from > year || metadata.valid_to < year || typeof metadata.frame_id !== "string" || !metadata.frame_id) {
            throw new Error("历史帧的年份或有效范围不匹配，未替换当前视图。");
        }
        const source = record(metadata.source) ? metadata.source : {};
        const version = typeof source.version === "string" ? source.version : expectedVersion;
        if (version !== expectedVersion)
            throw new Error("历史资料版本已变化，请刷新运行状态后重试。");
        return { data: value, validFrom: metadata.valid_from, validTo: metadata.valid_to, id: metadata.frame_id, source, version, featureCount: value.features.length };
    }
    function create({ map, tiles, onCommittedView, onUserAction }) {
        const byId = (id) => {
            const node = document.getElementById(id);
            if (!node)
                throw new Error(`历史控件不存在：${id}`);
            return node;
        };
        const ui = {
            panel: byId("history-controls"), year: byId("history-year"), range: byId("history-range"),
            apply: byId("history-apply"), previousYear: byId("history-previous-year"), nextYear: byId("history-next-year"),
            previousFrame: byId("history-previous-frame"), nextFrame: byId("history-next-frame"),
            historical: byId("history-basemap-historical"), modern: byId("history-basemap-modern"),
            boundaries: byId("history-boundaries"), applied: byId("history-applied-year"), draft: byId("history-draft-year"),
            feedback: byId("history-feedback"), error: byId("history-error"), source: byId("history-source"),
            retry: byId("history-retry"), caption: document.getElementById("history-map-caption"),
        };
        let ready = false;
        let version = null;
        let reason = "历史资料尚未准备，请准备资料后刷新运行状态。";
        let minimum = minimumYear;
        let maximum = maximumYear;
        let changes = [];
        let desired = { year: 117, basemap: "historical", boundaries: true };
        let yearDraft = "117";
        let committed = null;
        let sequence = 0;
        let actions = 0;
        let timer = null;
        let controller = null;
        let landData = null;
        let landLayer = null;
        let boundaryLayer = null;
        let appliedFrame = null;
        let failed = false;
        let loading = false;
        let emptyFrame = false;
        const frames = new Map();
        let renderer = null;
        if (map && typeof L !== "undefined") {
            const historyPane = map.getPane("history-boundaries") ?? map.createPane("history-boundaries");
            historyPane.style.zIndex = "350";
            const landPane = map.getPane("history-land") ?? map.createPane("history-land");
            landPane.style.zIndex = "210";
            landPane.style.pointerEvents = "none";
            renderer = L.canvas({ pane: "history-boundaries" });
        }
        function cancel() {
            sequence++;
            if (timer !== null)
                clearTimeout(timer);
            timer = null;
            controller?.abort();
            controller = null;
            loading = false;
        }
        function userAction(intent) {
            if (intent === "user") {
                actions++;
                onUserAction();
            }
        }
        function showError(message) {
            ui.error.textContent = message;
            ui.error.hidden = !message;
        }
        function render() {
            const previousFocus = document.activeElement;
            const unavailable = map === null || !ready;
            ui.year.disabled = unavailable;
            ui.apply.disabled = unavailable;
            ui.range.disabled = unavailable;
            ui.previousYear.disabled = unavailable || desired.year <= minimum || desired.year > maximum;
            ui.nextYear.disabled = unavailable || desired.year >= maximum || desired.year < minimum;
            const targets = frameTargets(desired.year, changes, minimum);
            ui.previousFrame.disabled = unavailable || targets.previous === null;
            ui.nextFrame.disabled = unavailable || targets.next === null || targets.next > maximum;
            ui.previousFrame.title = targets.previous === null ? "已到首个疆域变化" : `上一疆域变化：${formatYear(targets.previous)}`;
            ui.nextFrame.title = targets.next === null ? "已到末个疆域变化" : `下一疆域变化：${formatYear(targets.next)}`;
            ui.historical.disabled = map === null;
            ui.modern.disabled = map === null;
            ui.boundaries.disabled = map === null;
            ui.historical.setAttribute("aria-pressed", String(desired.basemap === "historical"));
            ui.modern.setAttribute("aria-pressed", String(desired.basemap === "modern"));
            ui.boundaries.checked = desired.boundaries;
            ui.range.min = String(yearToStep(minimum));
            ui.range.max = String(yearToStep(maximum));
            ui.range.value = String(yearToStep(desired.year));
            ui.range.setAttribute("aria-valuetext", formatYear(desired.year));
            ui.year.min = String(minimum);
            ui.year.max = String(maximum);
            if (ui.year.value !== yearDraft)
                ui.year.value = yearDraft;
            ui.draft.textContent = yearDraft.trim() === String(desired.year)
                ? `计划年份：${formatYear(desired.year)}`
                : isValidYear(Number(yearDraft)) ? `年份草稿：${formatYear(Number(yearDraft))}，尚未应用` : "年份草稿尚未应用，请输入有效整数后确认。";
            ui.applied.textContent = committed ? `当前地图：${formatYear(committed.year)}` : "历史地图尚未加载";
            ui.panel.setAttribute("aria-busy", String(loading));
            ui.retry.hidden = !failed;
            ui.retry.disabled = loading || map === null;
            if (loading)
                ui.feedback.textContent = `正在加载${formatYear(desired.year)}；地图保留上次成功视图。`;
            else if (!ready && desired.boundaries)
                ui.feedback.textContent = reason;
            else if (!failed)
                ui.feedback.textContent = emptyFrame && committed?.boundaries
                    ? "该年份没有来源中的活动政权记录；地点标记仍保留。"
                    : committed?.boundaries ? "历史政权疆域概略独立于遗址排序；时间滑动不会重新检索地点。" : "历史政权疆域概略已关闭，地点与检索结果继续保留。";
            if ((previousFocus === ui.retry && ui.retry.hidden)
                || [ui.year, ui.range, ui.apply, ui.previousYear, ui.nextYear, ui.previousFrame, ui.nextFrame].some((control) => previousFocus === control && control.disabled)) {
                ui.feedback.tabIndex = -1;
                ui.feedback.focus({ preventScroll: true });
            }
        }
        async function getJson(path, signal) {
            const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
            let value;
            try {
                value = await response.json();
            }
            catch (error) {
                if (signal.aborted)
                    throw error;
                throw new Error(`地图资料无法读取（HTTP ${response.status}）。`);
            }
            if (!response.ok)
                throw new Error(record(value) ? text(value.detail, `地图请求失败（HTTP ${response.status}）。`) : `地图请求失败（HTTP ${response.status}）。`);
            return value;
        }
        async function loadLand(signal) {
            if (landData !== null)
                return landData;
            const value = await getJson("/static/data/land.geojson", signal);
            validateCollection(value);
            return value;
        }
        async function loadFrame(year, sourceVersion, signal) {
            for (const [key, frame] of frames) {
                if (frame.version === sourceVersion && frame.validFrom <= year && year <= frame.validTo) {
                    frames.delete(key);
                    frames.set(key, frame);
                    return frame;
                }
            }
            return parseFrame(await getJson(`/api/history/boundaries?year=${encodeURIComponent(year)}`, signal), year, sourceVersion);
        }
        function updateSource(frame) {
            const source = element("span", desired.basemap === "historical" ? "Natural Earth · 现代自然地理参照" : "OpenStreetMap · 现代底图");
            ui.source.replaceChildren(source);
            if (frame !== null && desired.boundaries) {
                ui.source.append(document.createTextNode(" · "), safeSource(frame.source.uri, `${text(frame.source.name, "Cliopatria")} ${frame.version}`), document.createTextNode(" · "), safeSource(frame.source.license_uri, text(frame.source.license, "CC BY 4.0")));
            }
            if (ui.caption)
                ui.caption.textContent = `${frame !== null && desired.boundaries ? "历史政权疆域概略" : "地点代表位置"} · ${desired.basemap === "historical" ? "现代海岸线参照" : "现代 OSM 底图"}`;
        }
        async function applyView() {
            const current = sequence;
            timer = null;
            if (!map || typeof L === "undefined") {
                showError("地图组件未能加载，仍可阅读地点资料与来源。");
                render();
                return;
            }
            const canRequestYear = ready && desired.year >= minimum && desired.year <= maximum;
            const request = { ...desired, year: canRequestYear ? desired.year : committed?.year ?? desired.year };
            const sourceVersion = version;
            const abort = new AbortController();
            controller = abort;
            loading = true;
            failed = false;
            showError("");
            render();
            let frame = null;
            let land = null;
            let nextBoundary = null;
            let nextLand = null;
            const previousTilesVisible = tiles !== null && map.hasLayer(tiles);
            const previousLandVisible = landLayer !== null && map.hasLayer(landLayer);
            const previousBoundary = boundaryLayer;
            try {
                [land, frame] = await Promise.all([
                    request.basemap === "historical" ? loadLand(abort.signal) : Promise.resolve(null),
                    request.boundaries && canRequestYear && sourceVersion ? loadFrame(request.year, sourceVersion, abort.signal)
                        : Promise.resolve(request.boundaries && appliedFrame && appliedFrame.validFrom <= request.year && request.year <= appliedFrame.validTo ? appliedFrame : null),
                ]);
                if (abort.signal.aborted || current !== sequence)
                    return;
                if (land !== null && landLayer === null) {
                    nextLand = L.geoJSON(worldCopies(land), { pane: "history-land", interactive: false, attribution: "Natural Earth · Public Domain", style: { fillColor: "#eee9dc", fillOpacity: 1, color: "#a3ad9c", weight: 0.7 } });
                }
                if (frame !== null) {
                    const source = frame.source;
                    nextBoundary = L.geoJSON(worldCopies(frame.data), {
                        pane: "history-boundaries", attribution: "Cliopatria · CC BY 4.0",
                        style: (feature) => {
                            const properties = record(feature?.properties) ? feature.properties : {};
                            const composite = properties.composite === true;
                            return { pane: "history-boundaries", renderer: renderer ?? undefined, color: colorForName(text(properties.Name, String(feature?.id ?? "unknown"))), weight: composite ? 1.3 : 1, opacity: 0.8, fill: !composite, fillOpacity: composite ? 0 : 0.1, dashArray: composite ? "5 4" : undefined };
                        },
                        onEachFeature: (feature, layer) => { layer.bindPopup(() => popup(record(feature.properties) ? feature.properties : {}, source), { maxWidth: 310 }); },
                    });
                }
                if (abort.signal.aborted || current !== sequence)
                    return;
                if (nextLand)
                    nextLand.addTo(map);
                if (nextBoundary)
                    nextBoundary.addTo(map);
                if (request.basemap === "historical") {
                    if (tiles && map.hasLayer(tiles))
                        map.removeLayer(tiles);
                    if (landLayer && !map.hasLayer(landLayer))
                        landLayer.addTo(map);
                }
                else {
                    if (tiles && !map.hasLayer(tiles))
                        tiles.addTo(map);
                    if (landLayer && map.hasLayer(landLayer))
                        map.removeLayer(landLayer);
                }
                if (previousBoundary)
                    map.removeLayer(previousBoundary);
            }
            catch (error) {
                if (abort.signal.aborted || current !== sequence)
                    return;
                if (nextBoundary && map.hasLayer(nextBoundary))
                    map.removeLayer(nextBoundary);
                if (nextLand && map.hasLayer(nextLand))
                    map.removeLayer(nextLand);
                if (previousBoundary && !map.hasLayer(previousBoundary))
                    previousBoundary.addTo(map);
                if (tiles && previousTilesVisible && !map.hasLayer(tiles))
                    tiles.addTo(map);
                if (tiles && !previousTilesVisible && map.hasLayer(tiles))
                    map.removeLayer(tiles);
                if (landLayer && previousLandVisible && !map.hasLayer(landLayer))
                    landLayer.addTo(map);
                if (landLayer && !previousLandVisible && map.hasLayer(landLayer))
                    map.removeLayer(landLayer);
                abort.abort();
                failed = true;
                showError(`${error instanceof Error ? error.message : "历史地图加载失败。"}${committed ? ` 仍显示${formatYear(committed.year)}的上次成功视图。` : " 当前底图与地点标记保持原样。"}`);
                ui.feedback.textContent = "可调整年份或重试；失败请求不会改写已应用的地图年份。";
                return;
            }
            finally {
                if (current === sequence) {
                    loading = false;
                    controller = null;
                    render();
                }
            }
            if (nextLand)
                landLayer = nextLand;
            if (land !== null)
                landData = land;
            boundaryLayer = nextBoundary;
            appliedFrame = frame;
            if (frame !== null) {
                frames.set(frame.id, frame);
                while (frames.size > 4)
                    frames.delete(frames.keys().next().value);
            }
            committed = { ...request, boundaries: frame !== null, frame_id: frame?.id ?? null, source_version: frame?.version ?? null };
            emptyFrame = frame?.featureCount === 0;
            ui.year.removeAttribute("aria-invalid");
            map.getContainer().dataset.basemap = request.basemap;
            updateSource(frame);
            render();
            onCommittedView({ ...committed });
        }
        function schedule() {
            cancel();
            failed = false;
            showError("");
            render();
            timer = setTimeout(() => { void applyView(); }, 200);
        }
        function setYear(year, intent = "user") {
            userAction(intent);
            if (!isValidYear(year)) {
                if (Number.isFinite(year))
                    yearDraft = String(year);
                cancel();
                ui.year.setAttribute("aria-invalid", "true");
                showError(Number.isInteger(year) && year !== 0
                    ? "该年份无可用疆域数据；保留最后成功地图。资料覆盖公元前 3400 年至公元 2024 年。"
                    : "请输入公元前 3400 年至公元 2024 年的整数年份；负数表示公元前，没有公元 0 年。");
                render();
                return;
            }
            desired = { ...desired, year };
            yearDraft = String(year);
            ui.year.value = String(year);
            ui.year.removeAttribute("aria-invalid");
            if (year < minimum || year > maximum) {
                cancel();
                showError(`${formatYear(year)}超出当前历史资料范围，计划年份保持不变；请选择范围内年份后应用。`);
                render();
                return;
            }
            if (!ready) {
                cancel();
                ui.feedback.textContent = reason;
                render();
                return;
            }
            schedule();
        }
        function setBasemap(basemap, intent = "user") {
            userAction(intent);
            if (basemap !== "historical" && basemap !== "modern")
                return;
            desired = { ...desired, basemap };
            schedule();
        }
        function setBoundaries(boundaries, intent = "user") {
            userAction(intent);
            desired = { ...desired, boundaries: Boolean(boundaries) };
            schedule();
        }
        function configure(status) {
            const nextVersion = typeof status?.version === "string" && status.version ? status.version : null;
            if (nextVersion !== version)
                frames.clear();
            version = nextVersion;
            ready = status?.ready === true && version !== null;
            reason = text(status?.reason, ready ? "" : "历史资料尚未准备，请准备资料后刷新运行状态。");
            minimum = isValidYear(status?.min_year ?? NaN) ? status?.min_year ?? minimumYear : minimumYear;
            maximum = isValidYear(status?.max_year ?? NaN) ? status?.max_year ?? maximumYear : maximumYear;
            if (minimum > maximum) {
                minimum = minimumYear;
                maximum = maximumYear;
                ready = false;
            }
            changes = Array.isArray(status?.change_years) ? status.change_years.filter((year) => isValidYear(year) && minimum <= year && year <= maximum) : [];
            if (ready && (desired.year < minimum || desired.year > maximum)) {
                cancel();
                showError(`${formatYear(desired.year)}超出当前历史资料范围，计划年份保持不变；请选择范围内年份后应用。`);
                render();
                return;
            }
            if (!ready) {
                cancel();
                render();
                return;
            }
            schedule();
        }
        const readYear = () => {
            const raw = ui.year.value.trim();
            setYear(/^-?\d+$/u.test(raw) ? Number(raw) : NaN);
        };
        ui.range.addEventListener("input", () => {
            try {
                setYear(stepToYear(Number(ui.range.value)));
            }
            catch {
                showError("年份刻度无效。");
            }
        });
        ui.year.addEventListener("input", () => { yearDraft = ui.year.value; userAction("user"); cancel(); render(); });
        ui.year.addEventListener("change", readYear);
        ui.year.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                readYear();
            }
            else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                event.preventDefault();
                const draft = Number(ui.year.value);
                const base = isValidYear(draft) && draft >= minimum && draft <= maximum ? draft : desired.year;
                const step = yearToStep(base) + (event.key === "ArrowUp" ? 1 : -1);
                if (step >= yearToStep(minimum) && step <= yearToStep(maximum))
                    setYear(stepToYear(step));
            }
        });
        ui.apply.addEventListener("click", readYear);
        ui.previousYear.addEventListener("click", () => { if (desired.year > minimum)
            setYear(stepToYear(yearToStep(desired.year) - 1)); });
        ui.nextYear.addEventListener("click", () => { if (desired.year < maximum)
            setYear(stepToYear(yearToStep(desired.year) + 1)); });
        ui.previousFrame.addEventListener("click", () => { const target = frameTargets(desired.year, changes, minimum).previous; if (target !== null)
            setYear(target); });
        ui.nextFrame.addEventListener("click", () => { const target = frameTargets(desired.year, changes, minimum).next; if (target !== null)
            setYear(target); });
        ui.historical.addEventListener("click", () => setBasemap("historical"));
        ui.modern.addEventListener("click", () => setBasemap("modern"));
        ui.boundaries.addEventListener("change", () => setBoundaries(ui.boundaries.checked));
        ui.retry.addEventListener("click", () => { userAction("user"); schedule(); });
        render();
        return { configure, getView: () => committed ? { ...committed } : null, setYear, setBasemap, setBoundaries, actionVersion: () => actions };
    }
    return { create, isValidYear, yearToStep, stepToYear, formatYear, frameTargets, colorForName, worldCopies };
})();
//# sourceMappingURL=history.js.map
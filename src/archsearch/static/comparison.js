"use strict";
const ArchSearchComparison = (() => {
    "use strict";
    function camera(map) {
        if (!map)
            return null;
        const center = map.getCenter();
        return { center: [ArchSearchMapView.wrapLongitude(center.lng, 0), Math.max(-85.0511287798, Math.min(85.0511287798, center.lat))], zoom: map.getZoom() };
    }
    function sharedZoom(zoom) { return Math.min(9, Math.max(1, zoom)); }
    function create({ modern, historical, tiles, initial, onSelect, onChanged, onEvidence }) {
        const byId = (id) => {
            const node = document.getElementById(id);
            if (!node)
                throw new Error(`对照地图控件不存在：${id}`);
            return node;
        };
        const ui = {
            osm: byId("modern-basemap-osm"), natural: byId("modern-basemap-natural"),
            sync: byId("comparison-sync"), modernStatus: byId("comparison-modern-status"),
            warning: byId("tile-warning"), warningText: byId("tile-warning-text"),
            evidence: byId("comparison-evidence"), evidenceTitle: byId("comparison-evidence-title"),
            evidenceDate: byId("comparison-evidence-date"), evidenceQuote: byId("comparison-evidence-quote"),
            evidenceSources: byId("comparison-evidence-sources"), evidenceOpen: byId("comparison-evidence-open"),
        };
        let requested = initial.modern_basemap;
        let displayed = modern ? "loading" : "unavailable";
        let sync = initial.sync_centers;
        let syncing = false;
        let restoringCameras = false;
        const restoredZoom = sharedZoom(initial.history_view?.zoom ?? initial.modern_view?.zoom ?? historical?.getZoom() ?? modern?.getZoom() ?? 1);
        let alignedLegacyZoom = [initial.modern_view, initial.history_view].some(view => view !== null && view.zoom !== restoredZoom);
        let failedTiles = false;
        let land = null;
        let landPromise = null;
        let selected = null;
        let selectedMarker = null;
        let cameraActions = 0;
        let modernTouched = false, historicalTouched = false;
        let catalogueSignature = "";
        let candidateValues = [];
        const mapSizes = new Map();
        for (const map of [modern, historical])
            if (map) {
                const size = map.getSize();
                mapSizes.set(map, { x: size.x, y: size.y });
            }
        const markers = new Map();
        const circles = new Map();
        const candidateLayer = historical && typeof L !== "undefined" ? L.layerGroup().addTo(historical) : null;
        const catalogueLayer = historical && typeof L !== "undefined" ? L.layerGroup().addTo(historical) : null;
        let sourceRenderer = null;
        if (historical && typeof L !== "undefined") {
            const pane = historical.getPane("history-boundaries") ?? historical.createPane("history-boundaries");
            pane.style.zIndex = "350";
            sourceRenderer = L.canvas({ pane: "history-boundaries" });
        }
        if (modern) {
            const pane = modern.getPane("comparison-modern-land") ?? modern.createPane("comparison-modern-land");
            pane.style.zIndex = "190";
            pane.style.pointerEvents = "none";
        }
        function changed() { render(); onChanged(); }
        function render() {
            ui.osm.disabled = modern === null;
            ui.natural.disabled = modern === null;
            ui.osm.setAttribute("aria-pressed", String(requested === "osm"));
            ui.natural.setAttribute("aria-pressed", String(requested === "natural"));
            ui.sync.checked = sync;
            ui.sync.disabled = modern === null || historical === null;
            ui.modernStatus.textContent = displayed === "osm" ? "OpenStreetMap · 当前现代位置参照"
                : displayed === "natural" ? failedTiles && requested === "osm" ? "OSM 不可用 · 已显示本地自然轮廓" : "本地自然轮廓 · 现代地理参照"
                    : displayed === "loading" ? "正在加载现代底图；定位点可独立使用" : "现代底图暂不可用，定位点与资料仍保留";
            if (alignedLegacyZoom)
                ui.modernStatus.textContent += ` · 旧链接缩放已统一为 ${restoredZoom} 级，分别保留两图中心`;
            if (modern)
                modern.getContainer().dataset.basemap = displayed;
        }
        async function ensureLand() {
            if (land)
                return;
            if (landPromise)
                return landPromise;
            landPromise = (async () => {
                const response = await fetch("/static/data/land.geojson", { headers: { Accept: "application/json" } });
                if (!response.ok)
                    throw new Error("本地自然地理轮廓读取失败。");
                const value = await response.json();
                const validate = ArchSearchHistory.validateCollection;
                validate(value);
                if (!modern || typeof L === "undefined")
                    return;
                const next = L.geoJSON(ArchSearchHistory.worldCopies(value), { pane: "comparison-modern-land", interactive: false,
                    attribution: "Natural Earth · Public Domain", style: { fillColor: "#eee9dc", fillOpacity: 1, color: "#9ca998", weight: 0.8 } });
                next.addTo(modern);
                land = next;
            })().finally(() => { landPromise = null; });
            return landPromise;
        }
        async function naturalFallback() {
            try {
                await ensureLand();
                if (!modern || !land || (requested === "osm" && !failedTiles))
                    return;
                if (tiles && modern.hasLayer(tiles))
                    modern.removeLayer(tiles);
                displayed = "natural";
                if (requested === "natural")
                    ui.warning.hidden = true;
                changed();
            }
            catch {
                if (displayed !== "osm")
                    displayed = "unavailable";
                ui.warning.hidden = false;
                ui.warningText.textContent = "本地自然轮廓未能读取；保留可用底图与资料标记。";
                changed();
            }
        }
        function setModernBasemap(value) {
            requested = value;
            if (value === "natural") {
                ui.warning.hidden = true;
                void naturalFallback();
            }
            else if (modern && tiles) {
                failedTiles = false;
                displayed = "loading";
                ui.warning.hidden = true;
                if (!modern.hasLayer(tiles))
                    tiles.addTo(modern);
                tiles.redraw();
            }
            changed();
        }
        function syncFrom(source, destination, copyCenter = sync) {
            if (syncing || restoringCameras)
                return;
            const center = source.getCenter();
            const other = destination.getCenter();
            const latitude = copyCenter ? center.lat : other.lat;
            const longitude = copyCenter ? ArchSearchMapView.wrapLongitude(center.lng, other.lng) : other.lng;
            const zoom = sharedZoom(source.getZoom());
            syncing = true;
            try {
                if (source.getZoom() !== zoom) {
                    source.stop();
                    source.setView([center.lat, center.lng], zoom, { animate: false });
                }
                if (Math.abs(latitude - other.lat) >= 1e-7 || Math.abs(longitude - other.lng) >= 1e-7 || zoom !== destination.getZoom()) {
                    destination.stop();
                    destination.setView([latitude, longitude], zoom, { animate: false });
                }
            }
            finally {
                syncing = false;
            }
        }
        function sizeChanged(map) {
            const next = map.getSize(), previous = mapSizes.get(map);
            mapSizes.set(map, { x: next.x, y: next.y });
            return previous !== undefined && (previous.x !== next.x || previous.y !== next.y);
        }
        function positionSelection(coordinate) {
            syncing = true;
            try {
                for (const map of [modern, historical])
                    if (map) {
                        map.stop();
                        map.setView([coordinate[1], ArchSearchMapView.wrapLongitude(coordinate[0], map.getCenter().lng)], 4, { animate: false });
                    }
            }
            finally {
                syncing = false;
            }
            for (const map of [modern, historical])
                if (map)
                    sizeChanged(map);
            onChanged();
        }
        function restoreViews() {
            if ((initial.modern_view === null && initial.history_view === null) || modernTouched || historicalTouched)
                return;
            restoringCameras = true;
            try {
                for (const [map, view] of [[modern, initial.modern_view], [historical, initial.history_view]])
                    if (map) {
                        const center = view ? [view.center[1], view.center[0]] : [map.getCenter().lat, map.getCenter().lng];
                        map.setView(center, restoredZoom, { animate: false });
                    }
            }
            finally {
                restoringCameras = false;
            }
            for (const map of [modern, historical])
                if (map)
                    sizeChanged(map);
        }
        function attachMarker(id, title, coordinate, rank) {
            if (!historical || !candidateLayer)
                return null;
            const content = document.createElement("span");
            content.className = "site-marker";
            content.textContent = rank === null ? "选" : String(rank);
            content.setAttribute("aria-hidden", "true");
            const marker = L.marker([coordinate[1], ArchSearchMapView.wrapLongitude(coordinate[0], historical.getCenter().lng)], {
                icon: L.divIcon({ className: "site-marker-icon comparison-history-marker", html: content, iconSize: [30, 30], iconAnchor: [15, 15] }),
                keyboard: true, autoPanOnFocus: false, title,
            }).addTo(candidateLayer);
            const label = document.createElement("span");
            label.textContent = title;
            marker.bindTooltip(label, { direction: "top", offset: [0, -13] });
            marker.on("click", () => onSelect(id, marker.getElement() ?? null));
            const icon = marker.getElement();
            icon?.setAttribute("aria-label", `历史图${rank === null ? "选中地点" : `候选 ${rank}`}：${title}，打开来源资料`);
            icon?.addEventListener("keydown", (event) => { if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();
                marker.fire("click");
            } });
            return marker;
        }
        function renderSelection() {
            for (const [id, marker] of markers) {
                const active = id === selected?.id;
                marker.getElement()?.classList.toggle("is-selected", active);
                marker.getElement()?.setAttribute("aria-pressed", String(active));
                marker.setZIndexOffset(active ? 1500 : 0);
            }
            for (const [id, group] of circles)
                for (const circle of group)
                    circle.setStyle({ fillColor: id === selected?.id ? "#a55339" : "#536a52", fillOpacity: id === selected?.id ? 0.95 : 0.55 });
        }
        function setCandidates(values, fit = true) {
            candidateValues = values;
            candidateLayer?.clearLayers();
            selectedMarker = null;
            markers.clear();
            for (const value of values)
                if (ArchSearchMapView.locationStatus(value.repr_point) === "mapped" && value.repr_point) {
                    const marker = attachMarker(value.id, value.title, value.repr_point, value.rank);
                    if (marker)
                        markers.set(value.id, marker);
                }
            if (fit)
                fitCandidates();
            renderSelection();
        }
        function fitCandidates() {
            const maps = [modern, historical].filter((map) => map !== null);
            if (!maps.length)
                return;
            const coordinates = candidateValues.filter((item) => ArchSearchMapView.locationStatus(item.repr_point) === "mapped").map((item) => [item.repr_point[1], item.repr_point[0]]);
            syncing = true;
            try {
                let center = { lat: 20, lng: 0 }, zoom = 1;
                if (coordinates.length) {
                    const bounds = L.latLngBounds(ArchSearchMapView.wrapCoordinates(coordinates));
                    zoom = sharedZoom(Math.min(4, ...maps.map(map => map.getBoundsZoom(bounds, false, L.point(70, 70)))));
                    const reference = maps[0];
                    reference.stop();
                    reference.fitBounds(bounds, { maxZoom: zoom, padding: [35, 35], animate: false });
                    center = reference.getCenter();
                }
                for (const map of maps) {
                    map.stop();
                    map.setView([center.lat, ArchSearchMapView.wrapLongitude(center.lng, map.getCenter().lng)], zoom, { animate: false });
                }
            }
            finally {
                syncing = false;
            }
            for (const map of maps)
                sizeChanged(map);
            onChanged();
        }
        function setCatalogue(values, visible) {
            const signature = visible ? JSON.stringify(values) : "hidden";
            if (signature === catalogueSignature)
                return;
            catalogueSignature = signature;
            catalogueLayer?.clearLayers();
            circles.clear();
            if (!historical || !catalogueLayer || !visible)
                return;
            for (const value of values) {
                if (ArchSearchMapView.locationStatus(value.coordinate) !== "mapped")
                    continue;
                for (const offset of [-360, 0, 360]) {
                    const circle = L.circleMarker([value.coordinate[1], value.coordinate[0] + offset], { renderer: sourceRenderer ?? undefined,
                        pane: "history-boundaries", radius: 2.2, weight: 0.5, color: "#536a52", fillColor: "#536a52", fillOpacity: 0.55 });
                    const label = document.createElement("span");
                    label.textContent = `${value.title} · ${value.representative ? "参考代表点" : "来源定位点"}`;
                    circle.bindTooltip(label).on("click", () => onSelect(value.id, null, { moveMap: false })).addTo(catalogueLayer);
                    const group = circles.get(value.id) ?? [];
                    group.push(circle);
                    circles.set(value.id, group);
                }
            }
            renderSelection();
        }
        function setSelection(value, focus = false) {
            selectedMarker?.remove();
            selectedMarker = null;
            selected = value;
            ui.evidence.hidden = value === null;
            ui.evidenceSources.replaceChildren();
            ui.evidenceQuote.textContent = "";
            if (!value) {
                renderSelection();
                return;
            }
            ui.evidenceTitle.textContent = value.title;
            const phase = value.phase;
            if (phase) {
                const date = (year) => year === null ? "未提供" : ArchSearchHistory.formatYear(year);
                const dates = phase.start_year === phase.end_year ? date(phase.start_year) : `${date(phase.start_year)} — ${date(phase.end_year)}`;
                const exact = phase.precision === "exact_year" && phase.start_year !== null && phase.start_year !== 0 && phase.start_year === phase.end_year;
                const precision = exact ? "明确单年事件" : phase.precision === "approximate_year" ? "约略年份，不推断单年"
                    : phase.precision === "range" ? "区间年代，不选取任意一年" : phase.precision === "period" ? "时期描述，未确定单年" : "来源日期未明确单年";
                ui.evidenceDate.textContent = `来源阶段：${phase.label} · ${dates} · ${precision}；实际背景见右图年份与联动状态。定位点不代表历史政治归属。`;
                ui.evidenceQuote.textContent = phase.sources[0]?.excerpt ?? "";
                for (const source of phase.sources) {
                    try {
                        const url = new URL(source.uri);
                        if (!["http:", "https:"].includes(url.protocol))
                            continue;
                        const link = document.createElement("a");
                        link.href = url.href;
                        link.textContent = source.title;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        ui.evidenceSources.append(link);
                    }
                    catch { /* Invalid source links remain available in the original record. */ }
                }
            }
            else
                ui.evidenceDate.textContent = `${value.status === "insufficient" ? "已核验但断代未确定" : "尚无经过核验的历史阶段"}；当前资料没有明确单年，实际背景见右图年份与联动状态。定位点不代表历史政治归属。`;
            ui.evidenceQuote.hidden = !ui.evidenceQuote.textContent;
            if (value.repr_point && ArchSearchMapView.locationStatus(value.repr_point) === "mapped") {
                if (!markers.has(value.id))
                    selectedMarker = attachMarker(value.id, value.title, value.repr_point, null);
                selectedMarker?.getElement()?.classList.add("is-selected");
                if (focus)
                    positionSelection(value.repr_point);
            }
            renderSelection();
        }
        function focusSelected({ preserveCamera = false } = {}) {
            if (preserveCamera || (modern === null && historical === null) || !selected?.repr_point || ArchSearchMapView.locationStatus(selected.repr_point) !== "mapped")
                return false;
            const coordinate = selected.repr_point;
            modernTouched = true;
            historicalTouched = true;
            cameraActions++;
            alignedLegacyZoom = false;
            render();
            positionSelection(coordinate);
            return modern !== null || historical !== null;
        }
        if (modern && historical) {
            modern.on("moveend", () => {
                if (syncing || restoringCameras)
                    return;
                const resized = sizeChanged(modern);
                syncFrom(modern, historical, sync && !resized);
                onChanged();
            });
            historical.on("moveend", () => {
                for (const marker of [...markers.values(), ...(selectedMarker ? [selectedMarker] : [])]) {
                    const value = marker.getLatLng();
                    const longitude = ArchSearchMapView.wrapLongitude(value.lng, historical.getCenter().lng);
                    if (value.lng !== longitude)
                        marker.setLatLng([value.lat, longitude]);
                }
                if (syncing || restoringCameras)
                    return;
                const resized = sizeChanged(historical);
                syncFrom(historical, modern, sync && !resized);
                onChanged();
            });
        }
        for (const [map, touch] of [[modern, () => { modernTouched = true; cameraActions++; alignedLegacyZoom = false; render(); }], [historical, () => { historicalTouched = true; cameraActions++; alignedLegacyZoom = false; render(); }]]) {
            if (!map)
                continue;
            map.on("dragstart", touch);
            for (const event of ["pointerdown", "wheel", "keydown"])
                map.getContainer().addEventListener(event, touch, { passive: true });
        }
        tiles?.on("tileerror", () => { if (requested !== "osm")
            return; failedTiles = true; ui.warning.hidden = false; ui.warningText.textContent = "现代 OSM 瓦片未能加载，正在切换本地自然轮廓；历史疆域独立保留。"; void naturalFallback(); });
        tiles?.on("tileload", () => { if (requested === "osm" && !failedTiles) {
            displayed = "osm";
            changed();
        } });
        ui.osm.addEventListener("click", () => setModernBasemap("osm"));
        ui.natural.addEventListener("click", () => setModernBasemap("natural"));
        ui.sync.addEventListener("change", () => {
            modernTouched = true;
            historicalTouched = true;
            cameraActions++;
            alignedLegacyZoom = false;
            sync = ui.sync.checked;
            if (modern && historical)
                syncFrom(modern, historical);
            changed();
        });
        ui.evidenceOpen.addEventListener("click", onEvidence);
        restoreViews();
        if (typeof ResizeObserver !== "undefined") {
            const observer = new ResizeObserver(() => { modern?.invalidateSize({ pan: true, animate: false }); historical?.invalidateSize({ pan: true, animate: false }); });
            if (modern)
                observer.observe(modern.getContainer());
            if (historical)
                observer.observe(historical.getContainer());
        }
        render();
        if (requested === "natural")
            void naturalFallback();
        else
            void ensureLand().catch(() => undefined);
        return {
            setCandidates, fitCandidates, setCatalogue, setSelection, focusSelected, setModernBasemap,
            getHistoricalRenderer: () => sourceRenderer,
            noteInteraction() { modernTouched = true; historicalTouched = true; cameraActions++; alignedLegacyZoom = false; render(); },
            actionVersion: () => cameraActions,
            restoreInitialViews: restoreViews,
            getMarker: (id) => markers.get(id) ?? null,
            state: () => ({ modern_basemap: displayed === "natural" ? "natural" : "osm", sync_centers: sync, modern_view: camera(modern), history_view: camera(historical) }),
            snapshot: (view) => ({
                layout: (typeof window !== "undefined" && window.matchMedia("(max-width: 620px)").matches ? "stacked" : "side-by-side"), sync_centers: sync,
                modern: { role: "modern-location", basemap: displayed, view: camera(modern) },
                historical: { role: "historical-polities", basemap: view ? "natural" : null, view: camera(historical),
                    year: view?.year ?? null, boundaries: view?.boundaries ?? false, frame_id: view?.frame_id ?? null, source_version: view?.source_version ?? null },
            }),
        };
    }
    return { create, camera };
})();
//# sourceMappingURL=comparison.js.map
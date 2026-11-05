"use strict";
const ArchSearchComparison = (() => {
    "use strict";
    function camera(map) {
        if (!map)
            return null;
        const center = map.getCenter();
        return { center: [ArchSearchMapView.wrapLongitude(center.lng, 0), Math.max(-85.0511287798, Math.min(85.0511287798, center.lat))], zoom: map.getZoom() };
    }
    function regionZoom(zoom) { return Math.min(5, Math.max(1, zoom)); }
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
        let failedTiles = false;
        let land = null;
        let landPromise = null;
        let selected = null;
        let selectedMarker = null;
        let cameraActions = 0;
        let modernTouched = false, historicalTouched = false;
        let catalogueSignature = "";
        let candidateValues = [];
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
        function syncFrom(source, destination, regional) {
            if (!sync || syncing)
                return;
            const center = source.getCenter();
            const other = destination.getCenter();
            const longitude = ArchSearchMapView.wrapLongitude(center.lng, other.lng);
            const zoom = regional ? regionZoom(destination.getZoom()) : destination.getZoom();
            if (Math.abs(center.lat - other.lat) < 1e-7 && Math.abs(longitude - other.lng) < 1e-7 && zoom === destination.getZoom())
                return;
            syncing = true;
            try {
                destination.stop();
                destination.setView([center.lat, longitude], zoom, { animate: false });
            }
            finally {
                syncing = false;
            }
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
            if (!historical)
                return;
            const coordinates = candidateValues.filter((item) => ArchSearchMapView.locationStatus(item.repr_point) === "mapped").map((item) => [item.repr_point[1], item.repr_point[0]]);
            if (coordinates.length)
                historical.fitBounds(L.latLngBounds(ArchSearchMapView.wrapCoordinates(coordinates)), { maxZoom: 4, padding: [35, 35], animate: false });
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
                ui.evidenceDate.textContent = `${phase.label} · ${dates} · ${exact ? "明确单年事件，历史背景自动联动，实际图年见右图" : "约略／区间证据，不推断年份；保留最后成功的历史背景"}`;
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
                ui.evidenceDate.textContent = value.status === "insufficient" ? "已核验但断代未确定；不推断年份，保留最后成功的历史背景。" : "尚无经过核验的历史阶段；不推断年份，保留最后成功的历史背景。";
            ui.evidenceQuote.hidden = !ui.evidenceQuote.textContent;
            if (value.repr_point && ArchSearchMapView.locationStatus(value.repr_point) === "mapped") {
                if (!markers.has(value.id))
                    selectedMarker = attachMarker(value.id, value.title, value.repr_point, null);
                selectedMarker?.getElement()?.classList.add("is-selected");
                if (focus && historical)
                    historical.setView([value.repr_point[1], ArchSearchMapView.wrapLongitude(value.repr_point[0], historical.getCenter().lng)], 4, { animate: false });
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
            if (modern) {
                modern.stop();
                modern.setView([coordinate[1], ArchSearchMapView.wrapLongitude(coordinate[0], modern.getCenter().lng)], 15, { animate: false });
            }
            if (historical) {
                historical.stop();
                historical.setView([coordinate[1], ArchSearchMapView.wrapLongitude(coordinate[0], historical.getCenter().lng)], 4, { animate: false });
            }
            return modern !== null || historical !== null;
        }
        if (modern && historical) {
            modern.on("moveend", () => { syncFrom(modern, historical, true); onChanged(); });
            historical.on("moveend", () => {
                for (const marker of [...markers.values(), ...(selectedMarker ? [selectedMarker] : [])]) {
                    const value = marker.getLatLng();
                    const longitude = ArchSearchMapView.wrapLongitude(value.lng, historical.getCenter().lng);
                    if (value.lng !== longitude)
                        marker.setLatLng([value.lat, longitude]);
                }
                syncFrom(historical, modern, false);
                onChanged();
            });
            modern.on("zoomend", onChanged);
            historical.on("zoomend", onChanged);
        }
        for (const [map, touch] of [[modern, () => { modernTouched = true; cameraActions++; }], [historical, () => { historicalTouched = true; cameraActions++; }]]) {
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
        ui.sync.addEventListener("change", () => { sync = ui.sync.checked; if (sync && modern && historical)
            syncFrom(modern, historical, true); changed(); });
        ui.evidenceOpen.addEventListener("click", onEvidence);
        for (const [map, view] of [[modern, initial.modern_view], [historical, initial.history_view]])
            if (map && view)
                map.setView([view.center[1], view.center[0]], view.zoom, { animate: false });
        if (typeof ResizeObserver !== "undefined") {
            const observer = new ResizeObserver(() => { modern?.invalidateSize({ pan: false }); historical?.invalidateSize({ pan: false }); });
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
            noteInteraction() { modernTouched = true; historicalTouched = true; cameraActions++; },
            actionVersion: () => cameraActions,
            restoreInitialViews() {
                if (modern && initial.modern_view && !modernTouched)
                    modern.setView([initial.modern_view.center[1], initial.modern_view.center[0]], initial.modern_view.zoom, { animate: false });
                if (historical && initial.history_view && !historicalTouched)
                    historical.setView([initial.history_view.center[1], initial.history_view.center[0]], initial.history_view.zoom, { animate: false });
            },
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
    return { create, camera, regionZoom };
})();
//# sourceMappingURL=comparison.js.map
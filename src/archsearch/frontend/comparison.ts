const ArchSearchComparison = (() => {
  "use strict";

  interface Camera { center: [number, number]; zoom: number }
  interface State { modern_basemap: "osm" | "natural"; sync_centers: boolean; modern_view: Camera | null; history_view: Camera | null }
  interface Candidate { id: string; title: string; repr_point: [number, number] | null; rank: number }
  interface Placement { id: string; title: string; coordinate: [number, number]; representative: boolean }
  interface Phase { label: string; precision: string; start_year: number | null; end_year: number | null; sources: { title: string; uri: string; excerpt: string }[] }
  interface Selected { id: string; title: string; repr_point: [number, number] | null; status: string; phase: Phase | null }
  interface Options {
    modern: L.Map | null;
    historical: L.Map | null;
    tiles: L.TileLayer | null;
    initial: State;
    onSelect(id: string, opener: HTMLElement | null, options?: { moveMap?: boolean }): void;
    onChanged(): void;
    onEvidence(): void;
  }

  const latitudeLimit = 85.0511287798;
  const cameraTolerance = 1e-7;

  function settledCenter(latitude: number, longitude: number): L.LatLngTuple {
    return [Math.max(-latitudeLimit, Math.min(latitudeLimit, latitude)), ArchSearchMapView.wrapLongitude(longitude, 0)];
  }

  function camera(map: L.Map | null): Camera | null {
    if (!map) return null;
    const center = map.getCenter();
    const [latitude, longitude] = settledCenter(center.lat, center.lng);
    return { center: [longitude, latitude], zoom: map.getZoom() };
  }

  function sharedZoom(zoom: number): number { return Math.min(9, Math.max(1, zoom)); }

  function create({ modern, historical, tiles, initial, onSelect, onChanged, onEvidence }: Options) {
    const byId = <T extends HTMLElement>(id: string): T => {
      const node = document.getElementById(id);
      if (!node) throw new Error(`对照地图控件不存在：${id}`);
      return node as T;
    };
    const optionalById = <T extends HTMLElement>(id: string): T | null => document.getElementById(id) as T | null;
    const ui = {
      osm: byId<HTMLButtonElement>("modern-basemap-osm"), natural: byId<HTMLButtonElement>("modern-basemap-natural"),
      sync: byId<HTMLInputElement>("comparison-sync"), modernStatus: byId<HTMLElement>("comparison-modern-status"),
      modernBadge: optionalById<HTMLElement>("comparison-modern-badge"),
      warning: byId<HTMLElement>("tile-warning"), warningText: byId<HTMLElement>("tile-warning-text"),
      evidence: optionalById<HTMLElement>("comparison-evidence"), evidenceTitle: optionalById<HTMLElement>("comparison-evidence-title"),
      evidenceDate: optionalById<HTMLElement>("comparison-evidence-date"), evidenceQuote: optionalById<HTMLElement>("comparison-evidence-quote"),
      evidenceSources: optionalById<HTMLElement>("comparison-evidence-sources"), evidenceOpen: optionalById<HTMLButtonElement>("comparison-evidence-open"),
    };
    let requested: State["modern_basemap"] = initial.modern_basemap;
    let displayed: "osm" | "natural" | "loading" | "unavailable" = modern ? "loading" : "unavailable";
    let sync = initial.sync_centers;
    let syncing = false;
    let restoringCameras = false;
    let resizing = false;
    let activeDrag: L.Map | null = null;
    const restoredZoom = sharedZoom(initial.history_view?.zoom ?? initial.modern_view?.zoom ?? historical?.getZoom() ?? modern?.getZoom() ?? 1);
    let alignedLegacyZoom = [initial.modern_view, initial.history_view].some(view => view !== null && view.zoom !== restoredZoom);
    let failedTiles = false;
    let loadedTiles = 0;
    let consecutiveTileErrors = 0;
    let tileGeneration = 0;
    let land: L.GeoJSON | null = null;
    let landPromise: Promise<void> | null = null;
    let selected: Selected | null = null;
    let selectedMarker: L.Marker | null = null;
    let cameraActions = 0;
    let modernTouched = false, historicalTouched = false;
    let catalogueSignature = "";
    let candidateValues: Candidate[] = [];
    const mapSizes = new Map<L.Map, { x: number; y: number }>();
    function recordMapSizes(): void {
      for (const map of [modern, historical]) if (map) {
        const size = map.getSize();
        mapSizes.set(map, { x: size.x, y: size.y });
      }
    }
    recordMapSizes();
    const markers = new Map<string, L.Marker>();
    const candidateLayer = historical && typeof L !== "undefined" ? L.layerGroup().addTo(historical) : null;
    let sourceRenderer: L.Canvas | null = null;
    if (historical && typeof L !== "undefined") {
      const pane = historical.getPane("history-boundaries") ?? historical.createPane("history-boundaries");
      pane.style.zIndex = "350";
      sourceRenderer = L.canvas({ pane: "history-boundaries" });
    }
    const density = historical && sourceRenderer && typeof ArchSearchDensity !== "undefined"
      ? ArchSearchDensity.create({ map: historical, pane: "history-boundaries", renderer: sourceRenderer, cellSize: 128, cluster: false,
        onSelect: (id, opener) => onSelect(id, opener, { moveMap: false }) })
      : null;
    const catalogueLayer = density?.layer.addTo(historical!) ?? null;
    if (modern) {
      const pane = modern.getPane("comparison-modern-land") ?? modern.createPane("comparison-modern-land");
      pane.style.zIndex = "190"; pane.style.pointerEvents = "none";
    }
    function changed(): void { render(); onChanged(); }
    function render(): void {
      ui.osm.disabled = modern === null; ui.natural.disabled = modern === null;
      ui.osm.setAttribute("aria-pressed", String(requested === "osm"));
      ui.natural.setAttribute("aria-pressed", String(requested === "natural"));
      ui.sync.checked = sync; ui.sync.disabled = modern === null || historical === null;
      ui.modernStatus.textContent = displayed === "osm" ? "OpenStreetMap · 当前现代位置参照"
        : displayed === "natural" ? failedTiles && requested === "osm" ? "OSM 不可用 · 已显示本地自然轮廓" : "本地自然轮廓 · 现代地理参照"
        : displayed === "loading" ? "正在加载现代底图；定位点可独立使用" : "现代底图暂不可用，定位点与资料仍保留";
      if (alignedLegacyZoom) ui.modernStatus.textContent += ` · 旧链接缩放已统一为 ${restoredZoom} 级，分别保留两图中心`;
      if (ui.modernBadge) {
        ui.modernBadge.textContent = displayed === "osm" ? "现代 OSM"
          : displayed === "natural" ? "本地自然轮廓"
          : displayed === "loading" ? "底图加载中" : "底图暂不可用";
        ui.modernBadge.dataset.basemap = displayed;
      }
      if (modern) {
        const container = modern.getContainer();
        const changedBasemap = container.dataset.basemap !== displayed;
        container.dataset.basemap = displayed;
        if (changedBasemap) modern.fire("archsearch:basemapchange", { basemap: displayed });
      }
    }
    async function ensureLand(): Promise<void> {
      if (land) return;
      if (landPromise) return landPromise;
      landPromise = (async () => {
        const response = await fetch("/static/data/land.geojson", { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("本地自然地理轮廓读取失败。");
        const value: unknown = await response.json();
        const validate: (input: unknown) => void = ArchSearchHistory.validateCollection;
        validate(value);
        if (!modern || typeof L === "undefined") return;
        const next = L.geoJSON(ArchSearchHistory.worldCopies(value), { pane: "comparison-modern-land", interactive: false,
          attribution: "Natural Earth · Public Domain", style: { fillColor: "#eee9dc", fillOpacity: 1, color: "#9ca998", weight: 0.8 } });
        next.addTo(modern); land = next;
      })().finally(() => { landPromise = null; });
      return landPromise;
    }
    async function naturalFallback(): Promise<void> {
      try {
        await ensureLand();
        if (!modern || !land || (requested === "osm" && !failedTiles)) return;
        if (tiles && modern.hasLayer(tiles)) modern.removeLayer(tiles);
        displayed = "natural"; if (requested === "natural") ui.warning.hidden = true; changed();
      } catch {
        if (displayed !== "osm") displayed = "unavailable";
        ui.warning.hidden = false; ui.warningText.textContent = "本地自然轮廓未能读取；保留可用底图与资料标记。"; changed();
      }
    }
    function rotateOsmSubdomain(src: string): string {
      const order = ["a", "b", "c"];
      return src.replace(/^(https:\/\/)([abc])(\.tile\.openstreetmap\.org\/)/u, (_match, prefix: string, host: string, suffix: string) => {
        const next = order[(order.indexOf(host) + 1) % order.length];
        return `${prefix}${next}${suffix}`;
      });
    }
    function setModernBasemap(value: State["modern_basemap"]): void {
      requested = value;
      tileGeneration++;
      loadedTiles = 0;
      consecutiveTileErrors = 0;
      if (value === "natural") { ui.warning.hidden = true; void naturalFallback(); }
      else if (modern && tiles) {
        failedTiles = false; displayed = "loading"; ui.warning.hidden = true;
        if (!modern.hasLayer(tiles)) tiles.addTo(modern);
        tiles.redraw();
      }
      changed();
    }
    function applyCamera(map: L.Map, center: L.LatLngTuple, zoom: number): void {
      const actual = map.getCenter();
      const longitudeDelta = Math.abs(center[1] - actual.lng);
      if (Math.abs(center[0] - actual.lat) < cameraTolerance && longitudeDelta < cameraTolerance && zoom === map.getZoom()) return;
      // Leaflet can resolve a same-zoom correction to a zero-pixel pan at the projection limit.
      const reset = Math.abs(actual.lat) > latitudeLimit + cameraTolerance || longitudeDelta > 180;
      const options = { animate: false, reset };
      map.setView(center, zoom, options);
    }
    function syncFrom(source: L.Map, destination: L.Map | null, copyCenter = sync): void {
      if (syncing || restoringCameras) return;
      const actual = source.getCenter();
      const center = settledCenter(actual.lat, actual.lng);
      const zoom = sharedZoom(source.getZoom());
      syncing = true;
      try {
        applyCamera(source, center, zoom);
        if (destination) {
          const other = destination.getCenter();
          applyCamera(destination, copyCenter ? center : [other.lat, other.lng], zoom);
        }
      }
      finally { syncing = false; }
    }
    function hasSizeChanged(map: L.Map): boolean {
      const next = map.getSize(), previous = mapSizes.get(map);
      return previous !== undefined && (previous.x !== next.x || previous.y !== next.y);
    }
    function sizeChanged(map: L.Map): boolean {
      const changed = hasSizeChanged(map);
      const next = map.getSize();
      mapSizes.set(map, { x: next.x, y: next.y });
      return changed;
    }
    function invalidateSizes(): void {
      resizing = true;
      try {
        modern?.invalidateSize({ pan: true, animate: false });
        historical?.invalidateSize({ pan: true, animate: false });
      } finally {
        recordMapSizes();
        resizing = false;
      }
    }
    function prefersReducedMotion(): boolean {
      return typeof window !== "undefined" && typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }
    function shouldAnimateZoom(map: L.Map | null): boolean {
      return map !== null && !prefersReducedMotion() && !Boolean((map as unknown as { _animatingZoom?: boolean })._animatingZoom);
    }
    const animatingPartners = new Set<L.Map>();
    const partnerTimers = new Map<L.Map, ReturnType<typeof setTimeout>>();
    function clearPartnerAnimating(map: L.Map): void {
      animatingPartners.delete(map);
      const timer = partnerTimers.get(map);
      if (timer !== undefined) {
        clearTimeout(timer);
        partnerTimers.delete(map);
      }
    }
    function markPartnerAnimating(map: L.Map): void {
      clearPartnerAnimating(map);
      animatingPartners.add(map);
      partnerTimers.set(map, setTimeout(() => clearPartnerAnimating(map), 350));
    }
    function syncZoomAnim(source: L.Map, destination: L.Map | null, event: L.ZoomAnimEvent): void {
      if (syncing || restoringCameras || resizing || !destination || animatingPartners.has(source)) return;
      const targetZoom = sharedZoom(event.zoom);
      const other = destination.getCenter();
      const targetCenter = sync ? settledCenter(event.center.lat, event.center.lng) : settledCenter(other.lat, other.lng);
      const longitudeDelta = Math.abs(targetCenter[1] - other.lng);
      if (Math.abs(targetCenter[0] - other.lat) < cameraTolerance && longitudeDelta < cameraTolerance && targetZoom === destination.getZoom()) return;
      syncing = true;
      markPartnerAnimating(destination);
      try {
        destination.setView(targetCenter, targetZoom, { animate: shouldAnimateZoom(destination) });
      } finally {
        syncing = false;
      }
    }
    function syncLive(source: L.Map, destination: L.Map | null): void {
      if (syncing || restoringCameras || resizing || !destination || animatingPartners.has(source) || animatingPartners.has(destination)) return;
      if (activeDrag !== source && hasSizeChanged(source)) {
        sizeChanged(source);
        return;
      }
      const actual = source.getCenter();
      const zoom = sharedZoom(source.getZoom());
      const other = destination.getCenter();
      const targetCenter: L.LatLngTuple = sync
        ? [Math.max(-latitudeLimit, Math.min(latitudeLimit, actual.lat)), actual.lng]
        : [other.lat, other.lng];
      syncing = true;
      try {
        applyCamera(destination, targetCenter, zoom);
      } finally { syncing = false; }
    }
    function finishMove(source: L.Map, destination: L.Map | null): void {
      if (animatingPartners.has(source)) {
        clearPartnerAnimating(source);
        return;
      }
      if (syncing || restoringCameras) return;
      if (resizing) {
        sizeChanged(source);
        return;
      }
      const resized = activeDrag !== source && sizeChanged(source);
      syncFrom(source, destination, sync && !resized);
      onChanged();
    }
    function positionSelection(coordinate: [number, number]): void {
      syncing = true;
      try {
        for (const map of [modern, historical]) if (map) {
          map.stop(); map.setView(settledCenter(coordinate[1], coordinate[0]), 4, { animate: shouldAnimateZoom(map) });
        }
      } finally { syncing = false; }
      for (const map of [modern, historical]) if (map) sizeChanged(map);
      onChanged();
    }
    function restoreViews(): void {
      if ((initial.modern_view === null && initial.history_view === null) || modernTouched || historicalTouched) return;
      restoringCameras = true;
      try {
        for (const [map, view] of [[modern, initial.modern_view], [historical, initial.history_view]] as const) if (map) {
          const actual = map.getCenter();
          const center = view ? settledCenter(view.center[1], view.center[0]) : settledCenter(actual.lat, actual.lng);
          map.setView(center, restoredZoom, { animate: false });
        }
      } finally { restoringCameras = false; }
      for (const map of [modern, historical]) if (map) sizeChanged(map);
    }
    function attachMarker(id: string, title: string, coordinate: [number, number], rank: number | null): L.Marker | null {
      if (!historical || !candidateLayer) return null;
      const content = document.createElement("span"); content.className = "site-marker"; content.textContent = rank === null ? "选" : String(rank);
      content.setAttribute("aria-hidden", "true");
      const marker = L.marker([coordinate[1], ArchSearchMapView.wrapLongitude(coordinate[0], historical.getCenter().lng)], {
        icon: L.divIcon({ className: "site-marker-icon comparison-history-marker", html: content, iconSize: [30, 30], iconAnchor: [15, 15] }),
        keyboard: true, autoPanOnFocus: false, title,
      }).addTo(candidateLayer);
      const label = document.createElement("span"); label.textContent = title; marker.bindTooltip(label, { direction: "top", offset: [0, -13] });
      marker.on("click", () => onSelect(id, marker.getElement() ?? null));
      const icon = marker.getElement();
      icon?.setAttribute("aria-label", `历史图${rank === null ? "选中地点" : `候选 ${rank}`}：${title}，打开来源资料`);
      icon?.addEventListener("keydown", (event) => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); event.stopPropagation(); marker.fire("click"); } });
      return marker;
    }
    function renderSelection(): void {
      for (const [id, marker] of markers) {
        const active = id === selected?.id; marker.getElement()?.classList.toggle("is-selected", active);
        marker.getElement()?.setAttribute("aria-pressed", String(active)); marker.setZIndexOffset(active ? 1500 : 0);
      }
      density?.select(selected?.id ?? null);
      historical?.fire("archsearch:markerschange");
    }
    function setCandidates(values: Candidate[], fit = true): void {
      candidateValues = values;
      candidateLayer?.clearLayers(); selectedMarker = null; markers.clear();
      for (const value of values) if (ArchSearchMapView.locationStatus(value.repr_point) === "mapped" && value.repr_point) {
        const marker = attachMarker(value.id, value.title, value.repr_point, value.rank); if (marker) markers.set(value.id, marker);
      }
      if (fit) fitCandidates();
      renderSelection();
    }
    function fitCandidates(): void {
      const maps = [modern, historical].filter((map): map is L.Map => map !== null);
      if (!maps.length) return;
      const coordinates = candidateValues.filter((item) => ArchSearchMapView.locationStatus(item.repr_point) === "mapped").map((item): L.LatLngTuple => [item.repr_point![1], item.repr_point![0]]);
      syncing = true;
      try {
        let center = { lat: 20, lng: 0 }, zoom = 1;
        if (coordinates.length) {
          const bounds = L.latLngBounds(ArchSearchMapView.wrapCoordinates(coordinates));
          zoom = sharedZoom(Math.min(4, ...maps.map(map => map.getBoundsZoom(bounds, false, L.point(70, 70)))));
          const reference = maps[0];
          reference.stop(); reference.fitBounds(bounds, { maxZoom: zoom, padding: [35, 35], animate: false });
          center = reference.getCenter();
        }
        for (const map of maps) {
          map.stop(); map.setView(settledCenter(center.lat, center.lng), zoom, { animate: false });
        }
      } finally { syncing = false; }
      for (const map of maps) sizeChanged(map);
      onChanged();
    }
    function setCatalogue(values: Placement[], visible: boolean): void {
      const signature = visible ? JSON.stringify(values) : "hidden";
      if (signature === catalogueSignature) return;
      catalogueSignature = signature;
      if (!historical || !catalogueLayer || !density) return;
      density.setData(values);
      if (visible && !historical.hasLayer(catalogueLayer)) catalogueLayer.addTo(historical);
      else if (!visible && historical.hasLayer(catalogueLayer)) historical.removeLayer(catalogueLayer);
      renderSelection();
    }
    function setSelection(value: Selected | null, focus = false): void {
      selectedMarker?.remove(); selectedMarker = null; selected = value;
      if (ui.evidence) ui.evidence.hidden = value === null;
      ui.evidenceSources?.replaceChildren();
      if (ui.evidenceQuote) ui.evidenceQuote.textContent = "";
      if (!value) { renderSelection(); return; }
      if (ui.evidenceTitle) ui.evidenceTitle.textContent = value.title;
      const phase = value.phase;
      if (phase) {
        const date = (year: number | null) => year === null ? "未提供" : ArchSearchHistory.formatYear(year);
        const dates = phase.start_year === phase.end_year ? date(phase.start_year) : `${date(phase.start_year)} — ${date(phase.end_year)}`;
        const exact = phase.precision === "exact_year" && phase.start_year !== null && phase.start_year !== 0 && phase.start_year === phase.end_year;
        const precision = exact ? "明确单年事件" : phase.precision === "approximate_year" ? "约略年份，不推断单年"
          : phase.precision === "range" ? "区间年代，不选取任意一年" : phase.precision === "period" ? "时期描述，未确定单年" : "来源日期未明确单年";
        if (ui.evidenceDate) ui.evidenceDate.textContent = `来源阶段：${phase.label} · ${dates} · ${precision}；实际背景见右图年份与联动状态。定位点不代表历史政治归属。`;
        if (ui.evidenceQuote) ui.evidenceQuote.textContent = phase.sources[0]?.excerpt ?? "";
        if (ui.evidenceSources) {
          for (const source of phase.sources) {
            try {
              const url = new URL(source.uri); if (!["http:", "https:"].includes(url.protocol)) continue;
              const link = document.createElement("a"); link.href = url.href; link.textContent = source.title; link.target = "_blank"; link.rel = "noopener noreferrer"; ui.evidenceSources.append(link);
            } catch { /* Invalid source links remain available in the original record. */ }
          }
        }
      } else if (ui.evidenceDate) {
        ui.evidenceDate.textContent = `${value.status === "insufficient" ? "已核验但断代未确定" : "尚无经过核验的历史阶段"}；当前资料没有明确单年，实际背景见右图年份与联动状态。定位点不代表历史政治归属。`;
      }
      if (ui.evidenceQuote) ui.evidenceQuote.hidden = !ui.evidenceQuote.textContent;
      if (value.repr_point && ArchSearchMapView.locationStatus(value.repr_point) === "mapped") {
        if (!markers.has(value.id)) selectedMarker = attachMarker(value.id, value.title, value.repr_point, null);
        selectedMarker?.getElement()?.classList.add("is-selected");
        if (focus) positionSelection(value.repr_point);
      }
      renderSelection();
    }
    function focusSelected({ preserveCamera = false }: { preserveCamera?: boolean } = {}): boolean {
      if (preserveCamera || (modern === null && historical === null) || !selected?.repr_point || ArchSearchMapView.locationStatus(selected.repr_point) !== "mapped") return false;
      const coordinate = selected.repr_point;
      modernTouched = true; historicalTouched = true; cameraActions++;
      alignedLegacyZoom = false; render();
      positionSelection(coordinate);
      return modern !== null || historical !== null;
    }
    if (modern) {
      modern.on("zoomanim", (event: L.ZoomAnimEvent) => syncZoomAnim(modern, historical, event));
      modern.on("drag move zoom", () => syncLive(modern, historical));
      modern.on("resize", () => { sizeChanged(modern); });
      modern.on("moveend", () => finishMove(modern, historical));
    }
    if (historical) {
      historical.on("zoomanim", (event: L.ZoomAnimEvent) => syncZoomAnim(historical, modern, event));
      historical.on("drag move zoom", () => syncLive(historical, modern));
      historical.on("resize", () => { sizeChanged(historical); });
      historical.on("moveend", () => {
        for (const marker of [...markers.values(), ...(selectedMarker ? [selectedMarker] : [])]) {
          const value = marker.getLatLng(); const longitude = ArchSearchMapView.wrapLongitude(value.lng, historical.getCenter().lng);
          if (value.lng !== longitude) marker.setLatLng([value.lat, longitude]);
        }
        finishMove(historical, modern);
      });
    }
    for (const [map, other, touch] of [
      [modern, historical, () => { modernTouched = true; cameraActions++; alignedLegacyZoom = false; render(); }],
      [historical, modern, () => { historicalTouched = true; cameraActions++; alignedLegacyZoom = false; render(); }],
    ] as const) {
      if (!map) continue;
      map.on("dragstart", () => {
        clearPartnerAnimating(map);
        activeDrag = map;
        recordMapSizes();
        other?.stop();
        touch();
      });
      map.on("dragend", () => {
        if (activeDrag === map) activeDrag = null;
      });
      for (const event of ["pointerdown", "wheel", "keydown"]) map.getContainer().addEventListener(event, touch, { passive: true });
    }
    tiles?.on("tileerror", (event?: { tile?: HTMLImageElement }) => {
      if (requested !== "osm" || (modern && !modern.hasLayer(tiles))) return;
      const tile = event?.tile;
      if (tile && tile.isConnected === false) return;
      if (tile && tile.dataset && tile.dataset.archsearchRetry !== "1" && typeof tile.src === "string" && /^https:\/\/[abc]\.tile\.openstreetmap\.org\//u.test(tile.src)) {
        tile.dataset.archsearchRetry = "1";
        const generation = tileGeneration;
        const nextSrc = rotateOsmSubdomain(tile.src);
        if (typeof setTimeout === "function") {
          setTimeout(() => {
            if (generation === tileGeneration && requested === "osm" && (!modern || modern.hasLayer(tiles)) && tile.isConnected !== false) {
              tile.src = nextSrc;
            }
          }, 500);
        }
        return;
      }
      consecutiveTileErrors++;
      const threshold = loadedTiles > 0 ? 4 : tile ? 2 : 1;
      if (consecutiveTileErrors < threshold) return;
      failedTiles = true;
      ui.warning.hidden = false;
      ui.warningText.textContent = "现代 OSM 瓦片未能加载，正在切换本地自然轮廓；历史疆域独立保留。";
      void naturalFallback();
    });
    tiles?.on("tileload", () => {
      loadedTiles++;
      consecutiveTileErrors = 0;
      if (requested !== "osm") return;
      const alreadyDisplayed = displayed === "osm" && !failedTiles && ui.warning.hidden;
      failedTiles = false;
      displayed = "osm";
      ui.warning.hidden = true;
      if (!alreadyDisplayed) changed();
    });
    ui.osm.addEventListener("click", () => setModernBasemap("osm"));
    ui.natural.addEventListener("click", () => setModernBasemap("natural"));
    ui.sync.addEventListener("change", () => {
      modernTouched = true; historicalTouched = true; cameraActions++; alignedLegacyZoom = false;
      sync = ui.sync.checked;
      if (modern && historical) syncFrom(modern, historical);
      changed();
    });
    ui.evidenceOpen?.addEventListener("click", onEvidence);
    restoreViews();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => { invalidateSizes(); });
      if (modern) observer.observe(modern.getContainer()); if (historical) observer.observe(historical.getContainer());
    }
    render(); if (requested === "natural") void naturalFallback(); else void ensureLand().catch(() => undefined);
    return {
      setCandidates, fitCandidates, setCatalogue, setSelection, focusSelected, setModernBasemap, invalidateSizes,
      getHistoricalRenderer: (): L.Canvas | null => sourceRenderer,
      noteInteraction(): void { modernTouched = true; historicalTouched = true; cameraActions++; alignedLegacyZoom = false; render(); },
      actionVersion: (): number => cameraActions,
      restoreInitialViews: restoreViews,
      getMarker: (id: string): L.Marker | null => markers.get(id) ?? null,
      state: (): State => ({ modern_basemap: displayed === "natural" ? "natural" : "osm", sync_centers: sync, modern_view: camera(modern), history_view: camera(historical) }),
      snapshot: (view: { year: number; boundaries: boolean; frame_id: string | null; source_version: string | null } | null) => ({
        layout: (typeof window !== "undefined" && window.matchMedia("(max-width: 620px)").matches ? "stacked" : "side-by-side") as "side-by-side" | "stacked", sync_centers: sync,
        modern: { role: "modern-location" as const, basemap: displayed, view: camera(modern) },
        historical: { role: "historical-polities" as const, basemap: view ? "natural" as const : null, view: camera(historical),
          year: view?.year ?? null, boundaries: view?.boundaries ?? false, frame_id: view?.frame_id ?? null, source_version: view?.source_version ?? null },
      }),
    };
  }
  return { create, camera };
})();

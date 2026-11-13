const ArchSearchDensity = (() => {
  "use strict";

  interface Placement {
    id: string;
    title: string;
    coordinate: [number, number];
    representative: boolean;
    tooltip?(): HTMLElement;
  }
  interface Pixel { x: number; y: number }
  interface Viewport { origin: Pixel; width: number; height: number; worldWidth: number; cellSize?: number; selectedId?: string | null }
  interface Item { value: Placement; coordinate: [number, number]; pixel: Pixel; copy: number }
  interface Group { key: string; items: Item[]; pixel: Pixel; focusPixel: Pixel; copy: number }
  interface Options {
    map: L.Map;
    pane: string;
    renderer?: L.Canvas;
    cellSize?: number;
    onSelect(id: string, opener: HTMLElement): void;
  }
  interface Symbol { layer: L.Layer; circle?: L.CircleMarker; marker?: L.Marker; count?: HTMLElement }

  function valid(value: unknown): value is [number, number] {
    return Array.isArray(value) && value.length === 2 && value.every(item => typeof item === "number" && Number.isFinite(item))
      && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 85.0511287798;
  }

  function plan(values: readonly Placement[], project: (coordinate: [number, number]) => Pixel, viewport: Viewport): Group[] {
    const { origin, width, height, worldWidth, selectedId = null } = viewport;
    const cellSize = viewport.cellSize ?? 48;
    if (![origin.x, origin.y, width, height, worldWidth, cellSize].every(Number.isFinite)
      || width <= 0 || height <= 0 || worldWidth <= 0 || cellSize < 24) return [];
    const bins = new Map<string, Item[]>();
    const seen = new Set<string>();
    for (const value of values) {
      if (!valid(value.coordinate)) continue;
      const identity = JSON.stringify([value.id, ...value.coordinate]);
      if (seen.has(identity)) continue;
      seen.add(identity);
      const point = project(value.coordinate);
      if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) continue;
      const firstCopy = Math.ceil((origin.x - cellSize * 2 - point.x) / worldWidth);
      const lastCopy = Math.floor((origin.x + width + cellSize * 2 - point.x) / worldWidth);
      for (let copy = firstCopy; copy <= lastCopy; copy++) {
        const pixel = { x: point.x + copy * worldWidth, y: point.y };
        const x = Math.floor(pixel.x / cellSize), y = Math.floor(pixel.y / cellSize);
        if ((x + 1) * cellSize < origin.x - cellSize || x * cellSize > origin.x + width + cellSize
          || (y + 1) * cellSize < origin.y - cellSize || y * cellSize > origin.y + height + cellSize) continue;
        const key = value.id === selectedId ? `selected:${identity}:${copy}` : `${x}:${y}`;
        const items = bins.get(key) ?? [];
        items.push({ value, coordinate: [value.coordinate[0] + copy * 360, value.coordinate[1]], pixel, copy });
        bins.set(key, items);
      }
    }
    const selectedPixels = [...bins.values()].flatMap(items => items.filter(item => item.value.id === selectedId).map(item => item.pixel));
    return [...bins].flatMap(([key, items]): Group[] => {
      const focusPixel = { x: items.reduce((sum, item) => sum + item.pixel.x, 0) / items.length,
        y: items.reduce((sum, item) => sum + item.pixel.y, 0) / items.length };
      const pixel = items.length > 1 ? { x: (Math.floor(items[0].pixel.x / cellSize) + 0.5) * cellSize,
        y: (Math.floor(items[0].pixel.y / cellSize) + 0.5) * cellSize } : focusPixel;
      if (items.length > 1 && selectedPixels.some(point => Math.hypot(point.x - pixel.x, point.y - pixel.y) < 28)) {
        return items.map((item, index) => ({ key: `${key}:near-selection:${index}`, items: [item], pixel: item.pixel, focusPixel: item.pixel, copy: item.copy }));
      }
      return [{ key, items, pixel, focusPixel, copy: items[0].copy }];
    });
  }

  function members(group: Pick<Group, "items">): Placement[] {
    const unique = new Map<string, Placement>();
    for (const item of group.items) if (!unique.has(item.value.id)) unique.set(item.value.id, item.value);
    return [...unique.values()].sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
  }

  function create({ map, pane, renderer, cellSize = 48, onSelect }: Options) {
    const layer = L.layerGroup();
    const clusterPane = map.getPane("catalogue-density-clusters") ?? map.createPane("catalogue-density-clusters");
    clusterPane.style.zIndex = "460";
    const popupPane = map.getPane("catalogue-density-popup") ?? map.createPane("catalogue-density-popup", map.getContainer());
    popupPane.style.zIndex = "1100"; popupPane.style.pointerEvents = "none";
    const popupPaneEvents = "move zoom resize zoomanim moveend zoomend";
    function syncPopupPane(): void {
      const offset = map.layerPointToContainerPoint([0, 0]);
      popupPane.style.transform = `translate3d(${offset.x}px, ${offset.y}px, 0)`;
    }
    map.on(popupPaneEvents, syncPopupPane); syncPopupPane();
    let values: Placement[] = [];
    let selectedId: string | null = null;
    let revision = 0, signature = "", dataSignature = "";
    let scheduled = false, destroyed = false, prepared = false;
    let popup: L.Popup | null = null;
    let popupZoom: HTMLButtonElement | null = null;
    let popupKey: string | null = null;
    let popupContent: HTMLElement | null = null;
    let clusterMarkers: L.Marker[] = [];
    const clusterByKey = new Map<string, L.Marker>();
    const drawn = new Map<string, Symbol>();
    const groupsByKey = new Map<string, Group>();
    const memberButtons = new Map<string, HTMLButtonElement>();
    let stats = { logicalPoints: 0, visiblePoints: 0, clusters: 0, symbols: 0 };

    function notify(): void { map.fire("archsearch:markerschange"); }
    function restorePopupFocus(): void {
      const icon = popupKey ? clusterByKey.get(popupKey)?.getElement() : null;
      const bounds = map.getContainer().getBoundingClientRect(), rect = icon?.getBoundingClientRect(), screen = visibleScreen();
      const visible = icon?.isConnected && rect && rect.top >= bounds.top + screen.top && rect.bottom <= bounds.top + screen.bottom
        && rect.left >= bounds.left + screen.left && rect.right <= bounds.left + screen.right;
      if (!visible && screen.height < 100) map.getContainer().scrollIntoView({ block: "center", behavior: "instant" });
      (visible && icon ? icon : map.getContainer()).focus({ preventScroll: true });
    }
    function closePopup(restore = false): void {
      const ownedFocus = popup?.getElement()?.contains(document.activeElement) ?? false;
      popup?.remove();
      if (restore || ownedFocus) restorePopupFocus();
      popup = null; popupZoom = null; popupKey = null; popupContent = null; memberButtons.clear();
    }
    function label(group: Group): string {
      return `${group.items.length.toLocaleString("zh-CN")} 个定位点 / ${members(group).length.toLocaleString("zh-CN")} 条资料 · 屏幕聚合示意，非遗址数量`;
    }
    function openMembers(group: Group, coordinate: L.LatLng): void {
      closePopup();
      if (visibleScreen().height < Math.min(260, map.getSize().y)) map.getContainer().scrollIntoView({ block: "center", behavior: "instant" });
      const entries = members(group), pageSize = 10;
      let page = 0;
      const content = document.createElement("section"); content.className = "catalogue-cluster-popup-body";
      content.setAttribute("aria-label", "聚合定位点所属资料");
      const activePopup = L.popup({ className: "catalogue-cluster-popup", pane: "catalogue-density-popup", maxWidth: 330, minWidth: 230,
        autoPan: false, closeOnEscapeKey: true, closeButton: true, offset: [0, 0] });
      popup = activePopup; popupKey = group.key; popupContent = content;
      content.style.overflowY = "auto"; content.style.maxHeight = `${Math.max(120, visibleScreen().height - 80)}px`;
      let popupHeading: HTMLElement | null = null;
      function render(focus: "previous" | "next" | null = null): void {
        const heading = document.createElement("h3"); heading.textContent = label(group); heading.tabIndex = -1;
        popupHeading = heading;
        const note = document.createElement("p"); note.className = "catalogue-cluster-note";
        note.textContent = "这是所选聚合组的资料，平移后列表保持。聚合位置仅作分布示意，选择真实资料不会替换原始坐标。";
        const list = document.createElement("ul"); list.className = "catalogue-cluster-members";
        memberButtons.clear();
        for (const entry of entries.slice(page * pageSize, (page + 1) * pageSize)) {
          const item = document.createElement("li"), button = document.createElement("button");
          button.type = "button"; button.textContent = entry.title; button.dataset.siteId = entry.id;
          const count = group.items.filter(member => member.value.id === entry.id).length;
          button.setAttribute("aria-label", `${entry.title}，本组 ${count} 个定位点，查看真实资料`);
          button.setAttribute("aria-pressed", String(entry.id === selectedId));
          button.addEventListener("click", () => onSelect(entry.id, button));
          memberButtons.set(entry.id, button); item.append(button); list.append(item);
        }
        const pagination = document.createElement("div"); pagination.className = "catalogue-cluster-actions";
        const previous = document.createElement("button"), next = document.createElement("button"), status = document.createElement("p");
        previous.type = next.type = "button"; previous.textContent = "上一页"; next.textContent = "下一页";
        previous.disabled = page === 0; next.disabled = (page + 1) * pageSize >= entries.length;
        status.className = "catalogue-cluster-page"; status.setAttribute("role", "status");
        status.textContent = `第 ${page + 1} / ${Math.max(1, Math.ceil(entries.length / pageSize))} 页 · ${entries.length} 条资料`;
        previous.addEventListener("click", () => { page--; render("previous"); });
        next.addEventListener("click", () => { page++; render("next"); });
        pagination.append(previous, status, next);
        const zoom = document.createElement("button"); zoom.type = "button"; zoom.className = "interaction-button catalogue-cluster-zoom"; zoom.textContent = "放大这组定位点";
        zoom.dataset.action = "zoom"; popupZoom = zoom;
        previous.dataset.action = "previous"; next.dataset.action = "next";
        zoom.disabled = map.getZoom() >= 9;
        zoom.addEventListener("click", () => { map.stop(); map.setView(coordinate, Math.min(9, map.getZoom() + 2), { animate: false }); });
        content.replaceChildren(heading, note, list, pagination, zoom);
        if (focus) {
          const target = focus === "previous" ? previous : next;
          (target.disabled ? heading : target).focus({ preventScroll: true });
        }
      }
      render(); activePopup.setLatLng(popupAnchor()).setContent(content).openOn(map);
      const wrapper = activePopup.getElement();
      wrapper?.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key !== "Escape") return;
        event.preventDefault(); closePopup(true);
      });
      wrapper?.addEventListener("click", (event) => {
        const target = event.target as Element | null;
        if (!target || typeof target.closest !== "function" || !target.closest(".leaflet-popup-close-button")) return;
        event.preventDefault(); event.stopPropagation(); closePopup(true);
      }, true);
      wrapper?.addEventListener("click", event => event.stopPropagation());
      (popupHeading as HTMLElement | null)?.focus({ preventScroll: true });
    }

    function visibleScreen() {
      const bounds = map.getContainer().getBoundingClientRect(), size = map.getSize();
      const viewportHeight = typeof window === "undefined" ? bounds.bottom : window.innerHeight;
      const viewportWidth = typeof window === "undefined" ? bounds.right : window.innerWidth;
      const search = typeof document.querySelector === "function" ? document.querySelector<HTMLElement>(".search-section") : null;
      const top = Math.max(0, -bounds.top, (search?.getBoundingClientRect().bottom ?? 0) - bounds.top);
      const bottom = Math.min(size.y, viewportHeight - bounds.top), left = Math.max(0, -bounds.left), right = Math.min(size.x, viewportWidth - bounds.left);
      return { top, bottom, left, right, height: Math.max(0, bottom - top), width: Math.max(0, right - left) };
    }
    function popupAnchor(): L.LatLng {
      const size = map.getSize(), zoom = map.getZoom(), center = map.project(map.getCenter(), zoom), screen = visibleScreen();
      const x = screen.width > 0 ? (screen.left + screen.right) / 2 : size.x / 2;
      const y = screen.height > 0 ? screen.bottom - 12 : size.y - 12;
      return map.unproject([center.x + x - size.x / 2, center.y + y - size.y / 2], zoom);
    }

    function configureMarker(marker: L.Marker): void {
      const icon = marker.getElement();
      if (!icon || icon.dataset.densityKeyboard === "ready") return;
      icon.dataset.densityKeyboard = "ready";
      icon.setAttribute("role", "button");
      icon.setAttribute("aria-label", marker.options.title ?? "查看聚合定位点资料");
      icon.addEventListener("keydown", (event) => {
        if (event.key !== " ") return;
        event.preventDefault(); event.stopPropagation(); marker.fire("click");
      });
    }

    function refresh(): void {
      if (popup) {
        popup.setLatLng(popupAnchor());
        if (popupContent) popupContent.style.maxHeight = `${Math.max(120, visibleScreen().height - 80)}px`;
        if (popupZoom) popupZoom.disabled = map.getZoom() >= 9;
      }
      if (destroyed || (prepared && !map.hasLayer(layer))) return;
      const zoom = map.getZoom(), size = map.getSize(), center = map.project(map.getCenter(), zoom);
      const nextSignature = [revision, selectedId, zoom, center.x, center.y, size.x, size.y].join(":");
      if (nextSignature === signature) return;
      signature = nextSignature; prepared = true;
      const origin = { x: center.x - size.x / 2, y: center.y - size.y / 2 };
      const worldWidth = map.project([0, 180], zoom).x - map.project([0, -180], zoom).x;
      const groups = plan(values, coordinate => map.project([coordinate[1], coordinate[0]], zoom),
        { origin, width: size.x, height: size.y, worldWidth, cellSize, selectedId });
      clusterMarkers = []; clusterByKey.clear(); groupsByKey.clear();
      const retained = new Set<string>();
      for (const group of groups) {
        if (group.items.length === 1) {
          const item = group.items[0], active = item.value.id === selectedId;
          const key = `point:${JSON.stringify([item.value.id, ...item.coordinate])}`;
          retained.add(key);
          let symbol = drawn.get(key);
          if (!symbol) {
            const circle = L.circleMarker([item.coordinate[1], item.coordinate[0]], { pane, renderer });
            circle.on("click", () => onSelect(item.value.id, map.getContainer())).addTo(layer);
            symbol = { layer: circle, circle }; drawn.set(key, symbol);
          }
          const circle = symbol.circle!;
          circle.setRadius(active ? 5 : 3.2);
          circle.setStyle({ color: active ? "#813d29" : "#586f60", fillColor: active ? "#a55339" : "#66745b", fillOpacity: active ? 0.95 : 0.5, weight: active ? 1.5 : 0.7 });
          circle.bindTooltip(item.value.tooltip ?? (() => {
            const node = document.createElement("span");
            node.textContent = `${item.value.title} · ${item.value.representative ? "参考代表点" : "来源定位点"}`;
            return node;
          }), { direction: "top", offset: [0, -4] });
          continue;
        }
        const key = `cluster:${group.key}`;
        retained.add(key); groupsByKey.set(group.key, group);
        const coordinate = map.unproject([group.pixel.x, group.pixel.y], zoom);
        let symbol = drawn.get(key);
        if (!symbol) {
          const count = document.createElement("span"); count.className = "catalogue-cluster-count"; count.setAttribute("aria-hidden", "true");
          const marker = L.marker(coordinate, { pane: "catalogue-density-clusters", keyboard: true, autoPanOnFocus: false,
            title: label(group), alt: label(group), icon: L.divIcon({ className: "catalogue-cluster-marker", html: count, iconSize: [44, 44], iconAnchor: [22, 22] }) });
          marker.on("click", () => {
            const current = groupsByKey.get(group.key);
            if (current) openMembers(current, map.unproject([current.focusPixel.x, current.focusPixel.y], map.getZoom()));
          });
          marker.bindTooltip(() => { const node = document.createElement("span"); node.textContent = label(groupsByKey.get(group.key) ?? group); return node; });
          marker.on("add", () => configureMarker(marker)); marker.addTo(layer);
          symbol = { layer: marker, marker, count }; drawn.set(key, symbol);
        }
        const marker = symbol.marker!;
        symbol.count!.textContent = group.items.length > 999 ? "999+" : String(group.items.length);
        marker.setLatLng(coordinate); marker.options.title = label(group);
        marker.getElement()?.setAttribute("aria-label", label(group)); marker.getElement()?.setAttribute("title", label(group));
        clusterMarkers.push(marker); clusterByKey.set(group.key, marker);
        configureMarker(marker);
      }
      for (const [key, symbol] of drawn) if (!retained.has(key)) {
        const lostFocus = symbol.marker?.getElement()?.contains(document.activeElement) ?? false;
        layer.removeLayer(symbol.layer); drawn.delete(key);
        if (lostFocus) map.getContainer().focus({ preventScroll: true });
      }
      for (const group of groups) if (group.items.length === 1 && group.items[0].value.id === selectedId) {
        const item = group.items[0]; drawn.get(`point:${JSON.stringify([item.value.id, ...item.coordinate])}`)?.circle?.bringToFront();
      }
      stats = { logicalPoints: new Set(values.filter(value => valid(value.coordinate)).map(value => JSON.stringify([value.id, ...value.coordinate]))).size,
        visiblePoints: groups.reduce((sum, group) => sum + group.items.length, 0), clusters: groups.filter(group => group.items.length > 1).length, symbols: groups.length };
      const container = map.getContainer();
      container.dataset.densitySymbols = String(map.hasLayer(layer) ? stats.symbols : 0); container.dataset.densityClusters = String(map.hasLayer(layer) ? stats.clusters : 0);
      container.dataset.densityLogicalPoints = String(stats.logicalPoints);
      container.dataset.densityCellSize = String(cellSize);
      notify();
    }
    function schedule(): void {
      if (scheduled || destroyed) return;
      scheduled = true;
      const run = () => { scheduled = false; refresh(); };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
      else void Promise.resolve().then(run);
    }
    const added = () => {
      refresh(); for (const marker of clusterMarkers) configureMarker(marker);
      map.getContainer().dataset.densitySymbols = String(stats.symbols); map.getContainer().dataset.densityClusters = String(stats.clusters); notify();
    };
    const removed = () => {
      closePopup(); map.getContainer().dataset.densitySymbols = "0"; map.getContainer().dataset.densityClusters = "0"; notify();
    };
    map.on("moveend zoomend resize", schedule);
    layer.on("add", added); layer.on("remove", removed);
    return {
      layer,
      setData(next: Placement[]): void {
        const nextSignature = JSON.stringify(next.map(value => [value.id, value.title, value.coordinate, value.representative]));
        if (nextSignature === dataSignature && next.every((value, index) => value.tooltip === values[index]?.tooltip)) return;
        dataSignature = nextSignature; values = next; revision++; closePopup(); prepared = false; refresh();
      },
      select(id: string | null): void {
        if (selectedId === id) return;
        selectedId = id;
        for (const [memberId, button] of memberButtons) button.setAttribute("aria-pressed", String(memberId === id));
        prepared = false; refresh();
      },
      refresh: schedule,
      stats: () => ({ ...stats }),
      destroy(): void {
        destroyed = true; map.off("moveend zoomend resize", schedule); layer.off("add", added); layer.off("remove", removed);
        map.off(popupPaneEvents, syncPopupPane);
        closePopup(); if (map.hasLayer(layer)) map.removeLayer(layer);
        layer.clearLayers(); drawn.clear(); groupsByKey.clear(); clusterByKey.clear(); values = []; clusterMarkers = [];
        map.getContainer().dataset.densitySymbols = "0"; map.getContainer().dataset.densityClusters = "0"; notify();
      },
    };
  }

  return { plan, members, valid, create };
})();

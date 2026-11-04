const ArchSearchRegisteredAreas = (() => {
  "use strict";

  type Coordinate = readonly [number, number];
  type AreaLabel = "现代遗产登记范围" | "来源古迹多边形" | "来源公开范围";
  interface Source {
    name: string;
    uri: string;
    version: string;
    sha256: string;
    license: string;
    license_uri: string;
  }
  interface AreaFeature {
    id: string;
    source_index: number;
    provider_object_id: number;
    title: string;
    source: Source;
    geometry_type: "esriGeometryPolygon";
    rings: readonly (readonly Coordinate[])[];
  }
  interface Areas {
    site_id: string;
    corpus_version: string;
    ready: boolean;
    reason: string | null;
    version: string | null;
    label: AreaLabel;
    note: string;
    features: readonly AreaFeature[];
  }
  type Snapshot = Readonly<Areas & { displayed: true }>;
  interface Options {
    map: L.Map | null;
    onShow?(): void;
    onVisibilityChange?(visible: boolean): void;
    getPadding?(): { topLeft: [number, number]; bottomRight: [number, number] };
  }
  interface Controller {
    readonly element: HTMLElement;
    select(id: string, title: string): void;
    setCorpusVersion(version: string | null, areasVersion: string | null): void;
    getSnapshot(): Snapshot | null;
    clear(): void;
  }

  const labels = ["现代遗产登记范围", "来源古迹多边形", "来源公开范围"] as const;
  const paneName = "registered-areas";
  const maximumLatitude = 85.0511287798;
  const scopeNote = "来源范围不是古代遗址轮廓、历史政权疆域或开放准入证明。未明确为法定边界的来源多边形不作法定边界使用。范围不补成代表点，也不计入遗址定位点数量。";

  function record(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function nonempty(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0;
  }

  function sourceUrl(value: unknown): string {
    if (typeof value !== "string") throw new Error("范围来源链接无效。");
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
      throw new Error("范围来源必须是无凭据的 HTTP(S) 链接。");
    }
    return value;
  }

  function parseAreas(value: unknown, siteId: string, corpusVersion?: string, areasVersion?: string | null): Areas {
    if (!record(value) || value.site_id !== siteId || !labels.includes(value.label as AreaLabel)
      || !nonempty(value.corpus_version) || typeof value.ready !== "boolean"
      || !(value.reason === null || typeof value.reason === "string")
      || !(value.version === null || nonempty(value.version))
      || typeof value.note !== "string" || !Array.isArray(value.features)) {
      throw new Error("来源范围响应与当前资料或来源合同不一致。");
    }
    if (corpusVersion !== undefined && value.corpus_version !== corpusVersion) throw new Error("来源范围与当前语料版本不一致。");
    if (value.features.length && (!value.ready || !nonempty(value.version))) throw new Error("可显示来源范围必须已就绪并提供非空版本。");
    if (value.features.length && value.label === "来源公开范围") throw new Error("可显示来源范围必须注明已核的来源类型。");
    if (value.features.length && areasVersion !== undefined && value.version !== areasVersion) throw new Error("来源范围与当前范围资料版本不一致，请刷新运行状态。");
    const identities = new Set<string>();
    const indexes = new Set<number>();
    const features = value.features.map((item: unknown): AreaFeature => {
      if (!record(item) || !nonempty(item.id) || identities.has(item.id)
        || !Number.isSafeInteger(item.source_index) || Number(item.source_index) < 0
        || indexes.has(Number(item.source_index)) || !Number.isSafeInteger(item.provider_object_id)
        || Number(item.provider_object_id) <= 0 || !nonempty(item.title)
        || item.geometry_type !== "esriGeometryPolygon" || !record(item.source)
        || !Array.isArray(item.rings) || item.rings.length === 0) {
        throw new Error("来源范围记录身份、类型或环序列无效。");
      }
      const source = item.source;
      if (!nonempty(source.name) || !nonempty(source.version) || !nonempty(source.license)
        || typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256)) {
        throw new Error("范围来源或版本缺失。");
      }
      const rings = item.rings.map((ring: unknown): readonly Coordinate[] => {
        if (!Array.isArray(ring) || ring.length < 4) throw new Error("来源范围必须保留完整闭环。");
        const points = ring.map((point: unknown): Coordinate => {
          if (!Array.isArray(point) || point.length !== 2
            || typeof point[0] !== "number" || typeof point[1] !== "number"
            || !Number.isFinite(point[0]) || !Number.isFinite(point[1])
            || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) {
            throw new Error("来源范围坐标必须为有效 WGS84 [经度, 纬度]。");
          }
          return [point[0], point[1]];
        });
        const first = points[0], last = points[points.length - 1];
        if (first[0] !== last[0] || first[1] !== last[1]) throw new Error("来源范围环未闭合。");
        if (new Set(points.map(point => `${point[0]},${point[1]}`)).size < 3) throw new Error("来源范围环至少需要三个不同位置。");
        return points;
      });
      identities.add(item.id); indexes.add(Number(item.source_index));
      return {
        id: item.id, source_index: Number(item.source_index), provider_object_id: Number(item.provider_object_id),
        title: item.title, geometry_type: "esriGeometryPolygon", rings,
        source: { name: source.name, uri: sourceUrl(source.uri), version: source.version,
          sha256: source.sha256, license: source.license, license_uri: sourceUrl(source.license_uri) },
      };
    });
    if (!value.ready && features.length !== 0) throw new Error("未就绪的来源范围不能混入部分几何。");
    return { site_id: siteId, corpus_version: value.corpus_version, ready: value.ready,
      reason: value.reason, version: value.version, label: value.label as AreaLabel, note: value.note, features };
  }

  function outlines(features: readonly AreaFeature[], center: number): L.LatLngTuple[][] {
    const firstLongitude = features[0]?.rings[0]?.[0]?.[0] ?? center;
    const anchor = firstLongitude + 360 * Math.round((center - firstLongitude) / 360);
    return features.flatMap(feature => feature.rings.map(ring => {
      let previous = anchor;
      return ring.map(([longitude, latitude]): L.LatLngTuple => {
        const displayLongitude = longitude + 360 * Math.round((previous - longitude) / 360);
        previous = displayLongitude;
        return [latitude, displayLongitude];
      });
    }));
  }

  function element<K extends keyof HTMLElementTagNameMap>(tag: K, text: string): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag); node.textContent = text; return node;
  }

  function create({ map, onShow, onVisibilityChange, getPadding }: Options): Controller {
    function byId<T extends HTMLElement>(id: string): T {
      const node = document.getElementById(id);
      if (!node) throw new Error(`页面元素不存在：${id}`);
      return node as T;
    }
    const ui = {
      section: byId<HTMLElement>("registered-areas"), status: byId<HTMLElement>("registered-areas-status"),
      note: byId<HTMLElement>("registered-areas-note"), sources: byId<HTMLElement>("registered-areas-sources"),
      label: byId<HTMLElement>("registered-areas-label"),
      show: byId<HTMLButtonElement>("registered-areas-show"), hide: byId<HTMLButtonElement>("registered-areas-hide"),
      retry: byId<HTMLButtonElement>("registered-areas-retry"),
    };
    let selected: { id: string; title: string } | null = null;
    let data: Areas | null = null;
    let controller: AbortController | null = null;
    let sequence = 0;
    let layer: L.LayerGroup | null = null;
    let renderer: L.Canvas | null = null;
    let corpusVersion: string | null = null;
    let areasVersion: string | null = null;
    if (map && typeof L !== "undefined") {
      const pane = map.getPane(paneName) ?? map.createPane(paneName);
      pane.style.zIndex = "400";
      pane.style.pointerEvents = "none";
      renderer = L.canvas({ pane: paneName });
    }

    function removeLayer(): void {
      if (layer && map) map.removeLayer(layer);
      layer = null;
      ui.show.setAttribute("aria-pressed", "false");
      ui.hide.hidden = true;
      onVisibilityChange?.(false);
    }

    function cancel(): void {
      sequence++;
      controller?.abort(); controller = null;
      ui.section.setAttribute("aria-busy", "false");
    }

    function status(message: string): void { ui.status.textContent = message; }

    function show(): void {
      if (!selected || !data?.ready || !data.features.length || !map || !renderer) return;
      if (data.corpus_version !== corpusVersion || data.version !== areasVersion) { removeLayer(); data = null; status("来源版本已变化，来源范围已隐藏，请重试读取。"); ui.retry.hidden = false; return; }
      let candidate: L.LayerGroup | null = null;
      try {
        const rings = outlines(data.features, map.getCenter().lng);
        if (rings.some(ring => ring.some(([latitude]) => Math.abs(latitude) > maximumLatitude))) {
          throw new Error("来源范围超出主地图投影范围；保留原坐标，不夹取纬度或生成中心。");
        }
        candidate = L.layerGroup(rings.map(ring => L.polyline(ring, {
          pane: paneName, renderer: renderer ?? undefined, color: "#286f80", weight: 2,
          opacity: 0.95, dashArray: "7 4", fill: false, fillOpacity: 0, interactive: false,
        })));
        const bounds = L.latLngBounds(rings.flat());
        if (!bounds.isValid()) throw new Error("来源未提供可显示的范围。");
        candidate.addTo(map);
        onVisibilityChange?.(true);
        const padding = getPadding?.() ?? { topLeft: [24, 24], bottomRight: [24, 24] };
        map.fitBounds(bounds, { paddingTopLeft: padding.topLeft, paddingBottomRight: padding.bottomRight, maxZoom: 16, animate: false });
        if (layer) map.removeLayer(layer);
        layer = candidate;
        ui.show.setAttribute("aria-pressed", "true"); ui.hide.hidden = false;
        status(`已显示：${selected.title} · ${data.label}。蓝绿色虚线仅描绘提供者原环，不填色或推断内外区域。`);
        onShow?.();
      } catch (error) {
        if (candidate && candidate !== layer) map.removeLayer(candidate);
        onVisibilityChange?.(layer !== null);
        status(`来源范围未能显示：${error instanceof Error ? error.message : "绘图失败"}。原历史地图与检索保持。`);
      }
    }

    function hide(): void {
      const returnFocus = document.activeElement === ui.hide;
      removeLayer();
      if (selected && data?.features.length) status(`已隐藏：${selected.title} · ${data.label}。可再次主动查看。`);
      if (returnFocus) ui.show.focus({ preventScroll: true });
    }

    function sourceList(value: Areas): void {
      ui.sources.replaceChildren();
      for (const feature of value.features) {
        const row = element("div", ""); row.className = "registered-area-source";
        const link = element("a", `${feature.title} · ${feature.source.name}`);
        link.href = feature.source.uri; link.target = "_blank"; link.rel = "noopener noreferrer";
        const license = element("a", feature.source.license);
        license.href = feature.source.license_uri; license.target = "_blank"; license.rel = "noopener noreferrer";
        row.append(link, element("p", `来源版本：${feature.source.version}`), license);
        ui.sources.append(row);
      }
    }

    async function load(): Promise<void> {
      if (!selected) return;
      cancel(); removeLayer(); data = null;
      const identity = selected.id, request = new AbortController(), requestSequence = sequence;
      controller = request;
      ui.section.hidden = false; ui.section.dataset.siteId = identity;
      ui.section.setAttribute("aria-busy", "true");
      if (document.activeElement === ui.retry) ui.status.focus({ preventScroll: true });
      ui.sources.replaceChildren(); ui.note.textContent = scopeNote;
      ui.label.textContent = "来源公开范围";
      ui.show.hidden = true; ui.show.disabled = true; ui.retry.hidden = true;
      if (corpusVersion === null) { ui.section.setAttribute("aria-busy", "false"); controller = null; status("当前语料版本尚未确认，请刷新运行状态后重试读取来源范围。"); ui.retry.hidden = false; return; }
      status(`正在读取 ${selected.title} 的公开来源范围…`);
      try {
        const response = await fetch(`/api/sites/${encodeURIComponent(identity)}/areas`, { signal: request.signal });
        if (!response.ok) throw new Error(`本地服务读取失败（HTTP ${response.status}）`);
        const value = parseAreas(await response.json(), identity, corpusVersion, areasVersion);
        if (request.signal.aborted || controller !== request || requestSequence !== sequence || selected?.id !== identity) return;
        data = value;
        ui.label.textContent = value.label;
        ui.show.textContent = value.label === "来源古迹多边形" ? "查看来源多边形" : "查看登记范围";
        ui.hide.textContent = value.label === "来源古迹多边形" ? "隐藏来源多边形" : "隐藏登记范围";
        ui.note.textContent = value.note ? `范围不补成代表点，也不计入遗址定位点数量。 ${value.note}` : scopeNote;
        sourceList(value);
        if (!value.ready) status(`来源范围尚未就绪：${value.reason || "请按项目文档准备本地范围资料。"}`);
        else if (!value.features.length) status("此资料未提供可用的来源范围；可继续阅读来源记录。");
        else {
          status(`${selected.title}：${value.features.length} 条${value.label}。点击后仅显示轮廓；当前尚未绘制。`);
          ui.show.hidden = false; ui.show.disabled = map === null || renderer === null;
          if (ui.show.disabled) status("来源范围资料已读取，地图组件不可用；仍可查看下方来源。");
        }
      } catch (error) {
        if (request.signal.aborted || controller !== request || requestSequence !== sequence || selected?.id !== identity) return;
        removeLayer(); data = null;
        status(`来源范围未能读取：${error instanceof Error ? error.message : "本地服务暂不可用"}。未显示范围，原地图与检索保持。`);
        ui.retry.hidden = false;
      } finally {
        if (controller === request) { controller = null; ui.section.setAttribute("aria-busy", "false"); }
      }
    }

    ui.show.addEventListener("click", show);
    ui.hide.addEventListener("click", hide);
    ui.retry.addEventListener("click", () => { void load(); });
    ui.show.setAttribute("aria-controls", "map"); ui.show.setAttribute("aria-pressed", "false");
    return {
      element: ui.section,
      select(id, title): void {
        if (selected?.id === id) { selected.title = title; return; }
        selected = { id, title }; void load();
      },
      setCorpusVersion(version, registeredVersion): void {
        const next = version?.trim() || null;
        const nextAreas = registeredVersion?.trim() || null;
        if (next === corpusVersion && nextAreas === areasVersion) return;
        const previous = corpusVersion;
        corpusVersion = next;
        areasVersion = nextAreas;
        if (selected && previous !== null) {
          cancel(); removeLayer(); data = null;
          ui.show.hidden = true; ui.show.disabled = true; ui.sources.replaceChildren(); ui.retry.hidden = false;
          status("当前语料或范围版本已变化；旧来源范围已隐藏，请主动重试读取。");
        }
      },
      getSnapshot(): Snapshot | null {
        if (!selected || !data || !layer || !map?.hasLayer(layer) || data.corpus_version !== corpusVersion || data.version !== areasVersion) return null;
        return { ...parseAreas(data, selected.id, corpusVersion, areasVersion), displayed: true };
      },
      clear(): void {
        cancel(); removeLayer(); selected = null; data = null;
        ui.section.hidden = true; ui.section.dataset.siteId = "";
        ui.sources.replaceChildren(); ui.retry.hidden = true;
      },
    };
  }

  return { create, parseAreas, outlines };
})();

const ArchSearchHistory = (() => {
  "use strict";

  type Basemap = "historical" | "modern";
  type Intent = "user" | "site";
  interface View {
    year: number;
    basemap: Basemap;
    boundaries: boolean;
    frame_id: string | null;
    source_version: string | null;
  }
  interface Status {
    ready: boolean;
    reason?: string | null;
    version?: string | null;
    min_year?: number;
    max_year?: number;
    change_years?: number[];
  }
  interface Frame {
    data: Parameters<typeof L.geoJSON>[0];
    validFrom: number;
    validTo: number;
    id: string;
    source: Record<string, unknown>;
    version: string;
    featureCount: number;
  }
  interface Options {
    map: L.Map | null;
    tiles: L.TileLayer | null;
    onCommittedView(view: View): void;
    onUserAction(): void;
    fixedHistorical?: boolean;
    sharedRenderer?: L.Canvas | null;
    automaticOnly?: boolean;
  }
  interface SelectionContext {
    title: string;
    precision: string | null;
    start_year: number | null;
    end_year: number | null;
  }
  interface YearOptions { selectionOwned?: boolean }

  const minimumYear = -3400;
  const maximumYear = 2024;
  const palette = ["#8b603e", "#687457", "#496d77", "#93616b", "#8d783d", "#70617f"] as const;

  function isValidYear(year: number): boolean {
    return Number.isInteger(year) && year !== 0 && year >= minimumYear && year <= maximumYear;
  }

  function yearToStep(year: number): number {
    if (!isValidYear(year)) throw new Error("年份必须在公元前 3400 年至公元 2024 年之间，且没有公元 0 年。");
    return year < 0 ? year : year - 1;
  }

  function stepToYear(step: number): number {
    if (!Number.isInteger(step)) throw new Error("年份刻度无效。");
    const year = step < 0 ? step : step + 1;
    if (!isValidYear(year)) throw new Error("年份刻度超出资料范围。");
    return year;
  }

  function formatYear(year: number): string {
    return year < 0 ? `公元前 ${Math.abs(year)} 年` : `公元 ${year} 年`;
  }

  function frameTargets(year: number, changes: readonly number[], minimum = minimumYear): { previous: number | null; next: number | null } {
    const starts = [...new Set([minimum, ...changes.filter(isValidYear)])].sort((left, right) => left - right);
    let index = 0;
    while (index + 1 < starts.length && starts[index + 1] <= year) index++;
    return { previous: starts[index - 1] ?? null, next: starts[index + 1] ?? null };
  }

  function colorForName(name: string): string {
    let hash = 2166136261;
    for (const character of name) hash = Math.imul(hash ^ (character.codePointAt(0) ?? 0), 16777619);
    return palette[(hash >>> 0) % palette.length];
  }

  function worldCopies(value: unknown): Parameters<typeof L.geoJSON>[0] {
    if (!record(value) || !Array.isArray(value.features)) throw new Error("地图资料格式无效。");
    const originals: unknown[] = value.features;
    const shift = (coordinates: unknown, offset: number): unknown => {
      if (!Array.isArray(coordinates)) return coordinates;
      if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number") return [coordinates[0] + offset, ...coordinates.slice(1)];
      return coordinates.map((item: unknown) => shift(item, offset));
    };
    const features = [-360, 0, 360].flatMap((offset) => originals.map((feature: unknown) => {
      if (!record(feature) || !record(feature.geometry)) throw new Error("地图几何格式无效。");
      return { ...feature, geometry: { ...feature.geometry, coordinates: shift(feature.geometry.coordinates, offset) } };
    }));
    return { ...value, type: "FeatureCollection", features } as Parameters<typeof L.geoJSON>[0];
  }

  function record(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function text(value: unknown, fallback = "来源未提供"): string {
    return typeof value === "string" && value.trim() ? value : typeof value === "number" && Number.isFinite(value) ? String(value) : fallback;
  }

  function element<K extends keyof HTMLElementTagNameMap>(tag: K, content?: string): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function safeSource(value: unknown, label: string): HTMLElement {
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
      } catch { /* A source without a usable URL remains plain text. */ }
    }
    return element("span", label);
  }

  function sourceYear(value: unknown): string {
    if (value === 0) return "原值 0（查询中按公元前 1 年处理）";
    return typeof value === "number" && Number.isInteger(value) ? formatYear(value) : text(value);
  }

  function popup(properties: Record<string, unknown>, source: Record<string, unknown>): HTMLElement {
    const content = element("div");
    content.className = "history-popup";
    content.append(element("strong", text(properties.Name, "未命名历史政权")));
    content.append(element("p", `来源范围：${sourceYear(properties.FromYear)} — ${sourceYear(properties.ToYear)}`));
    if (typeof properties.Type === "string" && properties.Type) content.append(element("p", `来源类型：${properties.Type}`));
    if (properties.composite === true) content.append(element("p", "复合政体边界以虚线显示，不填色；组成关系与范围须回到来源核验。"));
    content.append(element("p", "历史边界是来源中的重建记录，可能存在概略范围、争议与不确定性。"));
    const links = element("p");
    links.append(safeSource(properties.Wikipedia, "维基百科来源"), document.createTextNode(" · "), safeSource(source.uri, text(source.name, "Cliopatria")));
    content.append(links);
    content.append(element("p", `${text(source.version, "版本未提供")} · ${text(source.license, "许可未提供")}`));
    return content;
  }

  function validGeometry(value: unknown): boolean {
    if (!record(value) || !Array.isArray(value.coordinates)) return false;
    const ring = (points: unknown): boolean => Array.isArray(points) && points.length >= 4
      && points.every((point: unknown) => Array.isArray(point) && point.length >= 2
        && typeof point[0] === "number" && Number.isFinite(point[0]) && Math.abs(point[0]) <= 180
        && typeof point[1] === "number" && Number.isFinite(point[1]) && Math.abs(point[1]) <= 90)
      && JSON.stringify(points[0]) === JSON.stringify(points[points.length - 1]);
    const polygon = (rings: unknown): boolean => Array.isArray(rings) && rings.length > 0 && rings.every(ring);
    return value.type === "Polygon" ? polygon(value.coordinates)
      : value.type === "MultiPolygon" && value.coordinates.length > 0 && value.coordinates.every(polygon);
  }

  function validateCollection(value: unknown): asserts value is Record<string, unknown> & { type: "FeatureCollection"; features: Record<string, unknown>[] } {
    if (!record(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features)
      || value.features.some((feature: unknown) => !record(feature) || feature.type !== "Feature" || !validGeometry(feature.geometry))) {
      throw new Error("地图资料格式无效，未替换当前视图。");
    }
  }

  function parseFrame(value: unknown, year: number, expectedVersion: string): Frame {
    validateCollection(value);
    const metadata = value.metadata;
    if (!record(metadata) || metadata.year !== year || !isValidYear(Number(metadata.valid_from))
      || !isValidYear(Number(metadata.valid_to)) || typeof metadata.valid_from !== "number" || typeof metadata.valid_to !== "number"
      || metadata.valid_from > year || metadata.valid_to < year || typeof metadata.frame_id !== "string" || !metadata.frame_id) {
      throw new Error("历史帧的年份或有效范围不匹配，未替换当前视图。");
    }
    const source = record(metadata.source) ? metadata.source : {};
    const version = typeof source.version === "string" ? source.version : expectedVersion;
    if (version !== expectedVersion) throw new Error("历史资料版本已变化，请刷新运行状态后重试。");
    return { data: value as Parameters<typeof L.geoJSON>[0], validFrom: metadata.valid_from, validTo: metadata.valid_to, id: metadata.frame_id, source, version, featureCount: value.features.length };
  }

  function create({ map, tiles, onCommittedView, onUserAction, fixedHistorical = false, sharedRenderer = null, automaticOnly = false }: Options) {
    fixedHistorical ||= automaticOnly;
    const byId = <T extends HTMLElement>(id: string): T => {
      const node = document.getElementById(id);
      if (!node) throw new Error(`历史控件不存在：${id}`);
      return node as T;
    };
    const controls = automaticOnly ? null : {
      year: byId<HTMLInputElement>("history-year"), range: byId<HTMLInputElement>("history-range"),
      apply: byId<HTMLButtonElement>("history-apply"), previousYear: byId<HTMLButtonElement>("history-previous-year"), nextYear: byId<HTMLButtonElement>("history-next-year"),
      previousFrame: byId<HTMLButtonElement>("history-previous-frame"), nextFrame: byId<HTMLButtonElement>("history-next-frame"),
      historical: byId<HTMLButtonElement>("history-basemap-historical"), modern: byId<HTMLButtonElement>("history-basemap-modern"),
      boundaries: byId<HTMLInputElement>("history-boundaries"), draft: byId<HTMLElement>("history-draft-year"),
    };
    const ui = {
      panel: byId<HTMLElement>("history-controls"), applied: byId<HTMLElement>("history-applied-year"),
      feedback: byId<HTMLElement>("history-feedback"), error: byId<HTMLElement>("history-error"), source: byId<HTMLElement>("history-source"),
      retry: byId<HTMLButtonElement>("history-retry"), caption: document.getElementById("history-map-caption"),
      linkage: automaticOnly ? byId<HTMLElement>("history-linkage-status") : document.getElementById("history-linkage-status"),
    };
    let ready = false;
    let version: string | null = null;
    let reason = "历史资料尚未准备，请准备资料后刷新运行状态。";
    let minimum = minimumYear;
    let maximum = maximumYear;
    let changes: number[] = [];
    let desired = { year: 117, basemap: "historical" as Basemap, boundaries: true };
    let yearDraft = "117";
    let committed: View | null = null;
    let sequence = 0;
    let actions = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let landData: Parameters<typeof L.geoJSON>[0] | null = null;
    let landLayer: L.GeoJSON | null = null;
    let boundaryLayer: L.GeoJSON | null = null;
    let appliedFrame: Frame | null = null;
    let failed = false;
    let loading = false;
    let emptyFrame = false;
    let retentionNote: string | null = null;
    let selectionContext: SelectionContext | null = null;
    let selectionOwnsYear = false;
    const frames = new Map<string, Frame>();
    let renderer: L.Canvas | null = sharedRenderer;
    if (map && typeof L !== "undefined") {
      const historyPane = map.getPane("history-boundaries") ?? map.createPane("history-boundaries");
      historyPane.style.zIndex = "350";
      const landPane = map.getPane("history-land") ?? map.createPane("history-land");
      landPane.style.zIndex = "210";
      landPane.style.pointerEvents = "none";
      renderer ??= L.canvas({ pane: "history-boundaries" });
      if (fixedHistorical) {
        const labelsPane = map.getPane("history-polity-labels") ?? map.createPane("history-polity-labels");
        labelsPane.style.zIndex = "420"; labelsPane.style.pointerEvents = "none";
      }
    }

    function cancel(): void {
      sequence++;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      controller?.abort();
      controller = null;
      loading = false;
    }

    function userAction(intent: Intent): void {
      if (intent === "user") { actions++; onUserAction(); }
    }

    function showError(message: string): void {
      ui.error.textContent = message;
      ui.error.hidden = !message;
    }

    function renderLinkage(): void {
      if (!automaticOnly || !ui.linkage) return;
      const hasFrame = committed !== null && committed.boundaries && committed.frame_id !== null;
      const actual = hasFrame ? formatYear(committed!.year) : null;
      const pending = loading || timer !== null;
      const context = selectionContext;
      let state: "matched" | "retained" | "loading" | "unlinked" | "mismatched" | "unavailable";
      let message: string;
      if (context === null) {
        state = "unlinked";
        message = actual ? `未选遗址｜当前 ${actual} 仅为参考背景。` : "未选遗址｜历史疆域尚未载入。";
      } else if (context.precision === "loading") {
        state = "loading";
        message = actual ? `正在核对所选资料年代；当前 ${actual} 仅供参照。` : "正在核对所选资料年代；历史疆域尚未载入。";
      } else {
        const usableYear = (value: number | null): value is number => value !== null && Number.isInteger(value) && value !== 0;
        const exact = context.precision === "exact_year" && usableYear(context.start_year) && context.start_year === context.end_year;
        if (exact) {
          const expected = context.start_year!;
          const source = formatYear(expected);
          if (!isValidYear(expected) || expected < minimum || expected > maximum) {
            state = actual ? "mismatched" : "unavailable";
            message = `来源年代 ${source} 超出疆域覆盖（${formatYear(minimum)} — ${formatYear(maximum)}）；${actual ? `当前 ${actual} 仅供参照，未显示所选阶段的历史背景` : "历史疆域尚未载入，不选择邻近年份代替"}。`;
          } else if (pending && ready && desired.year >= minimum && desired.year <= maximum) {
            state = "loading";
            message = desired.year === expected
              ? `资料年代 ${source}，正在加载；${actual ? `当前仍显示 ${actual}` : "历史疆域尚未载入"}。`
              : `来源年代 ${source}；正在加载参考背景 ${formatYear(desired.year)}，与所选阶段不一致；${actual ? `当前仍显示 ${actual}` : "历史疆域尚未载入"}。`;
          } else if (actual && committed!.year === expected) {
            state = "matched";
            message = `已按来源切到 ${actual}，对应所选明确单年阶段。`;
          } else if (actual) {
            state = "mismatched";
            message = `来源年代 ${source}；当前历史背景 ${actual}，与所选阶段不一致，仅供参照。`;
          } else {
            state = "unavailable";
            message = `来源年代 ${source}；历史疆域尚未载入，尚未显示所选阶段的历史背景。`;
          }
        } else {
          const start = usableYear(context.start_year) ? formatYear(context.start_year) : null;
          const end = usableYear(context.end_year) ? formatYear(context.end_year) : null;
          const dates = start && end ? start === end ? start : `${start} — ${end}`
            : start ? `起年 ${start}，终年未提供` : end ? `起年未提供，终年 ${end}` : null;
          const scope = context.precision === "approximate_year" ? `来源约略年代${dates ? `：${dates}` : "未给出可用年份"}`
            : context.precision === "range" ? `来源区间${dates ? `：${dates}` : "未给出可用年份"}`
            : context.precision === "period" ? `来源仅有时期描述${dates ? `：${dates}` : ""}` : "当前资料无明确单年";
          state = actual ? "retained" : "unavailable";
          message = actual ? `${scope}；保留 ${actual} 参考背景，不能视为该遗址年代。` : `${scope}；历史疆域尚未载入，不推定遗址年份。`;
        }
      }
      ui.linkage.dataset.state = state;
      if (ui.linkage.textContent !== message) ui.linkage.textContent = message;
      ui.linkage.setAttribute("aria-label", context ? `${context.title}：${message}` : message);
    }

    function render(): void {
      const previousFocus = document.activeElement;
      const unavailable = map === null || !ready;
      if (controls) {
        controls.year.disabled = unavailable;
        controls.apply.disabled = unavailable;
        controls.range.disabled = unavailable;
        controls.previousYear.disabled = unavailable || desired.year <= minimum || desired.year > maximum;
        controls.nextYear.disabled = unavailable || desired.year >= maximum || desired.year < minimum;
        const targets = frameTargets(desired.year, changes, minimum);
        controls.previousFrame.disabled = unavailable || targets.previous === null;
        controls.nextFrame.disabled = unavailable || targets.next === null || targets.next > maximum;
        controls.previousFrame.title = targets.previous === null ? "已到首个疆域变化" : `上一疆域变化：${formatYear(targets.previous)}`;
        controls.nextFrame.title = targets.next === null ? "已到末个疆域变化" : `下一疆域变化：${formatYear(targets.next)}`;
        controls.historical.disabled = map === null || fixedHistorical;
        controls.modern.disabled = map === null || fixedHistorical;
        controls.boundaries.disabled = map === null;
        controls.historical.setAttribute("aria-pressed", String(desired.basemap === "historical"));
        controls.modern.setAttribute("aria-pressed", String(desired.basemap === "modern"));
        controls.boundaries.checked = desired.boundaries;
        controls.range.min = String(yearToStep(minimum));
        controls.range.max = String(yearToStep(maximum));
        controls.range.value = String(yearToStep(desired.year));
        controls.range.setAttribute("aria-valuetext", formatYear(desired.year));
        controls.year.min = String(minimum);
        controls.year.max = String(maximum);
        if (controls.year.value !== yearDraft) controls.year.value = yearDraft;
        controls.draft.textContent = yearDraft.trim() === String(desired.year)
          ? `计划年份：${formatYear(desired.year)}`
          : isValidYear(Number(yearDraft)) ? `年份草稿：${formatYear(Number(yearDraft))}，尚未应用` : "年份草稿尚未应用，请输入有效整数后确认。";
      }
      ui.applied.textContent = committed ? `当前${automaticOnly ? "历史背景" : fixedHistorical ? "历史图" : "地图"}：${formatYear(committed.year)}` : "历史地图尚未加载";
      renderLinkage();
      ui.panel.setAttribute("aria-busy", String(loading));
      ui.retry.hidden = !failed;
      ui.retry.disabled = loading || map === null;
      if (loading) ui.feedback.textContent = `正在加载${formatYear(desired.year)}；地图保留上次成功视图。`;
      else if (!ready && desired.boundaries) ui.feedback.textContent = retentionNote ? `${retentionNote} ${reason}` : reason;
      else if (retentionNote) ui.feedback.textContent = retentionNote;
      else if (!failed) ui.feedback.textContent = emptyFrame && committed?.boundaries
        ? "该年份没有来源中的活动政权记录；地点标记仍保留。"
        : committed?.boundaries ? automaticOnly ? "历史背景可按明确年份联动；区间或未知年代不推断年份，当前关联见上方状态。" : "历史政权疆域概略独立于遗址排序；时间滑动不会重新检索地点。" : "历史政权疆域概略已关闭，地点与检索结果继续保留。";
      if ((previousFocus === ui.retry && ui.retry.hidden)
        || (controls && [controls.year, controls.range, controls.apply, controls.previousYear, controls.nextYear, controls.previousFrame, controls.nextFrame].some((control) => previousFocus === control && control.disabled))) {
        const target = automaticOnly && ui.linkage ? ui.linkage : ui.feedback;
        target.tabIndex = -1;
        if (automaticOnly && ui.linkage) target.focus();
        else target.focus({ preventScroll: true });
      }
    }

    async function getJson(path: string, signal: AbortSignal): Promise<unknown> {
      const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
      let value: unknown;
      try { value = await response.json(); }
      catch (error) {
        if (signal.aborted) throw error;
        throw new Error(`地图资料无法读取（HTTP ${response.status}）。`);
      }
      if (!response.ok) throw new Error(record(value) ? text(value.detail, `地图请求失败（HTTP ${response.status}）。`) : `地图请求失败（HTTP ${response.status}）。`);
      return value;
    }

    async function loadLand(signal: AbortSignal): Promise<Parameters<typeof L.geoJSON>[0]> {
      if (landData !== null) return landData;
      const value = await getJson("/static/data/land.geojson", signal);
      validateCollection(value);
      return value as Parameters<typeof L.geoJSON>[0];
    }

    async function loadFrame(year: number, sourceVersion: string, signal: AbortSignal): Promise<Frame> {
      for (const [key, frame] of frames) {
        if (frame.version === sourceVersion && frame.validFrom <= year && year <= frame.validTo) {
          frames.delete(key); frames.set(key, frame);
          return frame;
        }
      }
      return parseFrame(await getJson(`/api/history/boundaries?year=${encodeURIComponent(year)}`, signal), year, sourceVersion);
    }

    function updateSource(frame: Frame | null): void {
      const source = element("span", desired.basemap === "historical" ? "Natural Earth · 现代自然地理参照" : "OpenStreetMap · 现代底图");
      ui.source.replaceChildren(source);
      if (frame !== null && desired.boundaries) {
        ui.source.append(document.createTextNode(" · "), safeSource(frame.source.uri, `${text(frame.source.name, "Cliopatria")} ${frame.version}`), document.createTextNode(" · "), safeSource(frame.source.license_uri, text(frame.source.license, "CC BY 4.0")));
      }
      if (ui.caption) ui.caption.textContent = `${frame !== null && desired.boundaries ? "历史政权疆域概略" : "地点代表位置"} · ${desired.basemap === "historical" ? "现代海岸线参照" : "现代 OSM 底图"}`;
      const actual = document.getElementById("comparison-history-year");
      if (actual) {
        const yearLabel = committed ? formatYear(committed.year) : null;
        const layerState = frame ? committed?.boundaries ? "" : "疆域层未显示" : "无可用疆域数据";
        actual.textContent = yearLabel ? [yearLabel, layerState].filter(Boolean).join(" · ") : "尚未加载";
        actual.title = yearLabel ? [yearLabel, frame?.version, layerState, frame ? null : "仅显示本地自然地理参照"].filter(Boolean).join(" · ") : "等待成功历史视图";
        actual.setAttribute("aria-label", `实际显示的历史背景：${actual.title}`);
        actual.dataset.state = committed ? frame && committed.boundaries ? "ready" : "reference" : "loading";
      }
    }

    function refreshPolityLabels(): void {
      if (!fixedHistorical || !map || !boundaryLayer) return;
      const visible = map.getZoom() >= 3;
      boundaryLayer.eachLayer((layer) => {
        const tooltip = layer.getTooltip();
        if (!tooltip) return;
        const bounded = layer as L.Layer & { getBounds?: () => L.LatLngBounds };
        const inView = !bounded.getBounds || map.getBounds().intersects(bounded.getBounds());
        tooltip.options.permanent = visible && inView;
        try { if (visible && inView) layer.openTooltip(); else layer.closeTooltip(); }
        catch { layer.closeTooltip(); }
      });
    }

    async function applyView(): Promise<void> {
      const current = sequence;
      timer = null;
      if (!map || typeof L === "undefined") { showError("地图组件未能加载，仍可阅读地点资料与来源。"); render(); return; }
      const canRequestYear = ready && desired.year >= minimum && desired.year <= maximum;
      const request = { ...desired, year: canRequestYear ? desired.year : committed?.year ?? desired.year };
      const sourceVersion = version;
      const abort = new AbortController();
      controller = abort;
      loading = true;
      failed = false;
      showError("");
      render();
      let frame: Frame | null = null;
      let land: Parameters<typeof L.geoJSON>[0] | null = null;
      let nextBoundary: L.GeoJSON | null = null;
      let nextLand: L.GeoJSON | null = null;
      const previousTilesVisible = tiles !== null && map.hasLayer(tiles);
      const previousLandVisible = landLayer !== null && map.hasLayer(landLayer);
      const previousBoundary = boundaryLayer;
      try {
        [land, frame] = await Promise.all([
          request.basemap === "historical" ? loadLand(abort.signal) : Promise.resolve(null),
          request.boundaries && canRequestYear && sourceVersion ? loadFrame(request.year, sourceVersion, abort.signal)
            : Promise.resolve(request.boundaries && appliedFrame && appliedFrame.validFrom <= request.year && request.year <= appliedFrame.validTo ? appliedFrame : null),
        ]);
        if (abort.signal.aborted || current !== sequence) return;
        if (land !== null && landLayer === null) {
          nextLand = L.geoJSON(worldCopies(land), { pane: "history-land", interactive: false, attribution: "Natural Earth · Public Domain", style: { fillColor: "#eee9dc", fillOpacity: 1, color: "#a3ad9c", weight: 0.7 } });
        }
        if (frame !== null) {
          const source = frame.source;
          const boundaryOptions: L.GeoJSONOptions & L.PathOptions = {
            pane: "history-boundaries", renderer: renderer ?? undefined, attribution: "Cliopatria · CC BY 4.0",
            style: (feature) => {
              const properties: Record<string, unknown> = record(feature?.properties) ? feature.properties : {};
              const composite = properties.composite === true;
              return { pane: "history-boundaries", renderer: renderer ?? undefined, color: colorForName(text(properties.Name, String(feature?.id ?? "unknown"))), weight: fixedHistorical ? composite ? 2.1 : 1.7 : composite ? 1.3 : 1, opacity: fixedHistorical ? 0.95 : 0.8, fill: !composite, fillOpacity: composite ? 0 : fixedHistorical ? 0.26 : 0.1, dashArray: composite ? fixedHistorical ? "7 5" : "5 4" : undefined };
            },
            onEachFeature: (feature, layer) => {
              const properties = record(feature.properties) ? feature.properties : {};
              layer.bindPopup(() => popup(properties, source), { maxWidth: 310 });
              if (fixedHistorical) layer.bindTooltip(element("span", text(properties.Name, "未命名历史政权")), { pane: "history-polity-labels", className: "history-polity-label", direction: "center", sticky: false, opacity: 0.95 });
            },
          };
          nextBoundary = L.geoJSON(worldCopies(frame.data), boundaryOptions);
        }
        if (abort.signal.aborted || current !== sequence) return;
        if (nextLand) nextLand.addTo(map);
        if (nextBoundary) {
          nextBoundary.addTo(map);
          if (sharedRenderer) nextBoundary.bringToBack();
        }
        if (request.basemap === "historical") {
          if (tiles && map.hasLayer(tiles)) map.removeLayer(tiles);
          if (landLayer && !map.hasLayer(landLayer)) landLayer.addTo(map);
        } else {
          if (tiles && !map.hasLayer(tiles)) tiles.addTo(map);
          if (landLayer && map.hasLayer(landLayer)) map.removeLayer(landLayer);
        }
        if (previousBoundary) map.removeLayer(previousBoundary);
      } catch (error) {
        if (abort.signal.aborted || current !== sequence) return;
        if (nextBoundary && map.hasLayer(nextBoundary)) map.removeLayer(nextBoundary);
        if (nextLand && map.hasLayer(nextLand)) map.removeLayer(nextLand);
        if (previousBoundary && !map.hasLayer(previousBoundary)) previousBoundary.addTo(map);
        if (tiles && previousTilesVisible && !map.hasLayer(tiles)) tiles.addTo(map);
        if (tiles && !previousTilesVisible && map.hasLayer(tiles)) map.removeLayer(tiles);
        if (landLayer && previousLandVisible && !map.hasLayer(landLayer)) landLayer.addTo(map);
        if (landLayer && !previousLandVisible && map.hasLayer(landLayer)) map.removeLayer(landLayer);
        abort.abort();
        failed = true;
        showError(`${error instanceof Error ? error.message : "历史地图加载失败。"}${committed ? ` 仍显示${formatYear(committed.year)}的上次成功视图。` : " 当前底图与地点标记保持原样。"}`);
        ui.feedback.textContent = "可调整年份或重试；失败请求不会改写已应用的地图年份。";
        return;
      } finally {
        if (current === sequence) { loading = false; controller = null; render(); }
      }
      if (nextLand) landLayer = nextLand;
      if (land !== null) landData = land;
      boundaryLayer = nextBoundary;
      appliedFrame = frame;
      if (frame !== null) {
        frames.set(frame.id, frame);
        while (frames.size > 4) frames.delete(frames.keys().next().value as string);
      }
      committed = { ...request, boundaries: frame !== null, frame_id: frame?.id ?? null, source_version: frame?.version ?? null };
      emptyFrame = frame?.featureCount === 0;
      controls?.year.removeAttribute("aria-invalid");
      map.getContainer().dataset.basemap = request.basemap;
      updateSource(frame);
      refreshPolityLabels();
      render();
      onCommittedView({ ...committed });
    }

    function schedule(): void {
      cancel();
      failed = false;
      showError("");
      timer = setTimeout(() => { void applyView(); }, 200);
      render();
    }

    function setYear(year: number, intent: Intent = "user", options: YearOptions = {}): void {
      userAction(intent);
      selectionOwnsYear = intent === "site" && options.selectionOwned === true;
      retentionNote = null;
      if (!isValidYear(year)) {
        if (Number.isFinite(year)) yearDraft = String(year);
        cancel(); controls?.year.setAttribute("aria-invalid", "true");
        const message = Number.isInteger(year) && year !== 0
          ? "该年份无可用疆域数据；保留最后成功地图。资料覆盖公元前 3400 年至公元 2024 年。"
          : "请输入公元前 3400 年至公元 2024 年的整数年份；负数表示公元前，没有公元 0 年。";
        showError(message);
        if (automaticOnly && committed === null) { retentionNote = message; timer = setTimeout(() => { void applyView(); }, 200); }
        render(); return;
      }
      desired = { ...desired, year };
      yearDraft = String(year);
      if (controls) controls.year.value = String(year);
      controls?.year.removeAttribute("aria-invalid");
      if (year < minimum || year > maximum) {
        cancel();
        showError(automaticOnly ? `${formatYear(year)}无可用疆域数据；保留最后成功的历史背景。` : `${formatYear(year)}超出当前历史资料范围，计划年份保持不变；请选择范围内年份后应用。`);
        if (automaticOnly && committed === null) { retentionNote = ui.error.textContent; timer = setTimeout(() => { void applyView(); }, 200); }
        render(); return;
      }
      if (!ready) {
        cancel(); ui.feedback.textContent = reason; render();
        if (fixedHistorical) timer = setTimeout(() => { void applyView(); }, 200);
        return;
      }
      schedule();
    }

    function retainBackground(note = "当前资料没有明确单年证据；保留最后成功的历史背景，不推断年份。"): void {
      cancel();
      selectionOwnsYear = false;
      desired = { ...desired, year: committed?.year ?? 117 };
      yearDraft = String(desired.year);
      retentionNote = note;
      failed = false;
      showError("");
      render();
      if (committed === null && fixedHistorical) timer = setTimeout(() => { void applyView(); }, 200);
    }

    function setSelectionContext(context: SelectionContext | null): void {
      selectionContext = context ? { ...context } : null;
      if (context === null) {
        if (selectionOwnsYear) retainBackground("");
        else { retentionNote = null; render(); }
      } else render();
    }

    function setBasemap(basemap: Basemap, intent: Intent = "user"): void {
      userAction(intent);
      if (basemap !== "historical" && basemap !== "modern") return;
      desired = { ...desired, basemap: fixedHistorical ? "historical" : basemap };
      schedule();
    }

    function setBoundaries(boundaries: boolean, intent: Intent = "user"): void {
      userAction(intent);
      desired = { ...desired, boundaries: automaticOnly || Boolean(boundaries) };
      schedule();
    }

    function configure(status: Status | null | undefined): void {
      const nextVersion = typeof status?.version === "string" && status.version ? status.version : null;
      if (nextVersion !== version) frames.clear();
      version = nextVersion;
      ready = status?.ready === true && version !== null;
      reason = text(status?.reason, ready ? "" : "历史资料尚未准备，请准备资料后刷新运行状态。");
      minimum = isValidYear(status?.min_year ?? NaN) ? status?.min_year ?? minimumYear : minimumYear;
      maximum = isValidYear(status?.max_year ?? NaN) ? status?.max_year ?? maximumYear : maximumYear;
      if (minimum > maximum) { minimum = minimumYear; maximum = maximumYear; ready = false; }
      changes = Array.isArray(status?.change_years) ? status.change_years.filter((year) => isValidYear(year) && minimum <= year && year <= maximum) : [];
      if (ready && (desired.year < minimum || desired.year > maximum)) {
        cancel();
        showError(automaticOnly ? `${formatYear(desired.year)}无可用疆域数据；保留最后成功的历史背景。` : `${formatYear(desired.year)}超出当前历史资料范围，计划年份保持不变；请选择范围内年份后应用。`);
        render();
        return;
      }
      if (!ready) {
        cancel(); render();
        if (fixedHistorical) timer = setTimeout(() => { void applyView(); }, 200);
        return;
      }
      schedule();
    }

    if (controls) {
      const readYear = (): void => {
        const raw = controls.year.value.trim();
        setYear(/^-?\d+$/u.test(raw) ? Number(raw) : NaN);
      };
      controls.range.addEventListener("input", () => {
        try { setYear(stepToYear(Number(controls.range.value))); }
        catch { showError("年份刻度无效。"); }
      });
      controls.year.addEventListener("input", () => { yearDraft = controls.year.value; userAction("user"); cancel(); render(); });
      controls.year.addEventListener("change", readYear);
      controls.year.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); readYear(); }
        else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault();
          const draft = Number(controls.year.value);
          const base = isValidYear(draft) && draft >= minimum && draft <= maximum ? draft : desired.year;
          const step = yearToStep(base) + (event.key === "ArrowUp" ? 1 : -1);
          if (step >= yearToStep(minimum) && step <= yearToStep(maximum)) setYear(stepToYear(step));
        }
      });
      controls.apply.addEventListener("click", readYear);
      controls.previousYear.addEventListener("click", () => { if (desired.year > minimum) setYear(stepToYear(yearToStep(desired.year) - 1)); });
      controls.nextYear.addEventListener("click", () => { if (desired.year < maximum) setYear(stepToYear(yearToStep(desired.year) + 1)); });
      controls.previousFrame.addEventListener("click", () => { const target = frameTargets(desired.year, changes, minimum).previous; if (target !== null) setYear(target); });
      controls.nextFrame.addEventListener("click", () => { const target = frameTargets(desired.year, changes, minimum).next; if (target !== null) setYear(target); });
      controls.historical.addEventListener("click", () => setBasemap("historical"));
      controls.modern.addEventListener("click", () => setBasemap("modern"));
      controls.boundaries.addEventListener("change", () => setBoundaries(controls.boundaries.checked));
    }
    ui.retry.addEventListener("click", () => { userAction("user"); schedule(); });
    if (fixedHistorical && map && typeof map.on === "function") map.on("moveend zoomend", refreshPolityLabels);
    render();
    return { configure, getView: (): View | null => committed ? { ...committed } : null, setYear, retainBackground, setSelectionContext, setBasemap, setBoundaries, actionVersion: (): number => actions };
  }

  return { create, isValidYear, yearToStep, stepToYear, formatYear, frameTargets, colorForName, worldCopies, validateCollection };
})();

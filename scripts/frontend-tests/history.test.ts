import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface View { year: number; basemap: 'historical' | 'modern'; boundaries: boolean; frame_id: string | null; source_version: string | null }
interface HistoryStatus { ready: boolean; reason?: string; version?: string; min_year?: number; max_year?: number; change_years?: number[] }
interface Controller {
  configure(status: HistoryStatus | null | undefined): void;
  getView(): View | null;
  setYear(year: number, intent?: 'user' | 'site', options?: { selectionOwned?: boolean }): void;
  setBasemap(basemap: 'historical' | 'modern', intent?: 'user' | 'site'): void;
  setBoundaries(enabled: boolean, intent?: 'user' | 'site'): void;
  retainBackground(note?: string): void;
  setSelectionContext(context: { title: string; precision: string | null; start_year: number | null; end_year: number | null } | null): void;
  actionVersion(): number;
}
interface Helpers {
  create(options: { map: FakeMap | null; tiles: FakeLayer | null; onCommittedView(view: View): void; onUserAction(): void; fixedHistorical?: boolean; sharedRenderer?: object | null; automaticOnly?: boolean }): Controller;
  isValidYear(year: number): boolean;
  yearToStep(year: number): number;
  stepToYear(step: number): number;
  formatYear(year: number): string;
  frameTargets(year: number, changes: number[], minimum?: number): { previous: number | null; next: number | null };
  colorForName(name: string): string;
  worldCopies(value: unknown): unknown;
  layoutPolityLabels(candidates: LabelCandidate[], viewport: { width: number; height: number }, exclusions?: LabelRect[]): number[];
}
interface LabelRect { x: number; y: number; width: number; height: number }
interface LabelCandidate extends LabelRect { token: number; name: string; area: number; composite: boolean }

class FakeElement extends EventTarget {
  tagName: string;
  textContent = '';
  title = '';
  className = '';
  hidden = false;
  disabled = false;
  value = '117';
  checked = false;
  min = '';
  max = '';
  href = '';
  target = '';
  rel = '';
  style: Record<string, string> = {};
  dataset: Record<string, string> = {};
  children: FakeElement[] = [];
  attributes = new Map<string, string>();
  tabIndex = 0;
  lastFocusOptions?: FocusOptions;
  onFocus?: () => void;
  parentElement: FakeElement | null = null;
  fixtureNodes: FakeElement[] = [];
  bounds = { left: 0, top: 0, width: 600, height: 400 };
  canvasUnavailable = false;

  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  removeAttribute(key: string): void { this.attributes.delete(key); }
  append(...nodes: FakeElement[]): void { for (const node of nodes) node.parentElement = this; this.children.push(...nodes); }
  replaceChildren(...nodes: FakeElement[]): void { this.children = [...nodes]; }
  focus(options?: FocusOptions): void { this.lastFocusOptions=options; this.onFocus?.(); }
  remove(): void { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((child) => child !== this); this.parentElement = null; }
  getBoundingClientRect() { return { ...this.bounds, right: this.bounds.left + this.bounds.width, bottom: this.bounds.top + this.bounds.height }; }
  querySelectorAll(): FakeElement[] { return this.fixtureNodes; }
  getContext() { return this.canvasUnavailable ? null : { font: '', measureText: (value: string) => ({ width: Array.from(value).length * 7 }) }; }
  set innerHTML(_value: string) { throw new Error('Unsafe innerHTML write'); }
  fire(type: string, key?: string): Event {
    const event = new Event(type, { cancelable: true });
    if (key !== undefined) Object.defineProperty(event, 'key', { value: key });
    this.dispatchEvent(event);
    return event;
  }
}

class FakeBounds {
  west: number; south: number; east: number; north: number;
  constructor(west: number, south: number, east: number, north: number) { this.west = west; this.south = south; this.east = east; this.north = north; }
  isValid(): boolean { return [this.west, this.south, this.east, this.north].every(Number.isFinite); }
  getCenter() { return { lat: (this.south + this.north) / 2, lng: (this.west + this.east) / 2 }; }
  getNorthWest() { return { lat: this.north, lng: this.west }; }
  getSouthEast() { return { lat: this.south, lng: this.east }; }
  intersects(other: FakeBounds): boolean { return this.west <= other.east && this.east >= other.west && this.south <= other.north && this.north >= other.south; }
}

class FakeLayer {
  data: unknown;
  options: GeoOptions;
  popups: (FakeElement | (() => FakeElement))[] = [];
  tooltip: { content: FakeElement; options: Record<string, unknown>; element: FakeElement; getElement(): FakeElement } | null = null;
  tooltipOpen = false;
  sentToBack = 0;
  members: FakeLayer[] = [];
  tooltipAnchor: { lat: number; lng: number } | null = null;
  listeners = new Map<string, (() => void)[]>();
  constructor(data: unknown = null, options: GeoOptions = {}) { this.data = data; this.options = options; }
  addTo(map: FakeMap): this { map.layers.add(this); return this; }
  bindPopup(node: FakeElement | (() => FakeElement)): this { this.popups.push(node); return this; }
  bindTooltip(node: FakeElement, options: Record<string, unknown>): this {
    const element = new FakeElement(); this.tooltip = { content: node, options, element, getElement: () => element };
    this.on('mouseover', () => { this.openTooltip(); }); this.on('mouseout', () => { this.closeTooltip(); });
    return this;
  }
  on(name: string, callback: () => void): this { this.listeners.set(name, [...this.listeners.get(name) ?? [], callback]); return this; }
  fire(name: string): void { for (const callback of this.listeners.get(name) ?? []) callback(); }
  getTooltip() { return this.tooltip; }
  openTooltip(anchor?: { lat: number; lng: number }): this { this.tooltipOpen = true; this.tooltipAnchor = anchor ?? null; return this; }
  closeTooltip(): this { this.tooltipOpen = false; return this; }
  eachLayer(callback: (layer: FakeLayer) => void): void { for (const child of this.members) callback(child); }
  getBounds(): FakeBounds {
    const points: [number, number][] = [];
    const visit = (input: unknown): void => {
      if (!Array.isArray(input)) return;
      if (typeof input[0] === 'number' && typeof input[1] === 'number') points.push([input[0], input[1]]);
      else input.forEach(visit);
    };
    visit((this.data as { geometry?: { coordinates?: unknown } })?.geometry?.coordinates);
    return new FakeBounds(Math.min(...points.map(point => point[0])), Math.min(...points.map(point => point[1])), Math.max(...points.map(point => point[0])), Math.max(...points.map(point => point[1])));
  }
  getCenter() { return this.getBounds().getCenter(); }
  bringToBack(): this { this.sentToBack++; return this; }
}

interface GeoOptions {
  renderer?: object;
  pane?: string;
  interactive?: boolean;
  attribution?: string;
  style?: Record<string, unknown> | ((feature: { properties: Record<string, unknown>; id?: string }) => Record<string, unknown>);
  onEachFeature?: (feature: { properties: Record<string, unknown>; id?: string }, layer: FakeLayer) => void;
}

class FakeMap {
  layers = new Set<FakeLayer>();
  panes = new Map<string, FakeElement>();
  container = new FakeElement();
  zoom = 4; center = { lat: 30.5, lng: 10.5 }; width = 600; height = 400;
  listeners = new Map<string, (() => void)[]>();
  getZoom(): number { return this.zoom; }
  getSize() { return { x: this.width, y: this.height }; }
  latLngToContainerPoint(value: { lat: number; lng: number }) {
    const scale = 256 * 2 ** this.zoom / 360;
    return { x: this.width / 2 + (value.lng - this.center.lng) * scale, y: this.height / 2 - (value.lat - this.center.lat) * scale };
  }
  getBounds(): FakeBounds { const scale = 256 * 2 ** this.zoom / 360; return new FakeBounds(this.center.lng - this.width / scale / 2, this.center.lat - this.height / scale / 2, this.center.lng + this.width / scale / 2, this.center.lat + this.height / scale / 2); }
  on(names: string, callback: () => void): this { for (const name of names.split(' ')) this.listeners.set(name, [...this.listeners.get(name) ?? [], callback]); return this; }
  fire(name: string): void { for (const callback of this.listeners.get(name) ?? []) callback(); }
  getPane(name: string): FakeElement | undefined { return this.panes.get(name); }
  createPane(name: string): FakeElement { const pane = new FakeElement(); this.panes.set(name, pane); return pane; }
  getContainer(): FakeElement { return this.container; }
  hasLayer(layer: FakeLayer): boolean { return this.layers.has(layer); }
  removeLayer(layer: FakeLayer): this { this.layers.delete(layer); layer.eachLayer(child => child.closeTooltip()); return this; }
}

interface Pending {
  url: string;
  signal: AbortSignal;
  resolve(value: { ok: boolean; status: number; json(): Promise<unknown> }): void;
  reject(error: Error): void;
  done: boolean;
}

const compiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/history.ts', import.meta.url), 'utf8'), {
  fileName: 'history.ts', compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true }, reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter((item) => item.category === ts.DiagnosticCategory.Error).length, 0);

const polygon = { type: 'Polygon', coordinates: [[[10, 30], [11, 30], [11, 31], [10, 30]]] };
const land = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: polygon }] };
const status: HistoryStatus = { ready: true, version: 'v0.2.1', min_year: -3400, max_year: 2024, change_years: [-100, 100, 200, 500] };

function frame(year: number, options: { from?: number; to?: number; id?: string; version?: string; empty?: boolean; name?: string; composite?: boolean } = {}) {
  return {
    type: 'FeatureCollection',
    features: options.empty ? [] : [{ type: 'Feature', id: 'polity-1', properties: { Name: options.name ?? 'Roman Empire', FromYear: -27, ToYear: 0, composite: options.composite ?? false, Wikipedia: 'javascript:alert(1)' }, geometry: structuredClone(polygon) }],
    metadata: { year, valid_from: options.from ?? 100, valid_to: options.to ?? 199, frame_id: options.id ?? 'frame-100-199', source: { name: 'Cliopatria', version: options.version ?? 'v0.2.1', uri: 'https://github.com/ercrema/cliopatria', license: 'CC BY 4.0', license_uri: 'https://creativecommons.org/licenses/by/4.0/' } },
  };
}

function setup(withMap = true, fixedHistorical = false, sharedRenderer: object | null = null, automaticOnly = false, includeLegacyControls = !automaticOnly) {
  const ids = ['history-controls', 'history-year', 'history-range', 'history-apply', 'history-previous-year', 'history-next-year', 'history-previous-frame', 'history-next-frame', 'history-basemap-historical', 'history-basemap-modern', 'history-boundaries', 'history-applied-year', 'history-draft-year', 'history-feedback', 'history-error', 'history-source', 'history-retry', 'history-map-caption', 'comparison-history-year'];
  if (automaticOnly) ids.push('history-linkage-status');
  const nodes = new Map(ids.map((id) => [id, new FakeElement()]));
  const legacyIds = ['history-year', 'history-range', 'history-apply', 'history-previous-year', 'history-next-year', 'history-previous-frame', 'history-next-frame', 'history-basemap-historical', 'history-basemap-modern', 'history-boundaries', 'history-draft-year'];
  if (!includeLegacyControls) for (const id of legacyIds) nodes.delete(id);
  const doc: { activeElement: FakeElement | null; getElementById(id: string): FakeElement | null; createElement(tag: string): FakeElement; createTextNode(text: string): FakeElement } = {
    activeElement: null,
    getElementById: (id) => nodes.get(id) ?? null,
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (text) => { const node = new FakeElement('#text'); node.textContent = text; return node; },
  };
  for (const node of nodes.values()) node.onFocus = () => { doc.activeElement = node; };
  const pending: Pending[] = [];
  const layers: FakeLayer[] = [];
  const timers = new Map<number, () => void>();
  const delays: number[] = [];
  let timerId = 0;
  const animationFrames: (() => void)[] = [];
  const context = createContext({
    document: doc, URL, AbortController,
    getComputedStyle: () => ({ fontStyle: 'normal', fontWeight: '600', fontSize: '12px', fontFamily: 'Georgia, serif' }),
    requestAnimationFrame(callback: () => void) { animationFrames.push(callback); return animationFrames.length; },
    setTimeout(callback: () => void, delay: number) { delays.push(delay); const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout(id: number) { timers.delete(id); },
    fetch(url: string, options: { signal: AbortSignal }) {
      return new Promise((resolve, reject) => { pending.push({ url, signal: options.signal, resolve, reject, done: false }); });
    },
    L: {
      canvas: (options: object) => ({ ...options }),
      geoJSON(data: unknown, options: GeoOptions) {
        const layer = new FakeLayer(data, options);
        if (typeof data === 'object' && data !== null && 'features' in data && Array.isArray(data.features)) {
          for (const feature of data.features as { properties: Record<string, unknown>; id?: string }[]) {
            const child = new FakeLayer(feature, options); layer.members.push(child);
            options.onEachFeature?.(feature, child);
          }
        }
        layers.push(layer);
        return layer;
      },
    },
  });
  const helpers = runInContext(`${compiled.outputText}\nArchSearchHistory;`, context) as Helpers;
  const map = new FakeMap();
  const tiles = new FakeLayer();
  tiles.addTo(map);
  const commits: View[] = [];
  let actions = 0;
  const view = helpers.create({ map: withMap ? map : null, tiles: withMap ? tiles : null, onCommittedView: (value) => commits.push(value), onUserAction: () => { actions++; }, fixedHistorical, sharedRenderer, automaticOnly });
  const node = (id: string): FakeElement => { const value = nodes.get(id); assert.ok(value); return value; };
  const flushLabels = () => { const callbacks = animationFrames.splice(0); callbacks.forEach(callback => callback()); };
  function runTimers(): void { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } }
  function complete(request: Pending, value: unknown, code = 200): void {
    request.done = true;
    request.resolve({ ok: code >= 200 && code < 300, status: code, json: async () => value });
  }
  function boundaryRequest(year: number): Pending {
    const request = pending.find((item) => !item.done && item.url === `/api/history/boundaries?year=${year}`);
    assert.ok(request, `No pending boundary request for ${year}`);
    return request;
  }
  async function finishInitial(options: Parameters<typeof frame>[1] = {}): Promise<void> {
    view.configure(status); runTimers();
    const landRequest = pending.find((request) => request.url.endsWith('land.geojson'));
    assert.ok(landRequest); complete(landRequest, land);
    complete(boundaryRequest(117), frame(117, options));
    await tick();
  }
  return { helpers, view, map, tiles, pending, commits, node, doc, layers, delays, runTimers, complete, boundaryRequest, finishInitial, flushLabels, animationFrames, get actions() { return actions; } };
}

async function tick(): Promise<void> { for (let index = 0; index < 20; index++) await Promise.resolve(); }
function allText(node: FakeElement): string { return node.textContent + node.children.map(allText).join(''); }
function allNodes(node: FakeElement): FakeElement[] { return [node, ...node.children.flatMap(allNodes)]; }

function candidate(token: number, x: number, y: number, extra: Partial<LabelCandidate> = {}): LabelCandidate {
  return { token, name: `Polity ${token}`, x, y, width: 90, height: 20, area: 8000, composite: false, ...extra };
}

test('screen label layout is deterministic, rejects collisions and prioritizes solid larger visible shapes', () => {
  const { helpers } = setup();
  const values = [candidate(1, 60, 30, { area: 1000 }), candidate(2, 64, 32, { area: 9000 }),
    candidate(3, 65, 34, { area: 100000, composite: true }), candidate(4, 210, 30), candidate(5, 210, 120)];
  const selected = helpers.layoutPolityLabels(values, { width: 400, height: 240 });
  assert.deepEqual(Array.from(selected), [2, 5, 4]);
  assert.deepEqual(Array.from(helpers.layoutPolityLabels(values.slice().reverse(), { width: 400, height: 240 })), Array.from(selected));
  const selectedBoxes = selected.map(token => values.find(value => value.token === token)!);
  for (const [index, left] of selectedBoxes.entries()) for (const right of selectedBoxes.slice(index + 1)) {
    assert(left.x + left.width + 6 <= right.x || right.x + right.width + 6 <= left.x || left.y + left.height + 6 <= right.y || right.y + right.height + 6 <= left.y);
  }
});

test('same-name fragments and world copies choose one fitting label without merging source identity', () => {
  const { helpers } = setup();
  const values = [candidate(1, -50, 40, { name: 'Shared source name' }), candidate(2, 20, 60, { name: 'Shared source name' }),
    candidate(3, 150, 90, { name: 'Shared source name' }), candidate(4, 310, 60, { name: 'Other source name' })];
  const frozen = JSON.stringify(values);
  assert.deepEqual(Array.from(helpers.layoutPolityLabels(values, { width: 450, height: 220 })), [3, 4]);
  assert.equal(JSON.stringify(values), frozen);
});

test('labels avoid marker and control rectangles and do not force tiny, offscreen or invalid names into the view', () => {
  const { helpers } = setup();
  const values = [candidate(1, 50, 50), candidate(2, 200, 50), candidate(3, 40, 120, { area: 10 }),
    candidate(4, 330, 20, { width: 100 }), candidate(5, 30, 100, { name: '  ' }), candidate(6, 80, 80, { x: NaN })];
  assert.deepEqual(Array.from(helpers.layoutPolityLabels(values, { width: 400, height: 200 }, [{ x: 40, y: 40, width: 120, height: 44 }])), [2]);
  assert.deepEqual(Array.from(helpers.layoutPolityLabels(values, { width: 0, height: 200 })), []);
  assert.deepEqual(Array.from(helpers.layoutPolityLabels(values, { width: 400, height: NaN })), []);
});

test('historical label refresh batches map changes and avoids point markers and sibling captions without requesting another year', async () => {
  const env = setup(true, true); env.map.zoom = 7; await env.finishInitial();
  const boundary = env.layers.find(layer => layer.options.pane === 'history-boundaries')!;
  const visible = () => boundary.members.filter(layer => layer.tooltipOpen);
  assert.equal(visible().length, 1);
  const original = JSON.stringify(boundary.data), requests = env.pending.length;
  const marker = new FakeElement(); marker.bounds = { left: 270, top: 180, width: 60, height: 40 }; env.map.container.fixtureNodes = [marker];
  for (const event of ['moveend', 'resize', 'archsearch:markerschange']) env.map.fire(event);
  assert.equal(env.animationFrames.length, 1); env.flushLabels(); assert.equal(visible().length, 0);
  env.map.container.fixtureNodes = [];
  const shell = new FakeElement(), caption = new FakeElement(); caption.bounds = { left: 260, top: 180, width: 80, height: 40 };
  shell.fixtureNodes = [caption]; env.map.container.parentElement = shell;
  env.map.fire('archsearch:markerschange'); env.flushLabels(); assert.equal(visible().length, 0);
  shell.fixtureNodes = []; env.map.width = 390; env.map.height = 200;
  env.map.fire('resize'); env.flushLabels(); assert.equal(visible().length, 1);
  env.map.fire('zoomstart'); assert.equal(visible().length, 0);
  env.map.zoom = 2; env.map.fire('zoomend'); env.flushLabels(); assert.equal(visible().length, 0);
  env.map.zoom = 7; env.map.fire('zoomend'); env.flushLabels(); assert.equal(visible().length, 1);
  assert.equal(env.pending.length, requests); assert.equal(env.view.getView()?.year, 117); assert.equal(env.actions, 0);
  assert.equal(JSON.stringify(boundary.data), original);
});

test('long and absent permanent labels retain complete safe source popups and new frames close old labels', async () => {
  const env = setup(true, true); env.map.zoom = 7;
  const name = '<b>Literal source</b> ' + 'VeryLongName'.repeat(30); await env.finishInitial({ name });
  const old = env.layers.find(layer => layer.options.pane === 'history-boundaries')!;
  const chosen = old.members.find(layer => layer.tooltipOpen)!;
  assert.ok(chosen); assert.equal(chosen.tooltip?.content.textContent, name);
  assert.equal(chosen.tooltip?.content.style.width, '128px'); assert.equal(chosen.tooltip?.content.style.height, '32px');
  assert.equal(chosen.tooltip?.element.attributes.get('data-polity-label'), name);
  const sourcePopup = chosen.popups[0]; assert.equal(typeof sourcePopup, 'function');
  assert.ok(allText((sourcePopup as () => FakeElement)()).includes(name));
  env.view.setYear(200); env.runTimers(); env.complete(env.boundaryRequest(200), frame(200, { from: 200, to: 299, name: '' })); await tick();
  assert.ok(old.members.every(layer => !layer.tooltipOpen));
  const next = env.layers.filter(layer => layer.options.pane === 'history-boundaries').at(-1)!;
  assert.ok(next.members.every(layer => !layer.tooltipOpen && layer.tooltip !== null));
  assert.ok(next.members.every(layer => layer.popups.length === 1));
  assert.equal(env.view.getView()?.year, 200);
});

test('no canvas text context never estimates permanent label widths and leaves source reading available', async () => {
  const env = setup(true, true); env.map.zoom = 7;
  const create = env.doc.createElement;
  env.doc.createElement = (tag) => { const node = create(tag); if (tag === 'canvas') node.canvasUnavailable = true; return node; };
  await env.finishInitial();
  const boundary = env.layers.find(layer => layer.options.pane === 'history-boundaries')!;
  assert.ok(boundary.members.every(layer => !layer.tooltipOpen && layer.tooltip !== null));
  assert.ok(boundary.members.every(layer => layer.tooltip?.content.style.width === '128px' && layer.tooltip.content.style.height === '32px'));
  boundary.members[1].openTooltip(); assert.equal(boundary.members[1].tooltipOpen, true);
  const source = boundary.members[1].popups[0]; assert.equal(typeof source, 'function');
  assert.match(allText((source as () => FakeElement)()), /Roman Empire.*Cliopatria.*CC BY 4\.0/u);
});

test('native mouseout does not erase a managed permanent name while a suppressed name remains an ordinary hover tooltip', async () => {
  const env = setup(true, true); env.map.zoom = 7; await env.finishInitial();
  const boundary = env.layers.find(layer => layer.options.pane === 'history-boundaries')!;
  const selected = boundary.members.find(layer => layer.tooltipOpen)!;
  selected.fire('mouseover'); selected.fire('mouseout');
  assert.equal(selected.tooltipOpen, true); assert.equal(selected.tooltip?.options.permanent, true);
  const marker = new FakeElement(); marker.bounds = { left: 270, top: 180, width: 60, height: 40 }; env.map.container.fixtureNodes = [marker];
  env.map.fire('archsearch:markerschange'); env.flushLabels();
  assert.equal(selected.tooltipOpen, false); assert.equal(selected.tooltip?.options.permanent, false);
  selected.fire('mouseover'); assert.equal(selected.tooltipOpen, true);
  selected.fire('mouseout'); assert.equal(selected.tooltipOpen, false);
});

test('fixed historical comparison retains real filled polities and literal names instead of an OSM base', async () => {
  const env = setup(true, true); env.map.zoom = 7; await env.finishInitial({ name: '<b>Kingdom fixture</b>' });
  const boundary = env.layers.find(layer => layer.options.pane === 'history-boundaries'); assert.ok(boundary);
  assert.equal(typeof boundary.options.style, 'function');
  const style = boundary.options.style as (feature: { properties: Record<string, unknown> }) => Record<string, unknown>;
  assert.equal(style({ properties: { Name: 'Kingdom fixture', composite: false } }).fillOpacity, 0.26);
  assert.equal(style({ properties: { Name: 'Composite fixture', composite: true } }).fillOpacity, 0);
  assert.equal(style({ properties: { Name: 'Composite fixture', composite: true } }).dashArray, '7 5');
  const names = boundary.members.filter(child => child.tooltipOpen);
  assert.equal(names.length, 1); assert.equal(names[0].tooltip?.content.textContent, '<b>Kingdom fixture</b>');
  assert.equal(env.map.panes.get('history-polity-labels')?.style.zIndex, '420');
  env.view.setBasemap('modern'); env.runTimers(); await tick();
  assert.equal(env.view.getView()?.basemap, 'historical'); assert.equal(env.map.hasLayer(env.tiles), false);
  assert.equal(env.node('comparison-history-year').textContent, '公元 117 年');
  assert.match(env.node('comparison-history-year').title, /117.*v0\.2\.1/u);
  assert.match(env.node('comparison-history-year').attributes.get('aria-label')!, /实际显示.*117.*v0\.2\.1/u);
});

test('a quick exact-year site selection while history is unprepared still loads local land without a historical frame', async () => {
  const env = setup(true, true); env.view.configure({ ready: false, reason: '请准备疆域资料' });
  env.view.setYear(1616, 'site'); env.runTimers();
  const request = env.pending.find(item => item.url.endsWith('land.geojson')); assert.ok(request);
  env.complete(request, land); await tick();
  assert.equal(env.pending.some(item => item.url.includes('/api/history/')), false);
  assert.ok(env.layers.some(layer => layer.options.pane === 'history-land' && env.map.hasLayer(layer)));
  assert.equal(env.view.getView()?.frame_id, null); assert.equal(env.view.getView()?.boundaries, false);
  assert.match(env.node('comparison-history-year').textContent, /无可用疆域数据/u);
  assert.equal(env.map.hasLayer(env.tiles), false);
});

test('the timeline has no year zero and crosses BCE/CE in both directions', () => {
  const { helpers } = setup();
  for (const year of [-3400, -1, 1, 117, 2024]) assert.equal(helpers.stepToYear(helpers.yearToStep(year)), year);
  assert.equal(helpers.stepToYear(helpers.yearToStep(-1) + 1), 1);
  assert.equal(helpers.stepToYear(helpers.yearToStep(1) - 1), -1);
  for (const value of [0, -3401, 2025, 1.5, NaN, Infinity]) assert.equal(helpers.isValidYear(value), false);
  assert.throws(() => helpers.yearToStep(0), /0/);
  assert.throws(() => helpers.stepToYear(1.5));
  assert.equal(helpers.formatYear(-27), '公元前 27 年');
});

test('previous and next frames leave the current unchanged interval rather than stepping to its start', () => {
  const { helpers } = setup();
  const targets = helpers.frameTargets(117, [200, 100, -100, 100, 0]);
  assert.equal(targets.previous, -100); assert.equal(targets.next, 200);
  assert.equal(helpers.frameTargets(-3400, [-100, 100]).previous, null);
  assert.equal(helpers.frameTargets(2024, [-100, 100]).next, null);
});

test('unprepared and missing maps reject year actions without throwing or creating requests', () => {
  const env = setup();
  env.view.configure({ ready: false, reason: '请准备边界数据' });
  assert.doesNotThrow(() => env.view.setYear(117));
  assert.doesNotThrow(() => env.view.setYear(0));
  env.runTimers(); assert.equal(env.pending.length, 0); assert.equal(env.view.getView(), null);
  assert.equal(env.node('history-range').disabled, true);
  const missing = setup(false); missing.view.configure(status); missing.runTimers();
  assert.equal(missing.pending.length, 0); assert.equal(missing.node('history-basemap-modern').disabled, true);
});

test('the initial world view commits only after both local basemap and year 117 frame succeed', async () => {
  const env = setup(); await env.finishInitial();
  assert.equal(env.commits.length, 1); assert.equal(env.view.getView()?.year, 117);
  assert.equal(env.view.getView()?.basemap, 'historical'); assert.equal(env.view.getView()?.frame_id, 'frame-100-199');
  assert.equal(env.map.hasLayer(env.tiles), false);
  assert.equal(env.map.panes.get('history-boundaries')?.style.zIndex, '350');
  assert.equal(env.map.container.dataset.basemap, 'historical');
  assert.match(allText(env.node('history-source')), /Cliopatria.*v0\.2\.1.*CC BY 4\.0/);
  assert.ok(env.delays.every((delay) => delay === 200));
});

test('rapid year changes debounce to one request and only user intent increments the action version', async () => {
  const env = setup(); await env.finishInitial();
  env.view.setYear(201); env.view.setYear(202); env.view.setYear(203, 'site');
  assert.equal(env.view.actionVersion(), 2); assert.equal(env.actions, 2);
  env.runTimers(); assert.ok(env.boundaryRequest(203));
  assert.equal(env.pending.filter((item) => /year=20[12]$/.test(item.url)).length, 0);
});

test('changing years within the same valid frame reuses geometry while committing the requested year', async () => {
  const env = setup(); await env.finishInitial();
  const count = env.pending.length;
  env.view.setYear(118); env.runTimers(); await tick();
  assert.equal(env.pending.length, count); assert.equal(env.view.getView()?.year, 118);
  assert.equal(env.view.getView()?.frame_id, 'frame-100-199');
  const copy = env.view.getView(); assert.ok(copy); copy.year = 500;
  assert.equal(env.view.getView()?.year, 118);
});

test('a canceled stale response cannot overwrite a newer successful map year', async () => {
  const env = setup(); await env.finishInitial();
  env.view.setYear(200); env.runTimers(); const old = env.boundaryRequest(200);
  env.view.setYear(500); env.runTimers(); assert.equal(old.signal.aborted, true);
  env.complete(env.boundaryRequest(500), frame(500, { from: 500, to: 600, id: 'new-frame' })); await tick();
  env.complete(old, frame(200, { from: 200, to: 499, id: 'old-frame' })); await tick();
  assert.equal(env.view.getView()?.year, 500); assert.equal(env.commits.length, 2);
});

for (const failure of ['http-503', 'invalid-json'] as const) {
  test(`a canceled ${failure} response cannot restore old boundaries or basemap after newer success`, async () => {
    const env = setup(); await env.finishInitial();
    env.view.setYear(200); env.runTimers(); const old = env.boundaryRequest(200);
    env.view.setYear(500); env.view.setBasemap('modern'); env.runTimers();
    assert.equal(old.signal.aborted, true);
    env.complete(env.boundaryRequest(500), frame(500, { from: 500, to: 600, id: 'new-frame' }));
    await tick();
    const layers = new Set(env.map.layers);
    assert.equal([...layers].filter((layer) => layer.options.pane === 'history-boundaries').length, 1);
    assert.equal(env.map.hasLayer(env.tiles), true);
    if (failure === 'http-503') env.complete(old, { detail: 'Old failed request' }, 503);
    else {
      old.done = true;
      old.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('Invalid old JSON'); } });
    }
    await tick();
    assert.deepEqual(env.map.layers, layers);
    assert.equal([...env.map.layers].filter((layer) => layer.options.pane === 'history-boundaries').length, 1);
    assert.equal(env.map.hasLayer(env.tiles), true);
    assert.equal(env.map.container.dataset.basemap, 'modern');
    assert.equal(env.view.getView()?.basemap, 'modern');
    assert.equal(env.view.getView()?.year, 500);
    assert.equal(env.view.getView()?.frame_id, 'new-frame');
    assert.equal(env.commits.length, 2);
    assert.equal(env.node('history-error').hidden, true);
  });
}

test('HTTP failures preserve the prior year, geometry, attribution and tiles with a retry action', async () => {
  const env = setup(); await env.finishInitial(); const before = new Set(env.map.layers);
  env.view.setYear(200); env.runTimers(); env.complete(env.boundaryRequest(200), { detail: '受控边界失败' }, 503); await tick();
  assert.equal(env.view.getView()?.year, 117); assert.deepEqual(env.map.layers, before); assert.equal(env.commits.length, 1);
  assert.match(env.node('history-error').textContent, /受控边界失败.*117/);
  assert.equal(env.node('history-retry').hidden, false);
});

test('mismatched frame year, bounds and source versions never replace the committed frame', async () => {
  for (const invalid of [frame(201, { from: 200, to: 300 }), frame(200, { from: 100, to: 199 }), frame(200, { from: 200, to: 300, version: 'other' })]) {
    const env = setup(); await env.finishInitial();
    env.view.setYear(200); env.runTimers(); env.complete(env.boundaryRequest(200), invalid); await tick();
    assert.equal(env.view.getView()?.year, 117); assert.equal(env.commits.length, 1); assert.equal(env.node('history-error').hidden, false);
  }
});

test('invalid and nonfinite geometry is rejected before creating any replacement layer', async () => {
  const env = setup(); await env.finishInitial(); const before = env.layers.length;
  env.view.setYear(200); env.runTimers();
  const invalid = frame(200, { from: 200, to: 300 });
  invalid.features[0].geometry.coordinates[0][1][0] = Infinity;
  env.complete(env.boundaryRequest(200), invalid); await tick();
  assert.equal(env.layers.length, before); assert.equal(env.view.getView()?.year, 117);
});

test('empty historical frames are successful and explicitly distinguished from empty search results', async () => {
  const env = setup(); await env.finishInitial({ empty: true });
  assert.equal(env.view.getView()?.year, 117); assert.equal(env.commits.length, 1);
  assert.match(env.node('history-feedback').textContent, /没有.*活动政权.*地点标记仍保留/);
});

test('boundaries and basemap switches remain independent and do not move or replace site markers', async () => {
  const env = setup(); const marker = new FakeLayer(); marker.addTo(env.map); await env.finishInitial();
  env.view.setBasemap('modern'); env.runTimers(); await tick();
  assert.equal(env.map.hasLayer(env.tiles), true); assert.equal(env.view.getView()?.boundaries, true);
  env.view.setBoundaries(false); env.runTimers(); await tick();
  assert.equal(env.view.getView()?.frame_id, null); assert.equal(env.view.getView()?.basemap, 'modern');
  assert.equal(env.map.hasLayer(marker), true);
  env.view.setBasemap('historical'); env.runTimers(); await tick();
  assert.equal(env.map.hasLayer(env.tiles), false); assert.equal(env.view.getView()?.boundaries, false); assert.equal(env.map.hasLayer(marker), true);
});

test('source content remains literal text and composite boundaries have no fill', async () => {
  const env = setup(); await env.finishInitial({ name: '<img src=x onerror=alert(1)>', composite: true });
  const boundary = env.layers.find((layer) => layer.options.pane === 'history-boundaries'); assert.ok(boundary);
  const styleFor = boundary.options.style;
  assert.ok(typeof styleFor === 'function');
  const style = styleFor({ properties: { Name: 'Composite', composite: true } });
  assert.equal(style.fill, false); assert.equal(style.fillOpacity, 0); assert.equal(style.dashArray, '5 4');
  const normal = styleFor({ properties: { Name: 'Empire', composite: false } });
  assert.equal(normal.fillOpacity, 0.1);
  assert.equal(env.helpers.colorForName('Empire'), normal.color);
  const readPopup = boundary.members[0].popups[0]; assert.ok(typeof readPopup === 'function');
  const popup = readPopup();
  assert.match(allText(popup), /<img src=x onerror=alert\(1\)>/);
  assert.ok(allNodes(popup).filter((node) => node.tagName === 'A').every((node) => node.href.startsWith('https://')));
  assert.match(allText(popup), /原值 0.*公元前 1 年/);
});

test('new status versions invalidate cached historical frames', async () => {
  const env = setup(); await env.finishInitial();
  env.view.configure({ ...status, version: 'v0.2.2' }); env.runTimers();
  const request = env.boundaryRequest(117);
  env.complete(request, frame(117, { version: 'v0.2.2', id: 'version-two' })); await tick();
  assert.equal(env.view.getView()?.source_version, 'v0.2.2'); assert.equal(env.view.getView()?.frame_id, 'version-two');
});

test('keyboard year actions and the range step directly from BCE 1 to CE 1', async () => {
  const env = setup(); await env.finishInitial();
  env.view.setYear(-1); env.node('history-next-year').fire('click');
  assert.equal(env.node('history-range').value, '0'); assert.equal(env.node('history-year').value, '1');
  env.node('history-previous-year').fire('click'); assert.equal(env.node('history-year').value, '-1');
  const event = env.node('history-year').fire('keydown', 'ArrowUp'); assert.equal(event.defaultPrevented, true);
  assert.equal(env.node('history-year').value, '1');
  env.doc.activeElement = env.node('history-year'); env.node('history-year').value = '500'; env.node('history-year').fire('input');
  env.node('history-year').fire('keydown', 'ArrowUp'); assert.equal(env.node('history-year').value, '501');
});

test('invalid draft input cancels pending work and preserves the last committed snapshot', async () => {
  const env = setup(); await env.finishInitial();
  env.view.setYear(200); env.runTimers(); const request = env.boundaryRequest(200);
  env.doc.activeElement = env.node('history-year'); env.node('history-year').value = '0'; env.node('history-year').fire('input'); env.node('history-year').fire('change');
  assert.equal(request.signal.aborted, true); assert.equal(env.view.getView()?.year, 117);
  assert.equal(env.node('history-year').attributes.get('aria-invalid'), 'true');
  assert.match(env.node('history-error').textContent, /没有公元 0 年/);
});

test('modern basemap remains usable while historical boundary data is unprepared', async () => {
  const env = setup(); env.view.configure({ ready: false, reason: '准备中' });
  env.view.setBasemap('modern'); env.runTimers(); await tick();
  assert.equal(env.pending.length, 0); assert.equal(env.map.hasLayer(env.tiles), true);
  assert.equal(env.view.getView()?.basemap, 'modern'); assert.equal(env.view.getView()?.boundaries, false);
  assert.match(env.node('history-feedback').textContent, /准备中/);
});

test('unprepared status preserves a previously committed historical frame on basemap switches', async () => {
  const env = setup(); await env.finishInitial();
  env.view.configure({ ready: false, version: 'v0.2.1', reason: '边界暂不可用' });
  env.view.setBasemap('modern'); env.runTimers(); await tick();
  assert.equal(env.view.getView()?.year, 117); assert.equal(env.view.getView()?.frame_id, 'frame-100-199');
  assert.equal(env.view.getView()?.boundaries, true); assert.equal(env.view.getView()?.basemap, 'modern');
});

test('a failed local geographic basemap load preserves the successful modern view', async () => {
  const env = setup(); env.view.configure(status); env.view.setBasemap('modern'); env.runTimers();
  env.complete(env.boundaryRequest(117), frame(117)); await tick();
  const before = new Set(env.map.layers);
  env.view.setBasemap('historical'); env.runTimers();
  const request = env.pending.find((item) => !item.done && item.url.endsWith('land.geojson')); assert.ok(request);
  env.complete(request, { detail: '自然地理资料缺失' }, 404); await tick();
  assert.deepEqual(env.map.layers, before); assert.equal(env.view.getView()?.basemap, 'modern');
  assert.equal(env.map.hasLayer(env.tiles), true); assert.equal(env.commits.length, 1);
});

test('retry controls hand keyboard focus to persistent feedback before becoming hidden', async () => {
  const env = setup(); await env.finishInitial();
  env.view.setYear(200); env.runTimers(); env.complete(env.boundaryRequest(200), { detail: '失败' }, 503); await tick();
  env.doc.activeElement = env.node('history-retry'); env.node('history-retry').fire('click');
  assert.equal(env.node('history-retry').hidden, true); assert.equal(env.doc.activeElement, env.node('history-feedback'));
  assert.equal(env.node('history-feedback').lastFocusOptions?.preventScroll,true);
});

test('automatic retry hands keyboard focus to the visible linkage banner instead of clipped legacy feedback', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setSelectionContext(exactContext(366)); env.view.setYear(366,'site',{selectionOwned:true}); env.runTimers();
  env.complete(env.boundaryRequest(366),{detail:'失败'},503); await tick();
  const linkage=env.node('history-linkage-status');
  env.doc.activeElement=env.node('history-retry'); env.node('history-retry').fire('click');
  assert.equal(env.node('history-retry').hidden,true); assert.equal(env.doc.activeElement,linkage);
  assert.equal(linkage.tabIndex,-1); assert.equal(linkage.lastFocusOptions,undefined);
  env.runTimers(); env.complete(env.boundaryRequest(366),frame(366,{from:366,to:366,id:'keyboard-retry-366'})); await tick();
  assert.equal(env.doc.activeElement,linkage); assert.equal(linkage.dataset.state,'matched');
});

test('a restored year remains pending while data is unavailable and loads unchanged after refresh', async () => {
  const env = setup(); env.view.configure({ ready: false, reason: '准备中' });
  env.view.setYear(-44, 'site'); env.runTimers();
  assert.equal(env.pending.length, 0); assert.equal(env.view.getView(), null);
  assert.equal(env.node('history-year').value, '-44');
  assert.match(env.node('history-draft-year').textContent, /公元前 44 年/);
  env.view.configure(status); env.runTimers();
  const landRequest = env.pending.find((request) => request.url.endsWith('land.geojson')); assert.ok(landRequest);
  env.complete(landRequest, land); env.complete(env.boundaryRequest(-44), frame(-44, { from: -100, to: -1 })); await tick();
  assert.equal(env.view.getView()?.year, -44); assert.equal(env.view.actionVersion(), 0);
});

test('narrowed source bounds retain the plan and committed year without clamping or issuing a replacement request', async () => {
  const env = setup(); await env.finishInitial(); const before = env.pending.length;
  env.view.configure({ ...status, min_year: 1, max_year: 100 }); env.runTimers(); await tick();
  assert.equal(env.pending.length, before); assert.equal(env.view.getView()?.year, 117);
  assert.equal(env.node('history-year').value, '117'); assert.match(env.node('history-error').textContent, /117.*计划年份保持不变/);
  env.view.setYear(110, 'site'); env.runTimers();
  assert.equal(env.pending.length, before); assert.equal(env.node('history-year').value, '110');
  assert.equal(env.view.getView()?.year, 117);
});

test('a numeric draft stays visible until explicitly applied and never changes the successful frame', async () => {
  const env = setup(); await env.finishInitial();
  env.doc.activeElement = env.node('history-year'); env.node('history-year').value = '200'; env.node('history-year').fire('input');
  assert.equal(env.view.getView()?.year, 117); assert.match(env.node('history-draft-year').textContent, /200.*尚未应用/);
  env.doc.activeElement = env.node('history-apply'); env.node('history-apply').fire('click'); env.runTimers();
  assert.ok(env.boundaryRequest(200)); assert.equal(env.view.getView()?.year, 117);
});

test('display copies cover adjacent worlds without changing source geometry, IDs, properties or metadata', () => {
  const env = setup(); const original = frame(117); const before = JSON.stringify(original);
  const copied = env.helpers.worldCopies(original) as ReturnType<typeof frame>;
  assert.equal(JSON.stringify(original), before); assert.equal(copied.features.length, 3);
  assert.deepEqual(Array.from(copied.features, (feature) => feature.geometry.coordinates[0][0][0]), [-350, 10, 370]);
  for (const feature of copied.features) {
    assert.equal(feature.id, original.features[0].id); assert.equal(feature.properties, original.features[0].properties);
    assert.equal(feature.geometry.coordinates[0][0][1], original.features[0].geometry.coordinates[0][0][1]);
  }
  assert.equal(copied.metadata, original.metadata);
});

test('both historical boundaries and local land use display copies while committed frame identity stays original', async () => {
  const env = setup(); await env.finishInitial();
  const boundaries = env.layers.find((layer) => layer.options.pane === 'history-boundaries');
  const geography = env.layers.find((layer) => layer.options.pane === 'history-land');
  assert.ok(boundaries); assert.ok(geography);
  assert.equal((boundaries.data as { features: unknown[] }).features.length, 3);
  assert.equal((geography.data as { features: unknown[] }).features.length, 3);
  assert.equal(env.view.getView()?.frame_id, 'frame-100-199');
  assert.equal(boundaries.members.length, 3);
  assert.ok(boundaries.members.every(member => member.popups.length === 1 && typeof member.popups[0] === 'function'));
});

test('the bundled local Natural Earth geometry is accepted without alteration or network dependencies', async () => {
  const env = setup(); const original = readFileSync(new URL('../../src/archsearch/static/data/land.geojson', import.meta.url), 'utf8');
  const geography: unknown = JSON.parse(original); env.view.configure(status); env.runTimers();
  const request = env.pending.find((item) => item.url.endsWith('land.geojson')); assert.ok(request);
  env.complete(request, geography); env.complete(env.boundaryRequest(117), frame(117)); await tick();
  assert.equal(env.view.getView()?.basemap, 'historical'); assert.equal(env.node('history-error').hidden, true);
  assert.equal(JSON.stringify(geography), JSON.stringify(JSON.parse(original)));
});

test('shared historical Canvas keeps source-point hit testing and places every replacement polity underneath it', async () => {
  const sharedRenderer = { fixture: 'same interactive canvas' };
  const env = setup(true, true, sharedRenderer); await env.finishInitial();
  const boundaries = () => env.layers.filter(layer => layer.options.pane === 'history-boundaries');
  const first = boundaries()[0]; assert.ok(first);
  assert.equal(first.options.renderer, sharedRenderer);
  assert.equal((first.options.style as (feature: { properties: Record<string, unknown> }) => Record<string, unknown>)({ properties: { Name: 'Fixture' } }).renderer, sharedRenderer);
  assert.equal(first.sentToBack, 1);
  env.view.setYear(200); env.runTimers(); env.complete(env.boundaryRequest(200), frame(200, {from:200,to:299,id:'new-frame'})); await tick();
  assert.equal(boundaries().length, 2); assert.ok(boundaries().every(layer => layer.options.renderer === sharedRenderer && layer.sentToBack === 1));
  assert.equal(env.map.hasLayer(first), false); assert.equal(env.map.hasLayer(boundaries()[1]), true);
});

test('automatic history needs only status display elements and follows explicit site years', async () => {
  const renderer = { shared: 'source-points-and-polities' };
  const env = setup(true, false, renderer, true); await env.finishInitial();
  assert.equal(env.view.getView()?.year, 117);
  assert.match(env.node('history-applied-year').textContent, /历史背景.*117/u);
  assert.match(env.node('history-feedback').textContent, /明确年份联动.*区间或未知年代不推断/u);
  env.view.setYear(1616, 'site'); env.runTimers();
  env.complete(env.boundaryRequest(1616), frame(1616, {from:1616,to:1616,id:'burial-frame'})); await tick();
  assert.equal(env.view.getView()?.year, 1616); assert.equal(env.view.getView()?.basemap, 'historical');
  assert.equal(env.view.actionVersion(), 0); assert.match(allText(env.node('history-source')), /Cliopatria/u);
  const boundary = env.layers.filter(layer => layer.options.pane === 'history-boundaries').at(-1)!;
  assert.equal(boundary.options.renderer, renderer); assert.equal(boundary.sentToBack, 1);
});

test('automatic history never binds old manual controls even when a legacy layout contains them', async () => {
  const env = setup(true, false, null, true, true); await env.finishInitial(); const before = env.pending.length;
  env.node('history-year').value = '1930'; env.node('history-year').fire('input'); env.node('history-year').fire('change');
  env.node('history-year').fire('keydown', 'Enter'); env.node('history-range').value = '1929'; env.node('history-range').fire('input');
  for (const id of ['history-apply','history-previous-year','history-next-year','history-previous-frame','history-next-frame','history-basemap-modern']) env.node(id).fire('click');
  env.node('history-boundaries').checked = false; env.node('history-boundaries').fire('change');
  env.runTimers(); await tick(); assert.equal(env.pending.length, before); assert.equal(env.view.getView()?.year, 117);
  assert.equal(env.view.getView()?.boundaries, true); assert.equal(env.view.actionVersion(), 0);
});

test('automatic old shares restore the year while keeping the natural polity view enabled', async () => {
  const env = setup(true, false, null, true);
  env.view.setBasemap('modern', 'site'); env.view.setBoundaries(false, 'site'); env.view.setYear(-44, 'site');
  env.view.configure(status); env.runTimers();
  const landRequest = env.pending.find(request => request.url.endsWith('land.geojson')); assert.ok(landRequest);
  env.complete(landRequest, land); env.complete(env.boundaryRequest(-44), frame(-44, {from:-100,to:-1})); await tick();
  assert.equal(env.view.getView()?.year, -44); assert.equal(env.view.getView()?.basemap, 'historical');
  assert.equal(env.view.getView()?.boundaries, true); assert.equal(env.map.hasLayer(env.tiles), false);
});

test('an uncertain selection cancels the previous exact year and retains only the last successful background', async () => {
  const env = setup(true, false, null, true); await env.finishInitial(); const before = new Set(env.map.layers);
  env.view.setYear(200, 'site'); env.runTimers(); const old = env.boundaryRequest(200);
  env.view.retainBackground('区间证据：公元1至100年；不推断年份。');
  assert.equal(old.signal.aborted, true); assert.equal(env.view.getView()?.year, 117);
  env.complete(old, frame(200, {from:200,to:299,id:'too-late'})); await tick();
  assert.equal(env.view.getView()?.year, 117); assert.deepEqual(env.map.layers, before); assert.equal(env.commits.length, 1);
  assert.match(env.node('history-feedback').textContent, /区间证据.*不推断/u); assert.equal(env.view.actionVersion(), 0);
});

test('unknown selection before the first frame keeps default117 and still prepares local geography', async () => {
  const env = setup(true, false, null, true); env.view.configure(status); env.view.setYear(1616, 'site');
  env.view.retainBackground(); env.runTimers();
  assert.equal(env.pending.some(request => request.url.includes('year=1616')), false);
  const geography = env.pending.find(request => request.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography, land); env.complete(env.boundaryRequest(117), frame(117)); await tick();
  assert.equal(env.view.getView()?.year, 117); assert.match(env.node('history-feedback').textContent, /没有明确单年证据.*不推断/u);
});

test('automatic loading failure preserves the successful year and retries without any year input', async () => {
  const env = setup(true, false, null, true); await env.finishInitial();
  env.view.setYear(200, 'site'); env.runTimers();
  assert.equal(env.node('comparison-history-year').textContent, '公元 117 年');
  env.complete(env.boundaryRequest(200), {detail:'年度资料失败'}, 503); await tick();
  assert.equal(env.view.getView()?.year, 117); assert.match(env.node('comparison-history-year').textContent, /117/u);
  assert.equal(env.node('comparison-history-year').dataset.state, 'ready');
  assert.match(env.node('comparison-history-year').title, /117.*v0\.2\.1/u);
  assert.equal(env.node('history-retry').hidden, false); env.node('history-retry').fire('click'); env.runTimers();
  env.complete(env.boundaryRequest(200), frame(200, {from:200,to:299,id:'retry-success'})); await tick();
  assert.equal(env.view.getView()?.year, 200); assert.equal(env.node('history-error').hidden, true);
  assert.equal(env.node('comparison-history-year').textContent, '公元 200 年');
});

test('automatic exact years outside source coverage never clamp or invent a replacement year', async () => {
  const env = setup(true, false, null, true); await env.finishInitial(); const before = env.pending.length;
  env.view.setYear(2025, 'site'); env.runTimers(); await tick();
  assert.equal(env.pending.length, before); assert.equal(env.view.getView()?.year, 117);
  assert.match(env.node('history-error').textContent, /无可用疆域数据.*保留最后成功/u);
});

test('out-of-coverage selection before first automatic frame still loads a clearly unrelated default background', async () => {
  const env = setup(true, false, null, true); env.view.configure(status); env.view.setYear(-9600, 'site'); env.runTimers();
  const geography = env.pending.find(request => request.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography, land); env.complete(env.boundaryRequest(117), frame(117)); await tick();
  assert.equal(env.view.getView()?.year,117); assert.match(env.node('history-feedback').textContent,/无可用疆域数据/u);
  assert.equal(env.pending.some(request => request.url.includes('year=-9600')),false);
});

function exactContext(year: number, title = `地点 ${year}`) {
  return { title, precision: 'exact_year', start_year: year, end_year: year };
}

test('automatic linkage distinguishes a reference map from repeated real-year site transitions and unknown dates', async () => {
  const env = setup(true, false, null, true); await env.finishInitial();
  const linkage = env.node('history-linkage-status');
  assert.equal(linkage.dataset.state, 'unlinked');
  assert.match(linkage.textContent, /未选遗址.*117.*仅为参考背景/u);
  for (const year of [1616, 366, 1973, -183]) {
    const previous = env.view.getView()!.year;
    env.view.setSelectionContext(exactContext(year)); env.view.setYear(year, 'site', {selectionOwned:true});
    assert.equal(linkage.dataset.state, 'loading');
    assert.match(linkage.textContent, /正在加载.*当前仍显示/u);
    assert.ok(linkage.textContent.includes(env.helpers.formatYear(previous)));
    assert.ok(linkage.textContent.includes(env.helpers.formatYear(year)));
    env.runTimers();
    env.complete(env.boundaryRequest(year), frame(year, {from:year,to:year,id:`year-${year}`})); await tick();
    assert.equal(env.view.getView()?.year, year); assert.equal(linkage.dataset.state, 'matched');
    assert.ok(linkage.textContent.includes(env.helpers.formatYear(year)));
  }
  const before = new Set(env.map.layers), requests = env.pending.length;
  env.view.setSelectionContext({title:'断代未核验',precision:null,start_year:null,end_year:null});
  assert.equal(linkage.dataset.state, 'retained');
  assert.match(linkage.textContent, /无明确单年.*公元前 183 年.*不能视为该遗址年代/u);
  assert.equal(env.view.getView()?.year, -183); assert.deepEqual(env.map.layers, before); assert.equal(env.pending.length, requests);
});

test('range approximate and period context report source precision without choosing a year or claiming the retained year', async () => {
  const env = setup(true, false, null, true); await env.finishInitial();
  for (const [precision, pattern] of [['range',/来源区间/u],['approximate_year',/来源约略年代/u],['period',/来源仅有时期描述/u]] as const) {
    env.view.setSelectionContext({title:'有区间证据',precision,start_year:-100,end_year:100});
    const linkage = env.node('history-linkage-status');
    assert.equal(linkage.dataset.state, 'retained'); assert.match(linkage.textContent, pattern);
    assert.match(linkage.textContent, /公元前 100 年 — 公元 100 年.*117.*不能视为该遗址年代/u);
    assert.equal(env.view.getView()?.year, 117);
  }
  env.view.setSelectionContext({title:'详情在途',precision:'loading',start_year:null,end_year:null});
  assert.equal(env.node('history-linkage-status').dataset.state, 'loading');
  assert.match(env.node('history-linkage-status').textContent, /正在核对.*117.*仅供参照/u);
});

test('a saved1930 reference survives initial empty context and does not claim to be a1616 site stage', async () => {
  const env = setup(true, false, null, true);
  env.view.setYear(1930, 'site'); env.view.configure(status);
  env.view.setSelectionContext(null); env.view.setSelectionContext(null);
  env.view.setSelectionContext(exactContext(1616,'墓的埋葬阶段')); env.runTimers();
  const request = env.boundaryRequest(1930);
  assert.equal(request.signal.aborted, false);
  assert.equal(env.node('history-linkage-status').dataset.state, 'loading');
  assert.match(env.node('history-linkage-status').textContent, /来源年代 公元 1616 年.*加载参考背景 公元 1930 年.*不一致/u);
  assert.doesNotMatch(env.node('history-linkage-status').textContent, /资料年代 公元 1616 年，正在加载/u);
  const geography = env.pending.find(item => item.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography, land); env.complete(request, frame(1930,{from:1930,to:1930,id:'saved-view'})); await tick();
  assert.equal(env.view.getView()?.year, 1930); assert.equal(env.node('history-linkage-status').dataset.state, 'mismatched');
  assert.match(env.node('history-linkage-status').textContent, /1616.*1930.*不一致/u);
});

test('failed exact-year loading names the actual retained background until a successful retry', async () => {
  const env = setup(true, false, null, true); await env.finishInitial();
  env.view.setSelectionContext(exactContext(366)); env.view.setYear(366,'site',{selectionOwned:true}); env.runTimers();
  env.complete(env.boundaryRequest(366), {detail:'年度请求失败'}, 503); await tick();
  assert.equal(env.view.getView()?.year,117); assert.equal(env.node('history-linkage-status').dataset.state,'mismatched');
  assert.match(env.node('history-linkage-status').textContent,/来源年代 公元 366 年.*当前历史背景 公元 117 年.*不一致/u);
  env.node('history-retry').fire('click'); env.runTimers();
  assert.equal(env.node('history-linkage-status').dataset.state,'loading');
  env.complete(env.boundaryRequest(366), frame(366,{from:366,to:366,id:'retry-366'})); await tick();
  assert.equal(env.node('history-linkage-status').dataset.state,'matched'); assert.equal(env.view.getView()?.year,366);
});

test('out-of-coverage exact context preserves source date and never labels the reference as the site year', async () => {
  const env = setup(true, false, null, true); await env.finishInitial(); const requests=env.pending.length;
  env.view.setSelectionContext(exactContext(-9600)); env.view.setYear(-9600,'site',{selectionOwned:true}); env.runTimers(); await tick();
  assert.equal(env.view.getView()?.year,117); assert.equal(env.pending.length,requests);
  assert.equal(env.node('history-linkage-status').dataset.state,'mismatched');
  assert.match(env.node('history-linkage-status').textContent,/公元前 9600 年.*超出疆域覆盖.*公元 117 年.*仅供参照/u);
});

test('out-of-coverage explanation survives the initial reference117 fallback clearing transport errors', async () => {
  const env=setup(true,false,null,true); env.view.configure(status);
  env.view.setSelectionContext(exactContext(-9600)); env.view.setYear(-9600,'site',{selectionOwned:true}); env.runTimers();
  const geography=env.pending.find(item=>item.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography,land); env.complete(env.boundaryRequest(117),frame(117)); await tick();
  assert.equal(env.view.getView()?.year,117); assert.equal(env.node('history-error').hidden,true);
  assert.equal(env.node('history-linkage-status').dataset.state,'mismatched');
  assert.match(env.node('history-linkage-status').textContent,/公元前 9600 年.*超出疆域覆盖.*公元 117 年.*仅供参照/u);
  assert.equal(env.pending.some(item=>item.url.includes('year=-9600')),false);
});

test('unprepared geography is never reported as a successfully matched history frame', async () => {
  const env=setup(true,false,null,true);
  env.view.setSelectionContext(exactContext(1973)); env.view.setYear(1973,'site',{selectionOwned:true});
  env.view.configure({ready:false,reason:'历史数据库尚未准备'}); env.runTimers();
  const geography=env.pending.find(item=>item.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography,land); await tick();
  assert.equal(env.view.getView()?.boundaries,false);
  assert.equal(env.node('history-linkage-status').dataset.state,'unavailable');
  assert.match(env.node('history-linkage-status').textContent,/1973.*疆域尚未载入/u);
  assert.doesNotMatch(env.node('history-linkage-status').textContent,/已按来源切到/u);
});

test('clearing selected context cancels only its pending year and removes stale linkage after a new search', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setSelectionContext(exactContext(1616)); env.view.setYear(1616,'site',{selectionOwned:true}); env.runTimers();
  const old=env.boundaryRequest(1616);
  env.view.setSelectionContext(null);
  assert.equal(old.signal.aborted,true); assert.equal(env.node('history-linkage-status').dataset.state,'unlinked');
  assert.match(env.node('history-linkage-status').textContent,/未选遗址.*117.*仅为参考背景/u);
  assert.doesNotMatch(env.node('history-feedback').textContent,/保留最后成功历史背景/u);
  env.complete(old,frame(1616,{from:1616,to:1616,id:'too-late-1616'})); await tick();
  assert.equal(env.view.getView()?.year,117); assert.equal(env.commits.length,1);
});

test('clearing failed loading-site context preserves the independent initial1930 share request', async () => {
  const env=setup(true,false,null,true);
  env.view.setYear(1930,'site'); env.view.configure(status);
  env.view.setSelectionContext({title:'详情尚未读取的遗址',precision:'loading',start_year:null,end_year:null});
  env.runTimers(); const request=env.boundaryRequest(1930);
  env.view.setSelectionContext(null);
  assert.equal(request.signal.aborted,false); assert.equal(env.node('history-linkage-status').dataset.state,'unlinked');
  assert.equal(env.pending.some(item=>item.url.includes('year=117')),false);
  const geography=env.pending.find(item=>item.url.endsWith('land.geojson')); assert.ok(geography);
  env.complete(geography,land); env.complete(request,frame(1930,{from:1930,to:1930,id:'independent-share'})); await tick();
  assert.equal(env.view.getView()?.year,1930);
  assert.match(env.node('history-linkage-status').textContent,/未选遗址.*1930.*仅为参考背景/u);
});

test('matching the selected year does not confer ownership on an independent share', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setYear(1930,'site'); env.view.setSelectionContext(exactContext(1930)); env.runTimers();
  const request=env.boundaryRequest(1930); env.view.setSelectionContext(null);
  assert.equal(request.signal.aborted,false);
  env.complete(request,frame(1930,{from:1930,to:1930,id:'same-year-independent-share'})); await tick();
  assert.equal(env.view.getView()?.year,1930);
});

test('a newer explicit user or share year clears selection ownership before context is removed', async () => {
  for (const intent of ['user','site'] as const) {
    const env=setup(true,false,null,true); await env.finishInitial();
    env.view.setSelectionContext(exactContext(1616)); env.view.setYear(1616,'site',{selectionOwned:true}); env.runTimers();
    const previous=env.boundaryRequest(1616);
    env.view.setYear(1930,intent); env.runTimers(); const reference=env.boundaryRequest(1930);
    assert.equal(previous.signal.aborted,true); env.view.setSelectionContext(null); assert.equal(reference.signal.aborted,false);
    env.complete(reference,frame(1930,{from:1930,to:1930,id:`override-${intent}`})); await tick();
    assert.equal(env.view.getView()?.year,1930);
  }
});

test('status refresh preserves ownership of a still-pending selected phase year', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setSelectionContext(exactContext(1616)); env.view.setYear(1616,'site',{selectionOwned:true});
  env.view.configure({...status}); env.runTimers(); const request=env.boundaryRequest(1616);
  env.view.setSelectionContext(null); assert.equal(request.signal.aborted,true);
  env.complete(request,frame(1616,{from:1616,to:1616,id:'canceled-after-refresh'})); await tick();
  assert.equal(env.view.getView()?.year,117);
});

test('removing a failed selected-year plan does not revive that obsolete target on status refresh', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setSelectionContext(exactContext(366)); env.view.setYear(366,'site',{selectionOwned:true}); env.runTimers();
  env.complete(env.boundaryRequest(366),{detail:'旧阶段请求失败'},503); await tick();
  const requests=env.pending.length;
  env.view.setSelectionContext(null); env.view.configure({...status}); env.runTimers(); await tick();
  assert.equal(env.pending.length,requests); assert.equal(env.view.getView()?.year,117);
  assert.equal(env.node('history-linkage-status').dataset.state,'unlinked');
  assert.match(env.node('history-linkage-status').textContent,/117.*仅为参考背景/u);
});

test('unrelated failed site details cannot erase an independent background failure or its1930 retry', async () => {
  const env=setup(true,false,null,true); await env.finishInitial();
  env.view.setYear(1930,'site'); env.runTimers();
  env.complete(env.boundaryRequest(1930),{detail:'独立1930参考背景请求失败'},503); await tick();
  assert.equal(env.view.getView()?.year,117); assert.equal(env.node('history-error').hidden,false);
  assert.equal(env.node('history-retry').hidden,false);
  const error=env.node('history-error').textContent;
  env.view.setSelectionContext({title:'另一个读取失败的遗址',precision:'loading',start_year:null,end_year:null});
  env.view.setSelectionContext(null);
  assert.equal(env.node('history-linkage-status').dataset.state,'unlinked');
  assert.equal(env.node('history-error').textContent,error); assert.equal(env.node('history-error').hidden,false);
  assert.equal(env.node('history-retry').hidden,false);
  env.node('history-retry').fire('click'); env.runTimers();
  const retry=env.boundaryRequest(1930); assert.equal(retry.signal.aborted,false);
  env.complete(retry,frame(1930,{from:1930,to:1930,id:'independent-reference-retry'})); await tick();
  assert.equal(env.view.getView()?.year,1930); assert.equal(env.node('history-error').hidden,true);
  assert.equal(env.node('history-retry').hidden,true);
  assert.match(env.node('history-linkage-status').textContent,/未选遗址.*1930.*仅为参考背景/u);
});

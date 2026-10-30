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
  setYear(year: number, intent?: 'user' | 'site'): void;
  setBasemap(basemap: 'historical' | 'modern', intent?: 'user' | 'site'): void;
  setBoundaries(enabled: boolean, intent?: 'user' | 'site'): void;
  actionVersion(): number;
}
interface Helpers {
  create(options: { map: FakeMap | null; tiles: FakeLayer | null; onCommittedView(view: View): void; onUserAction(): void }): Controller;
  isValidYear(year: number): boolean;
  yearToStep(year: number): number;
  stepToYear(step: number): number;
  formatYear(year: number): string;
  frameTargets(year: number, changes: number[], minimum?: number): { previous: number | null; next: number | null };
  colorForName(name: string): string;
  worldCopies(value: unknown): unknown;
}

class FakeElement extends EventTarget {
  tagName: string;
  textContent = '';
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
  onFocus?: () => void;

  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  removeAttribute(key: string): void { this.attributes.delete(key); }
  append(...nodes: FakeElement[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: FakeElement[]): void { this.children = [...nodes]; }
  focus(_options?: FocusOptions): void { this.onFocus?.(); }
  set innerHTML(_value: string) { throw new Error('Unsafe innerHTML write'); }
  fire(type: string, key?: string): Event {
    const event = new Event(type, { cancelable: true });
    if (key !== undefined) Object.defineProperty(event, 'key', { value: key });
    this.dispatchEvent(event);
    return event;
  }
}

class FakeLayer {
  data: unknown;
  options: GeoOptions;
  popups: (FakeElement | (() => FakeElement))[] = [];
  constructor(data: unknown = null, options: GeoOptions = {}) { this.data = data; this.options = options; }
  addTo(map: FakeMap): this { map.layers.add(this); return this; }
  bindPopup(node: FakeElement | (() => FakeElement)): this { this.popups.push(node); return this; }
}

interface GeoOptions {
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
  getPane(name: string): FakeElement | undefined { return this.panes.get(name); }
  createPane(name: string): FakeElement { const pane = new FakeElement(); this.panes.set(name, pane); return pane; }
  getContainer(): FakeElement { return this.container; }
  hasLayer(layer: FakeLayer): boolean { return this.layers.has(layer); }
  removeLayer(layer: FakeLayer): this { this.layers.delete(layer); return this; }
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

function setup(withMap = true) {
  const ids = ['history-controls', 'history-year', 'history-range', 'history-apply', 'history-previous-year', 'history-next-year', 'history-previous-frame', 'history-next-frame', 'history-basemap-historical', 'history-basemap-modern', 'history-boundaries', 'history-applied-year', 'history-draft-year', 'history-feedback', 'history-error', 'history-source', 'history-retry', 'history-map-caption'];
  const nodes = new Map(ids.map((id) => [id, new FakeElement()]));
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
  const context = createContext({
    document: doc, URL, AbortController,
    setTimeout(callback: () => void, delay: number) { delays.push(delay); const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout(id: number) { timers.delete(id); },
    fetch(url: string, options: { signal: AbortSignal }) {
      return new Promise((resolve, reject) => { pending.push({ url, signal: options.signal, resolve, reject, done: false }); });
    },
    L: {
      canvas: (options: object) => ({ ...options }),
      geoJSON(data: unknown, options: GeoOptions) {
        const layer = new FakeLayer(data, options);
        if (options.onEachFeature && typeof data === 'object' && data !== null && 'features' in data && Array.isArray(data.features)) {
          for (const feature of data.features as { properties: Record<string, unknown>; id?: string }[]) options.onEachFeature(feature, layer);
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
  const view = helpers.create({ map: withMap ? map : null, tiles: withMap ? tiles : null, onCommittedView: (value) => commits.push(value), onUserAction: () => { actions++; } });
  const node = (id: string): FakeElement => { const value = nodes.get(id); assert.ok(value); return value; };
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
  return { helpers, view, map, tiles, pending, commits, node, doc, layers, delays, runTimers, complete, boundaryRequest, finishInitial, get actions() { return actions; } };
}

async function tick(): Promise<void> { for (let index = 0; index < 20; index++) await Promise.resolve(); }
function allText(node: FakeElement): string { return node.textContent + node.children.map(allText).join(''); }
function allNodes(node: FakeElement): FakeElement[] { return [node, ...node.children.flatMap(allNodes)]; }

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
  const readPopup = boundary.popups[0]; assert.ok(typeof readPopup === 'function');
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
  assert.ok(boundaries.popups.every((content) => typeof content === 'function'));
});

test('the bundled local Natural Earth geometry is accepted without alteration or network dependencies', async () => {
  const env = setup(); const original = readFileSync(new URL('../../src/archsearch/static/data/land.geojson', import.meta.url), 'utf8');
  const geography: unknown = JSON.parse(original); env.view.configure(status); env.runTimers();
  const request = env.pending.find((item) => item.url.endsWith('land.geojson')); assert.ok(request);
  env.complete(request, geography); env.complete(env.boundaryRequest(117), frame(117)); await tick();
  assert.equal(env.view.getView()?.basemap, 'historical'); assert.equal(env.node('history-error').hidden, true);
  assert.equal(JSON.stringify(geography), JSON.stringify(JSON.parse(original)));
});

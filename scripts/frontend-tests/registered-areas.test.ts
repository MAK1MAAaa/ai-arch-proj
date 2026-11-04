import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface Controller {
  element: FakeElement; select(id: string, title: string): void; clear(): void;
  setCorpusVersion(version: string | null, areasVersion: string | null): void;
  getSnapshot(): (ReturnType<typeof payload> & { displayed: true }) | null;
}
interface Helpers {
  create(options: { map: FakeMap | null; getPadding?(): { topLeft: [number, number]; bottomRight: [number, number] } }): Controller;
  parseAreas(value: unknown, id: string): unknown;
  outlines(features: unknown[], center: number): number[][][];
}
class FakeElement extends EventTarget {
  textContent = '';
  className = '';
  hidden = false;
  disabled = false;
  href = '';
  target = '';
  rel = '';
  style: Record<string, string> = {};
  dataset: Record<string, string> = {};
  children: FakeElement[] = [];
  attributes = new Map<string, string>();
  onFocus: (() => void) | undefined;
  tagName: string;
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  append(...children: FakeElement[]): void { this.children.push(...children); }
  replaceChildren(...children: FakeElement[]): void { this.children = [...children]; }
  setAttribute(name: string, value: string): void { this.attributes.set(name, value); }
  getAttribute(name: string): string | null { return this.attributes.get(name) ?? null; }
  click(): void { if (!this.disabled) this.dispatchEvent(new Event('click')); }
  focus(_options?: FocusOptions): void { this.onFocus?.(); }
  set innerHTML(_value: string) { throw new Error('Unsafe HTML'); }
}
interface Line { points: number[][]; options: Record<string, unknown> }
class FakeGroup {
  lines: Line[];
  constructor(lines: Line[]) { this.lines = lines; }
  addTo(map: FakeMap): this { map.layers.add(this); return this; }
}
class FakeMap {
  panes = new Map<string, FakeElement>();
  historical = {};
  markers = {};
  layers = new Set<unknown>([this.historical, this.markers]);
  fits: unknown[] = [];
  getPane(name: string): FakeElement | undefined { return this.panes.get(name); }
  createPane(name: string): FakeElement { const pane = new FakeElement(); this.panes.set(name, pane); return pane; }
  removeLayer(layer: unknown): this { this.layers.delete(layer); return this; }
  hasLayer(layer: unknown): boolean { return this.layers.has(layer); }
  getCenter(): { lng: number } { return { lng: 130 }; }
  fitBounds(bounds: unknown, options: unknown): this { this.fits.push({ bounds, options }); return this; }
}
interface Pending {
  url: string;
  signal: AbortSignal;
  resolve(response: { ok: boolean; status: number; json(): Promise<unknown> }): void;
  reject(error: Error): void;
}
const compiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/registered-areas.ts', import.meta.url), 'utf8'), {
  fileName: 'registered-areas.ts', compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true }, reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error).length, 0);

function payload(id = 'auth:fixture:a') {
  return {
    site_id: id, corpus_version: 'synthetic-corpus', ready: true, reason: null, version: 'area-fixture-v1',
    label: '现代遗产登记范围', note: 'Provider registration only.',
    features: [{
      id: 'area:' + id, source_index: 0, provider_object_id: 123, title: 'Register ' + id,
      geometry_type: 'esriGeometryPolygon',
      source: { name: 'Synthetic register', uri: 'https://example.org/record', version: 'fixture-raw-v1',
        sha256: 'a'.repeat(64), license: 'Synthetic licence', license_uri: 'https://example.org/licence' },
      rings: [[[130, -20], [131, -20], [131, -21], [130, -20]],
        [[130.1, -20.1], [130.2, -20.2], [130.3, -20.1], [130.1, -20.1]]],
    }],
  };
}
function text(node: FakeElement): string { return node.textContent + node.children.map(text).join(' '); }
async function tick(): Promise<void> { for (let index = 0; index < 20; index++) await Promise.resolve(); }
function setup(withMap = true, getPadding?: () => { topLeft: [number, number]; bottomRight: [number, number] }) {
  const ids = ['registered-areas', 'registered-areas-status', 'registered-areas-note', 'registered-areas-sources', 'registered-areas-show', 'registered-areas-hide', 'registered-areas-retry'];
  const nodes = new Map(ids.map(id => [id, new FakeElement(id.match(/show|hide|retry$/) ? 'button' : 'section')]));
  const pending: Pending[] = [], lines: Line[] = [];
  const document = { activeElement: null as FakeElement | null,
    getElementById: (id: string) => nodes.get(id), createElement: (tag: string) => new FakeElement(tag) };
  for (const node of nodes.values()) node.onFocus = () => { document.activeElement = node; };
  const context = createContext({
    URL, AbortController,
    document,
    fetch(url: string, options: { signal: AbortSignal }) {
      return new Promise((resolve, reject) => { pending.push({ url, signal: options.signal, resolve, reject }); });
    },
    L: {
      canvas: (options: object) => options,
      polyline(points: number[][], options: Record<string, unknown>): Line { const line = { points, options }; lines.push(line); return line; },
      layerGroup: (items: Line[]) => new FakeGroup(items),
      latLngBounds: (points: number[][]) => ({ points, isValid: () => points.length > 0 }),
      geoJSON() { throw new Error('Do not infer polygon hole topology'); },
      polygon() { throw new Error('Do not infer polygon hole topology'); },
    },
  });
  const helpers = runInContext(`${compiled.outputText}\nArchSearchRegisteredAreas;`, context) as Helpers;
  const map = new FakeMap(), controller = helpers.create({ map: withMap ? map : null, getPadding });
  controller.setCorpusVersion('synthetic-corpus', 'area-fixture-v1');
  function node(id: string): FakeElement { const value = nodes.get('registered-areas' + id); assert.ok(value); return value; }
  function complete(request: Pending, value: unknown, status = 200): void {
    request.resolve({ ok: status >= 200 && status < 300, status, json: async () => value });
  }
  return { helpers, map, controller, pending, lines, node, complete, document };
}

test('range reading follows explicit selection and requires a second explicit action to draw', async () => {
  const env = setup();
  env.node('-show').dispatchEvent(new Event('mouseenter')); assert.equal(env.pending.length, 0);
  env.controller.select('auth:fixture:a', 'Site with no representative');
  assert.equal(env.pending[0].url, '/api/sites/auth%3Afixture%3Aa/areas');
  env.complete(env.pending[0], payload()); await tick();
  assert.equal(env.lines.length, 0); assert.equal(env.map.fits.length, 0);
  assert.equal(env.node('-show').disabled, false); assert.equal(env.node('-show').getAttribute('aria-pressed'), 'false');
  env.node('-show').click();
  assert.equal(env.lines.length, 2); assert.equal(env.map.fits.length, 1);
  assert.equal(env.node('-show').getAttribute('aria-pressed'), 'true');
  assert.equal(env.node('-hide').hidden, false);
  assert.match(text(env.node('-status')), /已显示.*Site with no representative/u);
  assert.equal(text(env.node('-note')), `范围不补成代表点，也不计入遗址定位点数量。 ${payload().note}`);
  assert.equal(env.map.panes.get('registered-areas')?.style.zIndex, '400');
  assert.ok(env.map.layers.has(env.map.historical)); assert.ok(env.map.layers.has(env.map.markers));
  env.node('-hide').click();
  assert.equal(env.map.layers.size, 2); assert.equal(env.map.fits.length, 1);
  assert.equal(env.node('-show').getAttribute('aria-pressed'), 'false');
});

test('hide and retry leave keyboard focus on a persistent visible control', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'A');
  env.complete(env.pending[0], payload()); await tick(); env.node('-show').click();
  env.node('-hide').focus(); env.node('-hide').click();
  assert.equal(env.document.activeElement, env.node('-show'));
  env.controller.select('auth:fixture:b', 'B'); env.complete(env.pending[1], {}, 503); await tick();
  env.node('-retry').focus(); env.node('-retry').click();
  assert.equal(env.document.activeElement, env.node('-status'));
  assert.equal(env.node('-retry').hidden, true);
});

test('each original ring remains an unfilled independent Canvas outline without mutating coordinates', async () => {
  const env = setup(), original = payload(), before = JSON.stringify(original);
  original.features[0].rings.forEach(ring => { ring.forEach(Object.freeze); Object.freeze(ring); });
  env.controller.select(original.site_id, 'A'); env.complete(env.pending[0], original); await tick(); env.node('-show').click();
  assert.equal(JSON.stringify(original), before);
  assert.deepEqual(JSON.parse(JSON.stringify(env.lines.map(line => line.points))), original.features[0].rings.map(ring => ring.map(([lon, lat]) => [lat, lon])));
  assert.ok(env.lines.every(line => line.options.fill === false && line.options.fillOpacity === 0 && line.options.interactive === false));
  assert.ok(env.lines.every(line => line.options.pane === 'registered-areas' && line.options.renderer));
  assert.ok(env.lines.every(line => line.options.color === '#286f80'));
});

test('rapid selection aborts the earlier request and ignores a response that arrives despite abort', async () => {
  const env = setup();
  env.controller.select('auth:fixture:a', 'A'); env.controller.select('auth:fixture:b', 'B');
  assert.equal(env.pending[0].signal.aborted, true);
  env.complete(env.pending[1], payload('auth:fixture:b')); await tick();
  env.complete(env.pending[0], payload()); await tick();
  assert.equal(env.node('').dataset.siteId, 'auth:fixture:b'); assert.match(text(env.node('-sources')), /fixture:b/u);
  assert.equal(text(env.node('-sources')).includes('fixture:a'), false);
  env.node('-show').click(); assert.match(text(env.node('-status')), /已显示：B/u);
});

test('closing cancels outstanding work and removes only the registered-area layer', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'A');
  env.controller.clear(); assert.equal(env.pending[0].signal.aborted, true);
  env.complete(env.pending[0], payload()); await tick();
  assert.equal(env.node('').hidden, true); assert.equal(env.map.layers.size, 2);
  env.controller.select('auth:fixture:b', 'B'); env.complete(env.pending[1], payload('auth:fixture:b')); await tick(); env.node('-show').click();
  env.controller.clear(); assert.equal(env.node('').hidden, true); assert.equal(env.map.layers.size, 2);
});

test('failure after switching cannot display the previous range under a new title and retry stays scoped', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'A'); env.complete(env.pending[0], payload()); await tick(); env.node('-show').click();
  env.controller.select('auth:fixture:b', 'B'); assert.equal(env.map.layers.size, 2);
  env.complete(env.pending[1], {}, 503); await tick();
  assert.match(text(env.node('-status')), /HTTP 503.*未显示范围/u); assert.equal(env.node('-show').hidden, true);
  assert.equal(env.node('-retry').hidden, false); assert.equal(text(env.node('-sources')), '');
  env.node('-retry').click(); assert.equal(env.pending[2].url, '/api/sites/auth%3Afixture%3Ab/areas');
  env.complete(env.pending[2], payload('auth:fixture:b')); await tick(); env.node('-show').click();
  assert.match(text(env.node('-status')), /已显示：B/u);
});

test('not-ready reasons, successful empty sources and unavailable maps have distinct states', async () => {
  const unready = setup(); unready.controller.select('auth:fixture:a', 'A');
  unready.complete(unready.pending[0], { ...payload(), ready: false, reason: 'Run prepare-areas', features: [] }); await tick();
  assert.match(text(unready.node('-status')), /尚未就绪.*prepare-areas/u); assert.equal(unready.node('-show').hidden, true);
  const empty = setup(); empty.controller.select('auth:fixture:a', 'A');
  empty.complete(empty.pending[0], { ...payload(), features: [] }); await tick();
  assert.match(text(empty.node('-status')), /没有可用的公开登记范围/u); assert.equal(empty.node('-retry').hidden, true);
  const missing = setup(false); missing.controller.select('auth:fixture:a', 'A');
  missing.complete(missing.pending[0], payload()); await tick();
  assert.equal(missing.node('-show').disabled, true); assert.match(text(missing.node('-status')), /地图组件不可用/u);
  assert.match(text(missing.node('-sources')), /Synthetic register.*fixture-raw-v1/u);
});

test('same selected identity updates its title without duplicate reads or implicitly showing outlines', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'loading id'); env.controller.select('auth:fixture:a', 'Reviewed title');
  assert.equal(env.pending.length, 1); env.complete(env.pending[0], payload()); await tick();
  assert.match(text(env.node('-status')), /Reviewed title/u); assert.equal(env.lines.length, 0);
});

test('outline fitting respects the available map beside or above an open detail drawer', async () => {
  const padding = { topLeft: [24, 24] as [number, number], bottomRight: [389, 24] as [number, number] };
  const env = setup(true, () => padding);
  env.controller.select('auth:fixture:a', 'A'); env.complete(env.pending[0], payload()); await tick(); env.node('-show').click();
  const first = env.map.fits[0] as { options: { paddingTopLeft: number[]; paddingBottomRight: number[] } };
  assert.deepEqual(JSON.parse(JSON.stringify(first.options.paddingBottomRight)), [389, 24]);
  padding.bottomRight = [24, 210]; env.node('-show').click();
  const narrow = env.map.fits[1] as { options: { paddingBottomRight: number[] } };
  assert.deepEqual(JSON.parse(JSON.stringify(narrow.options.paddingBottomRight)), [24, 210]);
});

test('a changed current area version rejects old geometry even when the corpus identity is unchanged', async () => {
  const env = setup(); env.controller.setCorpusVersion('synthetic-corpus', 'areas-next');
  env.controller.select('auth:fixture:a', 'A'); env.complete(env.pending[0], payload()); await tick();
  assert.match(text(env.node('-status')), /范围资料版本不一致/u);
  assert.equal(env.controller.getSnapshot(), null); assert.equal(env.map.fits.length, 0);
});

test('invalid identity, topology, coordinate and source contracts cannot partially render', () => {
  const env = setup();
  const malformed: unknown[] = [
    { ...payload(), site_id: 'wrong' }, { ...payload(), label: '古代遗址边界' },
    { ...payload(), version: null },
    { ...payload(), ready: false },
    { ...payload(), features: [{ ...payload().features[0], geometry_type: 'Polygon' }] },
    { ...payload(), features: [{ ...payload().features[0], rings: [[[130, -20], [131, -20], [131, -21], [130, -21]]] }] },
    { ...payload(), features: [{ ...payload().features[0], rings: [[[true, 0], [1, 0], [1, 1], [true, 0]]] }] },
    { ...payload(), features: [{ ...payload().features[0], rings: [[[NaN, 0], [1, 0], [1, 1], [NaN, 0]]] }] },
    { ...payload(), features: [{ ...payload().features[0], rings: [[[130, -20], [130, -20], [130, -20], [130, -20]]] }] },
    { ...payload(), features: [{ ...payload().features[0], source: { ...payload().features[0].source, uri: 'javascript:alert(1)' } }] },
  ];
  for (const value of malformed) assert.throws(() => env.helpers.parseAreas(value, 'auth:fixture:a'));
  assert.equal(env.lines.length, 0);
});

test('only the actually displayed matching-version range has an independent original-coordinate export snapshot', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'A'); env.complete(env.pending[0], payload()); await tick();
  assert.equal(env.controller.getSnapshot(), null);
  env.node('-show').click(); const snapshot = env.controller.getSnapshot(); assert.ok(snapshot);
  assert.equal(snapshot.displayed, true); assert.deepEqual(JSON.parse(JSON.stringify(snapshot.features[0].rings)), payload().features[0].rings);
  snapshot.features[0].rings[0][0][0] = 999;
  assert.equal(env.controller.getSnapshot()?.features[0].rings[0][0][0], 130);
  env.node('-hide').click(); assert.equal(env.controller.getSnapshot(), null);
  env.node('-show').click(); env.controller.select('auth:fixture:b', 'B'); assert.equal(env.controller.getSnapshot(), null);
  env.complete(env.pending[1], {}, 503); await tick(); assert.equal(env.controller.getSnapshot(), null);
  env.controller.clear(); assert.equal(env.controller.getSnapshot(), null);
});

test('corpus mismatch rejects the reply and a later current-version change clears a displayed range', async () => {
  const env = setup(); env.controller.select('auth:fixture:a', 'A');
  env.complete(env.pending[0], { ...payload(), corpus_version: 'old-corpus' }); await tick();
  assert.equal(env.node('-retry').hidden, false); assert.match(text(env.node('-status')), /语料版本不一致/u);
  env.node('-retry').click(); env.complete(env.pending[1], payload()); await tick(); env.node('-show').click();
  assert.ok(env.controller.getSnapshot()); env.controller.setCorpusVersion('next-corpus', 'area-fixture-v1');
  assert.equal(env.controller.getSnapshot(), null); assert.equal(env.map.layers.size, 2);
  assert.equal(env.pending.length, 2); assert.match(text(env.node('-status')), /旧登记范围已隐藏/u);
});

test('date-line display unwrapping leaves original rings unchanged and does not invent hole relationships', () => {
  const env = setup(), original = payload();
  original.features[0].rings = [[[179, 10], [-179, 10], [-179, 11], [179, 10]], [[-179.5, 10.1], [179.5, 10.1], [179.5, 10.2], [-179.5, 10.1]]];
  const before = JSON.stringify(original), parsed = env.helpers.parseAreas(original, original.site_id) as { features: unknown[] };
  const result = env.helpers.outlines(parsed.features, 170);
  assert.equal(JSON.stringify(original), before); assert.equal(result.length, 2);
  assert.ok(result.flat().every(point => point[1] > 178 && point[1] < 182));
});

test('native keyboard buttons and app lifecycle are wired without changing sharing or point counts', () => {
  const html = readFileSync(new URL('../../src/archsearch/static/index.html', import.meta.url), 'utf8');
  for (const id of ['show', 'hide', 'retry']) assert.match(html, new RegExp(`<button id="registered-areas-${id}"[^>]+type="button"`));
  assert.ok(html.indexOf('/static/registered-areas.js') < html.indexOf('/static/app.js'));
  const app = readFileSync(new URL('../../src/archsearch/frontend/app.ts', import.meta.url), 'utf8');
  assert.match(app, /function closeDetail[\s\S]*?registeredAreas\?\.clear\(\)/u);
  assert.match(app, /registeredAreas\?\.select\(id, known/u);
  const env = setup(); assert.equal(env.node('-show').getAttribute('aria-controls'), 'map');
});

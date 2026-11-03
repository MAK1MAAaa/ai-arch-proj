import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface State { country: string | null; region: string | null; offset: number; visible: boolean }
interface Helpers {
  create(options: { map: FakeMap | null; onSelect(id: string, opener: FakeElement): void; onFilterChange?(state: State): void; onStateChange?(state: State): void; onCommittedState?(state: State): void }): Controller;
  normalizeState(value: Partial<State>): State;
  matches(point: { countries: string[]; regions: string[] }, state: Pick<State, 'country' | 'region'>): boolean;
  coordinate(value: unknown): boolean;
  displayCoordinates(value: [number, number]): [number, number][];
}
interface Controller {
  load(): Promise<void>;
  setState(state: Partial<State>, options?: { notify?: boolean }): Promise<void>;
  getState(): State;
  getCommittedState(): State | null;
  getPoint(id: string): [number, number] | null;
  select(id: string | null): void;
}

const compiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/explore.ts', import.meta.url), 'utf8'), {
  fileName: 'explore.ts', compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true }, reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter((item) => item.category === ts.DiagnosticCategory.Error).length, 0);
const helpers = runInContext(`${compiled.outputText}\nArchSearchExplore;`, createContext({ URL })) as Helpers;
const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

test('global exploration defaults are independent of a query, model or historical year', () => {
  assert.deepEqual(plain(helpers.normalizeState({})), { country: null, region: null, offset: 0, visible: true });
  assert.deepEqual(plain(helpers.normalizeState({ country: 'NZ', region: 'asia-pacific', offset: 50, visible: false })), { country: 'NZ', region: 'asia-pacific', offset: 50, visible: false });
});

test('restored catalogue filters reject coercion, unknown regions and invalid offsets', () => {
  for (const country of ['', 'nz', 'NZA', ' NZ ', '<script>']) assert.throws(() => helpers.normalizeState({ country }), /代码/u);
  for (const region of ['', 'asia', '__proto__']) assert.throws(() => helpers.normalizeState({ region }), /分区/u);
  for (const offset of [-1, 0.5, Number.NaN, Number.POSITIVE_INFINITY, 1_000_001]) assert.throws(() => helpers.normalizeState({ offset }), /起始位置/u);
  assert.throws(() => helpers.normalizeState({ visible: 'false' as unknown as boolean }), /开关/u);
});

test('source membership supports transnational sites and does not infer unlabelled countries', () => {
  const point = { countries: ['DE', 'PL'], regions: ['europe-north-america'] };
  assert.equal(helpers.matches(point, { country: 'DE', region: null }), true);
  assert.equal(helpers.matches(point, { country: 'PL', region: 'europe-north-america' }), true);
  assert.equal(helpers.matches(point, { country: 'DE', region: 'asia-pacific' }), false);
  assert.equal(helpers.matches({ countries: [], regions: [] }, { country: null, region: null }), true);
  assert.equal(helpers.matches({ countries: [], regions: [] }, { country: 'IT', region: null }), false);
});

test('missing representative points are rejected without converting them into zero coordinates', () => {
  for (const value of [null, undefined, [], [0], [181, 0], [0, 91], [null, null], ['0', '0'], [Number.NaN, 10]]) assert.equal(helpers.coordinate(value), false);
  assert.equal(helpers.coordinate([0, 0]), true);
  assert.equal(helpers.coordinate([179, -18]), true);
});

test('adjacent world display points preserve canonical longitude/latitude evidence', () => {
  const original: [number, number] = [-179, -18];
  assert.deepEqual(plain(helpers.displayCoordinates(original)), [[-18, -539], [-18, -179], [-18, 181]]);
  assert.deepEqual(original, [-179, -18]);
});

class FakeElement extends EventTarget {
  tagName: string;
  textContent = '';
  className = '';
  hidden = false;
  disabled = false;
  value = '';
  checked = true;
  type = '';
  tabIndex = 0;
  scrollTop = 0;
  style: Record<string, string> = {};
  dataset: Record<string, string> = {};
  children: FakeElement[] = [];
  attributes = new Map<string, string>();
  tokens = new Set<string>();
  classList = { toggle: (value: string, force: boolean): void => { if (force) this.tokens.add(value); else this.tokens.delete(value); } };
  onFocus?: () => void;
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  append(...nodes: FakeElement[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: FakeElement[]): void { this.children = [...nodes]; }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  contains(node: FakeElement | null): boolean { return node === this || this.children.some(child => child.contains(node)); }
  focus(_options?: FocusOptions): void { this.onFocus?.(); }
  fire(type: string): void { this.dispatchEvent(new Event(type)); }
  set innerHTML(_value: string) { throw new Error('Unsafe HTML insertion'); }
}

class FakeLayer {
  members: FakeCircle[] = [];
  addTo(map: FakeMap): this { map.layers.add(this); return this; }
}

class FakeCircle {
  location: [number, number];
  options: Record<string, unknown>;
  tooltip: (() => FakeElement) | null = null;
  handlers = new Map<string, () => void>();
  constructor(location: [number, number], options: Record<string, unknown>) { this.location = location; this.options = { ...options }; }
  bindTooltip(content: () => FakeElement): this { this.tooltip = content; return this; }
  on(type: string, handler: () => void): this { this.handlers.set(type, handler); return this; }
  addTo(layer: FakeLayer): this { layer.members.push(this); return this; }
  setRadius(radius: number): this { this.options.radius = radius; return this; }
  setStyle(style: Record<string, unknown>): this { Object.assign(this.options, style); return this; }
}

class FakeMap {
  layers = new Set<FakeLayer>();
  panes = new Map<string, FakeElement>();
  container = new FakeElement();
  lastBounds: unknown = null;
  getPane(name: string): FakeElement | undefined { return this.panes.get(name); }
  createPane(name: string): FakeElement { const node = new FakeElement(); this.panes.set(name, node); return node; }
  getContainer(): FakeElement { return this.container; }
  hasLayer(layer: FakeLayer): boolean { return this.layers.has(layer); }
  removeLayer(layer: FakeLayer): this { this.layers.delete(layer); return this; }
  fitBounds(bounds: unknown): void { this.lastBounds = bounds; }
}

interface Point { id: string; title: string; repr_point: [number, number]; countries: string[]; regions: string[]; source_kind: string; chronology_status: string }
interface Pending { url: string; signal: AbortSignal; resolve(response: { ok: boolean; status: number; json(): Promise<unknown> }): void; reject(error: Error): void; done: boolean }
const fixture: Point[] = [
  { id: 'whc:1', title: '<img src=x onerror=alert(1)>', repr_point: [179, -18], countries: ['NZ'], regions: ['asia-pacific'], source_kind: 'unesco', chronology_status: 'not_reviewed' },
  { id: 'wd:Q2', title: 'Beta monument', repr_point: [29, 40], countries: ['TR'], regions: ['europe-north-america'], source_kind: 'global', chronology_status: 'reviewed' },
  { id: '123', title: 'Untitled', repr_point: [12, 42], countries: [], regions: [], source_kind: 'pleiades', chronology_status: 'insufficient' },
];

function coverageFor(points = fixture) {
  const counts = (field: 'countries' | 'regions') => [...new Set(points.flatMap(point => point[field]))].map(id => ({ id, label: id, count: points.filter(point => point[field].includes(id)).length }));
  return { corpus_version: 'global-v3', total: points.length, countries: counts('countries'), regions: counts('regions'),
    sources: [...new Set(points.map(point => point.source_kind))].map(id => ({ id, label: id, count: points.filter(point => point.source_kind === id).length })),
    chronology: { reviewed: points.filter(point => point.chronology_status === 'reviewed').length, insufficient: points.filter(point => point.chronology_status === 'insufficient').length, not_reviewed: points.filter(point => point.chronology_status === 'not_reviewed').length },
    geography_unknown: points.filter(point => point.countries.length === 0).length, country_unknown: points.filter(point => point.countries.length === 0).length };
}

function pageFor(state: Partial<State> = {}, points = fixture) {
  const filtered = points.filter(point => (state.country == null || point.countries.includes(state.country)) && (state.region == null || point.regions.includes(state.region)));
  const offset = state.offset ?? 0;
  return { corpus_version: 'global-v3', total: filtered.length, offset, limit: 50,
    sites: filtered.slice(offset, offset + 50).map(point => ({ id: point.id, title: point.title, repr_point: point.repr_point, source_kind: point.source_kind,
      geography: point.countries.length ? { countries: point.countries, regions: point.regions } : null, chronology: { status: point.chronology_status } })) };
}

function setup(withMap = true) {
  const ids = ['explore-panel', 'explore-summary', 'explore-authority', 'explore-country', 'explore-region', 'explore-clear', 'explore-points', 'explore-fit', 'explore-count', 'explore-list', 'explore-previous', 'explore-next', 'explore-page', 'explore-feedback', 'explore-retry', 'explore-limit-note'];
  const nodes = new Map(ids.map(id => [id, new FakeElement()]));
  const doc: { activeElement: FakeElement | null; getElementById(id: string): FakeElement | null; createElement(tag: string): FakeElement } = {
    activeElement: null, getElementById: id => nodes.get(id) ?? null,
    createElement: tag => { const node = new FakeElement(tag); node.onFocus = () => { doc.activeElement = node; }; return node; },
  };
  for (const node of nodes.values()) node.onFocus = () => { doc.activeElement = node; };
  const pending: Pending[] = [];
  const selects: { id: string; opener: FakeElement }[] = [];
  const changes: State[] = [];
  const filters: State[] = [];
  const commits: State[] = [];
  const circles: FakeCircle[] = [];
  const map = withMap ? new FakeMap() : null;
  const context = createContext({ document: doc, URL, URLSearchParams, AbortController,
    fetch: (url: string, options: { signal: AbortSignal }) => new Promise((resolve, reject) => pending.push({ url, signal: options.signal, resolve, reject, done: false })),
    L: { canvas: (options: unknown) => options, layerGroup: () => new FakeLayer(), circleMarker: (location: [number, number], options: Record<string, unknown>) => { const marker = new FakeCircle(location, options); circles.push(marker); return marker; }, latLngBounds: (points: unknown) => points },
    ArchSearchMapView: { wrapCoordinates: (points: unknown) => points },
  });
  const api = runInContext(`${compiled.outputText}\nArchSearchExplore;`, context) as Helpers;
  const controller = api.create({ map, onSelect: (id, opener) => selects.push({ id, opener }), onFilterChange: state => filters.push(plain(state)), onStateChange: state => changes.push(plain(state)), onCommittedState: state => commits.push(plain(state)) });
  const node = (id: string) => { const found = nodes.get(id); assert.ok(found); return found; };
  const response = (request: Pending, value: unknown, status = 200) => { request.done = true; request.resolve({ ok: status < 400, status, json: async () => value }); };
  const find = (path: string) => { const found = pending.find(item => !item.done && item.url.startsWith(path)); assert.ok(found, path); return found; };
  const respondAll = (points = fixture, state: Partial<State> = {}) => {
    for (const request of pending.filter(item => !item.done && !item.signal.aborted)) {
      if (request.url === '/api/coverage') response(request, coverageFor(points));
      else if (request.url === '/api/catalogue') response(request, { corpus_version: 'global-v3', total: points.length, points });
      else response(request, pageFor(state, points));
    }
  };
  const boot = async (points = fixture) => { const job = controller.load(); respondAll(points); await job; };
  return { controller, node, pending, selects, changes, filters, commits, circles, map, doc, find, response, respondAll, boot };
}

test('coverage, full points and directory page commit together without a model or map', async () => {
  const app = setup(false);
  await app.boot();
  assert.match(app.node('explore-summary').textContent, /3 条资料.*2 个国家/u);
  assert.equal(app.node('explore-list').children.length, 3);
  assert.deepEqual(plain(app.controller.getPoint('whc:1')), [179, -18]);
  const point = app.controller.getPoint('whc:1'); assert.ok(point); point[0] = 0;
  assert.deepEqual(plain(app.controller.getPoint('whc:1')), [179, -18]);
  assert.equal(app.node('explore-points').disabled, true);
  assert.match(app.node('explore-feedback').textContent, /地图组件不可用/u);
});

test('Canvas uses an independent pane and adjacent worlds while source point coordinates remain unchanged', async () => {
  const app = setup(); await app.boot();
  assert.equal(app.map?.panes.get('catalogue-points')?.style.zIndex, '450');
  assert.equal(app.circles.length, 9);
  assert.deepEqual(app.circles.slice(0, 3).map(circle => plain(circle.location)), [[-18, -181], [-18, 179], [-18, 539]]);
  assert.deepEqual(fixture[0].repr_point, [179, -18]);
  assert.equal(app.map?.layers.size, 1);
});

test('literal directory titles and source review status do not become HTML or fabricated dates', async () => {
  const app = setup(); await app.boot();
  const button = app.node('explore-list').children[0].children[0];
  assert.equal(button.children[0].textContent, fixture[0].title);
  assert.match(button.children[2].textContent, /断代尚未核验/u);
  assert.match(app.node('explore-list').children[2].children[0].children[2].textContent, /已核验，断代未确定/u);
  assert.equal(app.circles[0].tooltip?.().textContent, fixture[0].title);
});

test('mouse circles and keyboard-accessible buttons only emit site identity and their opener', async () => {
  const app = setup(); await app.boot();
  const button = app.node('explore-list').children[0].children[0];
  button.fire('click');
  app.circles[0].handlers.get('click')?.();
  assert.deepEqual(app.selects.map(item => item.id), ['whc:1', 'whc:1']);
  assert.equal(app.selects[0].opener, button);
  assert.equal(app.selects[1].opener, app.map?.container);
  app.controller.select('whc:1');
  assert.equal(button.attributes.get('aria-pressed'), 'true');
  assert.equal(app.circles[0].options.radius, 5);
  app.controller.select(null);
  assert.equal(button.attributes.get('aria-pressed'), 'false');
  assert.equal(app.circles[0].options.radius, 3.2);
});

test('restored filters notify nobody; user filtering notifies next-search conditions without submitting search', async () => {
  const app = setup(); await app.boot();
  const restored = app.controller.setState({ country: 'NZ', region: 'asia-pacific' });
  app.respondAll(fixture, { country: 'NZ', region: 'asia-pacific' }); await restored;
  assert.equal(app.changes.length, 0); assert.equal(app.filters.length, 0);
  assert.equal(app.node('explore-list').children.length, 1);
  assert.deepEqual(plain(app.controller.getPoint('wd:Q2')), [29, 40]);
  const changed = app.controller.setState({ country: 'TR', region: 'europe-north-america' }, { notify: true });
  app.respondAll(fixture, { country: 'TR', region: 'europe-north-america' }); await changed;
  assert.equal(app.changes.length, 1); assert.equal(app.filters.length, 1);
  assert.ok(app.pending.every(request => request.url !== '/api/search'));
});

test('visibility toggles do not refetch catalogue, replace results or change the map camera', async () => {
  const app = setup(); await app.boot(); const calls = app.pending.length;
  await app.controller.setState({ visible: false }, { notify: true });
  assert.equal(app.map?.layers.size, 0); assert.equal(app.pending.length, calls);
  assert.equal(app.filters.length, 0); assert.equal(app.changes.length, 1);
  await app.controller.setState({ visible: true }, { notify: true });
  assert.equal(app.map?.layers.size, 1); assert.equal(app.map?.lastBounds, null);
  app.node('explore-fit').fire('click'); assert.notEqual(app.map?.lastBounds, null);
});

test('rapid filters cancel prior requests and a late success cannot overwrite the current point layer', async () => {
  const app = setup(); await app.boot();
  const old = app.controller.setState({ country: 'NZ' }); const previous = app.find('/api/sites');
  const current = app.controller.setState({ country: 'TR' }); const latest = app.pending.at(-1); assert.ok(latest);
  assert.equal(previous.signal.aborted, true);
  app.response(latest, pageFor({ country: 'TR' })); await current;
  const layer = [...(app.map?.layers ?? [])][0];
  app.response(previous, pageFor({ country: 'NZ' })); await old;
  assert.equal([...app.map!.layers][0], layer);
  assert.equal(app.node('explore-list').children[0].children[0].dataset.siteId, 'wd:Q2');
});

test('a late old failure is ignored before it can rollback a newer successful layer or show an error', async () => {
  const app = setup(); await app.boot();
  const old = app.controller.setState({ country: 'NZ' }); const previous = app.find('/api/sites');
  const current = app.controller.setState({ country: 'TR' }); const latest = app.pending.at(-1); assert.ok(latest);
  app.response(latest, pageFor({ country: 'TR' })); await current;
  const layer = [...app.map!.layers][0];
  app.response(previous, { detail: 'stale 503' }, 503); await old;
  assert.equal(app.map!.layers.size, 1); assert.equal([...app.map!.layers][0], layer);
  assert.equal(app.node('explore-retry').hidden, true);
  assert.equal(app.node('explore-panel').tokens.has('has-error'), false);
});

test('failed current filters retain the last successful directory and point layer and reject restoration', async () => {
  const app = setup(); await app.boot(); const layer = [...app.map!.layers][0];
  const changed = app.controller.setState({ country: 'NZ' });
  const rejection = assert.rejects(changed, /local failure/u);
  app.response(app.find('/api/sites'), { detail: 'local failure' }, 503); await rejection;
  assert.equal([...app.map!.layers][0], layer);
  assert.equal(app.node('explore-list').children.length, 3);
  assert.match(app.node('explore-feedback').textContent, /保留上次成功/u);
  assert.equal(app.node('explore-retry').hidden, false);
});

test('unknown restored source countries reject without broadening to the whole corpus', async () => {
  const app = setup(); await app.boot();
  const job = app.controller.setState({ country: 'ZZ' }); const rejection = assert.rejects(job, /地域标签/u);
  app.response(app.find('/api/sites'), { ...pageFor(), total: 0, sites: [] }); await rejection;
  assert.equal(app.controller.getState().country, 'ZZ');
  assert.equal(app.node('explore-list').children.length, 3);
  assert.ok(app.pending.at(-1)?.url.includes('country=ZZ'));
});

test('version or coordinate mismatches are rejected atomically before replacing the successful catalogue', async () => {
  const app = setup(); await app.boot(); const layer = [...app.map!.layers][0];
  const job = app.controller.load(); const rejection = assert.rejects(job, /版本或总数/u);
  app.response(app.find('/api/coverage'), coverageFor());
  app.response(app.find('/api/catalogue'), { corpus_version: 'wrong-version', total: 3, points: fixture });
  app.response(app.find('/api/sites'), pageFor()); await rejection;
  assert.equal([...app.map!.layers][0], layer);
  assert.deepEqual(plain(app.controller.getPoint('whc:1')), fixture[0].repr_point);
});

test('pagination exposes every matching record without assigning scores or changing a selected site', async () => {
  const many = Array.from({ length: 60 }, (_, index): Point => ({ ...fixture[0], id: `whc:${index + 1}`, title: `Site ${String(index + 1).padStart(3, '0')}` }));
  const app = setup(); await app.boot(many);
  assert.equal(app.node('explore-list').children.length, 50); assert.equal(app.node('explore-next').disabled, false);
  const originalLayer = [...app.map!.layers][0];
  const originalCircles = app.circles.length;
  app.controller.select('whc:1');
  const next = app.controller.setState({ offset: 50 }, { notify: true }); app.respondAll(many, { offset: 50 }); await next;
  assert.equal(app.node('explore-list').children.length, 10); assert.equal(app.node('explore-next').disabled, true);
  assert.equal(app.node('explore-list').children[0].children[0].dataset.siteId, 'whc:51');
  assert.match(app.node('explore-page').textContent, /51—60.*无相关性分数/u);
  assert.deepEqual(plain(app.controller.getPoint('whc:1')), fixture[0].repr_point);
  assert.equal(app.filters.length, 0); assert.equal(app.changes.length, 1);
  assert.equal([...app.map!.layers][0], originalLayer);
  assert.equal(app.circles.length, originalCircles);
});

test('a valid region and country with no intersection commits an explicit empty directory', async () => {
  const app = setup(); await app.boot();
  const next = app.controller.setState({ country: 'NZ', region: 'europe-north-america' });
  app.respondAll(fixture, { country: 'NZ', region: 'europe-north-america' }); await next;
  assert.match(app.node('explore-list').children[0].textContent, /暂无资料/u);
  assert.equal([...app.map!.layers][0].members.length, 0);
  assert.equal(app.node('explore-fit').disabled, true);
});

test('committed browse snapshots stay unchanged before or after a failed draft and publish only after success', async () => {
  const app = setup();
  assert.equal(app.controller.getCommittedState(), null);
  await app.boot();
  const original = plain(app.controller.getCommittedState());
  assert.deepEqual(original, { country: null, region: null, offset: 0, visible: true });
  assert.equal(app.commits.length, 1);
  const failed = app.controller.setState({ country: 'NZ' }, { notify: true });
  assert.equal(app.controller.getState().country, 'NZ');
  assert.deepEqual(plain(app.controller.getCommittedState()), original);
  const rejection = assert.rejects(failed, /failed draft/u);
  app.response(app.find('/api/sites'), { detail: 'failed draft' }, 503); await rejection;
  assert.deepEqual(plain(app.controller.getCommittedState()), original);
  assert.equal(app.commits.length, 1);
  const retry = app.controller.load(); app.respondAll(fixture, { country: 'NZ' }); await retry;
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: 'NZ', region: null, offset: 0, visible: true });
  assert.equal(app.commits.length, 2);
  const snapshot = app.controller.getCommittedState(); assert.ok(snapshot); snapshot.country = 'TR';
  assert.equal(app.controller.getCommittedState()?.country, 'NZ');
});

test('the point-layer switch commits immediately without relabelling an uncommitted region draft', async () => {
  const app = setup(); await app.boot();
  const pending = app.controller.setState({ country: 'TR' });
  await app.controller.setState({ visible: false }, { notify: true });
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: null, region: null, offset: 0, visible: false });
  app.response(app.find('/api/sites'), pageFor({ country: 'TR' })); await pending;
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: 'TR', region: null, offset: 0, visible: false });
  assert.equal(app.map?.layers.size, 0);
});

test('authority denominator is source-scoped and retains its official version and license links', async () => {
  const app = setup();
  const job = app.controller.load();
  const authority = { dataset: 'whc001', source_uri: 'https://data.unesco.org/explore/dataset/whc001/', source_modified: '2026-11-03T12:00:00Z', source_sha256: 'a'.repeat(64), license: 'CC BY-SA 4.0', license_uri: 'https://creativecommons.org/licenses/by-sa/4.0/', eligible_total: 2, covered: 1, missing: 1, excluded_natural: 1, note: 'Frozen cultural and mixed source scope, not all world sites.' };
  app.response(app.find('/api/coverage'), { ...coverageFor(), authority });
  app.response(app.find('/api/catalogue'), { corpus_version: 'global-v3', total: 3, points: fixture });
  app.response(app.find('/api/sites'), pageFor()); await job;
  const node = app.node('explore-authority');
  assert.equal(node.hidden, false);
  assert.match(node.children[0].textContent, /官方文化／混合名录 1 \/ 2/u);
  assert.equal((node.children[1] as FakeElement & { href: string }).href, authority.source_uri);
  assert.match(node.children[3].textContent, /2026-11-03.*1 条待覆盖.*纯自然遗产/u);
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

type Coordinate = [number, number];
interface Point { id: string; title: string; repr_point: Coordinate | null; location_status: 'mapped' | 'polar' | 'unknown'; regions: string[]; source_kind: string }
interface Controller { setSites(points: readonly Point[]): void; ensureSite(point: Point): boolean; select(id: string | null): void; locate(id: string): boolean; focusSelected(): void }
interface Helpers { create(options: { onSelect(id: string, opener: FakeElement): void }): Controller; project(value: Coordinate): Coordinate; clipRing(value: unknown): Coordinate[]; landPaths(value: unknown): string[]; antarcticSites(points: readonly Point[]): Point[] }
const compiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/polar-view.ts', import.meta.url), 'utf8'), {
  fileName: 'polar-view.ts', compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true }, reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error).length, 0);
const helpers = runInContext(`${compiled.outputText}\nArchSearchPolarView;`, createContext({})) as Helpers;
const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const close = (actual: Coordinate, expected: Coordinate) => { assert.ok(Math.abs(actual[0] - expected[0]) < 1e-8); assert.ok(Math.abs(actual[1] - expected[1]) < 1e-8); };
const fixture: Point[] = [
  { id: 'ats:hsm:1', title: 'South Pole flag mast', repr_point: [0, -90], location_status: 'polar', source_kind: 'ats', regions: ['antarctica'] },
  { id: 'ats:hsm:24', title: 'Rock cairn', repr_point: [-87.113111, -85.173278], location_status: 'polar', source_kind: 'ats', regions: ['antarctica'] },
  { id: 'ats:hsm:80', title: 'Amundsen’s tent', repr_point: [0, -90], location_status: 'polar', source_kind: 'ats', regions: ['antarctica'] },
  { id: 'ats:hsm:34', title: '<img src=x onerror=alert(1)>', repr_point: [-55.716667, -62.183333], location_status: 'mapped', source_kind: 'ats', regions: ['antarctica'] },
  { id: 'ats:hsm:95', title: 'Lost vessel', repr_point: null, location_status: 'unknown', source_kind: 'ats', regions: ['antarctica'] },
];
const landFixture = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [
  [[-80, -70], [0, -80], [80, -70], [-80, -70]], [[-5, -75], [0, -76], [5, -75], [-5, -75]],
] } }] };

test('spherical south-pole azimuthal projection keeps true poles and WGS84 axis order', () => {
  close(helpers.project([0, -90]), [250, 250]); close(helpers.project([180, -90]), [250, 250]);
  close(helpers.project([0, -60]), [250, 50]); close(helpers.project([90, -60]), [450, 250]);
  close(helpers.project([-90, -60]), [50, 250]); close(helpers.project([180, -60]), [250, 450]);
  close(helpers.project([0, -75]), [250, 150]);
  const source: Coordinate = [-87.113111, -85.173278]; helpers.project(source);
  assert.deepEqual(source, [-87.113111, -85.173278]);
  for (const point of [[0, -59.999], [0, -91], [181, -90], [Number.NaN, -90]]) assert.throws(() => helpers.project(point as Coordinate), /源WGS84/u);
});

test('land is clipped at 60S with closed rings and holes retained without changing source coordinates', () => {
  const original = plain(landFixture); const paths = helpers.landPaths(landFixture);
  assert.equal(paths.length, 1); assert.equal(paths[0].split('M').length, 3); assert.equal(paths[0].split('Z').length, 3);
  assert.deepEqual(landFixture, original);
  const clipped = helpers.clipRing([[-10, -50], [10, -70], [-10, -70], [-10, -50]]);
  assert.ok(clipped.every(point => point[1] <= -60)); assert.deepEqual(plain(clipped[0]), plain(clipped.at(-1)));
  assert.deepEqual(plain(helpers.clipRing([[0, 0], [10, 0], [10, 10], [0, 0]])), []);
  assert.throws(() => helpers.clipRing([[0, -70], [5, -75], [0, -80], [1, -70]]), /闭合/u);
  assert.throws(() => helpers.landPaths({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, -90] } }] }), /多边形/u);
});

test('bundled Natural Earth can render local southern land without a network dependency', () => {
  const source: unknown = JSON.parse(readFileSync(new URL('../../src/archsearch/static/data/land.geojson', import.meta.url), 'utf8'));
  const paths = helpers.landPaths(source);
  assert.ok(paths.length > 0); assert.ok(paths.every(path => !/NaN|Infinity|undefined/u.test(path)));
});

test('Antarctic records retain unknown positions and independent overlapping identities', () => {
  const global: Point = { id: 'whc:1', title: 'Elsewhere', repr_point: [12, 40], location_status: 'mapped', source_kind: 'unesco', regions: ['europe-north-america'] };
  const sites = helpers.antarcticSites([...fixture, global]);
  assert.deepEqual(plain(sites.map(site => site.id)), ['ats:hsm:1', 'ats:hsm:24', 'ats:hsm:34', 'ats:hsm:80', 'ats:hsm:95']);
  assert.equal(sites.at(-1)?.repr_point, null); assert.equal(sites.filter(site => site.repr_point?.[1] === -90).length, 2);
  assert.throws(() => helpers.antarcticSites([...fixture, fixture[0]]), /身份或源坐标/u);
  assert.throws(() => helpers.antarcticSites([{ ...fixture[0], location_status: 'mapped' }]), /定位状态/u);
  assert.throws(() => helpers.antarcticSites([{ ...fixture[0], repr_point: [0, -50] }]), /源坐标/u);
  sites[0].repr_point![1] = 0; assert.equal(fixture[0].repr_point![1], -90);
});

test('the frozen 91-record ATS corpus retains 90 true points, three polar sites and one unknown location', () => {
  const records = JSON.parse(readFileSync(new URL('../../src/archsearch/data/polar_sites.json', import.meta.url), 'utf8')) as {
    id: string; title: string; repr_point: Coordinate | null; source_kind: string; geography: { regions: string[] };
  }[];
  const points = records.map((site): Point => ({ id: site.id, title: site.title, repr_point: site.repr_point,
    source_kind: site.source_kind, regions: site.geography.regions,
    location_status: site.repr_point === null ? 'unknown' : Math.abs(site.repr_point[1]) > 85.0511287798 ? 'polar' : 'mapped' }));
  const sites = helpers.antarcticSites(points);
  assert.equal(sites.length, 91); assert.equal(sites.filter(site => site.repr_point !== null).length, 90);
  assert.equal(sites.filter(site => site.location_status === 'polar').length, 3);
  assert.equal(sites.find(site => site.id === 'ats:hsm:95')?.repr_point, null);
  for (const site of sites) if (site.repr_point) {
    const [x, y] = helpers.project(site.repr_point);
    assert.ok(Math.hypot(x - 250, y - 250) <= 200 + 1e-8);
  }
});

class FakeElement extends EventTarget {
  tagName: string;
  textContent = '';
  className = '';
  hidden = false;
  open = false;
  type = '';
  title = '';
  tabIndex = 0;
  style: Record<string, string> = {};
  dataset: Record<string, string> = {};
  attributes = new Map<string, string>();
  children: FakeElement[] = [];
  tokens = new Set<string>();
  classList = { toggle: (value: string, force: boolean) => { if (force) this.tokens.add(value); else this.tokens.delete(value); } };
  onFocus?: () => void;
  scrolls = 0;
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  replaceChildren(...children: FakeElement[]): void { this.children = [...children]; }
  contains(node: FakeElement | null): boolean { return this === node || this.children.some(child => child.contains(node)); }
  focus(_options?: FocusOptions): void { this.onFocus?.(); this.dispatchEvent(new Event('focus')); }
  scrollIntoView(_options?: ScrollIntoViewOptions): void { this.scrolls++; }
  fire(type: string): void { this.dispatchEvent(new Event(type)); }
  key(key: string): Event { const event = new Event('keydown', { cancelable: true }); Object.defineProperty(event, 'key', { value: key }); this.dispatchEvent(event); return event; }
  set innerHTML(_value: string) { throw new Error('Unsafe HTML insertion'); }
}
interface Pending { signal: AbortSignal; resolve(response: { ok: boolean; status: number; json(): Promise<unknown> }): void; done: boolean }
function setup() {
  const ids = ['polar-panel', 'polar-summary', 'polar-count', 'polar-map', 'polar-points', 'polar-selection', 'polar-unknown', 'polar-feedback', 'polar-retry', 'polar-land'];
  const nodes = new Map(ids.map(id => [id, new FakeElement()])); nodes.get('polar-panel')!.hidden = true;
  const doc: { activeElement: FakeElement | null; getElementById(id: string): FakeElement | null; createElement(tag: string): FakeElement; createElementNS(namespace: string, tag: string): FakeElement } = {
    activeElement: null, getElementById: id => nodes.get(id) ?? null,
    createElement: tag => { const element = new FakeElement(tag); element.onFocus = () => { doc.activeElement = element; }; return element; },
    createElementNS: (_namespace, tag) => new FakeElement(tag),
  };
  for (const node of nodes.values()) node.onFocus = () => { doc.activeElement = node; };
  const pending: Pending[] = []; const selects: { id: string; opener: FakeElement }[] = [];
  const context = createContext({ document: doc, HTMLElement: FakeElement, AbortController,
    fetch: (url: string, options: { signal: AbortSignal }) => { assert.equal(url, '/static/data/land.geojson'); return new Promise(resolve => pending.push({ signal: options.signal, resolve, done: false })); },
  });
  const api = runInContext(`${compiled.outputText}\nArchSearchPolarView;`, context) as Helpers;
  const controller = api.create({ onSelect: (id, opener) => selects.push({ id, opener }) });
  const node = (id: string) => { const value = nodes.get(id); assert.ok(value); return value; };
  const response = (request: Pending, value: unknown = landFixture, status = 200) => { request.done = true; request.resolve({ ok: status < 400, status, json: async () => value }); };
  const button = (id: string) => { const value = [...node('polar-points').children, ...node('polar-unknown').children].find(child => child.dataset.siteId === id); assert.ok(value); return value; };
  return { api, controller, node, button, doc, selects, pending, response };
}
const settle = () => new Promise<void>(resolve => setImmediate(resolve));

test('all known Antarctic sites use independent true-coordinate buttons and the unknown source stays selectable', () => {
  const app = setup(); app.controller.setSites(fixture);
  assert.equal(app.node('polar-panel').hidden, false); assert.equal(app.node('polar-panel').open, false);
  assert.equal(app.pending.length, 0); assert.equal(app.node('polar-points').children.length, 4); assert.equal(app.node('polar-unknown').children.length, 1);
  assert.match(app.node('polar-count').textContent, /5 条来源记录.*4 处有源坐标.*1 处位置未知/u);
  assert.equal(app.button('ats:hsm:1').style.left, '50%'); assert.equal(app.button('ats:hsm:1').style.top, '50%');
  assert.equal(app.button('ats:hsm:80').style.left, '50%'); assert.equal(app.button('ats:hsm:80').style.top, '50%');
  assert.equal(app.button('ats:hsm:24').dataset.latitude, '-85.173278');
  assert.equal(app.button('ats:hsm:95').dataset.latitude, undefined); assert.match(app.button('ats:hsm:95').textContent, /位置未知/u);
  assert.match(app.button('ats:hsm:34').attributes.get('aria-label')!, /<img src=x onerror=alert\(1\)>/u);
  app.button('ats:hsm:95').fire('click');
  assert.equal(app.selects[0].id, 'ats:hsm:95'); assert.equal(app.selects[0].opener, app.button('ats:hsm:95'));
});

test('selection opens polar and unknown views without stealing focus or issuing a selection callback', () => {
  const app = setup(); app.controller.setSites(fixture); app.node('polar-summary').focus();
  app.controller.select('ats:hsm:1'); assert.equal(app.node('polar-panel').open, true);
  assert.equal(app.doc.activeElement, app.node('polar-summary')); assert.equal(app.selects.length, 0);
  assert.equal(app.button('ats:hsm:1').attributes.get('aria-pressed'), 'true'); assert.match(app.node('polar-selection').textContent, /纬度 -90°/u);
  app.controller.select('ats:hsm:95'); assert.match(app.node('polar-selection').textContent, /位置未知.*未绘制/u);
  app.controller.select(null); assert.equal(app.button('ats:hsm:95').attributes.get('aria-pressed'), 'false');
  assert.equal(app.selects.length, 0);
});

test('roving arrow keys expose overlapping points individually and explicit locate restores keyboard focus', () => {
  const app = setup(); app.controller.setSites(fixture);
  assert.equal(app.button('ats:hsm:1').tabIndex, 0); assert.equal(app.button('ats:hsm:80').tabIndex, -1);
  app.button('ats:hsm:1').focus(); assert.equal(app.node('polar-points').key('ArrowRight').defaultPrevented, true);
  assert.equal(app.doc.activeElement, app.button('ats:hsm:24')); assert.equal(app.selects.length, 0);
  app.node('polar-points').key('End'); assert.equal(app.doc.activeElement, app.button('ats:hsm:80'));
  app.node('polar-points').key('Home'); assert.equal(app.doc.activeElement, app.button('ats:hsm:1'));
  assert.equal(app.controller.locate('ats:hsm:95'), true); assert.equal(app.doc.activeElement, app.button('ats:hsm:95'));
  assert.equal(app.node('polar-map').scrolls, 1); assert.equal(app.controller.locate('whc:1'), false);
  app.node('polar-panel').key('Escape'); assert.equal(app.node('polar-panel').open, false); assert.equal(app.doc.activeElement, app.node('polar-summary'));
});

test('successful catalogue refresh reuses opener buttons and a malformed refresh preserves the complete old view', () => {
  const app = setup(); app.controller.setSites(fixture); const opener = app.button('ats:hsm:80'); opener.focus();
  app.controller.setSites(plain(fixture)); assert.equal(app.button('ats:hsm:80'), opener); assert.equal(app.doc.activeElement, opener);
  app.controller.setSites([{ ...fixture[0], repr_point: [0, -30] }]);
  assert.equal(app.node('polar-points').children.length, 4); assert.equal(app.button('ats:hsm:80'), opener);
  assert.match(app.node('polar-feedback').textContent, /保留上次成功/u);
  app.controller.setSites([]); assert.equal(app.node('polar-panel').hidden, true); assert.equal(app.node('polar-panel').open, false);
});

test('local coastline failure leaves points and grid usable and retry renders a verified contour', async () => {
  const app = setup(); app.controller.setSites(fixture); app.controller.locate('ats:hsm:1');
  assert.equal(app.pending.length, 1); app.response(app.pending[0], null, 404); await settle();
  assert.match(app.node('polar-feedback').textContent, /轮廓未加载.*点位与网格仍可使用/u); assert.equal(app.node('polar-retry').hidden, false);
  assert.equal(app.node('polar-points').children.length, 4); assert.equal(app.node('polar-land').children.length, 0);
  app.node('polar-retry').fire('click'); app.response(app.pending[1]); await settle();
  assert.equal(app.node('polar-land').children.length, 1); assert.equal(app.node('polar-retry').hidden, true);
  assert.match(app.node('polar-feedback').textContent, /本地 Natural Earth.*已加载/u);
});

test('old success and failure cannot overwrite a newer coastline request even when cancellation is ignored', async () => {
  const app = setup(); app.controller.setSites(fixture); app.controller.locate('ats:hsm:1');
  const stale = app.pending[0]; app.node('polar-retry').fire('click'); const latest = app.pending[1];
  assert.equal(stale.signal.aborted, true); app.response(latest); await settle();
  const successful = app.node('polar-land').children[0]; app.response(stale, null, 503); await settle();
  assert.equal(app.node('polar-land').children[0], successful); assert.equal(app.node('polar-retry').hidden, true);
  app.node('polar-retry').fire('click'); const older = app.pending[2]; app.node('polar-retry').fire('click');
  app.response(app.pending[3], null, 404); await settle(); const failure = app.node('polar-feedback').textContent;
  app.response(older); await settle(); assert.equal(app.node('polar-feedback').textContent, failure);
  assert.equal(app.node('polar-land').children[0], successful); assert.match(failure, /保留上次成功轮廓/u);
});

test('removing all polar records cancels an in-flight coast and a late response cannot reintroduce the panel', async () => {
  const app = setup(); app.controller.setSites(fixture); app.controller.locate('ats:hsm:1'); const request = app.pending[0];
  app.controller.setSites([]); assert.equal(request.signal.aborted, true); app.response(request); await settle();
  assert.equal(app.node('polar-panel').hidden, true); assert.equal(app.node('polar-land').children.length, 0);
});

test('a verified polar detail provides a clearly partial fallback before catalogue readiness', () => {
  const app = setup(); assert.equal(app.controller.locate('ats:hsm:1'), false);
  assert.equal(app.controller.ensureSite(fixture[0]), true);
  assert.equal(app.node('polar-panel').hidden, false); assert.equal(app.node('polar-panel').dataset.scope, 'details-only');
  assert.match(app.node('polar-count').textContent, /仅已读详情，完整目录未就绪.*1 条来源记录.*1 处有源坐标.*0 处位置未知/u);
  assert.equal(app.controller.locate('ats:hsm:1'), true); assert.equal(app.doc.activeElement, app.button('ats:hsm:1'));
  assert.equal(app.button('ats:hsm:1').dataset.latitude, '-90');
  assert.equal(app.button('ats:hsm:1').style.top, '50%');
  assert.equal(app.controller.ensureSite(fixture[2]), true);
  assert.equal(app.node('polar-points').children.length, 2);
  assert.match(app.node('polar-count').textContent, /2 条来源记录/u);
  assert.equal(app.controller.ensureSite(fixture[0]), true); assert.equal(app.node('polar-points').children.length, 2);
});

test('unknown detail fallback retains null and complete catalogue recovery replaces partial coverage atomically', () => {
  const app = setup(); assert.equal(app.controller.ensureSite(fixture[4]), true);
  app.controller.select('ats:hsm:95'); assert.equal(app.node('polar-panel').open, true);
  assert.equal(app.node('polar-points').children.length, 0); assert.equal(app.node('polar-unknown').children.length, 1);
  assert.match(app.node('polar-count').textContent, /仅已读详情.*1 条来源记录.*0 处有源坐标.*1 处位置未知/u);
  assert.equal(app.button('ats:hsm:95').dataset.latitude, undefined);
  const opener = app.button('ats:hsm:95'); opener.focus();
  app.controller.setSites(fixture);
  assert.equal(app.node('polar-panel').dataset.scope, 'complete'); assert.doesNotMatch(app.node('polar-count').textContent, /未就绪|仅已读详情/u);
  assert.equal(app.node('polar-points').children.length, 4); assert.equal(app.node('polar-unknown').children.length, 1);
  assert.equal(app.button('ats:hsm:95'), opener); assert.equal(app.doc.activeElement, opener);
  assert.equal(app.controller.ensureSite({ ...fixture[0], id: 'ats:hsm:100' }), false);
  assert.equal(app.node('polar-panel').dataset.scope, 'complete'); assert.equal(app.node('polar-points').children.length, 4);
});

test('invalid partial and full replacements retain prior true points and non-ATS details are ignored', () => {
  const app = setup(); assert.equal(app.controller.ensureSite(fixture[0]), true); const opener = app.button('ats:hsm:1');
  assert.equal(app.controller.ensureSite({ ...fixture[4], location_status: 'mapped' }), false);
  assert.equal(app.node('polar-points').children.length, 1); assert.equal(app.node('polar-unknown').children.length, 0);
  app.controller.setSites([{ ...fixture[0], repr_point: [0, -30] }]);
  assert.equal(app.button('ats:hsm:1'), opener); assert.equal(app.node('polar-panel').dataset.scope, 'details-only');
  assert.match(app.node('polar-count').textContent, /仅已读详情.*1 条来源记录/u);
  const feedback = app.node('polar-feedback').textContent;
  assert.equal(app.controller.ensureSite({ id: 'whc:1', title: 'Global site', repr_point: [12, 40], location_status: 'mapped', regions: [], source_kind: 'unesco' }), false);
  assert.equal(app.node('polar-feedback').textContent, feedback);
  assert.equal(app.controller.ensureSite(fixture[4]), true);
  assert.equal(app.node('polar-unknown').children.length, 1); assert.equal(app.button('ats:hsm:1'), opener);
});

test('keyboard retry moves focus to persistent status before hiding its button', async () => {
  const app = setup(); app.controller.setSites(fixture); app.controller.locate('ats:hsm:1');
  app.response(app.pending[0], null, 404); await settle();
  const retry = app.node('polar-retry'); retry.focus(); assert.equal(app.doc.activeElement, retry);
  retry.fire('click');
  assert.equal(retry.hidden, true); assert.equal(app.doc.activeElement, app.node('polar-feedback'));
  assert.equal(app.node('polar-feedback').tabIndex, -1);
  app.response(app.pending[1]); await settle();
  assert.equal(retry.hidden, true); assert.equal(app.doc.activeElement, app.node('polar-feedback'));
  assert.match(app.node('polar-feedback').textContent, /已加载/u);
});

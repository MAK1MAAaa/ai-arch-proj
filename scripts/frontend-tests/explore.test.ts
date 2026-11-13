import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface State { country: string | null; region: string | null; offset: number; visible: boolean; bbox?: [number, number, number, number] | null; spatial_match_mode?: string; spatial_version?: string | null; subdivision?: string | null; subdivision_version?: string | null }
interface Helpers {
  create(options: { map: FakeMap | null; initialState?: Partial<State>; initialBoundsError?: string | null; onBoundsAction?(): void; onSelect(id: string, opener: FakeElement, options?: { moveMap?: boolean }): void; onFilterChange?(state: State): void; onStateChange?(state: State): void; onCommittedState?(state: State): void; onCatalogue?(points: Point[]): void }): Controller;
  normalizeState(value: Partial<State>): State;
  matches(point: { countries: string[]; regions: string[]; repr_point?: [number, number] | null; source_points?: [number, number][] }, state: Pick<State, 'country' | 'region' | 'bbox'>, mode?: string): boolean;
  insideBBox(point: [number, number], bbox: [number, number, number, number]): boolean;
  capturedBounds(bounds: { getWest(): number; getEast(): number; getSouth(): number; getNorth(): number }): [number, number, number, number];
  coordinate(value: unknown): boolean;
  displayCoordinates(value: [number, number]): [number, number][];
  locationStatus(value: [number, number] | null): 'mapped' | 'polar' | 'unknown';
  placements(point: { repr_point: [number, number] | null; source_points: [number, number][]; source_location_records: SourceLocation[] }): { coordinate: [number, number]; representative: boolean; sourceIndexes: number[] }[];
}
interface Controller {
  load(): Promise<void>;
  setState(state: Partial<State>, options?: { notify?: boolean }): Promise<void>;
  getState(): State;
  getCommittedState(): State | null;
  getPoint(id: string): [number, number] | null;
  getLocationStatus(id: string): 'mapped' | 'polar' | 'unknown' | null;
  getSourcePoints(id: string): [number, number][];
  getDisplayPoints(id: string): [number, number][];
  getDisplayedPlacements(): { id: string; title: string; coordinate: [number, number]; representative: boolean }[];
  getSourceLocationRecords(id: string): SourceLocation[];
  getSpatialMetadata(): Record<string, unknown> | null;
  getSpatialSource(id: string): { name: string; uri: string; license: string } | null;
  select(id: string | null): void;
  configureSubdivisions(status: { ready: boolean; reason: string | null; version: string | null } | null): void;
  validateSearchScope(scope: { country?: string | null; subdivision?: string | null }, signal: AbortSignal): Promise<string | null>;
  subdivisionReady(): boolean;
  subdivisionVersion(): string | null;
  subdivisionLabel(id: string): string | null;
}

const compiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/explore.ts', import.meta.url), 'utf8'), {
  fileName: 'explore.ts', compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true }, reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter((item) => item.category === ts.DiagnosticCategory.Error).length, 0);
const researchCompiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/research.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } });
const researchHelpers = runInContext(`${researchCompiled.outputText}\nArchSearchResearch;`, createContext({ URL }));
const helpers = runInContext(`${compiled.outputText}\nArchSearchExplore;`, createContext({ URL, ArchSearchResearch: researchHelpers })) as Helpers;
const mapCompiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/map-view.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } });
const mapHelpers = runInContext(`${mapCompiled.outputText}\nArchSearchMapView;`, createContext({})) as { wrapCoordinates(points: [number, number][]): [number, number][] };
const densityCompiled = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/density.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } });
const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

test('global exploration defaults are independent of a query, model or historical year', () => {
  assert.deepEqual(plain(helpers.normalizeState({})), { country: null, region: null, offset: 0, visible: true, bbox: null });
  assert.deepEqual(plain(helpers.normalizeState({ country: 'NZ', region: 'asia-pacific', offset: 50, visible: false, bbox: null })), { country: 'NZ', region: 'asia-pacific', offset: 50, visible: false, bbox: null });
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
  isConnected = true;
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
  getBoundingClientRect() { return {left:0,top:0,right:600,bottom:400,width:600,height:400}; }
  fire(type: string): void { this.dispatchEvent(new Event(type)); }
  set innerHTML(_value: string) { throw new Error('Unsafe HTML insertion'); }
}

class FakeLayer {
  members: FakeCircle[] = [];
  handlers=new Map<string,()=>void>();
  on(name:string,handler:()=>void):this { this.handlers.set(name,handler);return this; }
  addTo(map: FakeMap): this { map.layers.add(this); this.handlers.get('add')?.(); return this; }
  clearLayers():this {this.members=[];return this;}
  removeLayer(layer:FakeCircle):this {this.members=this.members.filter(item=>item!==layer);return this;}
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
  bringToFront():this {return this;}
}

class FakeMarker extends FakeCircle {
  element=new FakeElement('div');
  getElement(){return this.element;}
  setLatLng(value:{lat:number;lng:number}){this.location=[value.lat,value.lng];return this;}
  override addTo(layer:FakeLayer):this {super.addTo(layer);this.handlers.get('add')?.();return this;}
}
class FakePopup extends FakeMarker {
  content=new FakeElement('section'); map:FakeMap|null=null;
  setContent(content:FakeElement){this.content=content;this.element.children=[content];return this;}
  openOn(map:FakeMap){this.map=map;map.popup=this;return this;}
  remove(){if(this.map)this.map.popup=null;return this;}
}

class FakeMap {
  layers = new Set<FakeLayer>();
  panes = new Map<string, FakeElement>();
  container = new FakeElement();
  lastBounds: unknown = null;
  bounds: [number, number, number, number] = [-180, -60, 180, 85];
  zoom=9;center={lat:0,lng:0};listeners=new Map<string,(()=>void)[]>();
  popup:FakePopup|null=null;
  on(names:string,callback:()=>void):this {for(const name of names.split(' '))this.listeners.set(name,[...(this.listeners.get(name)??[]),callback]);return this;}
  off(names:string,callback:()=>void):this {for(const name of names.split(' '))this.listeners.set(name,(this.listeners.get(name)??[]).filter(item=>item!==callback));return this;}
  fire(name:string):this {for(const callback of this.listeners.get(name)??[])callback();return this;}
  getZoom(){return this.zoom;}getCenter(){return this.center;}
  getSize(){const world=256*2**this.zoom;return{x:world*3,y:world};}
  project(value:[number,number]|{lat:number;lng:number},zoom=this.zoom){const point=Array.isArray(value)?{lat:value[0],lng:value[1]}:value,world=256*2**zoom;return{x:(point.lng+180)/360*world,y:(90-point.lat)/180*world};}
  unproject(value:[number,number],zoom=this.zoom){const world=256*2**zoom;return{lng:value[0]/world*360-180,lat:90-value[1]/world*180};}
  layerPointToContainerPoint(point:[number,number]){return{x:point[0],y:point[1]};}
  stop(){}setView(value:{lat:number;lng:number},zoom:number){this.center={...value};this.zoom=zoom;this.fire('zoomend').fire('moveend');return this;}
  getBounds() { return { getWest: () => this.bounds[0], getSouth: () => this.bounds[1], getEast: () => this.bounds[2], getNorth: () => this.bounds[3] }; }
  getPane(name: string): FakeElement | undefined { return this.panes.get(name); }
  createPane(name: string): FakeElement { const node = new FakeElement(); this.panes.set(name, node); return node; }
  getContainer(): FakeElement { return this.container; }
  hasLayer(layer: FakeLayer): boolean { return this.layers.has(layer); }
  removeLayer(layer: FakeLayer): this { this.layers.delete(layer); layer.handlers.get('remove')?.(); return this; }
  fitBounds(bounds: unknown): void { this.lastBounds = bounds; }
}

interface SourceLocation { source_index: number; coordinate: [number, number]; name: string; ref: string }
interface Point { id: string; title: string; repr_point: [number, number] | null; location_status: 'mapped' | 'polar' | 'unknown'; countries: string[]; regions: string[]; source_kind: string; chronology_status: string; source_points?: [number, number][]; source_location_records?: SourceLocation[] }
interface Pending { url: string; signal: AbortSignal; resolve(response: { ok: boolean; status: number; json(): Promise<unknown> }): void; reject(error: Error): void; done: boolean }
const fixture: Point[] = [
  { id: 'whc:1', title: '<img src=x onerror=alert(1)>', repr_point: [179, -18], location_status: 'mapped', countries: ['NZ'], regions: ['asia-pacific'], source_kind: 'unesco', chronology_status: 'not_reviewed' },
  { id: 'wd:Q2', title: 'Beta monument', repr_point: [29, 40], location_status: 'mapped', countries: ['TR'], regions: ['europe-north-america'], source_kind: 'global', chronology_status: 'reviewed' },
  { id: '123', title: 'Untitled', repr_point: [12, 42], location_status: 'mapped', countries: [], regions: [], source_kind: 'pleiades', chronology_status: 'insufficient' },
];

function coverageFor(points = fixture) {
  const counts = (field: 'countries' | 'regions') => [...new Set(points.flatMap(point => point[field]))].map(id => ({ id, label: id, count: points.filter(point => point[field].includes(id)).length }));
  return { corpus_version: 'global-v3', total: points.length, countries: counts('countries'), regions: counts('regions'),
    sources: [...new Set(points.map(point => point.source_kind))].map(id => ({ id, label: id, count: points.filter(point => point.source_kind === id).length })),
    chronology: { reviewed: points.filter(point => point.chronology_status === 'reviewed').length, insufficient: points.filter(point => point.chronology_status === 'insufficient').length, not_reviewed: points.filter(point => point.chronology_status === 'not_reviewed').length },
    locations: { mapped: points.filter(point => point.location_status === 'mapped').length, polar: points.filter(point => point.location_status === 'polar').length, unknown: points.filter(point => point.location_status === 'unknown').length },
    geography_unknown: points.filter(point => point.countries.length === 0).length, country_unknown: points.filter(point => point.countries.length === 0).length };
}

function pageFor(state: Partial<State> = {}, points = fixture) {
  const mode = points.some(point => point.source_points?.length) ? 'source-or-representative' : 'representative-only';
  const inside = (point: [number, number]) => !state.bbox || helpers.insideBBox(point, state.bbox);
  const filtered = points.filter(point => (state.country == null || point.countries.includes(state.country)) && (state.region == null || point.regions.includes(state.region))
    && (!state.bbox || (point.repr_point !== null && inside(point.repr_point)) || point.source_points?.some(inside)));
  const offset = state.offset ?? 0;
  return { corpus_version: 'global-v3', total: filtered.length, offset, limit: 50, bbox: state.bbox ?? null, spatial_match_mode: mode, spatial_version: mode === 'source-or-representative' ? 'world-locations-v1' : null,
    sites: filtered.slice(offset, offset + 50).map(point => ({ id: point.id, title: point.title, repr_point: point.repr_point, source_kind: point.source_kind,
      geography: point.countries.length || point.regions.length ? { countries: point.countries, regions: point.regions } : null, chronology: { status: point.chronology_status } })) };
}

function setup(withMap = true, initialBoundsError: string | null = null) {
  const ids = ['explore-panel', 'explore-summary', 'explore-authority', 'explore-polar-authority', 'explore-spatial-source', 'explore-country', 'explore-region', 'explore-clear', 'explore-points', 'explore-fit', 'explore-count', 'explore-list', 'explore-previous', 'explore-next', 'explore-page', 'explore-feedback', 'explore-retry', 'explore-limit-note', 'explore-capture-bounds', 'explore-clear-bounds', 'explore-bounds-status'];
  ids.push('explore-subdivision-filter', 'explore-subdivision', 'explore-subdivision-note', 'explore-subdivision-feedback', 'explore-subdivision-retry');
  const nodes = new Map(ids.map(id => [id, new FakeElement()]));
  const doc: { activeElement: FakeElement | null; getElementById(id: string): FakeElement | null; createElement(tag: string): FakeElement } = {
    activeElement: null, getElementById: id => nodes.get(id) ?? null,
    createElement: tag => { const node = new FakeElement(tag); node.onFocus = () => { doc.activeElement = node; }; return node; },
  };
  for (const node of nodes.values()) node.onFocus = () => { doc.activeElement = node; };
  const pending: Pending[] = [];
  const selects: { id: string; opener: FakeElement; options?: { moveMap?: boolean } }[] = [];
  const changes: State[] = [];
  const filters: State[] = [];
  const commits: State[] = [];
  const catalogues: Point[][] = [];
  const boundsActions: number[] = [];
  const circles: FakeCircle[] = [];
  const map = withMap ? new FakeMap() : null;
  const context = createContext({ document: doc, URL, URLSearchParams, AbortController, ArchSearchResearch: researchHelpers,requestAnimationFrame:(fn:()=>void)=>fn(),
    fetch: (url: string, options: { signal: AbortSignal }) => new Promise((resolve, reject) => pending.push({ url, signal: options.signal, resolve, reject, done: false })),
    L: { canvas: (options: unknown) => options, layerGroup: () => new FakeLayer(), circleMarker: (location: [number, number], options: Record<string, unknown>) => { const marker = new FakeCircle(location, options); circles.push(marker); return marker; },
      marker:(location:{lat:number;lng:number},options:Record<string,unknown>)=>new FakeMarker([location.lat,location.lng],options),divIcon:(options:unknown)=>options,
      popup:()=>new FakePopup([0,0],{}),latLngBounds: (points: unknown) => points },
    ArchSearchMapView: mapHelpers,
  });
  const api = runInContext(`${densityCompiled.outputText}\n${compiled.outputText}\nArchSearchExplore;`, context) as Helpers;
  const controller = api.create({ map, initialBoundsError, onBoundsAction: () => boundsActions.push(1), onSelect: (id, opener, options) => selects.push({ id, opener, options: options ? plain(options) : undefined }), onFilterChange: state => filters.push(plain(state)), onStateChange: state => changes.push(plain(state)), onCommittedState: state => commits.push(plain(state)), onCatalogue: points => catalogues.push(points) });
  const node = (id: string) => { const found = nodes.get(id); assert.ok(found); return found; };
  const response = (request: Pending, value: unknown, status = 200) => { request.done = true; request.resolve({ ok: status < 400, status, json: async () => value }); };
  const find = (path: string) => { const found = pending.find(item => !item.done && item.url.startsWith(path)); assert.ok(found, path); return found; };
  const respondAll = (points = fixture, state: Partial<State> = {}, spatial?: Record<string, unknown> | null) => {
    for (const request of pending.filter(item => !item.done && !item.signal.aborted)) {
      if (request.url === '/api/coverage') response(request, { ...coverageFor(points), ...(spatial !== undefined ? { spatial_locations: spatial } : {}) });
      else if (request.url === '/api/catalogue') response(request, { corpus_version: 'global-v3', spatial_version: spatial?.version ?? null, total: points.length, points });
      else response(request, pageFor(state, points));
    }
  };
  const boot = async (points = fixture, spatial?: Record<string, unknown> | null) => { const job = controller.load(); respondAll(points, {}, spatial); await job; };
  return { controller, node, pending, selects, changes, filters, commits, catalogues, boundsActions, circles, map, doc, find, response, respondAll, boot };
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
  assert.equal(app.circles[0].tooltip?.().children[0].textContent, fixture[0].title);
  assert.match(app.circles[0].tooltip?.().children[1].textContent ?? '', /原始代表点/u);
});

test('mouse circles and keyboard-accessible buttons only emit site identity and their opener', async () => {
  const app = setup(); await app.boot();
  const button = app.node('explore-list').children[0].children[0];
  button.fire('click');
  app.circles[0].handlers.get('click')?.();
  assert.deepEqual(app.selects.map(item => item.id), ['whc:1', 'whc:1']);
  assert.equal(app.selects[0].opener, button);
  assert.equal(app.selects[1].opener, app.map?.container);
  assert.deepEqual(app.selects[1].options, { moveMap: false });
  assert.equal(app.selects[0].options, undefined);
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
  await app.controller.setState({ visible: false, bbox: null }, { notify: true });
  assert.equal(app.map?.layers.size, 0); assert.equal(app.pending.length, calls);
  assert.equal(app.filters.length, 0); assert.equal(app.changes.length, 1);
  await app.controller.setState({ visible: true, bbox: null }, { notify: true });
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
  app.controller.select('whc:1');
  const originalCircles = app.circles.length;
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
  assert.deepEqual(original, { country: null, region: null, offset: 0, visible: true, bbox: null, spatial_match_mode: 'representative-only', spatial_version: null });
  assert.equal(app.commits.length, 1);
  const failed = app.controller.setState({ country: 'NZ' }, { notify: true });
  assert.equal(app.controller.getState().country, 'NZ');
  assert.deepEqual(plain(app.controller.getCommittedState()), original);
  const rejection = assert.rejects(failed, /failed draft/u);
  app.response(app.find('/api/sites'), { detail: 'failed draft' }, 503); await rejection;
  assert.deepEqual(plain(app.controller.getCommittedState()), original);
  assert.equal(app.commits.length, 1);
  const retry = app.controller.load(); app.respondAll(fixture, { country: 'NZ' }); await retry;
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: 'NZ', region: null, offset: 0, visible: true, bbox: null, spatial_match_mode: 'representative-only', spatial_version: null });
  assert.equal(app.commits.length, 2);
  const snapshot = app.controller.getCommittedState(); assert.ok(snapshot); snapshot.country = 'TR';
  assert.equal(app.controller.getCommittedState()?.country, 'NZ');
});

test('the point-layer switch commits immediately without relabelling an uncommitted region draft', async () => {
  const app = setup(); await app.boot();
  const pending = app.controller.setState({ country: 'TR' });
  await app.controller.setState({ visible: false, bbox: null }, { notify: true });
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: null, region: null, offset: 0, visible: false, bbox: null, spatial_match_mode: 'representative-only', spatial_version: null });
  app.response(app.find('/api/sites'), pageFor({ country: 'TR' })); await pending;
  assert.deepEqual(plain(app.controller.getCommittedState()), { country: 'TR', region: null, offset: 0, visible: false, bbox: null, spatial_match_mode: 'representative-only', spatial_version: null });
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

const antarctic: Point[] = [
  { id: 'ats:hsm:1', title: 'HSM 1', repr_point: [0, -90], location_status: 'polar', countries: [], regions: ['antarctica'], source_kind: 'ats', chronology_status: 'not_reviewed' },
  { id: 'ats:hsm:24', title: 'HSM 24', repr_point: [-87.113111, -85.173278], location_status: 'polar', countries: [], regions: ['antarctica'], source_kind: 'ats', chronology_status: 'not_reviewed' },
  { id: 'ats:hsm:34', title: 'HSM 34', repr_point: [-55.716667, -62.183333], location_status: 'mapped', countries: [], regions: ['antarctica'], source_kind: 'ats', chronology_status: 'not_reviewed' },
  { id: 'ats:hsm:80', title: 'HSM 80', repr_point: [0, -90], location_status: 'polar', countries: [], regions: ['antarctica'], source_kind: 'ats', chronology_status: 'not_reviewed' },
  { id: 'ats:hsm:95', title: 'HSM 95', repr_point: null, location_status: 'unknown', countries: [], regions: ['antarctica'], source_kind: 'ats', chronology_status: 'not_reviewed' },
];

test('location status follows actual coordinates at the Mercator limit without clipping or zero-filling', () => {
  assert.equal(helpers.locationStatus(null), 'unknown');
  assert.equal(helpers.locationStatus([0, 0]), 'mapped');
  assert.equal(helpers.locationStatus([0, -85.0511287798]), 'mapped');
  assert.equal(helpers.locationStatus([0, -85.0511287799]), 'polar');
  assert.equal(helpers.locationStatus([0, 90]), 'polar');
});

test('all records remain browsable while only mapped points are added to the Mercator layer', async () => {
  const points = [...fixture, ...antarctic]; const app = setup(); await app.boot(points);
  assert.equal(app.node('explore-list').children.length, 8); assert.equal(app.circles.length, 12);
  assert.match(app.node('explore-feedback').textContent, /8 条资料.*主图可定位 4、极区 3、暂无可用代表点 1/u);
  assert.deepEqual(plain(app.controller.getPoint('ats:hsm:1')), [0, -90]);
  assert.deepEqual(plain(app.controller.getPoint('ats:hsm:24')), [-87.113111, -85.173278]);
  assert.equal(app.controller.getPoint('ats:hsm:95'), null);
  assert.equal(app.controller.getLocationStatus('ats:hsm:95'), 'unknown');
  assert.equal(app.controller.getLocationStatus('ats:hsm:1'), 'polar');
  assert.equal(app.controller.getLocationStatus('missing'), null);
  const unknown = app.node('explore-list').children.at(-1)!.children[0];
  assert.equal(unknown.dataset.locationStatus, 'unknown'); assert.match(unknown.children[2].textContent, /暂无可用代表点/u);
  unknown.fire('click'); assert.equal(app.selects.at(-1)?.id, 'ats:hsm:95');
  app.node('explore-fit').fire('click');
  const bounds = plain(app.map?.lastBounds) as [number, number][];
  assert.deepEqual(bounds.map(point => point[0]), [-18, 40, 42, -62.183333]);
  const canonical = [179, 29, 12, -55.716667];
  assert.ok(bounds.every((point, index) => Math.abs(((point[1] - canonical[index] + 540) % 360) - 180) < 1e-8));
});

test('catalogue callbacks always include cloned polar and unknown records independent of browse filters', async () => {
  const points = [...fixture, ...antarctic]; const app = setup(); await app.boot(points);
  assert.equal(app.catalogues.length, 1); assert.equal(app.catalogues[0].length, 8);
  const pole = app.catalogues[0].find(point => point.id === 'ats:hsm:1')!;
  pole.repr_point![1] = 0; pole.regions.length = 0;
  assert.deepEqual(plain(app.controller.getPoint('ats:hsm:1')), [0, -90]);
  const region = app.controller.setState({ region: 'antarctica' }); app.respondAll(points, { region: 'antarctica' }); await region;
  assert.equal(app.catalogues.length, 1); assert.equal(app.node('explore-list').children.length, 5);
  assert.equal([...app.map!.layers][0].members.length, 3);
  assert.match(app.node('explore-feedback').textContent, /主图可定位 1、极区 3、暂无可用代表点 1/u);
  const reload = app.controller.load(); app.respondAll(points, { region: 'antarctica' }); await reload;
  assert.equal(app.catalogues[1].length, 8);
});

test('contradictory coordinate/status or location totals cannot replace a successful catalogue', async () => {
  const app = setup(); await app.boot(); const layer = [...app.map!.layers][0];
  const invalid = [...fixture, { ...antarctic[0], location_status: 'mapped' as const }];
  const first = app.controller.load(); const firstRejected = assert.rejects(first, /定位状态与原始坐标/u);
  app.respondAll(invalid); await firstRejected;
  assert.equal([...app.map!.layers][0], layer); assert.equal(app.catalogues.length, 1);
  const second = app.controller.load(); const secondRejected = assert.rejects(second, /统计总数/u);
  app.response(app.find('/api/coverage'), { ...coverageFor(), locations: { mapped: 1, polar: 0, unknown: 1 } });
  app.response(app.find('/api/catalogue'), { corpus_version: 'global-v3', total: 3, points: fixture });
  app.response(app.find('/api/sites'), pageFor()); await secondRejected;
  assert.equal(app.node('explore-list').children.length, 3);
});

test('ATS source coverage counts unknown records as collected without claiming geolocation', async () => {
  const app = setup(); const job = app.controller.load();
  const polarAuthority = { dataset: 'ATS active HSM', source_uri: 'https://www.ats.aq/devphbackend/api/apa/search?lang=e', source_accessed: '2026-11-04', source_sha256: 'b'.repeat(64), license: 'CC BY 4.0', license_uri: 'https://creativecommons.org/licenses/by/4.0/', eligible_total: 91, covered: 91, missing: 0, excluded_types: { ASPA: 84, ASMA: 7 }, note: 'HSM95 has no confirmed coordinate.' };
  app.response(app.find('/api/coverage'), { ...coverageFor(antarctic), polar_authority: polarAuthority });
  app.response(app.find('/api/catalogue'), { corpus_version: 'global-v3', total: antarctic.length, points: antarctic });
  app.response(app.find('/api/sites'), pageFor({}, antarctic)); await job;
  const source = app.node('explore-polar-authority'); assert.equal(source.hidden, false);
  assert.match(source.children[0].textContent, /91 \/ 91 条已收录（包含位置未知记录）/u);
  assert.equal((source.children[1] as FakeElement & { href: string }).href, polarAuthority.source_uri);
  assert.match(source.children[3].textContent, /ASPA 84、ASMA 7/u);
});

const multiPoints: Point[] = fixture.map(point => ({ ...point, source_points: [], source_location_records: [] }));
multiPoints[0] = { ...multiPoints[0], countries: ['NZ', 'TR'], source_points: [[179, -18], [-179, -18], [179, -18]], source_location_records: [
  { source_index: 0, coordinate: [179, -18], name: '<b>Source name</b>', ref: '001-001' },
  { source_index: 1, coordinate: [-179, -18], name: '', ref: '001-002' },
  { source_index: 2, coordinate: [179, -18], name: 'Second source record at the same coordinate', ref: '001-003' },
] };
multiPoints[1] = { ...multiPoints[1], source_points: [[30, 41], [31, 42]], source_location_records: [
  { source_index: 0, coordinate: [30, 41], name: 'Source A', ref: '' },
  { source_index: 1, coordinate: [31, 42], name: 'Source B', ref: '' },
] };
const spatial = { ready: true, reason: null, version: 'world-locations-v1', records: 2, points: 5, distinct_points: 4, duplicate_points: 1, display_points: 6,
  source: { name: 'UNESCO DataHub source locations', uri: 'https://data.unesco.org/explore/dataset/whc001/', version: '2026-11-02T07:32:31Z', license: 'CC BY-SA 4.0', license_uri: 'https://creativecommons.org/licenses/by-sa/4.0/', sha256: 'c'.repeat(64) } };

test('source points retain raw order and duplicates while placements add only a necessary mapped representative', () => {
  const site = multiPoints[0]; const original = plain(site);
  assert.deepEqual(plain(helpers.placements({ repr_point: site.repr_point, source_points: site.source_points!, source_location_records: site.source_location_records! })), [
    { coordinate: [179, -18], sourceIndexes: [0, 2], representative: false },
    { coordinate: [-179, -18], sourceIndexes: [1], representative: false },
  ]);
  const second = multiPoints[1];
  assert.deepEqual(plain(helpers.placements({ repr_point: second.repr_point, source_points: second.source_points!, source_location_records: second.source_location_records! })).map(point => point.coordinate), [[30, 41], [31, 42], [29, 40]]);
  assert.deepEqual(site, original);
  assert.deepEqual(plain(helpers.placements({ repr_point: [0, -90], source_points: [[1, -89]], source_location_records: [] })), []);
  assert.deepEqual(plain(helpers.placements({ repr_point: null, source_points: [], source_location_records: [] })), []);
});

test('multi-point heritage remains one directory identity and all its source points share selection and a literal tooltip', async () => {
  const app = setup(); await app.boot(multiPoints, spatial);
  assert.equal(app.node('explore-list').children.length, 3); assert.equal(app.circles.length, 18);
  assert.match(app.node('explore-feedback').textContent, /3 条资料 \/ 主图 4 个源定位点 \+ 2 个必要代表点/u);
  app.controller.select('whc:1');
  assert.ok(app.circles.slice(0, 6).every(circle => circle.options.radius === 5));
  assert.ok(app.circles.slice(6).every(circle => circle.options.radius === 3.2));
  const tooltip = app.circles[0].tooltip!();
  assert.match(tooltip.children[1].textContent, /来源定位点.*1、3/u);
  assert.equal(tooltip.children[2].textContent, '<b>Source name</b> · 001-001');
  assert.match(app.circles[12].tooltip!().children[1].textContent, /原始代表点/u);
  app.circles[3].handlers.get('click')?.();
  assert.equal(app.selects.at(-1)?.id, 'whc:1'); assert.deepEqual(app.selects.at(-1)?.options, { moveMap: false });
  app.controller.select(null); assert.ok(app.circles.every(circle => circle.options.radius === 3.2));
});

test('raw source arrays, labels and spatial provenance are independently cloned for detail and export callers', async () => {
  const app = setup(); assert.equal(app.controller.getSpatialMetadata(), null); await app.boot(multiPoints, spatial);
  assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), [[179, -18], [-179, -18], [179, -18]]);
  assert.deepEqual(plain(app.controller.getDisplayPoints('whc:1')), [[179, -18], [-179, -18]]);
  const coordinates = app.controller.getSourcePoints('whc:1'); coordinates[0][0] = 0;
  const records = app.controller.getSourceLocationRecords('whc:1'); records[0].coordinate[0] = 0; records[0].name = 'changed';
  const metadata = app.controller.getSpatialMetadata()!; metadata.points = 0; (metadata.source as { license: string }).license = 'changed';
  assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), multiPoints[0].source_points);
  assert.equal(app.controller.getSourceLocationRecords('whc:1')[0].name, '<b>Source name</b>');
  assert.equal(app.controller.getSpatialMetadata()?.points, 5);
  app.catalogues[0][0].source_points![0][0] = 0; app.catalogues[0][0].source_location_records![0].ref = 'changed';
  assert.equal(app.controller.getSourcePoints('whc:1')[0][0], 179); assert.equal(app.controller.getSourceLocationRecords('whc:1')[0].ref, '001-001');
  assert.deepEqual(plain(app.controller.getSourcePoints('missing')), []);
  assert.equal(app.node('explore-spatial-source').hidden, false);
  assert.match(app.node('explore-spatial-source').children[0].textContent, /2 条文化资料.*5 个来源定位点记录/u);
});

test('country membership filtering retains every transnational source point and dateline fitting uses the short span', async () => {
  const app = setup(); await app.boot(multiPoints, spatial);
  const selected = app.controller.setState({ country: 'NZ' }); app.respondAll(multiPoints, { country: 'NZ' }); await selected;
  assert.equal(app.node('explore-list').children.length, 1); assert.equal([...app.map!.layers][0].members.length, 6);
  app.node('explore-fit').fire('click');
  const bounds = plain(app.map!.lastBounds) as [number, number][];
  assert.equal(Math.abs(bounds[0][1] - bounds[1][1]), 2);
  assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), [[179, -18], [-179, -18], [179, -18]]);
  assert.equal(app.controller.getCommittedState()?.country, 'NZ');
});

test('different heritage identities at a shared source coordinate remain independently selectable', async () => {
  const shared = multiPoints.map(point => plain(point));
  shared[1].source_points = [[179, -18]];
  shared[1].source_location_records = [{ source_index: 0, coordinate: [179, -18], name: 'Different heritage record', ref: '' }];
  const app = setup(); await app.boot(shared, { ...spatial, points: 4, distinct_points: 3, duplicate_points: 1, display_points: 5 });
  assert.equal(app.map!.container.dataset.densityLogicalPoints, '5');
  const cluster=[...app.map!.layers][0].members.find(marker=>marker.options.pane==='catalogue-density-clusters');assert.ok(cluster);
  cluster.handlers.get('click')?.();assert.ok(app.map!.popup);
  const descendants=(element:FakeElement):FakeElement[]=>[element,...element.children.flatMap(descendants)];
  const buttons=descendants(app.map!.popup!.content).filter(element=>element.dataset.siteId);
  const first=buttons.find(button=>button.dataset.siteId==='whc:1'),second=buttons.find(button=>button.dataset.siteId==='wd:Q2');assert.ok(first);assert.ok(second);
  first.fire('click');second.fire('click');
  assert.deepEqual(app.selects.map(selection => selection.id), ['whc:1', 'wd:Q2']);
  app.controller.select('wd:Q2');assert.equal(second.attributes.get('aria-pressed'),'true');
  assert.ok([...app.map!.layers][0].members.some(marker=>marker.options.radius===5));
});

test('source coordinates outside Mercator and unknown records stay out of the main layer without clipping', async () => {
  const points = antarctic.map(point => ({ ...plain(point), source_points: [] as [number, number][], source_location_records: [] as SourceLocation[] }));
  points[0].source_points = [[42, -89], [15, -90]];
  points[0].source_location_records = [{ source_index: 0, coordinate: [42, -89], name: '', ref: '' }, { source_index: 1, coordinate: [15, -90], name: '', ref: '' }];
  const app = setup(); await app.boot(points, { ...spatial, records: 1, points: 2, distinct_points: 2, duplicate_points: 0, display_points: 1 });
  assert.equal(app.node('explore-list').children.length, 5); assert.equal(app.circles.length, 3);
  assert.deepEqual(plain(app.controller.getSourcePoints('ats:hsm:1')), [[42, -89], [15, -90]]);
  assert.deepEqual(plain(app.controller.getDisplayPoints('ats:hsm:1')), []);
  assert.equal(app.controller.getPoint('ats:hsm:95'), null);
  assert.match(app.node('explore-feedback').textContent, /主图 0 个源定位点 \+ 1 个必要代表点/u);
});

test('source sequence, coordinate and version mismatches reject before replacing a successful spatial snapshot', async () => {
  const variants: { mutate(points: Point[]): void; match: RegExp }[] = [
    { mutate: points => { points[0].source_points = null as unknown as [number, number][]; }, match: /缺少源点或逐点记录/u },
    { mutate: points => { points[0].source_points![0] = [181, -18]; }, match: /坐标或数量/u },
    { mutate: points => { points[0].source_points = Array.from({ length: 10_001 }, () => [0, 0]); }, match: /坐标或数量/u },
    { mutate: points => { points[0].source_location_records!.pop(); }, match: /记录数量/u },
    { mutate: points => { points[0].source_location_records![0].source_index = 1; }, match: /顺序或标签/u },
    { mutate: points => { points[0].source_location_records![0].coordinate = [-179, -18]; }, match: /顺序或标签/u },
  ];
  const app = setup(); await app.boot(multiPoints, spatial); const layer = [...app.map!.layers][0];
  for (const variant of variants) {
    const invalid = plain(multiPoints); variant.mutate(invalid);
    const job = app.controller.load(); const rejection = assert.rejects(job, variant.match);
    app.respondAll(invalid, {}, spatial); await rejection;
    assert.equal([...app.map!.layers][0], layer); assert.equal(app.controller.getSpatialMetadata()?.points, 5);
    assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), multiPoints[0].source_points);
  }
  const mismatch = app.controller.load(); const rejected = assert.rejects(mismatch, /目录与统计版本/u);
  app.response(app.find('/api/coverage'), { ...coverageFor(multiPoints), spatial_locations: spatial });
  app.response(app.find('/api/catalogue'), { corpus_version: 'global-v3', spatial_version: 'wrong', total: 3, points: multiPoints });
  app.response(app.find('/api/sites'), pageFor({}, multiPoints)); await rejected;
  assert.equal([...app.map!.layers][0], layer);
});

test('unprepared source locations explicitly fall back to existing representative points and legacy snapshots stay compatible', async () => {
  const app = setup(); const degraded = { ready: false, reason: 'Source hash mismatch', version: null, source: null,
    records: 0, points: 0, distinct_points: 0, duplicate_points: 0, display_points: 3 };
  await app.boot(fixture, degraded);
  assert.equal(app.circles.length, 9); assert.match(app.node('explore-spatial-source').children[0].textContent, /未就绪.*Source hash mismatch.*保留可用代表点/u);
  assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), []);
  const legacy = setup(); await legacy.boot(); assert.equal(legacy.controller.getSpatialMetadata(), null);
  assert.deepEqual(plain(legacy.controller.getDisplayPoints('whc:1')), [[179, -18]]);
});

test('pagination counts heritage records rather than source points and does not rebuild the shared layer', async () => {
  const many = Array.from({ length: 60 }, (_, index): Point => ({ ...plain(multiPoints[0]), id: `whc:${index + 1}`, title: `Site ${String(index + 1).padStart(3, '0')}` }));
  const app = setup(); await app.boot(many, { ...spatial, records: 60, points: 180, distinct_points: 120, duplicate_points: 60, display_points: 120 });
  assert.equal(app.node('explore-list').children.length, 50);assert.equal(app.map!.container.dataset.densityLogicalPoints,'120');
  assert.equal(app.circles.length,0);assert.match(app.node('explore-feedback').textContent,/主图 120 个源定位点/u);
  const layer = [...app.map!.layers][0]; const next = app.controller.setState({ offset: 50 }); app.respondAll(many, { offset: 50 }); await next;
  assert.equal(app.node('explore-list').children.length, 10); assert.match(app.node('explore-page').textContent, /51—60.*共 60 条/u);
  assert.equal([...app.map!.layers][0], layer); assert.equal(app.circles.length,0);assert.equal(app.map!.container.dataset.densityLogicalPoints,'120');
});

test('a source-qualified supplement with unknown position remains in the directory and country facets', async () => {
  const unknown: Point = { id: 'auth:dva:betio-coast-watchers-memorial', title: 'Betio Coast Watchers Memorial',
    repr_point: null, location_status: 'unknown', countries: ['KI'], regions: ['asia-pacific'],
    source_kind: 'supplement', chronology_status: 'not_reviewed', source_points: [], source_location_records: [] };
  const points = [...fixture, unknown];
  const app = setup(); await app.boot(points);
  assert.equal(app.node('explore-list').children.length, 4); assert.equal(app.circles.length, 9);
  assert.equal(app.controller.getPoint(unknown.id), null); assert.equal(app.controller.getLocationStatus(unknown.id), 'unknown');
  assert.deepEqual(plain(app.controller.getDisplayPoints(unknown.id)), []);
  const filtered = app.controller.setState({ country: 'KI' }); app.respondAll(points, { country: 'KI' }); await filtered;
  assert.equal(app.node('explore-list').children.length, 1);
  const button = app.node('explore-list').children[0].children[0];
  assert.equal(button.dataset.siteId, unknown.id); assert.match(button.children[2].textContent, /暂无可用代表点/u);
  assert.equal(app.node('explore-fit').disabled, true);
  assert.match(app.node('explore-feedback').textContent, /1 条资料.*0 个源定位点 \+ 0 个必要代表点/u);
  button.fire('click'); assert.equal(app.selects.at(-1)?.id, unknown.id);
  assert.equal(app.selects.at(-1)?.options, undefined);
});

test('captured map bounds normalize world copies and preserve antimeridian width', () => {
  const capture = (west: number, east: number) => helpers.capturedBounds({ getWest: () => west, getEast: () => east, getSouth: () => -20, getNorth: () => 30 });
  for (const pair of [[170, 190], [530, 550], [-190, -170]]) assert.deepEqual(plain(capture(...pair as [number, number])), [170, -20, -170, 30]);
  assert.deepEqual(plain(capture(170, 180)), [170, -20, 180, 30]);
  assert.deepEqual(plain(capture(180, 190)), [-180, -20, -170, 30]);
  assert.deepEqual(plain(capture(180, 540)), [-180, -20, 180, 30]);
  assert.deepEqual(plain(capture(-541, 180)), [-180, -20, 180, 30]);
  assert.throws(() => capture(1, 1), /有效范围/u);
  assert.throws(() => capture(Number.NaN, 3), /有效范围/u);
});

test('closed bbox membership aliases both dateline spellings and keeps unknowns out', () => {
  for (const longitude of [-180, 180]) {
    assert.equal(helpers.insideBBox([longitude, 10], [170, 0, 180, 10]), true);
    assert.equal(helpers.insideBBox([longitude, 0], [-180, 0, -170, 10]), true);
    assert.equal(helpers.insideBBox([longitude, 10.1], [170, 0, -170, 10]), false);
  }
  assert.equal(helpers.insideBBox([0, 0], [170, -20, -170, 20]), false);
  assert.equal(helpers.matches({ countries: [], regions: [], repr_point: null }, { country: null, region: null, bbox: [-180, -90, 180, 90] }), false);
  assert.equal(helpers.matches({ countries: [], regions: [], repr_point: [0, -90] }, { country: null, region: null, bbox: [-180, -90, 180, 90] }), true);
});

test('a source point in a fixed bbox selects its heritage once and clips outside placements', async () => {
  const app = setup(); await app.boot(multiPoints, spatial);
  await assert.rejects(app.controller.setState({ bbox: [30, 41, 30, 42] }), /地图范围/u);
  const bbox: [number, number, number, number] = [30, 41, 30.5, 41.5];
  app.controller.select('wd:Q2');
  const changed = app.controller.setState({ bbox }, { notify: true });
  const request = app.find('/api/sites');
  assert.equal(new URL(request.url, 'http://local').searchParams.get('bbox'), bbox.join(','));
  app.response(request, pageFor({ bbox }, multiPoints)); await changed;
  assert.equal(app.node('explore-list').children.length, 1);
  const layer = [...app.map!.layers][0];
  assert.deepEqual(plain(layer.members.map(circle => circle.location)), [[41, -330], [41, 30], [41, 390]]);
  const placements = app.controller.getDisplayedPlacements();
  assert.deepEqual(plain(placements.map(point => ({ id: point.id, coordinate: point.coordinate, representative: point.representative }))), [{ id: 'wd:Q2', coordinate: [30, 41], representative: false }]);
  placements[0].coordinate[0] = 0;
  assert.deepEqual(plain(app.controller.getDisplayedPlacements()[0].coordinate), [30, 41]);
  assert.ok(layer.members.every(circle => circle.options.radius === 5));
  assert.deepEqual(plain(app.controller.getPoint('wd:Q2')), [29, 40]);
  assert.deepEqual(plain(app.controller.getSourcePoints('wd:Q2')), [[30, 41], [31, 42]]);
  app.node('explore-list').children[0].children[0].fire('click');
  assert.deepEqual(app.selects.at(-1)?.options, { moveMap: false });
  assert.equal(app.filters.length, 0);
  assert.equal(app.pending.filter(request => request.url.startsWith('/api/catalogue')).length, 1);
  assert.equal(app.pending.filter(request => request.url === '/api/search').length, 0);
  const snapshot = app.controller.getCommittedState(); assert.ok(snapshot?.bbox); snapshot.bbox[0] = 0;
  assert.deepEqual(plain(app.controller.getCommittedState()?.bbox), bbox);
  bbox[0] = 0;
  assert.deepEqual(plain(app.controller.getState().bbox), [30, 41, 30.5, 41.5]);
  await app.controller.setState({ visible: false }); assert.deepEqual(plain(app.controller.getDisplayedPlacements()), []);
});

test('captured bounds stay fixed after map movement and clearing preserves keyboard focus', async () => {
  const app = setup(); await app.boot();
  app.map!.bounds = [170, -20, 190, -10]; app.node('explore-capture-bounds').fire('click');
  app.response(app.find('/api/sites'), pageFor({ bbox: [170, -20, -170, -10] }));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(plain(app.controller.getCommittedState()?.bbox), [170, -20, -170, -10]);
  app.map!.bounds = [0, 0, 10, 10];
  assert.deepEqual(plain(app.controller.getState().bbox), [170, -20, -170, -10]);
  assert.equal(app.pending.filter(request => !request.done && !request.signal.aborted).length, 0);
  app.node('explore-clear-bounds').focus(); app.node('explore-clear-bounds').fire('click');
  app.response(app.find('/api/sites'), pageFor()); await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.controller.getCommittedState()?.bbox, null);
  assert.equal(app.doc.activeElement, app.node('explore-bounds-status'));
  assert.equal([...app.map!.layers][0].members.length, 9);
});

test('bbox echo, spatial mode and source version mismatches retain the successful snapshot', async () => {
  const app = setup(); await app.boot(multiPoints, spatial);
  const original = plain(app.controller.getCommittedState()); const layer = [...app.map!.layers][0];
  for (const change of [{ bbox: null }, { spatial_match_mode: 'representative-only' }, { spatial_version: 'other-version' }]) {
    const changed = app.controller.setState({ bbox: [30, 41, 30.5, 41.5] });
    const rejected = assert.rejects(changed, /地图范围.*定位匹配方式/u);
    app.response(app.find('/api/sites'), { ...pageFor({ bbox: [30, 41, 30.5, 41.5] }, multiPoints), ...change }); await rejected;
    assert.deepEqual(plain(app.controller.getCommittedState()), original);
    assert.equal([...app.map!.layers][0], layer);
  }
});

test('late bbox failures cannot replace a newer scope and fallback matches only representatives', async () => {
  const app = setup(); await app.boot(multiPoints, spatial);
  const first = app.controller.setState({ bbox: [30, 41, 30.5, 41.5] }); const old = app.find('/api/sites');
  const second = app.controller.setState({ bbox: [178, -19, 180, -17] });
  const latest = app.pending.filter(request => request.url.startsWith('/api/sites') && !request.done).at(-1)!;
  assert.equal(old.signal.aborted, true);
  app.response(latest, pageFor({ bbox: [178, -19, 180, -17] }, multiPoints)); await second;
  app.response(old, { detail: 'late old failure' }, 503); await first;
  assert.deepEqual(plain(app.controller.getCommittedState()?.bbox), [178, -19, 180, -17]);
  assert.equal(app.node('explore-retry').hidden, true);
  const fallback = setup();
  await fallback.boot(fixture, { ready: false, reason: 'missing source archive', version: null, source: null,
    records: 0, points: 0, distinct_points: 0, duplicate_points: 0, display_points: 3 });
  const job = fallback.controller.setState({ bbox: [30, 41, 30.5, 41.5] });
  fallback.response(fallback.find('/api/sites'), pageFor({ bbox: [30, 41, 30.5, 41.5] })); await job;
  assert.equal([...fallback.map!.layers][0].members.length, 0);
  assert.equal(fallback.controller.getCommittedState()?.spatial_match_mode, 'representative-only');
  assert.match(fallback.node('explore-feedback').textContent, /仅按原代表点匹配.*组成地点可能遗漏/u);
});

test('an invalid restored bbox gates every directory load until an explicit clear action', async () => {
  const app = setup(true, '链接中的 browse_bbox 参数不能重复。');
  await assert.rejects(app.controller.load(), /browse_bbox/u);
  await assert.rejects(app.controller.load(), /browse_bbox/u);
  await assert.rejects(app.controller.setState({ country: 'NZ' }, { notify: true }), /browse_bbox/u);
  assert.equal(app.pending.length, 0);
  assert.equal(app.controller.getCommittedState(), null);
  assert.equal(app.commits.length, 0);
  assert.equal(app.map!.layers.size, 0);
  assert.match(app.node('explore-bounds-status').textContent, /恢复失败.*明确清除范围/u);
  assert.equal(app.node('explore-clear-bounds').disabled, false);
  assert.equal(app.node('explore-capture-bounds').disabled, false);
  assert.equal(app.node('explore-retry').hidden, true);
  app.node('explore-clear-bounds').focus(); app.node('explore-clear-bounds').fire('click');
  app.respondAll(fixture, { country: 'NZ' }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.boundsActions.length, 1);
  assert.equal(app.controller.getCommittedState()?.country, 'NZ');
  assert.equal(app.controller.getCommittedState()?.bbox, null);
  assert.equal(app.node('explore-bounds-status').tokens.has('is-invalid'), false);
  assert.equal(app.doc.activeElement, app.node('explore-bounds-status'));
});

test('invalid bounds may be replaced by capture while capture failure preserves the recovery gate', async () => {
  const app = setup(true, '地图范围无效。');
  app.map!.bounds = [1, 0, 1, 20];
  app.node('explore-capture-bounds').fire('click');
  assert.equal(app.boundsActions.length, 0);
  await assert.rejects(app.controller.load(), /地图范围无效/u);
  assert.equal(app.pending.length, 0);
  app.map!.bounds = [170, -20, 190, -10];
  app.node('explore-capture-bounds').fire('click');
  app.respondAll(fixture, { bbox: [170, -20, -170, -10] }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.boundsActions.length, 1);
  assert.deepEqual(plain(app.controller.getCommittedState()?.bbox), [170, -20, -170, -10]);
  assert.equal(app.node('explore-bounds-status').tokens.has('is-invalid'), false);
});

const groupedSpatial = {
  ...spatial, version: 'world-locations-v1+protection-locations-v1',
  source_groups: [
    { version: 'world-locations-v1', source: spatial.source, site_ids: ['whc:1'] },
    { version: 'protection-locations-v1', source: { ...spatial.source, name: 'UNESCO DataHub chp001', uri: 'https://data.unesco.org/explore/dataset/chp001/', sha256: 'd'.repeat(64) }, site_ids: ['wd:Q2'] },
  ],
};

async function bootGrouped(app: ReturnType<typeof setup>, metadata = groupedSpatial): Promise<void> {
  const job = app.controller.load();
  for (const request of app.pending.filter(request => !request.done && !request.signal.aborted)) {
    if (request.url === '/api/coverage') app.response(request, { ...coverageFor(multiPoints), spatial_locations: metadata });
    else if (request.url === '/api/catalogue') app.response(request, { corpus_version: 'global-v3', spatial_version: metadata.version, total: multiPoints.length, points: multiPoints });
    else app.response(request, { ...pageFor({}, multiPoints), spatial_version: metadata.version });
  }
  await job;
}

test('multiple location sources retain separate identity, license and cloned provenance', async () => {
  const app = setup(); await bootGrouped(app);
  assert.equal(app.controller.getCommittedState()?.spatial_version, groupedSpatial.version);
  assert.equal(app.controller.getSpatialSource('whc:1')?.uri, spatial.source.uri);
  assert.equal(app.controller.getSpatialSource('wd:Q2')?.uri, groupedSpatial.source_groups[1].source.uri);
  assert.equal(app.controller.getSpatialSource('123'), null);
  const source = app.controller.getSpatialSource('wd:Q2'); assert.ok(source); source.uri = 'https://changed.example/';
  assert.equal(app.controller.getSpatialSource('wd:Q2')?.uri, groupedSpatial.source_groups[1].source.uri);
  const metadata = app.controller.getSpatialMetadata()!;
  (metadata.source_groups as { site_ids: string[] }[])[1].site_ids.push('changed');
  assert.equal((app.controller.getSpatialMetadata()?.source_groups as { site_ids: string[] }[])[1].site_ids.length, 1);
  assert.match(app.node('explore-spatial-source').children[0].textContent, /2 套固定来源合计/u);
  assert.ok(app.node('explore-spatial-source').children.some(node => node.textContent.includes('chp001')));
  assert.deepEqual(plain(app.controller.getSourcePoints('whc:1')), multiPoints[0].source_points);
});

test('source-group identity, metadata and version corruption cannot replace a successful layer', async () => {
  const app = setup(); await bootGrouped(app);
  const layer = [...app.map!.layers][0];
  for (const variant of ['version', 'duplicate', 'foreign', 'source'] as const) {
    const broken = plain(groupedSpatial);
    if (variant === 'version') broken.source_groups[1].version = 'old-protection-locations';
    if (variant === 'duplicate') broken.source_groups[1].site_ids = ['whc:1'];
    if (variant === 'foreign') broken.source_groups[1].site_ids = ['auth:unesco-chp:foreign'];
    if (variant === 'source') broken.source_groups[0].source.uri = 'https://different.example/';
    await assert.rejects(bootGrouped(app, broken), /来源定位分组/u);
    assert.equal([...app.map!.layers][0], layer);
    assert.equal(app.controller.getCommittedState()?.spatial_version, groupedSpatial.version);
    assert.equal(app.controller.getSpatialSource('wd:Q2')?.uri, groupedSpatial.source_groups[1].source.uri);
  }
});

test('a page with an old single-source version cannot commit a combined-source scope', async () => {
  const app = setup(); await bootGrouped(app); const layer = [...app.map!.layers][0];
  const changed = app.controller.setState({ bbox: [30, 41, 30.5, 41.5] });
  const rejected = assert.rejects(changed, /地图范围.*定位匹配方式/u);
  app.response(app.find('/api/sites'), pageFor({ bbox: [30, 41, 30.5, 41.5] }, multiPoints)); await rejected;
  assert.equal([...app.map!.layers][0], layer);
  assert.equal(app.controller.getCommittedState()?.bbox, null);
  const retried = app.controller.setState({ bbox: [30, 41, 30.5, 41.5] });
  app.response(app.find('/api/sites'), { ...pageFor({ bbox: [30, 41, 30.5, 41.5] }, multiPoints), spatial_version: groupedSpatial.version }); await retried;
  assert.deepEqual(plain(app.controller.getCommittedState()?.bbox), [30, 41, 30.5, 41.5]);
  assert.equal(app.controller.getSpatialSource('wd:Q2')?.uri, groupedSpatial.source_groups[1].source.uri);
});

const subdivisionFixture: Point[] = [
  { id: 'auth:ca-dfhd:1', title: 'Alpha fort', repr_point: [-80, 45], location_status: 'mapped', countries: ['CA'], regions: ['europe-north-america'], source_kind: 'supplement', chronology_status: 'not_reviewed' },
  { id: 'auth:ca-dfhd:2', title: 'Beta building', repr_point: [-70, 46], location_status: 'mapped', countries: ['CA'], regions: ['europe-north-america'], source_kind: 'supplement', chronology_status: 'not_reviewed' },
  { id: 'auth:ca-dfhd:3', title: 'Cross province landscape', repr_point: null, location_status: 'unknown', countries: ['CA'], regions: ['europe-north-america'], source_kind: 'supplement', chronology_status: 'not_reviewed' },
  { id: 'auth:fixture:fr', title: 'French place', repr_point: [2, 48], location_status: 'mapped', countries: ['FR'], regions: ['europe-north-america'], source_kind: 'global', chronology_status: 'reviewed' },
  { id: 'auth:fixture:unassigned', title: 'Unassigned province', repr_point: [-79, 43], location_status: 'mapped', countries: ['CA'], regions: ['europe-north-america'], source_kind: 'global', chronology_status: 'reviewed' },
];
const membershipIds: Record<string, string[]> = {
  'CA:ontario': ['auth:ca-dfhd:1', 'auth:ca-dfhd:3'],
  'CA:quebec': ['auth:ca-dfhd:2', 'auth:ca-dfhd:3'],
};
const subset = (id: string) => subdivisionFixture.filter(point => membershipIds[id].includes(point.id));
const subdivisionOptions = (version = 'source-subdivisions-v1') => ({
  ready: true, reason: null, subdivision_version: version, corpus_version: 'global-v3', country: 'CA', supported: true,
  total: 4, assigned: 3, unassigned: 1, subdivisions: [{ id: 'CA:ontario', label: 'Ontario', count: 2 }, { id: 'CA:quebec', label: 'Quebec', count: 2 }],
  note: '按来源对象成员筛选，不是省界，也不证明各来源点的省份。',
});
const subdivisionPage = (id: string, state: Partial<State> = {}, version = 'source-subdivisions-v1') => ({ ...pageFor({ country: 'CA', ...state }, subset(id)), subdivision: id, subdivision_version: version });
const subdivisionCatalogue = (id: string, version = 'source-subdivisions-v1') => ({ corpus_version: 'global-v3', spatial_version: null, total: subset(id).length, points: subset(id), subdivision: id, subdivision_version: version });
const tick = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
function live(app: ReturnType<typeof setup>, path: string) {
  const request = app.pending.find(item => !item.done && !item.signal.aborted && item.url.startsWith(path));
  assert.ok(request, path); return request;
}
async function subdivisionApp() {
  const app = setup(); await app.boot(subdivisionFixture);
  app.controller.configureSubdivisions({ ready: true, reason: null, version: 'source-subdivisions-v1' });
  const country = app.controller.setState({ country: 'CA' }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA' }, subdivisionFixture)); await country; await tick();
  app.response(live(app, '/api/subdivisions?country=CA'), subdivisionOptions()); await tick();
  return app;
}
async function applySubdivision(app: ReturnType<typeof setup>, id: string, state: Partial<State> = {}) {
  const job = app.controller.setState({ subdivision: id, ...state });
  app.response(live(app, '/api/sites'), subdivisionPage(id, state)); await tick();
  app.response(live(app, '/api/catalogue?'), subdivisionCatalogue(id)); await job;
}

test('source province counts support overlap and unassigned objects without altering default country membership', async () => {
  const app = await subdivisionApp();
  assert.match(app.node('explore-count').textContent, /4 条/u);
  assert.match(app.node('explore-subdivision-note').textContent, /3 \/ 4.*1 条未采用.*同一对象可关联多个地区/u);
  assert.equal(app.node('explore-subdivision').disabled, false);
  assert.equal(app.node('explore-subdivision').children[1].textContent, 'Ontario · 2');
  await applySubdivision(app, 'CA:ontario');
  assert.match(app.node('explore-count').textContent, /2 条/u);
  assert.equal(app.node('explore-list').children[1].children[0].dataset.siteId, 'auth:ca-dfhd:3');
  assert.equal(app.node('explore-list').children[1].children[0].dataset.locationStatus, 'unknown');
  assert.equal([...app.map!.layers][0].members.length, 3);
  assert.deepEqual(plain(app.controller.getPoint('auth:fixture:unassigned')), [-79, 43]);
  assert.equal(app.catalogues.length, 1);
  assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:ontario');
  assert.equal(app.controller.getCommittedState()?.subdivision_version, 'source-subdivisions-v1');
  assert.ok(app.pending.every(request => request.url !== '/api/search'));
});

test('an old backend that ignores the province query cannot replace the last successful scoped list or layer', async () => {
  const app = await subdivisionApp(); await applySubdivision(app, 'CA:quebec');
  const layer = [...app.map!.layers][0], successful = plain(app.controller.getCommittedState());
  const job = app.controller.setState({ subdivision: 'CA:ontario' });
  const rejected = assert.rejects(job, /省区.*条件或资料版本/u);
  app.response(live(app, '/api/sites'), subdivisionPage('CA:ontario')); await tick();
  const reply = subdivisionCatalogue('CA:ontario');
  const { subdivision: _ignored, subdivision_version: _version, ...oldApi } = reply;
  app.response(live(app, '/api/catalogue?'), oldApi); await rejected;
  assert.deepEqual(plain(app.controller.getCommittedState()), successful);
  assert.equal([...app.map!.layers][0], layer);
  assert.equal(app.controller.getState().subdivision, 'CA:ontario');
  assert.equal(app.node('explore-list').children[0].children[0].dataset.siteId, 'auth:ca-dfhd:2');
  await applySubdivision(app, 'CA:ontario');
  assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:ontario');
});

test('page and province point versions must match each other and the loaded source options', async () => {
  for (const changed of ['page', 'catalogue']) {
    const app = await subdivisionApp(); await applySubdivision(app, 'CA:quebec');
    const layer = [...app.map!.layers][0];
    const job = app.controller.setState({ subdivision: 'CA:ontario' }); const rejected = assert.rejects(job, /省区.*版本/u);
    app.response(live(app, '/api/sites'), subdivisionPage('CA:ontario', {}, changed === 'page' ? 'changed-v2' : undefined)); await tick();
    app.response(live(app, '/api/catalogue?'), subdivisionCatalogue('CA:ontario', changed === 'catalogue' ? 'changed-v2' : undefined)); await rejected;
    assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:quebec');
    assert.equal([...app.map!.layers][0], layer);
  }
});

test('a filtered point cannot replace original coordinate evidence or add a foreign identity', async () => {
  const app = await subdivisionApp(); await applySubdivision(app, 'CA:quebec');
  const job = app.controller.setState({ subdivision: 'CA:ontario' }); const rejected = assert.rejects(job, /点位身份或原始来源/u);
  app.response(live(app, '/api/sites'), subdivisionPage('CA:ontario')); await tick();
  const reply = subdivisionCatalogue('CA:ontario'); reply.points = reply.points.map((point, index) => index ? point : { ...point, repr_point: [-81, 45] });
  app.response(live(app, '/api/catalogue?'), reply); await rejected;
  assert.deepEqual(plain(app.controller.getPoint('auth:ca-dfhd:1')), [-80, 45]);
  assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:quebec');
});

test('country changes clear desired province and late previous-country options cannot overwrite the new country', async () => {
  const app = setup(); await app.boot(subdivisionFixture);
  app.controller.configureSubdivisions({ ready: true, reason: null, version: 'source-subdivisions-v1' });
  const ca = app.controller.setState({ country: 'CA' }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA' }, subdivisionFixture)); await ca; await tick();
  const old = live(app, '/api/subdivisions?country=CA');
  const fr = app.controller.setState({ country: 'FR' }); app.response(live(app, '/api/sites'), pageFor({ country: 'FR' }, subdivisionFixture)); await fr; await tick();
  app.response(live(app, '/api/subdivisions?country=FR'), { ...subdivisionOptions(), country: 'FR', total: 1, assigned: 0, unassigned: 1, supported: false, subdivisions: [], note: '该国家尚无采用的省区字段。' }); await tick();
  app.response(old, subdivisionOptions()); await tick();
  assert.equal(old.signal.aborted, true);
  assert.equal(app.controller.getState().country, 'FR'); assert.equal(app.controller.getState().subdivision, undefined);
  assert.equal(app.node('explore-subdivision-filter').hidden, true);
  assert.match(app.node('explore-subdivision-note').textContent, /该国家尚无/u);
  assert.equal(app.node('explore-list').children[0].children[0].dataset.siteId, 'auth:fixture:fr');
});

test('a cancelled province response cannot replace a later successful province selection', async () => {
  const app = await subdivisionApp();
  const oldJob = app.controller.setState({ subdivision: 'CA:ontario' }); const oldPage = live(app, '/api/sites');
  const newJob = app.controller.setState({ subdivision: 'CA:quebec' }); app.response(live(app, '/api/sites'), subdivisionPage('CA:quebec')); await tick();
  app.response(live(app, '/api/catalogue?'), subdivisionCatalogue('CA:quebec')); await newJob;
  app.response(oldPage, subdivisionPage('CA:ontario')); await oldJob;
  assert.equal(oldPage.signal.aborted, true); assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:quebec');
});

test('missing subdivision capability retains a successful province snapshot and rejects active search validation', async () => {
  const app = await subdivisionApp(); await applySubdivision(app, 'CA:ontario');
  const successful = plain(app.controller.getCommittedState()), layer = [...app.map!.layers][0];
  app.controller.configureSubdivisions({ ready: false, reason: '请运行 prepare source subdivisions', version: null });
  assert.equal(app.controller.subdivisionReady(), false);
  await assert.rejects(app.controller.validateSearchScope({ country: 'CA', subdivision: 'CA:ontario' }, new AbortController().signal), /尚未就绪/u);
  assert.deepEqual(plain(app.controller.getCommittedState()), successful); assert.equal([...app.map!.layers][0], layer);
  const cleared = app.controller.setState({ subdivision: null }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA' }, subdivisionFixture)); await cleared;
  assert.equal(app.controller.getCommittedState()?.subdivision, undefined); assert.equal(app.controller.subdivisionReady(), true);
});

test('explicit search scope is checked independently without changing desired or committed directory country', async () => {
  const app = await subdivisionApp(); await applySubdivision(app, 'CA:quebec');
  const before = plain(app.controller.getCommittedState());
  const validated = app.controller.validateSearchScope({ country: 'CA', subdivision: 'CA:ontario' }, new AbortController().signal);
  app.response(live(app, '/api/subdivisions?country=CA'), subdivisionOptions());
  assert.equal(await validated, 'source-subdivisions-v1');
  assert.equal(app.controller.getState().subdivision, 'CA:quebec'); assert.deepEqual(plain(app.controller.getCommittedState()), before);
  assert.equal(app.controller.subdivisionLabel('CA:ontario'), 'Ontario');
});

test('province facet failures preserve basic country browsing and keyboard retry keeps a persistent focus target', async () => {
  const app = setup(); await app.boot(subdivisionFixture);
  app.controller.configureSubdivisions({ ready: true, reason: null, version: 'source-subdivisions-v1' });
  const country = app.controller.setState({ country: 'CA' }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA' }, subdivisionFixture)); await country; await tick();
  app.response(live(app, '/api/subdivisions?country=CA'), { detail: 'source unavailable' }, 503); await tick();
  const successful = plain(app.controller.getCommittedState()), layer = [...app.map!.layers][0];
  assert.equal(app.controller.subdivisionReady(), true);
  assert.equal(app.node('explore-subdivision-filter').hidden, true);
  assert.equal(app.node('explore-subdivision-retry').hidden, false);
  app.node('explore-subdivision-retry').focus(); app.node('explore-subdivision-retry').fire('click'); await tick();
  assert.equal(app.doc.activeElement, app.node('explore-subdivision-note'));
  app.response(live(app, '/api/subdivisions?country=CA'), { ...subdivisionOptions(), assigned: 4, unassigned: 0 }); await tick();
  assert.match(app.node('explore-subdivision-note').textContent, /当前国家／地区目录均有采用的来源地区关联/u);
  assert.doesNotMatch(app.node('explore-subdivision-note').textContent, /条未采用/u);
  assert.equal(app.node('explore-subdivision-retry').hidden, true);
  assert.deepEqual(plain(app.controller.getCommittedState()), successful); assert.equal([...app.map!.layers][0], layer);
});

test('changing source province or country resets draft pagination while restored explicit offsets remain valid', async () => {
  const app = await subdivisionApp();
  const offset = app.controller.setState({ offset: 50 }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA', offset: 50 }, subdivisionFixture)); await offset;
  await applySubdivision(app, 'CA:ontario'); assert.equal(app.controller.getState().offset, 0);
  const restored = app.controller.setState({ subdivision: 'CA:quebec', offset: 50 });
  app.response(live(app, '/api/sites'), subdivisionPage('CA:quebec', { offset: 50 })); await tick();
  app.response(live(app, '/api/catalogue?'), subdivisionCatalogue('CA:quebec')); await restored;
  assert.equal(app.controller.getCommittedState()?.offset, 50);
  const fr = app.controller.setState({ country: 'FR' }); app.response(live(app, '/api/sites'), pageFor({ country: 'FR' }, subdivisionFixture)); await fr;
  assert.equal(app.controller.getState().offset, 0); assert.equal(app.controller.getState().subdivision, undefined);
});

test('a registry version change retains the actual earlier snapshot until an explicit successful retry', async () => {
  const app = await subdivisionApp(); await applySubdivision(app, 'CA:ontario');
  const before = plain(app.controller.getCommittedState()), layer = [...app.map!.layers][0];
  app.controller.configureSubdivisions({ ready: true, reason: null, version: 'source-subdivisions-v2' }); await tick();
  assert.equal(app.controller.subdivisionReady(), false);
  app.response(live(app, '/api/subdivisions?country=CA'), subdivisionOptions('source-subdivisions-v2')); await tick();
  assert.deepEqual(plain(app.controller.getCommittedState()), before); assert.equal([...app.map!.layers][0], layer);
  assert.match(app.node('explore-subdivision-note').textContent, /尚未成功应用/u);
  const retry = app.controller.setState({ subdivision: 'CA:ontario' });
  app.response(live(app, '/api/sites'), subdivisionPage('CA:ontario', {}, 'source-subdivisions-v2')); await tick();
  app.response(live(app, '/api/catalogue?'), subdivisionCatalogue('CA:ontario', 'source-subdivisions-v2')); await retry;
  assert.equal(app.controller.getCommittedState()?.subdivision_version, 'source-subdivisions-v2');
});

test('source province membership retains the complete original multi-point object and bbox applies independently', async () => {
  const points = plain(subdivisionFixture);
  for (const point of points) { point.source_points = []; point.source_location_records = []; }
  points[0].source_points = [[-80, 45], [2, 48], [-80, 45]];
  points[0].source_location_records = points[0].source_points.map((coordinate, source_index) => ({ source_index, coordinate, name: `Original location ${source_index}`, ref: `Official ${source_index}` }));
  const metadata = { ...spatial, records: 1, points: 3, distinct_points: 2, duplicate_points: 1, display_points: 5 };
  const members = points.filter(point => membershipIds['CA:ontario'].includes(point.id));
  const app = setup(); await app.boot(points, metadata);
  app.controller.configureSubdivisions({ ready: true, reason: null, version: 'source-subdivisions-v1' });
  const country = app.controller.setState({ country: 'CA' }); app.response(live(app, '/api/sites'), pageFor({ country: 'CA' }, points)); await country; await tick();
  app.response(live(app, '/api/subdivisions?country=CA'), subdivisionOptions()); await tick();
  for (const bbox of [null, [1, 47, 3, 49] as [number, number, number, number]]) {
    const job = app.controller.setState({ subdivision: 'CA:ontario', bbox });
    app.response(live(app, '/api/sites'), { ...pageFor({ country: 'CA', bbox }, members), subdivision: 'CA:ontario', subdivision_version: 'source-subdivisions-v1' }); await tick();
    app.response(live(app, '/api/catalogue?'), { ...subdivisionCatalogue('CA:ontario'), spatial_version: 'world-locations-v1', points: members }); await job;
    assert.deepEqual(plain(app.controller.getSourcePoints(points[0].id)), [[-80, 45], [2, 48], [-80, 45]]);
    assert.equal([...app.map!.layers][0].members.length, bbox ? 3 : 6);
    assert.equal(app.controller.getCommittedState()?.subdivision, 'CA:ontario');
    assert.match(app.node('explore-count').textContent, bbox ? /1 条/u : /2 条/u);
  }
});

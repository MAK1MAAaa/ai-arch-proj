import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';
import ts from 'typescript';

class Element extends EventTarget {
  hidden = false; disabled = false; checked = false; textContent = ''; className = ''; href = ''; target = ''; rel = '';
  style: Record<string, string> = {}; dataset: Record<string, string> = {}; children: Element[] = []; attributes = new Map<string, string>();
  tokens = new Set<string>(); classList = { toggle: (key: string, active?: boolean) => { if (active ?? !this.tokens.has(key)) this.tokens.add(key); else this.tokens.delete(key); }, add: (key: string) => this.tokens.add(key) };
  append(...nodes: Element[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: Element[]): void { this.children = nodes; }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  fire(name: string): void { this.dispatchEvent(new Event(name)); }
  set innerHTML(_value: string) { throw new Error('Unsafe innerHTML'); }
}
class Events {
  listeners = new Map<string, (() => void)[]>();
  on(names: string, callback: () => void): this { for (const name of names.split(' ')) this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]); return this; }
  fire(name: string): this { for (const callback of this.listeners.get(name) ?? []) callback(); return this; }
}
class Layer extends Events {
  layers = new Set<Layer>(); parent: { layers: Set<Layer> } | null = null; element = new Element(); tooltip: Element | null = null;
  location = { lat: 0, lng: 0 }; options: Record<string, unknown>; zIndex = 0;
  constructor(options: Record<string, unknown> = {}) { super(); this.options = options; }
  addTo(parent: { layers: Set<Layer> }): this { this.parent = parent; parent.layers.add(this); return this; }
  remove(): this { this.parent?.layers.delete(this); return this; }
  clearLayers(): this { this.layers.clear(); return this; }
  bindTooltip(element: Element): this { this.tooltip = element; return this; }
  getElement(): Element { return this.element; }
  getLatLng() { return this.location; }
  setLatLng(value: [number, number]): this { this.location = { lat: value[0], lng: value[1] }; return this; }
  setZIndexOffset(value: number): this { this.zIndex = value; return this; }
  setStyle(value: Record<string, unknown>): this { Object.assign(this.options, value); return this; }
  redraw(): this { return this; }
}
interface Bounds { points: [number, number][] }
class MapView extends Events {
  layers = new Set<Layer>(); panes = new Map<string, Element>(); container = new Element(); center = { lat: 20, lng: 0 }; zoom = 1;
  width = 600; height = 400; boundsZoom = 4;
  private measuredWidth = this.width; private measuredHeight = this.height;
  sizeOptions: { pan?: boolean; animate?: boolean }[] = [];
  boundsRead: { points: [number, number][]; padding: { x: number; y: number } } | null = null;
  getPane(name: string) { return this.panes.get(name); }
  createPane(name: string) { const element = new Element(); this.panes.set(name, element); return element; }
  getContainer() { return this.container; }
  getCenter() { return this.center; }
  getZoom() { return this.zoom; }
  getSize() { return { x: this.width, y: this.height }; }
  setView(center: [number, number], zoom: number): this {
    const zoomChanged = this.zoom !== zoom, moved = this.center.lat !== center[0] || this.center.lng !== center[1];
    this.center = { lat: center[0], lng: center[1] }; this.zoom = zoom;
    if (zoomChanged) this.fire('zoomend');
    if (zoomChanged || moved) this.fire('moveend');
    return this;
  }
  getBoundsZoom(bounds: Bounds, _inside: boolean, padding: { x: number; y: number }): number { this.boundsRead = { points: bounds.points, padding }; return this.boundsZoom; }
  fitBounds(bounds: Bounds, options: { maxZoom: number }): this {
    const coordinates=bounds.points, latitudes=coordinates.map(p=>p[0]), longitudes=coordinates.map(p=>p[1]);
    return this.setView([(Math.min(...latitudes)+Math.max(...latitudes))/2,(Math.min(...longitudes)+Math.max(...longitudes))/2],Math.min(this.boundsZoom,options.maxZoom));
  }
  stop(): void { /* deterministic synchronous fake */ }
  invalidateSize(options: { pan?: boolean; animate?: boolean }): void {
    this.sizeOptions.push(options);
    const changed=this.measuredWidth!==this.width||this.measuredHeight!==this.height;
    this.measuredWidth=this.width; this.measuredHeight=this.height;
    if (changed) this.fire('moveend');
  }
  hasLayer(layer: Layer) { return this.layers.has(layer); }
  removeLayer(layer: Layer): this { this.layers.delete(layer); return this; }
}
interface State { modern_basemap: 'osm' | 'natural'; sync_centers: boolean; modern_view: { center: [number, number]; zoom: number } | null; history_view: { center: [number, number]; zoom: number } | null }
interface Selected { id: string; title: string; repr_point: [number, number] | null; status: string; phase: { label: string; precision: string; start_year: number | null; end_year: number | null; sources: { title: string; uri: string; excerpt: string }[] } | null }
interface Frame { year: number; boundaries: boolean; frame_id: string | null; source_version: string | null }
interface Controller {
  setCandidates(values: { id: string; title: string; repr_point: [number, number] | null; rank: number }[], fit?: boolean): void;
  setCatalogue(values: { id: string; title: string; coordinate: [number, number]; representative: boolean }[], visible: boolean): void;
  setSelection(value: Selected | null, focus?: boolean): void; setModernBasemap(value: 'osm' | 'natural'): void;
  focusSelected(options?: { preserveCamera?: boolean }): boolean;
  getMarker(id: string): Layer | null; restoreInitialViews(): void; noteInteraction(): void; actionVersion(): number;
  getHistoricalRenderer(): object | null;
  state(): State; snapshot(value: Frame | null): { layout: string; modern: { role: string; basemap: string }; historical: { role: string; year: number | null; source_version: string | null } };
}
interface Helpers { create(options: { modern: MapView; historical: MapView; tiles: Layer; initial: State; onSelect(id: string, opener: Element | null, options?: { moveMap?: boolean }): void; onChanged(): void; onEvidence(): void }): Controller }
const scripts = ['map-view', 'history', 'comparison'].map(name => ts.transpileModule(readFileSync(`src/archsearch/frontend/${name}.ts`, 'utf8'), { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2022 } }).outputText).join('\n');
const land = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 0]]] } }] };
function harness(initial: Partial<State> = {}, small = false) {
  const ids = ['modern-basemap-osm', 'modern-basemap-natural', 'comparison-sync', 'comparison-modern-status', 'tile-warning', 'tile-warning-text', 'comparison-evidence', 'comparison-evidence-title', 'comparison-evidence-date', 'comparison-evidence-quote', 'comparison-evidence-sources', 'comparison-evidence-open'];
  const nodes = new Map(ids.map(id => [id, new Element()])); const pending: ((value: { ok: boolean; json(): Promise<unknown> }) => void)[] = [];
  const circles: Layer[] = []; const selected: string[] = []; const selectionOptions: ({ moveMap?: boolean } | undefined)[] = []; let changes = 0;
  const resizeCallbacks: (() => void)[] = [];
  const context = createContext({ URL, Error, window: { matchMedia: () => ({ matches: small }) },
    ResizeObserver: class { constructor(callback: () => void) { resizeCallbacks.push(callback); } observe(_element: Element): void {} },
    document: { getElementById: (id: string) => nodes.get(id), createElement: () => new Element() },
    fetch: () => new Promise(resolve => pending.push(resolve)),
    L: { canvas: (options: object) => ({ ...options }), geoJSON: (_value: unknown, options: Record<string, unknown>) => new Layer(options), layerGroup: () => new Layer(),
      marker: (coordinate: [number, number], options: Record<string, unknown>) => new Layer(options).setLatLng(coordinate), divIcon: (value: unknown) => value,
      circleMarker: (coordinate: [number, number], options: Record<string, unknown>) => { const layer = new Layer(options).setLatLng(coordinate); circles.push(layer); return layer; },
      latLngBounds: (points: [number, number][]) => ({points}), point: (x: number, y: number) => ({x,y}) },
  });
  const helper = runInContext(scripts+'\nArchSearchComparison;', context) as Helpers;
  const modern = new MapView(), historical = new MapView(), tiles = new Layer(); tiles.addTo(modern);
  const controller = helper.create({ modern, historical, tiles, initial: { modern_basemap: 'osm', sync_centers: false, modern_view: null, history_view: null, ...initial }, onSelect: (id, _opener, options) => { selected.push(id); selectionOptions.push(options); }, onChanged: () => { changes++; }, onEvidence: () => undefined });
  return { controller, modern, historical, tiles, circles, pending, selected, selectionOptions, node: (id: string) => nodes.get(id)!, changes: () => changes, resize: () => resizeCallbacks.forEach(callback => callback()) };
}
async function tick() { for (let i=0;i<20;i++) await Promise.resolve(); }
async function completeLand(h: ReturnType<typeof harness>, value: unknown = land) { h.pending[0]({ ok: true, json: async () => value }); await tick(); }
const selectedSite: Selected = { id: 'auth:fixture:church', title: '<b>Church reference</b>', repr_point: [-1.71, 52.18], status: 'reviewed', phase: { label: 'Source burial event', precision: 'exact_year', start_year: 1616, end_year: 1616, sources: [{ title: 'Official source', uri: 'https://source.example/evidence', excerpt: 'Recorded burial event, not construction.' }] } };

test('candidate selection locates both map roles at the same regional scale', () => {
  const h=harness(); h.modern.setView([52.18,-1.71],15);
  h.controller.setCandidates([{ id:selectedSite.id,title:selectedSite.title,repr_point:selectedSite.repr_point,rank:1 }]);
  h.controller.setSelection(selectedSite,true);
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  assert.equal(h.controller.getMarker(selectedSite.id)?.getLatLng().lat,52.18);
  assert.equal(h.node('comparison-evidence-title').textContent,'<b>Church reference</b>');
  assert.match(h.node('comparison-evidence-date').textContent,/1616/u);
  h.controller.getMarker(selectedSite.id)?.fire('click'); assert.deepEqual(h.selected,[selectedSite.id]);
});
test('zoom always stays paired while center synchronization remains optional and bidirectional', () => {
  const h=harness(); h.modern.setView([40,2],15); h.historical.setView([50,8],4);
  assert.equal(h.modern.getCenter().lng,2); assert.deepEqual(h.selected,[]);
  h.node('comparison-sync').checked=true; h.node('comparison-sync').fire('change');
  h.modern.setView([42,12],7); assert.equal(h.historical.getCenter().lng,12); assert.equal(h.historical.getZoom(),7);
  h.historical.setView([51,-2],3); assert.equal(h.modern.getCenter().lng,-2); assert.equal(h.modern.getZoom(),3);
  h.node('comparison-sync').checked=false; h.node('comparison-sync').fire('change');
  h.historical.setView([61,9],6); assert.equal(h.modern.getCenter().lng,-2); assert.equal(h.modern.getZoom(),6);
});
test('tile failure falls back to local land without changing history year or either camera', async () => {
  const h=harness(); h.tiles.fire('tileerror'); await completeLand(h);
  assert.equal(h.controller.state().modern_basemap,'natural'); assert.equal(h.modern.hasLayer(h.tiles),false);
  const snapshot=h.controller.snapshot({year:1616,boundaries:true,frame_id:'real-frame',source_version:'v0.2.1'});
  assert.equal(snapshot.modern.basemap,'natural'); assert.equal(snapshot.historical.year,1616); assert.equal(snapshot.historical.source_version,'v0.2.1');
  assert.equal(h.modern.getCenter().lng,0); assert.equal(h.historical.getCenter().lng,0);
});
test('an explicit natural base ignores errors from old OSM tiles and can retry OSM later', async () => {
  const h=harness({modern_basemap:'natural'}); await completeLand(h); h.tiles.fire('tileerror');
  assert.equal(h.node('tile-warning').hidden,true);
  h.controller.setModernBasemap('osm'); assert.equal(h.modern.hasLayer(h.tiles),true); h.tiles.fire('tileload');
  assert.equal(h.controller.snapshot(null).modern.basemap,'osm');
});
test('source placements preserve coordinates and world copies in a pane above historical polygons', () => {
  const h=harness(); const values=[{id:'auth:fixture:coast',title:'Source reference',coordinate:[179,-18] as [number,number],representative:false}];
  h.controller.setCatalogue(values,true); assert.equal(h.circles.length,3);
  assert.deepEqual(h.circles.map(circle=>circle.getLatLng().lng),[-181,179,539]);
  assert.equal(h.historical.panes.get('history-boundaries')?.style.zIndex,'350');
  assert.equal(h.historical.panes.has('comparison-source-points'),false);
  assert.ok(h.circles.every(circle=>circle.options.renderer===h.controller.getHistoricalRenderer()));
  h.circles[1].fire('click'); assert.deepEqual(h.selected,['auth:fixture:coast']);
  assert.deepEqual(JSON.parse(JSON.stringify(h.selectionOptions)), [{moveMap:false}]);
  h.controller.setCatalogue(values,true); assert.equal(h.circles.length,3);
  assert.deepEqual(values[0].coordinate,[179,-18]);
});
test('unknown coordinates do not create zero markers and unknown dates retain their state', () => {
  const h=harness(); h.controller.setCandidates([{id:'unknown',title:'Unknown',repr_point:null,rank:1}]);
  h.controller.setSelection({...selectedSite,id:'unknown',repr_point:null,status:'not_reviewed',phase:null},true);
  assert.equal(h.controller.getMarker('unknown'),null); assert.match(h.node('comparison-evidence-date').textContent,/尚无经过核验/u);
  assert.equal(h.historical.getZoom(),1);
});
test('restored camera views do not overwrite a later user map action', () => {
  const h=harness({modern_view:{center:[-1.7,52.18],zoom:15},history_view:{center:[-1.7,52.18],zoom:4}});
  h.modern.container.fire('pointerdown'); h.modern.setView([60,10],8); h.historical.setView([35,30],3);
  h.controller.restoreInitialViews(); assert.equal(h.modern.getCenter().lng,10); assert.equal(h.historical.getCenter().lng,30);
  assert.equal(h.modern.getZoom(),3); assert.equal(h.historical.getZoom(),3);
  assert.ok(h.controller.actionVersion()>0);
});
test('export layout reports the actual stacked mobile arrangement and distinct map roles', () => {
  const h=harness({},true); const snapshot=h.controller.snapshot(null);
  assert.equal(snapshot.layout,'stacked'); assert.equal(snapshot.modern.role,'modern-location'); assert.equal(snapshot.historical.role,'historical-polities'); assert.equal(snapshot.historical.year,null);
});
test('failed local natural data does not claim a successful fallback', async () => {
  const h=harness(); h.tiles.fire('tileerror'); await completeLand(h,{type:'FeatureCollection',features:[{}]});
  assert.equal(h.controller.snapshot(null).modern.basemap,'unavailable'); assert.match(h.node('tile-warning-text').textContent,/未能读取/u);
});

test('saved camera centers stay within the projection without modifying site source coordinates', () => {
  const h=harness(); h.modern.setView([91,540],15); h.historical.setView([-95,-541],4);
  assert.deepEqual(JSON.parse(JSON.stringify(h.controller.state().modern_view?.center)),[180,85.0511287798]);
  assert.deepEqual(JSON.parse(JSON.stringify(h.controller.state().history_view?.center)),[179,-85.0511287798]);
  assert.deepEqual(selectedSite.repr_point,[-1.71,52.18]);
});

test('range and approximate evidence retain explicit uncertainty without offering a chosen year', () => {
  const h = harness();
  for (const precision of ['range', 'period', 'approximate_year']) {
    h.controller.setSelection({...selectedSite,phase:{...selectedSite.phase!,precision,start_year:1500,end_year:1650}});
    assert.match(h.node('comparison-evidence-date').textContent,/来源阶段.*1500.*1650.*实际背景见右图/u);
    assert.doesNotMatch(h.node('comparison-evidence-date').textContent,/自动联动|保留最后成功/u);
    assert.doesNotMatch(h.node('comparison-evidence-date').textContent,/选择观察年份/u);
    assert.equal(h.historical.getZoom(),1);
  }
});

test('explicit locate focuses both map roles while preserved or unavailable selections keep their cameras', () => {
  const h = harness(); h.modern.setView([30,12],18); h.historical.setView([40,22],7);
  h.controller.setSelection(selectedSite);
  assert.equal(h.controller.focusSelected({preserveCamera:true}),false);
  assert.equal(h.modern.getZoom(),7); assert.equal(h.historical.getZoom(),7); assert.equal(h.controller.actionVersion(),0);
  assert.equal(h.controller.focusSelected(),true);
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  assert.equal(h.modern.getCenter().lng,-1.71); assert.equal(h.historical.getCenter().lng,-1.71);
  assert.ok(h.controller.actionVersion()>0);
  h.controller.setSelection({...selectedSite,repr_point:null}); const before = h.controller.actionVersion();
  assert.equal(h.controller.focusSelected(),false); assert.equal(h.controller.actionVersion(),before);
});

test('source-point selection preserves the clicked view but numbered candidates keep normal locating', () => {
  const h = harness(); h.controller.setCatalogue([{id:'source',title:'Component',coordinate:[20,10],representative:false}],true);
  h.circles[1].fire('click'); assert.deepEqual(JSON.parse(JSON.stringify(h.selectionOptions)),[{moveMap:false}]);
  h.controller.setCandidates([{id:selectedSite.id,title:selectedSite.title,repr_point:selectedSite.repr_point,rank:1}],false);
  h.controller.getMarker(selectedSite.id)?.fire('click'); assert.equal(h.selectionOptions.at(-1),undefined);
});

test('legacy different zooms align to the historical view while preserving both saved centers', () => {
  const h=harness({sync_centers:true,modern_view:{center:[12,48],zoom:15},history_view:{center:[30,20],zoom:4}});
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  assert.deepEqual(h.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(h.historical.getCenter(),{lat:20,lng:30});
  assert.match(h.node('comparison-modern-status').textContent,/旧链接缩放已统一为 4 级.*分别保留两图中心/u);
  h.controller.restoreInitialViews();
  assert.deepEqual(h.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(h.historical.getCenter(),{lat:20,lng:30});
  h.modern.container.fire('pointerdown'); h.modern.setView([47,13],5);
  assert.equal(h.historical.getZoom(),5); assert.equal(h.historical.getCenter().lng,13);
  assert.doesNotMatch(h.node('comparison-modern-status').textContent,/旧链接缩放/u);
});

test('a sole saved modern zoom is clamped to the common range and a sole history zoom applies to both', () => {
  const modern=harness({modern_view:{center:[12,48],zoom:15}});
  assert.equal(modern.modern.getZoom(),9); assert.equal(modern.historical.getZoom(),9);
  assert.deepEqual(modern.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(modern.historical.getCenter(),{lat:20,lng:0});
  assert.match(modern.node('comparison-modern-status').textContent,/旧链接缩放已统一为 9 级/u);
  const history=harness({history_view:{center:[30,20],zoom:7}});
  assert.equal(history.modern.getZoom(),7); assert.equal(history.historical.getZoom(),7);
  assert.deepEqual(history.modern.getCenter(),{lat:20,lng:0}); assert.deepEqual(history.historical.getCenter(),{lat:20,lng:30});
  assert.doesNotMatch(history.node('comparison-modern-status').textContent,/旧链接缩放/u);
});

test('zoom changes submit one complete paired camera state without nested save notifications', () => {
  const h=harness(); const initial=h.changes();
  h.modern.setView([40,2],7);
  assert.equal(h.modern.getZoom(),7); assert.equal(h.historical.getZoom(),7); assert.equal(h.changes()-initial,1);
  assert.deepEqual(h.historical.getCenter(),{lat:20,lng:0});
  h.historical.setView([50,8],3);
  assert.equal(h.modern.getZoom(),3); assert.equal(h.changes()-initial,2);
  h.node('comparison-sync').checked=true; h.node('comparison-sync').fire('change');
  assert.equal(h.changes()-initial,3); assert.deepEqual(h.historical.getCenter(),h.modern.getCenter());
});

test('shared zoom range is enforced from either map even when centers are independent', () => {
  const h=harness(); h.modern.setView([40,2],18);
  assert.equal(h.modern.getZoom(),9); assert.equal(h.historical.getZoom(),9); assert.equal(h.historical.getCenter().lng,0);
  h.historical.setView([50,8],-2);
  assert.equal(h.modern.getZoom(),1); assert.equal(h.historical.getZoom(),1); assert.equal(h.modern.getCenter().lng,2);
});

test('layout resizing preserves separate saved centers even with center sync enabled', () => {
  const h=harness({sync_centers:true,modern_view:{center:[12,48],zoom:4},history_view:{center:[30,20],zoom:4}});
  h.modern.width=840; h.historical.width=840; h.resize();
  assert.deepEqual(h.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(h.historical.getCenter(),{lat:20,lng:30});
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  assert.deepEqual(JSON.parse(JSON.stringify(h.modern.sizeOptions.at(-1))),{pan:true,animate:false});
  h.modern.setView([49,13],5); assert.deepEqual(h.historical.getCenter(),{lat:49,lng:13});
  assert.equal(h.historical.getZoom(),5);
});

test('late camera restoration cannot split views already synchronized by a user action', () => {
  const h=harness({sync_centers:true,modern_view:{center:[12,48],zoom:4},history_view:{center:[30,20],zoom:4}});
  h.modern.container.fire('pointerdown'); h.modern.setView([47,13],5);
  assert.deepEqual(h.modern.getCenter(),{lat:47,lng:13}); assert.deepEqual(h.historical.getCenter(),{lat:47,lng:13});
  h.controller.restoreInitialViews();
  assert.deepEqual(h.modern.getCenter(),{lat:47,lng:13}); assert.deepEqual(h.historical.getCenter(),{lat:47,lng:13});
  assert.equal(h.modern.getZoom(),5); assert.equal(h.historical.getZoom(),5);
});

test('changing center synchronization is a user camera action that blocks late restoration', () => {
  const h=harness({sync_centers:false,modern_view:{center:[12,48],zoom:15},history_view:{center:[30,20],zoom:4}});
  const version=h.controller.actionVersion();
  assert.match(h.node('comparison-modern-status').textContent,/旧链接缩放/u);
  h.node('comparison-sync').checked=true; h.node('comparison-sync').fire('change');
  assert.equal(h.controller.actionVersion(),version+1);
  assert.equal(h.controller.state().sync_centers,true);
  assert.deepEqual(h.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(h.historical.getCenter(),{lat:48,lng:12});
  assert.doesNotMatch(h.node('comparison-modern-status').textContent,/旧链接缩放/u);
  h.controller.restoreInitialViews();
  assert.deepEqual(h.modern.getCenter(),{lat:48,lng:12}); assert.deepEqual(h.historical.getCenter(),{lat:48,lng:12});
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  h.node('comparison-sync').checked=false; h.node('comparison-sync').fire('change');
  assert.equal(h.controller.actionVersion(),version+2);
  h.controller.restoreInitialViews();
  assert.deepEqual(h.historical.getCenter(),{lat:48,lng:12});
});

test('fit uses the smaller available scale and a shared wrapped bounds center for both maps', () => {
  const h=harness(); h.modern.boundsZoom=4; h.historical.boundsZoom=3;
  h.controller.setCandidates([
    {id:'west',title:'West',repr_point:[179,10],rank:1},
    {id:'east',title:'East',repr_point:[-179,12],rank:2},
    {id:'missing',title:'No point',repr_point:null,rank:3},
  ]);
  assert.equal(h.modern.getZoom(),3); assert.equal(h.historical.getZoom(),3);
  assert.equal(h.modern.getCenter().lat,11); assert.equal(h.historical.getCenter().lat,11);
  assert.equal(Math.abs(h.modern.getCenter().lng),180); assert.equal(Math.abs(h.historical.getCenter().lng),180);
  assert.equal(Math.abs(h.historical.getCenter().lng-h.modern.getCenter().lng)%360,0);
  const longitudes=h.modern.boundsRead!.points.map(p=>p[1]); assert.equal(Math.max(...longitudes)-Math.min(...longitudes),2);
  assert.deepEqual(JSON.parse(JSON.stringify(h.modern.boundsRead?.padding)),{x:70,y:70});
});

test('no mapped candidates reset both maps to the same global reference', () => {
  const h=harness(); h.modern.setView([40,2],7); h.historical.setView([50,8],7);
  h.controller.setCandidates([{id:'missing',title:'No point',repr_point:null,rank:1}]);
  assert.deepEqual(h.modern.getCenter(),{lat:20,lng:0}); assert.deepEqual(h.historical.getCenter(),{lat:20,lng:0});
  assert.equal(h.modern.getZoom(),1); assert.equal(h.historical.getZoom(),1);
});

test('camera restoration without saved views does not reset a newly fitted result scale', () => {
  const h=harness();
  h.controller.setCandidates([{id:selectedSite.id,title:selectedSite.title,repr_point:selectedSite.repr_point,rank:1}]);
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
  h.controller.restoreInitialViews();
  assert.equal(h.modern.getZoom(),4); assert.equal(h.historical.getZoom(),4);
});

test('paired camera changes still wrap historical numbered markers across the date line', () => {
  const h=harness();
  h.controller.setCandidates([
    {id:'west',title:'West',repr_point:[179,10],rank:1},
    {id:'east',title:'East',repr_point:[-179,12],rank:2},
  ],false);
  h.controller.setSelection({...selectedSite,id:'west',repr_point:[179,10]},true);
  assert.equal(h.historical.getCenter().lng,179);
  assert.equal(h.controller.getMarker('east')!.getLatLng().lng,181);
  assert.equal(h.controller.getMarker('west')!.getLatLng().lng,179);
});

test('source phase evidence does not claim a retained or linked background matches the event year', () => {
  const h=harness(); h.controller.setSelection(selectedSite);
  const snapshot=h.controller.snapshot({year:1930,boundaries:true,frame_id:'saved-1930',source_version:'v0.2.1'});
  assert.equal(snapshot.historical.year,1930);
  assert.match(h.node('comparison-evidence-date').textContent,/来源阶段.*1616.*明确单年事件.*实际背景见右图/u);
  assert.doesNotMatch(h.node('comparison-evidence-date').textContent,/自动联动/u);
});

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface State { state: 'loading' | 'ready' | 'error' | 'unavailable'; message: string; visible: boolean; sourceVersion: string | null }
interface Controller { retry(): Promise<void>; getState(): State }
interface Feature { type: 'Feature'; properties: { record_id: number; source_id: number; classification: string }; geometry: { type: string; coordinates: number[][] | number[][][] } }
interface Collection { type: string; features: Feature[]; metadata: { schema_version: number; feature_count: number; source: { name: string; version: string; uri: string; license: string } } }
interface Options { pane: string; renderer: object; interactive: boolean; attribution: string; style(feature: Feature): { weight: number; fill: boolean; interactive: boolean; dashArray?: string; color: string } }
interface Helpers { create(options: { map: FakeMap | null; onStatus?(state: State): void }): Controller; parse(value: unknown): Collection; worldCopies(value: Collection): Collection; style(value: string, halo?: boolean): { color: string; weight: number; fill: boolean; interactive: boolean; dashArray?: string } }
interface Reply { ok: boolean; json(): Promise<unknown> }
class FakeMap {
  panes = new Map<string, { style: Record<string, string> }>();
  layers = new Set<Layer>();
  getPane(name: string) { return this.panes.get(name); }
  createPane(name: string) { const pane = { style: {} }; this.panes.set(name, pane); return pane; }
}
class Layer {
  map: FakeMap | null = null;
  readonly data: Collection;
  readonly options: Options;
  readonly fail: boolean;
  constructor(data: Collection, options: Options, fail: boolean) { this.data = data; this.options = options; this.fail = fail; }
  addTo(map: FakeMap): this { if (this.fail) throw new Error('fixture renderer failure'); this.map = map; map.layers.add(this); return this; }
  remove(): this { this.map?.layers.delete(this); this.map = null; return this; }
}
const fixture: Collection = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { record_id: 1, source_id: 42, classification: 'International boundary (verify)' }, geometry: { type: 'LineString', coordinates: [[179, 20], [180, 21]] } },
    { type: 'Feature', properties: { record_id: 2, source_id: 42, classification: 'Disputed (please verify)' }, geometry: { type: 'MultiLineString', coordinates: [[[20, 30], [21, 31]], [[22, 32], [23, 33]]] } },
  ],
  metadata: { schema_version: 1, feature_count: 2, source: { name: 'Natural Earth 1:50m Admin 0 land boundary lines', version: '5.1.0', uri: 'https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-boundary-lines-2/', license: 'Public domain' } },
};
const clone = <T>(value: T): T => structuredClone(value);
const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const script = ts.transpileModule(readFileSync(new URL('../../src/archsearch/frontend/modern-boundaries.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2022 } }).outputText;

function harness(withMap = true) {
  const pending: { url: string; resolve(value: Reply): void; reject(reason: Error): void }[] = [];
  const layers: Layer[] = [], statuses: State[] = [];
  let failIndex = -1;
  const helpers = runInContext(script + '\nArchSearchModernBoundaries;', createContext({
    Set, Number, Array, Error,
    fetch: (url: string) => new Promise<Reply>((resolve, reject) => pending.push({ url, resolve, reject })),
    L: { canvas: (value: object) => ({ ...value }), geoJSON: (data: Collection, options: Options) => { const layer = new Layer(data, options, layers.length === failIndex); layers.push(layer); return layer; } },
  })) as Helpers;
  const map = new FakeMap();
  const controller = helpers.create({ map: withMap ? map : null, onStatus: value => statuses.push(value) });
  const reply = async (index = pending.length - 1, value: unknown = clone(fixture), ok = true) => { pending[index].resolve({ ok, json: async () => value }); await controller.retry(); };
  return { helpers, map, controller, pending, layers, statuses, reply, failLayer(index: number) { failIndex = index; } };
}

test('local modern line data is pinned, traceable and preserves every source line and uncertain classification', () => {
  const bytes = readFileSync(new URL('../../src/archsearch/static/data/modern-boundaries.geojson', import.meta.url));
  const manifest = JSON.parse(readFileSync(new URL('../../src/archsearch/static/data/modern-boundaries-source.json', import.meta.url), 'utf8')) as { sha256: string; feature_count: number; distinct_source_ids: number; point_count: number; line_count: number; classification_counts: Record<string, number>; source: { version: string; commit: string; geojson_uri: string; archive_sha256: string; license: string } };
  assert.equal(createHash('sha256').update(bytes).digest('hex'), manifest.sha256);
  assert.equal(manifest.source.version, '5.1.0'); assert.equal(manifest.source.license, 'Public domain');
  assert.match(manifest.source.geojson_uri, new RegExp(manifest.source.commit));
  assert.equal(manifest.source.archive_sha256, '02f369ae10578c4ce33fc4a08f8cdd69ea11eb39b44d7923e88eb7199aaff8ea');
  const h = harness(false); const value = h.helpers.parse(JSON.parse(bytes.toString('utf8')));
  assert.equal(value.features.length, 390); assert.equal(new Set(value.features.map(f => f.properties.record_id)).size, 390);
  assert.equal(new Set(value.features.map(f => f.properties.source_id)).size, 382);
  let points = 0, lines = 0;
  for (const feature of value.features) {
    const values = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates as number[][]] : feature.geometry.coordinates as number[][][];
    lines += values.length; points += values.reduce((count, line) => count + line.length, 0);
  }
  assert.equal(lines, 393); assert.equal(points, 19859); assert.equal(manifest.point_count, points); assert.equal(manifest.line_count, lines);
  assert.deepEqual(manifest.classification_counts, { 'Disputed (please verify)': 21, 'International boundary (verify)': 355, 'Line of control (please verify)': 7, 'Indefinite (please verify)': 5, 'Indeterminant frontier': 2 });
});

test('world copies preserve source coordinates and both LineString and MultiLineString segments', () => {
  const h = harness(false), original = clone(fixture); const result = h.helpers.worldCopies(h.helpers.parse(fixture));
  assert.equal(result.features.length, 6); assert.deepEqual(fixture, original);
  assert.deepEqual(plain(result.features[0].geometry.coordinates), [[-181, 20], [-180, 21]]);
  assert.deepEqual(plain(result.features[3].geometry.coordinates), fixture.features[1].geometry.coordinates);
  assert.deepEqual(plain(result.features[5].geometry.coordinates), [[[380, 30], [381, 31]], [[382, 32], [383, 33]]]);
});

test('source repeated NE_ID records remain distinct, while duplicate record identities are rejected', () => {
  const h = harness(false); assert.equal(h.helpers.parse(fixture).features.length, 2);
  const value = clone(fixture); value.features[1].properties.record_id = 1;
  assert.throws(() => h.helpers.parse(value), /来源分类|几何/u);
});

test('wrong versions, polygon fills, zero-length lines and cross-world jumps never replace a valid line collection', () => {
  const h = harness(false);
  const cases: Collection[] = [];
  const version = clone(fixture); version.metadata.source.version = 'new'; cases.push(version);
  const count = clone(fixture); count.metadata.feature_count = 9; cases.push(count);
  const polygon = clone(fixture); polygon.features[0].geometry.type = 'Polygon'; cases.push(polygon);
  const short = clone(fixture); short.features[0].geometry.coordinates = [[1, 1]]; cases.push(short);
  const jump = clone(fixture); jump.features[0].geometry.coordinates = [[179, 10], [-179, 11]]; cases.push(jump);
  const nan = clone(fixture); nan.features[0].geometry.coordinates = [[Number.NaN, 0], [1, 1]]; cases.push(nan);
  const unknown = clone(fixture); unknown.features[0].properties.classification = 'assumed sovereign border'; cases.push(unknown);
  for (const value of cases) assert.throws(() => h.helpers.parse(value));
});

test('halo and source-classified ink load above all basemaps, below source points and without intercepting events', async () => {
  const h = harness(); assert.equal(h.pending[0].url, '/static/data/modern-boundaries.geojson');
  const first = h.controller.retry(); assert.equal(first, h.controller.retry()); assert.equal(h.pending.length, 1);
  await h.reply(); await first;
  assert.equal(h.controller.getState().state, 'ready'); assert.equal(h.controller.getState().visible, true);
  assert.equal(h.map.layers.size, 2); assert.equal(h.map.panes.get('modern-country-boundaries')?.style.zIndex, '320');
  assert.equal(h.map.panes.get('modern-country-boundaries')?.style.pointerEvents, 'none');
  assert.equal(h.layers[0].data.features.length, 6); assert.equal(h.layers[0].options.renderer, h.layers[1].options.renderer);
  for (const layer of h.layers) { assert.equal(layer.options.interactive, false); assert.match(layer.options.attribution, /Natural Earth/u); }
  const halo = h.layers[0].options.style(fixture.features[0]), ink = h.layers[1].options.style(fixture.features[0]);
  assert.ok(halo.weight > ink.weight); assert.equal(halo.fill, false); assert.equal(ink.interactive, false); assert.equal(ink.dashArray, undefined);
  assert.equal(h.layers[1].options.style(fixture.features[1]).dashArray, '5 4');
});

test('failed initial load leaves both maps and markers usable and can retry locally', async () => {
  const h = harness(); await h.reply(0, {}, false);
  assert.equal(h.controller.getState().state, 'error'); assert.equal(h.controller.getState().visible, false); assert.equal(h.map.layers.size, 0);
  assert.match(h.controller.getState().message, /历史图仍可使用/u);
  const retry = h.controller.retry(); assert.equal(h.pending.length, 2); await h.reply(1); await retry;
  assert.equal(h.controller.getState().state, 'ready'); assert.equal(h.map.layers.size, 2);
});

test('invalid refresh and partial renderer failure retain the previously successful border layer', async () => {
  const h = harness(); await h.reply(); const original = [...h.map.layers];
  const failed = h.controller.retry(); await h.reply(1, { type: 'FeatureCollection', features: [] }); await failed;
  assert.deepEqual([...h.map.layers], original); assert.equal(h.controller.getState().visible, true);
  assert.match(h.controller.getState().message, /保留已加载/u);
  h.failLayer(3); const render = h.controller.retry(); await h.reply(2); await render;
  assert.deepEqual([...h.map.layers], original); assert.equal(h.controller.getState().state, 'error');
  const success = h.controller.retry(); await h.reply(3); await success;
  assert.equal(h.map.layers.size, 2); assert.ok([...h.map.layers].every(layer => !original.includes(layer)));
});

test('a missing map makes no network request and status snapshots cannot mutate controller state', () => {
  const absent = harness(false); assert.equal(absent.pending.length, 0); assert.equal(absent.controller.getState().state, 'unavailable');
  const h = harness(); const state = h.controller.getState(); state.state = 'ready'; state.visible = true;
  assert.equal(h.controller.getState().state, 'loading'); assert.equal(h.controller.getState().visible, false);
});

test('rebuild refuses unpinned caches or invalid arguments without changing bundled data and without downloads', () => {
  const asset = new URL('../../src/archsearch/static/data/modern-boundaries.geojson', import.meta.url);
  const before = readFileSync(asset);
  const directory = mkdtempSync(join(tmpdir(), 'archsearch-modern-boundaries-'));
  const script = fileURLToPath(new URL('../build-modern-boundaries.ts', import.meta.url));
  try {
    writeFileSync(join(directory, 'source.geojson'), JSON.stringify(fixture));
    const bad = spawnSync(process.execPath, ['--experimental-strip-types', script, '--source-cache', directory], { encoding: 'utf8' });
    assert.notEqual(bad.status, 0); assert.match(bad.stderr, /Source checksum mismatch: source.geojson/u);
    const unknown = spawnSync(process.execPath, ['--experimental-strip-types', script, '--invalid-argument'], { encoding: 'utf8' });
    assert.notEqual(unknown.status, 0); assert.match(unknown.stderr, /Usage:/u);
    assert.deepEqual(readFileSync(asset), before);
  } finally {
    const insideTemp = relative(resolve(tmpdir()), resolve(directory));
    assert.ok(insideTemp && !isAbsolute(insideTemp) && insideTemp.startsWith('archsearch-modern-boundaries-') && !insideTemp.startsWith('..'));
    rmSync(directory, { recursive: true });
  }
});

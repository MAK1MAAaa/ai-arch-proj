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

interface CountryProperties {
  record_id: number;
  source_id: number;
  name: string;
  name_zh: string;
  formal_en: string;
  iso_a2: string;
  continent: string;
  subregion: string;
  type: string;
  wikidata_id: string;
}
interface CountryFeature {
  type: 'Feature';
  properties: CountryProperties;
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: number[][][] | number[][][][] };
}
interface Collection {
  type: 'FeatureCollection';
  features: CountryFeature[];
  metadata: { schema_version: number; feature_count: number; source: { name: string; version: string; uri: string; license: string; license_uri?: string } };
}
interface Helpers {
  create(options: { map: FakeMap | null; hoverDelayMs?: number }): { refreshStyles(): void; clearHoverPreview(): void };
  parse(value: unknown): Collection;
  worldCopies(value: Collection): Collection;
  style(naturalMode: boolean, hovered?: boolean): Record<string, unknown>;
}
interface GeoOptions {
  pane?: string;
  renderer?: object;
  interactive?: boolean;
  style?: () => Record<string, unknown>;
  onEachFeature?: (feature: CountryFeature, layer: FakeLayer) => void;
}
class FakeElement extends EventTarget {
  tagName: string;
  className = '';
  textContent = '';
  children: FakeElement[] = [];
  href = ''; target = ''; rel = '';
  dataset: Record<string, string> = {};
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  append(...nodes: FakeElement[]): void { this.children.push(...nodes); }
}
class FakePopup {
  map: FakeMap | null = null;
  latlng: { lat: number; lng: number } | null = null;
  content: FakeElement | null = null;
  setLatLng(value: { lat: number; lng: number }): this { this.latlng = value; return this; }
  setContent(value: FakeElement): this { this.content = value; return this; }
  openOn(map: FakeMap): this { this.map = map; map.openLayers.add(this); return this; }
}
class FakeTooltip {
  latlng: { lat: number; lng: number } | null = null;
  content: FakeElement | null = null;
  options: Record<string, unknown>;
  constructor(options: Record<string, unknown>) { this.options = options; }
  setLatLng(value: { lat: number; lng: number }): this { this.latlng = value; return this; }
  setContent(value: FakeElement): this { this.content = value; return this; }
  addTo(map: FakeMap): this { map.openLayers.add(this); return this; }
}
class FakeLayer {
  map: FakeMap | null = null;
  data: Collection;
  options: GeoOptions;
  members: FakeLayer[] = [];
  styles: Record<string, unknown>[] = [];
  listeners = new Map<string, ((event: unknown) => void)[]>();
  constructor(data: Collection, options: GeoOptions) { this.data = data; this.options = options; }
  addTo(map: FakeMap): this { this.map = map; map.layers.add(this); return this; }
  bringToBack(): this { return this; }
  setStyle(value: Record<string, unknown> | (() => Record<string, unknown>)): this {
    const resolved = typeof value === 'function' ? value() : value;
    this.styles.push(resolved);
    for (const child of this.members) child.setStyle(resolved);
    return this;
  }
  on(eventName: string, handler: (event: unknown) => void): this {
    this.listeners.set(eventName, [...(this.listeners.get(eventName) ?? []), handler]);
    return this;
  }
  fire(eventName: string, payload: unknown = {}): void {
    for (const handler of this.listeners.get(eventName) ?? []) handler(payload);
  }
  getCenter() { return { lat: 46, lng: 2 }; }
}
class FakeMap {
  panes = new Map<string, { style: Record<string, string> }>();
  layers = new Set<FakeLayer>();
  openLayers = new Set<unknown>();
  container = new FakeElement();
  listeners = new Map<string, ((event?: unknown) => void)[]>();
  getPane(name: string) { return this.panes.get(name); }
  createPane(name: string) { const pane = { style: {} }; this.panes.set(name, pane); return pane; }
  getContainer() { return this.container; }
  hasLayer(layer: unknown) { return this.openLayers.has(layer); }
  removeLayer(layer: unknown) { this.openLayers.delete(layer); return this; }
  closePopup(popup: FakePopup) { this.openLayers.delete(popup); }
  on(names: string, handler: (event?: unknown) => void): this {
    for (const name of names.split(' ')) this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
    return this;
  }
  fire(name: string): void {
    for (const handler of this.listeners.get(name) ?? []) handler();
  }
}

const fixture: Collection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {
        record_id: 1,
        source_id: 1159320637,
        name: 'France',
        name_zh: '法国',
        formal_en: 'French Republic',
        iso_a2: 'FR',
        continent: 'Europe',
        subregion: 'Western Europe',
        type: 'Sovereign country',
        wikidata_id: 'Q142',
      },
      geometry: { type: 'Polygon', coordinates: [[[0, 44], [5, 44], [5, 49], [0, 44]]] },
    },
  ],
  metadata: {
    schema_version: 1,
    feature_count: 1,
    source: {
      name: 'Natural Earth 1:110m Admin 0 countries',
      version: '5.1.1',
      uri: 'https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/',
      license: 'Public domain',
      license_uri: 'https://www.naturalearthdata.com/about/terms-of-use/',
    },
  },
};

const script = ts.transpileModule(
  readFileSync(new URL('../../src/archsearch/frontend/modern-countries.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2022, strict: true }, reportDiagnostics: true },
);
assert.equal(script.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error).length, 0);

const clone = <T>(value: T): T => structuredClone(value);

function harness(basemap: 'osm' | 'natural' = 'natural') {
  const pending: { url: string; resolve(value: { ok: boolean; json(): Promise<unknown> }): void }[] = [];
  const layers: FakeLayer[] = [];
  const popups: FakePopup[] = [];
  const tooltips: FakeTooltip[] = [];
  const timers = new Map<number, { fn: () => void; delay: number }>();
  let timerSeq = 0;
  let stoppedEvents = 0;
  const map = new FakeMap();
  map.container.dataset.basemap = basemap;
  const helpers = runInContext(script.outputText + '\nArchSearchModernCountries;', createContext({
    URL, Set, Number, Array, Error,
    document: {
      createElement: (tag: string) => new FakeElement(tag),
      createTextNode: (textValue: string) => { const n = new FakeElement('#text'); n.textContent = textValue; return n; },
    },
    setTimeout: (fn: () => void, delay: number) => { const id = ++timerSeq; timers.set(id, { fn, delay }); return id; },
    clearTimeout: (id: number) => { timers.delete(id); },
    fetch: (url: string) => new Promise(resolve => pending.push({ url, resolve })),
    L: {
      canvas: (value: object) => ({ ...value }),
      DomEvent: { stopPropagation: () => { stoppedEvents++; } },
      popup: () => { const p = new FakePopup(); popups.push(p); return p; },
      tooltip: (opts: Record<string, unknown>) => { const t = new FakeTooltip(opts); tooltips.push(t); return t; },
      geoJSON: (data: Collection, options: GeoOptions) => {
        const layer = new FakeLayer(data, options);
        for (const feature of data.features) {
          const child = new FakeLayer(data, options);
          layer.members.push(child);
          options.onEachFeature?.(feature, child);
        }
        layers.push(layer);
        return layer;
      },
    },
  })) as Helpers;
  const controller = helpers.create({ map });
  const complete = async (value: unknown = clone(fixture)) => {
    pending[0].resolve({ ok: true, json: async () => value });
    for (let i = 0; i < 6; i++) await Promise.resolve();
  };
  return { helpers, map, controller, pending, layers, popups, tooltips, timers, complete, stoppedEvents: () => stoppedEvents };
}

test('bundled modern countries dataset matches pinned SHA256 and Natural Earth metadata', () => {
  const bytes = readFileSync(new URL('../../src/archsearch/static/data/modern-countries.geojson', import.meta.url));
  const manifest = JSON.parse(readFileSync(new URL('../../src/archsearch/static/data/modern-countries-source.json', import.meta.url), 'utf8')) as {
    sha256: string; feature_count: number; distinct_source_ids: number; source: { version: string; license: string; geojson_sha256: string };
  };
  assert.equal(createHash('sha256').update(bytes).digest('hex'), manifest.sha256);
  assert.equal(manifest.feature_count, 177);
  assert.equal(manifest.source.version, '5.1.1');
  assert.equal(manifest.source.license, 'Public domain');
  const h = harness();
  const parsed = h.helpers.parse(JSON.parse(bytes.toString('utf8')));
  assert.equal(parsed.features.length, 177);
  const france = parsed.features.find(f => f.properties.iso_a2 === 'FR');
  assert.equal(france?.properties.name_zh, '法国');
});

test('clicking a country opens detailed popup only in natural basemap mode and closes when leaving natural', async () => {
  const h = harness('osm');
  await h.complete();
  const featureLayer = h.layers[0].members[1];
  featureLayer.fire('click', { latlng: { lat: 46.5, lng: 2.2 } });
  assert.equal(h.map.hasLayer(h.popups[0]), false);
  assert.equal(h.stoppedEvents(), 0);

  h.map.container.dataset.basemap = 'natural';
  h.map.fire('archsearch:basemapchange');
  featureLayer.fire('click', { latlng: { lat: 46.5, lng: 2.2 } });
  assert.equal(h.map.hasLayer(h.popups[0]), true);
  assert.equal(h.stoppedEvents(), 1);
  assert.equal(h.popups[0].content?.children[0].textContent, '法国');
  assert.match(h.popups[0].content?.children.map(c => c.textContent).join(' | ') ?? '', /French Republic/);

  h.map.container.dataset.basemap = 'osm';
  h.map.fire('archsearch:basemapchange');
  assert.equal(h.map.hasLayer(h.popups[0]), false);
});

test('hovering over a country shows concise name preview after 5000ms and clears on mousemove/mouseout/click/pan', async () => {
  const h = harness('osm');
  await h.complete();
  const featureLayer = h.layers[0].members[1];
  featureLayer.fire('mouseover', { latlng: { lat: 46, lng: 2 } });
  assert.equal(h.timers.size, 1);
  const firstEntry = [...h.timers.entries()][0];
  assert.equal(firstEntry[1].delay, 5000);
  assert.equal(h.map.hasLayer(h.tooltips[0]), false);

  // Moving within the same country updates anchor without resetting the 5s timer.
  featureLayer.fire('mousemove', { latlng: { lat: 47, lng: 3 } });
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.keys()][0], firstEntry[0]);

  h.timers.delete(firstEntry[0]);
  firstEntry[1].fn();
  assert.equal(h.map.hasLayer(h.tooltips[0]), true);
  assert.deepEqual(h.tooltips[0].latlng, { lat: 47, lng: 3 });
  assert.equal(h.tooltips[0].content?.children.map(c => c.textContent).join(' '), '法国 France');

  featureLayer.fire('mouseout');
  assert.equal(h.map.hasLayer(h.tooltips[0]), false);

  // Drag/zoom cancels an armed dwell timer before firing.
  featureLayer.fire('mouseover', { latlng: { lat: 46, lng: 2 } });
  assert.equal(h.timers.size, 1);
  h.map.fire('movestart');
  assert.equal(h.timers.size, 0);
});

test('rebuild script refuses bad checksums and invalid args without modifying bundled geojson', () => {
  const asset = new URL('../../src/archsearch/static/data/modern-countries.geojson', import.meta.url);
  const before = readFileSync(asset);
  const directory = mkdtempSync(join(tmpdir(), 'archsearch-modern-countries-'));
  const scriptPath = fileURLToPath(new URL('../build-modern-countries.ts', import.meta.url));
  try {
    writeFileSync(join(directory, 'source.geojson'), JSON.stringify(fixture));
    const bad = spawnSync(process.execPath, ['--experimental-strip-types', scriptPath, '--source-cache', directory], { encoding: 'utf8' });
    assert.notEqual(bad.status, 0);
    assert.match(bad.stderr, /Source checksum mismatch: source.geojson/u);
    const unknown = spawnSync(process.execPath, ['--experimental-strip-types', scriptPath, '--invalid'], { encoding: 'utf8' });
    assert.notEqual(unknown.status, 0);
    assert.match(unknown.stderr, /Usage:/u);
    assert.deepEqual(readFileSync(asset), before);
  } finally {
    const insideTemp = relative(resolve(tmpdir()), resolve(directory));
    assert.ok(insideTemp && !isAbsolute(insideTemp) && insideTemp.startsWith('archsearch-modern-countries-') && !insideTemp.startsWith('..'));
    rmSync(directory, { recursive: true });
  }
});

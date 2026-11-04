import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

import ts from 'typescript';

interface SearchSpec {
  query: string;
  mode: 'semantic' | 'bm25';
  type: string | null;
  limit: number;
  country?: string | null;
  region?: string | null;
}

interface SearchResponse<T> {
  query: string;
  mode: 'semantic' | 'bm25';
  corpus_version: string;
  elapsed_ms: number;
  total_candidates: number;
  results: T[];
}

interface ExportResult<T> {
  schema_version: number;
  exported_at: string;
  request: SearchSpec;
  response: SearchResponse<T>;
  map: HistoryView | null;
  selection: { site: string | null; phase: string | null };
  sources: { name: string; license: string; version?: string | null; note?: string }[];
  selected_site: unknown;
  spatial: { metadata: unknown; selected: { site_id: string; representative_point: [number, number] | null; source_points: [number, number][]; records: { source_index: number; coordinate: [number, number]; name: string; ref: string }[]; source?: { name: string; uri: string; version: string; license: string; license_uri: string; sha256: string } | null } | null } | null;
  browse: BrowseState | null;
  source: {
    name: string;
    version: string;
    uri: string;
    release_uri: string;
    commit: string;
    license: string;
    license_uri: string;
    attribution: string;
  };
  provenance: Record<'processing' | 'scope' | 'coordinates' | 'scores' | 'periods', string>;
}

interface ResearchHelpers {
  parseLink(url: URL): { request: SearchSpec | null; error: string | null };
  parseView(url: URL): { view: HistoryView | null; selection: { site: string | null; phase: string | null }; error: string | null };
  parseBrowse(url: URL): { state: BrowseState; error: string | null };
  buildLink(base: URL, request: SearchSpec | null, view?: HistoryView | null, selection?: { site: string | null; phase: string | null }, browse?: BrowseState | null): string;
  createExport<T>(request: SearchSpec, response: SearchResponse<T>, exportedAt: string, view?: HistoryView | null, selection?: { site: string | null; phase: string | null }, selectedSite?: unknown, browse?: BrowseState | null, spatial?: ExportResult<T>['spatial']): ExportResult<T>;
  automaticPhaseYear(phase: { precision: string; start_year: number | null; end_year: number | null }): number | null;
}

interface HistoryView {
  year: number; basemap: 'historical' | 'modern'; boundaries: boolean;
  frame_id: string | null; source_version: string | null;
}

interface BrowseState { country: string | null; region: string | null; offset: number; visible: boolean; bbox?: [number, number, number, number] | null; spatial_match_mode?: string; spatial_version?: string | null }

const source = readFileSync(new URL('../../src/archsearch/frontend/research.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  fileName: 'research.ts',
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None, strict: true },
  reportDiagnostics: true,
});
assert.equal(compiled.diagnostics?.filter((item) => item.category === ts.DiagnosticCategory.Error).length, 0);
const candidate: unknown = runInContext(`${compiled.outputText}\nArchSearchResearch;`, createContext({ URL }));
assert.ok(typeof candidate === 'object' && candidate !== null);
assert.ok('parseLink' in candidate && typeof candidate.parseLink === 'function');
assert.ok('buildLink' in candidate && typeof candidate.buildLink === 'function');
assert.ok('createExport' in candidate && typeof candidate.createExport === 'function');
const helpers = candidate as ResearchHelpers;

const request: SearchSpec = { query: '古代港口', mode: 'semantic', type: 'port', limit: 20 };
const base = new URL('http://127.0.0.1:8000/');

function parse(parameters: Record<string, string>) {
  const url = new URL(base);
  for (const [name, value] of Object.entries(parameters)) url.searchParams.set(name, value);
  return helpers.parseLink(url);
}

function plain<T>(value: T): T {
  const decoded: unknown = JSON.parse(JSON.stringify(value));
  return decoded as T;
}

test('an empty or unrelated URL does not trigger a search', () => {
  assert.deepEqual(plain(helpers.parseLink(base)), { request: null, error: null });
  assert.deepEqual(plain(parse({ campaign: 'example' })), { request: null, error: null });
});

test('q is trimmed and omitted optional parameters receive documented defaults', () => {
  assert.deepEqual(plain(parse({ q: '  ancient ports  ' })), {
    request: { query: 'ancient ports', mode: 'semantic', type: null, limit: 10 }, error: null,
  });
});

for (const mode of ['semantic', 'bm25'] as const) {
  for (const limit of [10, 20, 50]) {
    test(`canonical links restore ${mode} with limit ${limit}`, () => {
      const spec = { ...request, mode, limit };
      const link = helpers.buildLink(base, spec);
      assert.deepEqual(plain(helpers.parseLink(new URL(link))), { request: spec, error: null });
    });
  }
}

for (const name of ['q', 'mode', 'type', 'limit']) {
  test(`duplicate ${name} parameters are refused even when their values agree`, () => {
    const url = new URL(helpers.buildLink(base, request));
    url.searchParams.append(name, url.searchParams.get(name) ?? '');
    const result = helpers.parseLink(url);
    assert.equal(result.request, null);
    assert.match(result.error ?? '', new RegExp(name));
    assert.match(result.error ?? '', /重复/u);
  });
}

test('search parameters without q fail instead of initiating a fallback query', () => {
  const invalidParameters: Record<string, string>[] = [{ mode: 'bm25' }, { type: 'port' }, { limit: '20' }, { q: '' }, { q: ' \t\n ' }];
  for (const parameters of invalidParameters) {
    const result = parse(parameters);
    assert.equal(result.request, null);
    assert.match(result.error ?? '', /q/u);
  }
});

test('query length uses Unicode characters and refuses more than 500', () => {
  assert.equal(parse({ q: '𐀀'.repeat(500) }).request?.query, '𐀀'.repeat(500));
  assert.equal(parse({ q: '𐀀'.repeat(501) }).request, null);
  assert.match(parse({ q: 'x'.repeat(501) }).error ?? '', /500/u);
});

test('invalid modes are errors, including empty and differently cased values', () => {
  for (const mode of ['', 'SEMANTIC', 'vector', 'bm25 ']) {
    const result = parse({ q: 'ports', mode });
    assert.equal(result.request, null);
    assert.match(result.error ?? '', /mode/u);
  }
});

test('only literal UI limit values are accepted, without coercing numeric spellings', () => {
  for (const limit of ['', '0', '1', '10.0', '010', '1e1', ' 10', '51', 'Infinity']) {
    const result = parse({ q: 'ports', limit });
    assert.equal(result.request, null);
    assert.match(result.error ?? '', /limit/u);
  }
});

test('an empty type means all types while nonempty IDs remain exact for facet validation', () => {
  assert.equal(parse({ q: 'ports', type: '' }).request?.type, null);
  assert.equal(parse({ q: 'ports', type: 'unknown-raw-id' }).request?.type, 'unknown-raw-id');
  assert.equal(parse({ q: 'ports', type: ' port ' }).request?.type, ' port ');
  assert.equal(parse({ q: 'ports', type: 'x'.repeat(128) }).request?.type, 'x'.repeat(128));
});

test('type IDs reject excessive length and C0/C1 control characters', () => {
  for (const type of ['x'.repeat(129), 'a\u0000b', 'a\u001fb', 'a\u007fb', 'a\u009fb']) {
    const result = parse({ q: 'ports', type });
    assert.equal(result.request, null);
    assert.match(result.error ?? '', /type/u);
  }
});

test('URL encoding round trips punctuation, Unicode and literal HTML without interpreting it', () => {
  const spec = { ...request, query: '港口 + & "<img src=x onerror=alert(1)>" / ? # %' };
  const link = helpers.buildLink(base, spec);
  assert.ok(!link.includes('<img'));
  assert.deepEqual(plain(helpers.parseLink(new URL(link))), { request: spec, error: null });
});

test('canonical URLs retain only the current origin, path and four search parameters', () => {
  const original = new URL('https://user:secret@example.org/research/view?tracking=private&q=old#detail');
  const before = original.href;
  const link = new URL(helpers.buildLink(original, { ...request, type: null }));
  assert.equal(link.origin, original.origin);
  assert.equal(link.pathname, '/research/view');
  assert.equal(link.username, '');
  assert.equal(link.password, '');
  assert.equal(link.hash, '');
  assert.deepEqual([...link.searchParams.keys()], ['q', 'mode', 'type', 'limit']);
  assert.equal(link.searchParams.get('type'), '');
  assert.equal(original.href, before);
});

test('link building validates its request and refuses non-HTTP base URLs', () => {
  assert.throws(() => helpers.buildLink(base, { ...request, query: ' ' }), /q/u);
  assert.throws(() => helpers.buildLink(base, { ...request, limit: 15 }), /limit/u);
  assert.throws(() => helpers.buildLink(new URL('javascript:alert(1)'), request), /HTTP/u);
  assert.throws(() => helpers.buildLink(new URL('file:///private/report.html'), request), /HTTP/u);
});

test('a double-slash path cannot replace the current origin during link construction', () => {
  const original = new URL('https://example.org//external.invalid/research');
  const link = new URL(helpers.buildLink(original, request));
  assert.equal(link.origin, original.origin);
  assert.equal(link.pathname, original.pathname);
});

test('exports retain full original sites, ordering, scores and evidence values', () => {
  const results = [{
    site: {
      id: 'qa-500', title: 'Untitled', description: '<script>literal source</script>', details: 'None',
      names: ['原文别名'], types: ['port', 'unlabeled'], periods: ['roman', 'modern'],
      repr_point: [12.3456789, 40.1234567], location_precision: null,
      source_uri: 'https://pleiades.stoa.org/places/qa-500', contributors: ['Original Contributor'],
      period_evidence: [{
        resource_type: 'Name', resource_uri: 'https://pleiades.stoa.org/places/qa-500/name',
        period_id: 'roman', period_uri: 'https://pleiades.stoa.org/vocabularies/time-periods/roman',
        confidence: 'less-confident', association_certainty: null, start: -30, end: 0,
      }],
    },
    score: 0.123456789, matched_fields: ['names', 'description'],
  }, {
    site: { id: 'second', title: 'Second', unknown_original_field: 'preserved' },
    score: -0.15, matched_fields: [],
  }];
  const response = { ...request, corpus_version: 'v4.1', elapsed_ms: 13.4, total_candidates: 500, results };
  const before = JSON.stringify(response);
  const exported = helpers.createExport(request, response, '2026-10-23T12:34:56.000Z');
  assert.equal(exported.schema_version, 2);
  assert.equal(exported.exported_at, '2026-10-23T12:34:56.000Z');
  assert.deepEqual(plain(exported.request), request);
  assert.deepEqual(plain(exported.response), response);
  assert.equal(JSON.stringify(response), before);
  assert.equal(JSON.stringify(exported).includes('unknown_original_field'), true);
});

test('a successful zero-result response remains exportable with its actual query and counters', () => {
  const spec = { ...request, mode: 'bm25' as const, query: 'zzunknown' };
  const response = { query: spec.query, mode: spec.mode, corpus_version: 'v4.1', elapsed_ms: 0, total_candidates: 0, results: [] };
  const exported = helpers.createExport(spec, response, '2026-10-23T00:00:00.000Z');
  assert.deepEqual(plain(exported.response), response);
  assert.deepEqual(plain(exported.request), spec);
});

test('export provenance includes source release, attribution, license and interpretation limits', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'v4.1', elapsed_ms: 1, total_candidates: 0, results: [] };
  const exported = helpers.createExport(request, response, '2026-10-23T00:00:00.000Z');
  assert.equal(exported.source.version, 'v4.1');
  assert.equal(exported.source.release_uri, 'https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1');
  assert.equal(exported.source.commit, 'b6a6790f71c45e4a4ef60fce296c506f28f458bf');
  assert.equal(exported.source.license, 'CC BY 3.0');
  assert.equal(exported.source.license_uri, 'https://creativecommons.org/licenses/by/3.0/');
  assert.match(exported.source.attribution, /The Contributors/u);
  assert.match(exported.provenance.processing, /HTML.*原文出处.*贡献者/u);
  assert.match(exported.provenance.coordinates, /WGS84.*经度.*纬度.*代表点.*不等同/u);
  assert.match(exported.provenance.scores, /不是相关概率.*不可直接比较.*不包含人工/u);
  assert.match(exported.provenance.periods, /不等同于建造年代.*start\/end/u);
  assert.equal('metrics' in exported, false);
});

test('exports refuse mismatched queries or modes instead of mislabelling earlier results', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'v4.1', elapsed_ms: 1, total_candidates: 0, results: [] };
  assert.throws(() => helpers.createExport({ ...request, query: 'unsent edit' }, response, '2026-10-23T00:00:00.000Z'), /一致/u);
  assert.throws(() => helpers.createExport({ ...request, mode: 'bm25' }, response, '2026-10-23T00:00:00.000Z'), /一致/u);
});

test('map links preserve committed year, basemap, site and phase while old links stay valid', () => {
  const view: HistoryView = { year: -1, basemap: 'modern', boundaries: true, frame_id: 'frame', source_version: 'v0.2.1' };
  const selection = { site: 'wd:Q123', phase: 'construction-1' };
  const url = new URL(helpers.buildLink(base, request, view, selection));
  assert.deepEqual(plain(helpers.parseLink(url)), { request, error: null });
  assert.deepEqual(plain(helpers.parseView(url)), { view: { ...view, frame_id: null, source_version: null }, selection, error: null });
  assert.equal(helpers.parseView(new URL(helpers.buildLink(base, request))).view, null);
});

test('map links reject year zero, duplicate years, outside range and orphan phases', () => {
  for (const query of ['year=0', 'year=2025', 'year=-3401', 'year=1.0', 'year=117&year=117', 'phase=one', 'site=javascript:1', 'basemap=other']) {
    const parsed = helpers.parseView(new URL(`?${query}`, base));
    assert.notEqual(parsed.error, null);
    assert.equal(parsed.view, null);
  }
});

test('only exact single years auto-navigate; approximate and period evidence retain uncertainty', () => {
  assert.equal(helpers.automaticPhaseYear({ precision: 'exact_year', start_year: -1, end_year: -1 }), -1);
  for (const precision of ['approximate_year', 'range', 'period']) {
    assert.equal(helpers.automaticPhaseYear({ precision, start_year: 117, end_year: 117 }), null);
  }
  assert.equal(helpers.automaticPhaseYear({ precision: 'exact_year', start_year: 0, end_year: 0 }), null);
  assert.equal(helpers.automaticPhaseYear({ precision: 'period', start_year: null, end_year: null }), null);
});

test('v2 export freezes the actual displayed map and multiple source licenses', () => {
  const view: HistoryView = { year: 1930, basemap: 'historical', boundaries: true, frame_id: '1930-frame', source_version: 'v0.2.1' };
  const response = { query: request.query, mode: request.mode, corpus_version: 'global-v2', elapsed_ms: 1, total_candidates: 600, results: [] };
  const exported = helpers.createExport(request, response, '2026-10-31T00:00:00Z', view);
  view.year = 2024;
  assert.equal(exported.map?.year, 1930);
  assert.equal(exported.map?.source_version, 'v0.2.1');
  assert.equal(exported.schema_version, 2);
  assert.ok(exported.sources.some((source) => source.license === 'CC BY 4.0'));
  assert.ok(exported.sources.some((source) => source.license === 'CC0'));
  assert.equal(helpers.createExport(request, response, '2026-10-31T00:00:00Z').map, null);
});

test('catalogue-only links restore a namespaced site without inventing a search', () => {
  const selection = { site: 'whc:252', phase: null };
  const browse: BrowseState = { country: 'IN', region: 'asia-pacific', offset: 50, visible: false, bbox: null };
  const url = new URL(helpers.buildLink(base, null, null, selection, browse));
  assert.deepEqual(plain(helpers.parseLink(url)), { request: null, error: null });
  assert.deepEqual(plain(helpers.parseView(url).selection), selection);
  assert.deepEqual(plain(helpers.parseBrowse(url)), { state: browse, error: null });
});

test('Antarctic catalogue links retain independent region and HSM identity', () => {
  const browse: BrowseState = { country: null, region: 'antarctica', offset: 50, visible: true, bbox: null };
  const link = new URL(helpers.buildLink(base, null, null, { site: 'ats:hsm:95', phase: null }, browse));
  assert.equal(helpers.parseView(link).selection.site, 'ats:hsm:95');
  assert.equal(helpers.parseBrowse(link).state.region, 'antarctica');
  assert.equal(helpers.parseLink(link).request, null);
  const spec = { ...request, region: 'antarctica' };
  assert.deepEqual(plain(helpers.parseLink(new URL(helpers.buildLink(base, spec))).request), spec);
});

test('successful search filters and independently browsed filters never overwrite each other', () => {
  const searched = { ...request, country: 'FR', region: 'europe-north-america' };
  const browse: BrowseState = { country: 'CN', region: 'asia-pacific', offset: 0, visible: true, bbox: null };
  const url = new URL(helpers.buildLink(base, searched, null, { site: null, phase: null }, browse));
  assert.deepEqual(plain(helpers.parseLink(url).request), searched);
  assert.deepEqual(plain(helpers.parseBrowse(url).state), browse);
  assert.equal(url.searchParams.get('country'), 'FR');
  assert.equal(url.searchParams.get('browse_country'), 'CN');
});

test('explicitly cleared browse filters remain distinct from successful search filters', () => {
  const browse: BrowseState = { country: null, region: null, offset: 0, visible: true, bbox: null };
  const url = new URL(helpers.buildLink(base, { ...request, country: 'FR' }, null, { site: null, phase: null }, browse));
  assert.equal(url.searchParams.get('browse_country'), '');
  assert.equal(helpers.parseBrowse(url).state.country, null);
  assert.equal(helpers.parseLink(url).request?.country, 'FR');
});

test('NPS project grouping round trips independently from searched and browsed area codes', () => {
  const searched = { ...request, country: 'GU', region: 'nps-pacific' };
  const browse: BrowseState = { country: 'AS', region: 'nps-pacific', offset: 50, visible: true, bbox: null };
  const selection = { site: 'auth:nps-nris:03000549', phase: null };
  const url = new URL(helpers.buildLink(base, searched, null, selection, browse));
  assert.deepEqual(plain(helpers.parseLink(url).request), searched);
  assert.deepEqual(plain(helpers.parseBrowse(url).state), browse);
  assert.deepEqual(plain(helpers.parseView(url).selection), selection);
  assert.equal(url.searchParams.get('region'), 'nps-pacific');
  assert.equal(url.searchParams.get('browse_country'), 'AS');
});

test('geographic links reject malformed, duplicated or orphaned parameters', () => {
  for (const suffix of ['country=', 'region=', 'country=cn', 'region=unknown', 'country=CN&country=FR', 'region=africa&region=africa']) {
    assert.notEqual(helpers.parseLink(new URL(`?q=site&${suffix}`, base)).error, null);
  }
  for (const suffix of ['browse_country=cn', 'browse_region=unknown', 'points=true', 'browse_offset=-1', 'browse_offset=0&browse_offset=0']) {
    assert.notEqual(helpers.parseBrowse(new URL(`?${suffix}`, base)).error, null);
  }
  for (const site of ['whc:0', 'whc:-1', 'whc:252/javascript']) {
    assert.notEqual(helpers.parseView(new URL(`?site=${encodeURIComponent(site)}`, base)).error, null);
  }
});

test('exports include a separately selected catalogue record without fake ranking or score', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'global-v3', elapsed_ms: 1, total_candidates: 0, results: [] };
  const selected = { id: 'whc:2', title: 'City of Quito', source_refs: [{ license: 'CC BY-SA 4.0' }] };
  const report = helpers.createExport(request, response, '2026-11-04T00:00:00Z', null, { site: selected.id, phase: null }, selected);
  assert.deepEqual(plain(report.selected_site), selected);
  assert.deepEqual(plain(report.response.results), []);
  assert.ok(!('score' in (report.selected_site as Record<string, unknown>)));
  assert.ok(report.sources.some(source => source.name === 'UNESCO DataHub World Heritage List' && source.license === 'CC BY-SA 4.0'));
});

test('unknown Antarctic positions remain null in standalone exports with their own attribution', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'global-v4', elapsed_ms: 1, total_candidates: 0, results: [] };
  const selected = { id: 'ats:hsm:95', title: 'Wreck of San Telmo', repr_point: null, source_kind: 'ats' };
  const report = helpers.createExport(request, response, '2026-11-04T00:00:00Z', null, { site: selected.id, phase: null }, selected);
  assert.equal((report.selected_site as typeof selected).repr_point, null);
  assert.ok(!('score' in (report.selected_site as Record<string, unknown>)));
  assert.ok(report.sources.some(source => source.name.startsWith('Antarctic Treaty Secretariat') && source.license === 'CC BY 4.0'));
});

test('spatial exports retain source order, duplicates and labels separately from the representative point', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'global-v4', elapsed_ms: 1, total_candidates: 0, results: [] };
  const snapshot: NonNullable<ExportResult<never>['spatial']> = {
    metadata: { version: 'world-locations-v1', source: { license: 'CC BY-SA 4.0' } },
    selected: { site_id: 'whc:1', representative_point: [30, 40], source_points: [[10, 20], [10, 20], [11, 21]], records: [
      { source_index: 0, coordinate: [10, 20], name: '<b>Original A</b>', ref: 'same-ref' },
      { source_index: 1, coordinate: [10, 20], name: 'Original B', ref: 'same-ref' },
      { source_index: 2, coordinate: [11, 21], name: 'Original C', ref: 'same-ref' },
    ] },
  };
  const expected = plain(snapshot);
  const report = helpers.createExport(request, response, '2026-11-04T00:00:00Z', null, { site: 'whc:1', phase: null }, null, null, snapshot);
  snapshot.selected!.source_points[0][0] = 0;
  assert.deepEqual(plain(report.spatial), expected);
  assert.deepEqual(report.response.results, []);
  assert.equal(helpers.createExport(request, response, '2026-11-04T00:00:00Z').spatial, null);
});

test('source-qualified authority IDs round-trip without inventing a search or a historical phase', () => {
  const browse: BrowseState = { country: 'KI', region: 'asia-pacific', offset: 0, visible: true, bbox: null };
  const view: HistoryView = { year: 117, basemap: 'historical', boundaries: false, frame_id: 'frame-117', source_version: 'v0.2.1' };
  for (const id of ['auth:dva:betio-coast-watchers-memorial', 'auth:commonwealth:67579', 'auth:sprep:d6eab109-2e10-4654-b3c4-5bb94f6a8867']) {
    const selection = { site: id, phase: null };
    const url = new URL(helpers.buildLink(base, null, view, selection, browse));
    assert.equal(url.searchParams.get('site'), id);
    assert.deepEqual(plain(helpers.parseLink(url)), { request: null, error: null });
    assert.deepEqual(plain(helpers.parseView(url).selection), selection);
    assert.equal(helpers.parseView(url).view?.year, 117);
    assert.deepEqual(plain(helpers.parseBrowse(url)), { state: browse, error: null });
    assert.equal(url.searchParams.has('phase'), false);
  }
});

test('authority ID links reject path traversal, embedded URLs, delimiters and invalid namespace boundaries', () => {
  for (const id of [
    'auth:dva:../secret', 'auth:dva:..', 'auth:dva:a/b', 'auth:dva:a\\b',
    'auth:dva:%2Fapi%2Fstatus', 'auth:dva:https://example.org/place', 'auth:dva:a?year=1',
    'auth:dva:a#fragment', 'auth:dva:a:other', 'auth:DVA:place', 'auth:1provider:place',
    'auth::place', 'auth:dva:', 'auth:dva: leading', 'auth:dva:trailing ',
    'auth:dva:<script>', 'auth:dva:place\u0000', `auth:${'x'.repeat(41)}:place`,
    `auth:dva:${'x'.repeat(81)}`,
  ]) {
    const url = new URL(base); url.searchParams.set('site', id);
    const parsed = helpers.parseView(url);
    assert.notEqual(parsed.error, null, id);
    assert.deepEqual(plain(parsed.selection), { site: null, phase: null }, id);
    assert.equal(helpers.parseLink(url).request, null);
  }
});

test('an independently selected unknown supplement exports its own evidence without altering successful ranking', () => {
  const searched: SearchSpec = { ...request, country: 'BT', region: 'asia-pacific' };
  const response = { query: searched.query, mode: searched.mode, corpus_version: 'global-v5', elapsed_ms: 4,
    total_candidates: 1, results: [{ site: { id: 'wd:Q900000001', repr_point: [90, 27] }, score: 0.42, matched_fields: ['description'] }] };
  const selected = { id: 'auth:dva:betio-coast-watchers-memorial', title: 'Betio Coast Watchers Memorial',
    source_kind: 'supplement', repr_point: null, location_precision: null, periods: [], period_evidence: [],
    source_uri: 'https://example.org/official-memorial',
    source_refs: [{ id: 'authority:memorial', uri: 'https://example.org/official-memorial', publisher: 'Fixture government authority', license: null, revision: 'sha256:fixed', excerpt: 'Memorial at the cemetery.' }],
    chronology: { status: 'not_reviewed', phases: [], default_phase_id: null },
    geography: { authority_id: 'supplement:auth:dva:betio-coast-watchers-memorial', countries: ['KI'], regions: ['asia-pacific'], point_count: 0, note: 'No verified public coordinate; not substituted with an island centre.' },
  };
  const browse: BrowseState = { country: 'KI', region: 'asia-pacific', offset: 0, visible: false, bbox: null };
  const before = plain(response);
  const report = helpers.createExport(searched, response, '2026-11-04T00:00:00Z', null,
    { site: selected.id, phase: null }, selected, browse,
    { metadata: null, selected: { site_id: selected.id, representative_point: null, source_points: [], records: [] } });
  assert.deepEqual(plain(report.response), before);
  assert.deepEqual(plain(report.request), searched);
  assert.deepEqual(plain(report.browse), browse);
  assert.deepEqual(plain(report.selected_site), selected);
  assert.equal((report.selected_site as typeof selected).repr_point, null);
  assert.equal((report.selected_site as typeof selected).source_refs[0].license, null);
  const supplementSource = report.sources.find(source => source.name === 'Country cultural supplement');
  assert.equal(supplementSource?.version, 'country-supplement-v1');
  assert.equal(supplementSource?.license, 'Mixed rights — see individual source_refs');
  const regionalSource = report.sources.find(source => source.name === 'Regional cultural supplement');
  assert.equal(regionalSource?.version, 'regional-supplement-v1');
  assert.equal(regionalSource?.license, 'Mixed rights — see individual source_refs');
  const southAmericaSource = report.sources.find(source => source.name === 'South America cultural supplement');
  assert.equal(southAmericaSource?.version, 'southamerica-supplement-v1');
  assert.equal(southAmericaSource?.license, 'Mixed rights — see individual source_refs');
  assert.match(southAmericaSource?.note ?? '', /absent or conflicting coordinates remain null/u);
  const africaSource = report.sources.find(source => source.name === 'Africa cultural supplement');
  assert.equal(africaSource?.version, 'africa-supplement-v1');
  assert.equal(africaSource?.license, 'Mixed rights — see individual source_refs');
  assert.match(africaSource?.note ?? '', /not World Heritage inscriptions/u);
  const pacificSource = report.sources.find(source => source.name === 'Pacific and interior cultural supplement');
  assert.equal(pacificSource?.version, 'pacific-interior-supplement-v1');
  assert.equal(pacificSource?.license, 'Mixed rights — see individual source_refs');
  assert.match(pacificSource?.note ?? '', /address-restricted place remains unmapped/u);
  const npsSource = report.sources.find(source => source.name === 'NPS Pacific register supplement');
  assert.equal(npsSource?.version, 'nps-pacific-v1');
  assert.equal(npsSource?.license, 'NPS government structured metadata; other source rights retained');
  assert.match(npsSource?.note ?? '', /third-party nomination text/u);
  assert.match(npsSource?.note ?? '', /restricted locations remain unmapped/u);
  assert.equal(report.spatial?.selected?.representative_point, null);
  assert.deepEqual(plain(report.spatial?.selected?.source_points), []);
  assert.equal('score' in (report.selected_site as Record<string, unknown>), false);
  assert.equal('rank' in (report.selected_site as Record<string, unknown>), false);
  assert.equal(report.map, null);
});

test('fixed browse bounds round-trip independently of search filters and historical selection', () => {
  const bbox: [number, number, number, number] = [170, -20, -170, 10];
  const searched = { ...request, country: 'FR' };
  const browse: BrowseState = { country: 'NZ', region: 'asia-pacific', offset: 50, visible: false, bbox };
  const url = new URL(helpers.buildLink(base, searched, null, { site: 'whc:1', phase: null }, browse));
  assert.equal(url.searchParams.get('browse_bbox'), '170,-20,-170,10');
  assert.deepEqual(plain(helpers.parseBrowse(url)), { state: browse, error: null });
  assert.deepEqual(plain(helpers.parseLink(url).request), searched);
  assert.equal(url.searchParams.has('bbox'), false);
  assert.equal(helpers.parseBrowse(new URL('?q=harbor&mode=bm25', base)).state.bbox, null);
  assert.deepEqual(plain(helpers.parseBrowse(new URL('?browse_bbox=+1.7e2,+-2e1,-1.7e2,1e1', base)).state.bbox), bbox);
});

test('invalid or repeated bbox links reject without silently widening the restored scope', () => {
  const invalid = ['', '1,2,3', '1,2,3,4,5', '1,2,1,4', '180,-20,-180,20', '-181,-20,0,20',
    '-10,-91,10,20', '-10,0,10,91', '-10,2,10,2', '-10,3,10,2', 'NaN,0,10,20',
    'Infinity,0,10,20', '1e309,0,10,20', '0x10,0,20,30', '１,0,20,30', `${' '.repeat(190)}-10,0,10,20`];
  for (const bbox of invalid) {
    const url = new URL(base); url.searchParams.set('browse_bbox', bbox);
    assert.notEqual(helpers.parseBrowse(url).error, null, bbox);
  }
  assert.notEqual(helpers.parseBrowse(new URL('?browse_bbox=1,2,3,4&browse_bbox=1,2,3,4', base)).error, null);
  assert.deepEqual(plain(helpers.parseBrowse(new URL('?browse_bbox=-180,-90,180,90', base)).state.bbox), [-180, -90, 180, 90]);
  const boundary = new URL(base); boundary.searchParams.set('browse_bbox', `${' '.repeat(189)}-10,0,10,20`);
  assert.equal(boundary.searchParams.get('browse_bbox')?.length, 200);
  assert.deepEqual(plain(helpers.parseBrowse(boundary).state.bbox), [-10, 0, 10, 20]);
});

test('exports clone the committed bbox and source matching capability without changing the search snapshot', () => {
  const bbox: [number, number, number, number] = [29, 40, 31, 42];
  const browse: BrowseState = { country: 'TR', region: null, offset: 0, visible: true, bbox,
    spatial_match_mode: 'source-or-representative', spatial_version: 'world-locations-v1' };
  const response = { query: request.query, mode: request.mode, corpus_version: 'global-v6', elapsed_ms: 1, total_candidates: 1, results: [{ id: 'other' }] };
  const exported = helpers.createExport(request, response, '2026-11-04T00:00:00Z', null, { site: 'whc:1', phase: null }, null, browse);
  bbox[0] = 0;
  assert.deepEqual(plain(exported.browse?.bbox), [29, 40, 31, 42]);
  assert.equal(exported.browse?.spatial_match_mode, 'source-or-representative');
  assert.equal(exported.browse?.spatial_version, 'world-locations-v1');
  assert.deepEqual(plain(exported.request), request);
  assert.deepEqual(plain(exported.response), response);
  assert.equal(Object.hasOwn(exported.request, 'bbox'), false);
});

test('a selected protection location exports its own source alongside the combined identity groups', () => {
  const response = { query: request.query, mode: request.mode, corpus_version: 'fixture-v8', elapsed_ms: 1, total_candidates: 0, results: [] };
  const selectedSource = { name: 'UNESCO DataHub chp001', uri: 'https://data.unesco.org/explore/dataset/chp001/', version: '2026-10-31', license: 'CC BY-SA 4.0', license_uri: 'https://creativecommons.org/licenses/by-sa/4.0/', sha256: 'a'.repeat(64) };
  const snapshot: NonNullable<ExportResult<never>['spatial']> = {
    metadata: { version: 'world-locations-v1+protection-locations-v1', source_groups: [
      { version: 'world-locations-v1', source: { name: 'UNESCO DataHub whc001' }, site_ids: ['whc:1'] },
      { version: 'protection-locations-v1', source: selectedSource, site_ids: ['auth:unesco-chp:630'] },
    ] },
    selected: { site_id: 'auth:unesco-chp:630', representative_point: [36, 34], source_points: [[36, 34], [36.1, 34.1]], records: [
      { source_index: 0, coordinate: [36, 34], name: 'Dolmen 1', ref: 'source_index:0' },
      { source_index: 1, coordinate: [36.1, 34.1], name: 'Dolmen 2', ref: 'source_index:1' },
    ], source: selectedSource },
  };
  const original = plain(snapshot);
  const report = helpers.createExport(request, response, '2026-11-04T00:00:00Z', null, { site: snapshot.selected!.site_id, phase: null }, null, null, snapshot);
  selectedSource.uri = 'https://changed.example/'; snapshot.selected!.records[0].name = 'changed';
  assert.deepEqual(plain(report.spatial), original);
  assert.equal(report.spatial?.selected?.source?.name, 'UNESCO DataHub chp001');
  const source = report.sources.find(source => source.name === 'UNESCO Hague cultural properties');
  assert.equal(source?.license, 'CC BY-SA 4.0');
  assert.equal(source?.version, 'protection-supplement-v1');
});

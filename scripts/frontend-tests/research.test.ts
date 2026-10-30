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
  sources: { name: string; license: string }[];
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
  buildLink(base: URL, request: SearchSpec, view?: HistoryView | null, selection?: { site: string | null; phase: string | null }): string;
  createExport<T>(request: SearchSpec, response: SearchResponse<T>, exportedAt: string, view?: HistoryView | null): ExportResult<T>;
  automaticPhaseYear(phase: { precision: string; start_year: number | null; end_year: number | null }): number | null;
}

interface HistoryView {
  year: number; basemap: 'historical' | 'modern'; boundaries: boolean;
  frame_id: string | null; source_version: string | null;
}

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

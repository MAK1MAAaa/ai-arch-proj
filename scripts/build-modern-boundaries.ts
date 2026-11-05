import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const commit = 'f1890d9f152c896d250a77557a5751a93d494776';
const base = `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/${commit}/`;
const source = {
  name: 'Natural Earth 1:50m Admin 0 land boundary lines',
  version: '5.1.0',
  distribution_tag: 'v5.1.2',
  commit,
  uri: 'https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-boundary-lines-2/',
  geojson_uri: `${base}geojson/ne_50m_admin_0_boundary_lines_land.geojson`,
  geojson_sha256: '2faac4f6b34386f3d21b6e018cf151f241f00e5c936d44dd17d7d9bfb147fa48',
  archive_uri: 'https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_boundary_lines_land.zip',
  archive_sha256: '02f369ae10578c4ce33fc4a08f8cdd69ea11eb39b44d7923e88eb7199aaff8ea',
  version_uri: `${base}50m_cultural/ne_50m_admin_0_boundary_lines_land.VERSION.txt`,
  version_sha256: 'c0eacacd7e27bbf341d21e7e0e2997a363840a210d8e358d4babaebd765b5bfd',
  license: 'Public domain',
  license_uri: 'https://www.naturalearthdata.com/about/terms-of-use/',
};
const digest = (value: Uint8Array): string => createHash('sha256').update(value).digest('hex');
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const classes = ['International boundary (verify)', 'Disputed (please verify)', 'Line of control (please verify)', 'Indefinite (please verify)', 'Indeterminant frontier'];
type Point = [number, number];
interface Geometry { type: 'LineString' | 'MultiLineString'; coordinates: Point[] | Point[][] }

function geometry(value: unknown): Geometry {
  const line = (points: unknown): points is Point[] => Array.isArray(points) && points.length >= 2
    && points.every(p => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && Number.isFinite(p[0]) && Math.abs(p[0]) <= 180 && typeof p[1] === 'number' && Number.isFinite(p[1]) && Math.abs(p[1]) <= 90)
    && points.every((p, i) => i === 0 || Math.abs(p[0] - points[i - 1][0]) <= 180);
  if (!record(value) || !(value.type === 'LineString' ? line(value.coordinates) : value.type === 'MultiLineString' && Array.isArray(value.coordinates) && value.coordinates.length > 0 && value.coordinates.every(line))) throw new Error('Source contains invalid boundary line geometry.');
  return value as unknown as Geometry;
}

async function frozenFile(cache: string, name: string, uri: string, sha: string, download: boolean): Promise<Uint8Array> {
  const path = join(cache, name);
  let raw: Uint8Array;
  try { raw = await readFile(path); }
  catch (error) {
    if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT') || !download) throw error;
    const response = await fetch(uri);
    if (!response.ok) throw new Error(`Source download failed: ${response.status}`);
    raw = new Uint8Array(await response.arrayBuffer());
    if (digest(raw) !== sha) throw new Error(`Source checksum mismatch: ${name}`);
    await writeFile(path, raw);
  }
  if (digest(raw) !== sha) throw new Error(`Source checksum mismatch: ${name}`);
  return raw;
}

async function main(args: string[]): Promise<void> {
  let download = false, cacheArgument: string | null = null;
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--download') download = true;
    else if (args[index] === '--source-cache' && args[index + 1] && !args[index + 1].startsWith('--')) cacheArgument = args[++index];
    else throw new Error('Usage: node --experimental-strip-types scripts/build-modern-boundaries.ts [--download] [--source-cache DIR]');
  }
  const cache = resolve(cacheArgument ?? join(root, '.archsearch/downloads/modern-boundaries-v5.1.0'));
  await mkdir(cache, { recursive: true });
  const raw = await frozenFile(cache, 'source.geojson', source.geojson_uri, source.geojson_sha256, download);
  await frozenFile(cache, 'archive.zip', source.archive_uri, source.archive_sha256, download);
  const version = await frozenFile(cache, 'version.txt', source.version_uri, source.version_sha256, download);
  if (new TextDecoder().decode(version).trim() !== source.version) throw new Error('Source dataset version mismatch.');
  const value: unknown = JSON.parse(new TextDecoder().decode(raw));
  if (!record(value) || value.type !== 'FeatureCollection' || !Array.isArray(value.features) || value.features.length !== 390) throw new Error('Source feature count mismatch.');
  const ids = new Set<number>();
  let pointCount = 0, lineCount = 0;
  const counts: Record<string, number> = {};
  const features = value.features.map((feature: unknown, index: number) => {
    if (!record(feature) || feature.type !== 'Feature' || !record(feature.properties) || typeof feature.properties.NE_ID !== 'number' || !Number.isSafeInteger(feature.properties.NE_ID) || typeof feature.properties.FEATURECLA !== 'string' || !classes.includes(feature.properties.FEATURECLA)) throw new Error('Source boundary identity or classification mismatch.');
    ids.add(feature.properties.NE_ID);
    const shape = geometry(feature.geometry);
    const lines = shape.type === 'LineString' ? [shape.coordinates as Point[]] : shape.coordinates as Point[][];
    lineCount += lines.length; pointCount += lines.reduce((count, line) => count + line.length, 0);
    counts[feature.properties.FEATURECLA] = (counts[feature.properties.FEATURECLA] ?? 0) + 1;
    return { type: 'Feature', properties: { record_id: index + 1, source_id: feature.properties.NE_ID, classification: feature.properties.FEATURECLA }, geometry: shape };
  });
  if (lineCount !== 393 || pointCount !== 19859 || ids.size !== 382) throw new Error('Source coordinate or identity counts mismatch.');
  const processing = 'Preserve all source coordinates, order, NE_ID and FEATURECLA; remove unused attributes and bounding boxes. Assign record_id from one-based source feature order because eight NE_ID values each occur twice; do not merge those lines. Render all 390 source records, retaining disputed/control/indefinite classifications as dashed lines. No simplification, maritime boundaries, country assignment, alternate POV filtering, or sovereignty inference.';
  const result = { type: 'FeatureCollection', features, metadata: { schema_version: 1, feature_count: features.length, distinct_source_ids: ids.size, line_count: lineCount, point_count: pointCount, classification_counts: counts, source, processing } };
  const output = new TextEncoder().encode(JSON.stringify(result) + '\n');
  const folder = join(root, 'src/archsearch/static/data');
  await writeFile(join(folder, 'modern-boundaries.geojson'), output);
  await writeFile(join(folder, 'modern-boundaries-source.json'), JSON.stringify({ ...result.metadata, sha256: digest(output), artifact: 'modern-boundaries.geojson', rebuild: 'node --experimental-strip-types scripts/build-modern-boundaries.ts --download' }, null, 2) + '\n');
  console.log(JSON.stringify({ features: features.length, lines: lineCount, points: pointCount, bytes: output.byteLength, sha256: digest(output) }));
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await main(process.argv.slice(2));
}

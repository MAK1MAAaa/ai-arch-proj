import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const commit = 'f1890d9f152c896d250a77557a5751a93d494776';
const base = `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/${commit}/`;
const source = {
  name: 'Natural Earth 1:110m Admin 0 countries',
  version: '5.1.1',
  distribution_tag: 'v5.1.2',
  commit,
  uri: 'https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/',
  geojson_uri: `${base}geojson/ne_110m_admin_0_countries.geojson`,
  geojson_sha256: '6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f',
  version_uri: `${base}110m_cultural/ne_110m_admin_0_countries.VERSION.txt`,
  version_sha256: 'f9893302cd3158f3b5aea394dcd2a91574869e9e6ff69e9235b10a3bf8c983fb',
  license: 'Public domain',
  license_uri: 'https://www.naturalearthdata.com/about/terms-of-use/',
};
const digest = (value: Uint8Array): string => createHash('sha256').update(value).digest('hex');
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
type Point = [number, number];
type Ring = Point[];
type PolygonCoordinates = Ring[];
interface Geometry { type: 'Polygon' | 'MultiPolygon'; coordinates: PolygonCoordinates | PolygonCoordinates[] }

function cleanString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback;
}

function geometry(value: unknown): Geometry {
  const ring = (points: unknown): points is Ring => Array.isArray(points) && points.length >= 4
    && points.every(p => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && Number.isFinite(p[0]) && Math.abs(p[0]) <= 180
      && typeof p[1] === 'number' && Number.isFinite(p[1]) && Math.abs(p[1]) <= 90)
    && points[0][0] === points[points.length - 1][0] && points[0][1] === points[points.length - 1][1];
  const polygon = (rings: unknown): rings is PolygonCoordinates => Array.isArray(rings) && rings.length > 0 && rings.every(ring);
  if (!record(value) || !(value.type === 'Polygon' ? polygon(value.coordinates)
    : value.type === 'MultiPolygon' && Array.isArray(value.coordinates) && value.coordinates.length > 0 && value.coordinates.every(polygon))) {
    throw new Error('Source contains invalid country polygon geometry.');
  }
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
    else throw new Error('Usage: node --experimental-strip-types scripts/build-modern-countries.ts [--download] [--source-cache DIR]');
  }
  const cache = resolve(cacheArgument ?? join(root, '.archsearch/downloads/modern-countries-v5.1.1'));
  await mkdir(cache, { recursive: true });
  const raw = await frozenFile(cache, 'source.geojson', source.geojson_uri, source.geojson_sha256, download);
  const version = await frozenFile(cache, 'version.txt', source.version_uri, source.version_sha256, download);
  if (new TextDecoder().decode(version).trim() !== source.version) throw new Error('Source dataset version mismatch.');
  const value: unknown = JSON.parse(new TextDecoder().decode(raw));
  if (!record(value) || value.type !== 'FeatureCollection' || !Array.isArray(value.features) || value.features.length !== 177) {
    throw new Error('Source feature count mismatch.');
  }
  const ids = new Set<number>();
  const features = value.features.map((feature: unknown, index: number) => {
    if (!record(feature) || feature.type !== 'Feature' || !record(feature.properties)
      || typeof feature.properties.NE_ID !== 'number' || !Number.isSafeInteger(feature.properties.NE_ID)) {
      throw new Error('Source country identity mismatch.');
    }
    const name = cleanString(feature.properties.NAME);
    const nameZh = cleanString(feature.properties.NAME_ZH);
    const countryType = cleanString(feature.properties.TYPE);
    const wikidataId = cleanString(feature.properties.WIKIDATAID);
    if (!name || !nameZh || !countryType || !wikidataId) {
      throw new Error('Source country attributes missing.');
    }
    ids.add(feature.properties.NE_ID);
    const shape = geometry(feature.geometry);
    return {
      type: 'Feature',
      properties: {
        record_id: index + 1,
        source_id: feature.properties.NE_ID,
        name,
        name_zh: nameZh,
        formal_en: cleanString(feature.properties.FORMAL_EN),
        iso_a2: cleanString(feature.properties.ISO_A2_EH),
        continent: cleanString(feature.properties.CONTINENT),
        subregion: cleanString(feature.properties.SUBREGION),
        type: countryType,
        wikidata_id: wikidataId,
      },
      geometry: shape,
    };
  });
  const processing = 'Preserve all 177 source country/territory polygons and minimal reference attributes (NE_ID, NAME, NAME_ZH, FORMAL_EN, ISO_A2_EH, CONTINENT, SUBREGION, TYPE, WIKIDATAID) from Natural Earth 1:110m Admin 0 Countries v5.1.1 without geometry simplification or sovereignty inference.';
  const result = {
    type: 'FeatureCollection',
    features,
    metadata: {
      schema_version: 1,
      feature_count: features.length,
      distinct_source_ids: ids.size,
      source,
      processing,
    },
  };
  const output = new TextEncoder().encode(JSON.stringify(result) + '\n');
  const folder = join(root, 'src/archsearch/static/data');
  await writeFile(join(folder, 'modern-countries.geojson'), output);
  await writeFile(join(folder, 'modern-countries-source.json'), JSON.stringify({
    ...result.metadata,
    sha256: digest(output),
    artifact: 'modern-countries.geojson',
    rebuild: 'node --experimental-strip-types scripts/build-modern-countries.ts --download',
  }, null, 2) + '\n');
  console.log(JSON.stringify({ features: features.length, bytes: output.byteLength, sha256: digest(output) }));
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await main(process.argv.slice(2));
}

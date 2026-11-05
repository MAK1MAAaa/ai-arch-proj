import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';
import ts from 'typescript';

interface Config { provider: 'ollama' | 'openai'; base_url: string; model: string; revision: number; has_api_key: boolean }
interface Controller {
  load(): Promise<void>; discover(): Promise<void>; apply(clear?: boolean): Promise<void>;
  ready(): boolean; enabled(): boolean; getConfig(): Config | null; setRequested(value: boolean): void;
  requestOptions(): { enhance?: true; llm_revision?: number }; showSettings(): void;
}
interface Helpers {
  create(options: { onChange(): void; request<T>(path: string, init?: RequestInit): Promise<T>; debounceMs?: number }): Controller;
  parseConfig(value: unknown): Config;
  parseModels(value: unknown): unknown;
  endpoint(value: string): string;
}
class Element extends EventTarget {
  value = ''; textContent = ''; disabled = false; hidden = false; checked = false; open = false;
  children: Element[] = []; attributes = new Map<string, string>(); tagName: string;
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  replaceChildren(...children: Element[]): void { this.children = children; if (this.tagName === 'SELECT') this.value = children[0]?.value ?? ''; }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  fire(name: string): void { this.dispatchEvent(new Event(name, { cancelable: true })); }
  set innerHTML(_value: string) { throw new Error('Unsafe innerHTML'); }
}
interface Pending { path: string; init: RequestInit; resolve(value: unknown): void; reject(error: Error): void }
const source = readFileSync('src/archsearch/frontend/llm.ts', 'utf8');
const script = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } }).outputText;
function harness() {
  const ids = ['llm-settings', 'llm-settings-form', 'llm-provider', 'llm-base-url', 'llm-api-key', 'llm-api-key-group', 'llm-key-hint', 'llm-model', 'llm-refresh-models', 'llm-apply', 'llm-clear-config', 'llm-enhance', 'llm-active-model', 'llm-feedback', 'llm-provider-note', 'llm-error'];
  const elements = new Map(ids.map(id => [id, new Element(['llm-provider', 'llm-model'].includes(id) ? 'select' : 'div')]));
  elements.get('llm-provider')!.value = 'ollama'; elements.get('llm-base-url')!.value = 'http://127.0.0.1:11434';
  const pending: Pending[] = []; const timers = new Map<number, () => void>(); let counter = 0; let changes = 0;
  const context = createContext({ URL, AbortController, Error,
    document: { getElementById: (id: string) => elements.get(id), createElement: (tag: string) => new Element(tag) },
    setTimeout: (fn: () => void) => { const key = ++counter; timers.set(key, fn); return key; },
    clearTimeout: (key: number) => timers.delete(key),
    get localStorage() { throw new Error('Credentials must not enter localStorage'); },
    get sessionStorage() { throw new Error('Credentials must not enter sessionStorage'); },
  });
  const helpers = runInContext(`${script}\nArchSearchLlm;`, context) as Helpers;
  const controller = helpers.create({ onChange: () => { changes++; }, request: <T>(path: string, init: RequestInit = {}) => new Promise<T>((resolve, reject) => pending.push({ path, init, resolve: value => resolve(value as T), reject })) });
  return { helpers, controller, pending, element: (id: string) => elements.get(id)!, timers, changes: () => changes,
    flushTimers: () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()); } };
}
const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const config: Config = { provider: 'ollama', base_url: 'http://127.0.0.1:11434', model: '', revision: 0, has_api_key: false };
const modelList = { models: [{ id: 'qwen3.5:9b', label: 'qwen3.5:9b' }, { id: 'qwen3.5:2b', label: 'qwen3.5:2b', size_bytes: 2_000_000_000 }], truncated: false };
async function flush(): Promise<void> { for (let i = 0; i < 8; i++) await Promise.resolve(); }
async function start(h: ReturnType<typeof harness>, value: Config = config) {
  const loading = h.controller.load(); h.pending[0].resolve(value); await loading; await flush();
  assert.equal(h.pending[1].path, '/api/llm/models'); h.pending[1].resolve(modelList); await flush();
}

test('Ollama discovery prefers cached Qwen9b and requires explicit application', async () => {
  const h = harness(); await start(h);
  assert.equal(h.element('llm-model').value, 'qwen3.5:9b'); assert.equal(h.controller.ready(), false);
  assert.equal(h.element('llm-enhance').disabled, true); assert.equal(h.element('llm-apply').disabled, false);
  const applying = h.controller.apply(); const call = h.pending.at(-1)!;
  assert.equal(call.path, '/api/llm/config'); assert.deepEqual(JSON.parse(call.init.body as string), { provider: 'ollama', base_url: config.base_url, model: 'qwen3.5:9b', api_key: '', expected_revision: 0 });
  call.resolve({ ...config, model: 'qwen3.5:9b', revision: 1 }); await applying;
  h.controller.setRequested(true); assert.deepEqual(plain(h.controller.requestOptions()), { enhance: true, llm_revision: 1 });
  assert.match(h.element('llm-active-model').textContent, /Ollama.*qwen3.5:9b/u);
});

test('API provider starts with blank address and password without inheriting Ollama endpoint', async () => {
  const h = harness(); await start(h);
  h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  assert.equal(h.element('llm-base-url').value, ''); assert.equal(h.element('llm-api-key').value, '');
  assert.equal(h.element('llm-api-key-group').hidden, false); assert.equal(h.timers.size, 0);
  assert.equal(h.element('llm-model').value, ''); assert.equal(h.element('llm-apply').disabled, true);
});

test('a blank API configuration waits for an endpoint instead of sending a discovery request', async () => {
  const h = harness(); const loading = h.controller.load();
  h.pending[0].resolve({ ...config, provider: 'openai', base_url: '' }); await loading; await flush();
  assert.equal(h.pending.length, 1); assert.equal(h.controller.ready(), false); assert.equal(h.element('llm-error').hidden, true);
});

test('a late initial configuration response preserves API draft fields and their pending discovery', async () => {
  const h = harness(); const loading = h.controller.load();
  h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  h.element('llm-base-url').value = 'https://chosen.example/v1'; h.element('llm-base-url').fire('input');
  h.element('llm-api-key').value = 'new-draft-key'; h.element('llm-api-key').fire('input');
  h.pending[0].resolve({ ...config, revision: 4 }); await loading; await flush();
  assert.equal(h.element('llm-provider').value, 'openai');
  assert.equal(h.element('llm-base-url').value, 'https://chosen.example/v1');
  assert.equal(h.element('llm-api-key').value, 'new-draft-key');
  assert.equal(h.controller.getConfig()?.revision, 4); assert.equal(h.controller.getConfig()?.provider, 'ollama');
  assert.equal(h.pending.length, 1); assert.equal(h.timers.size, 1);
  h.flushTimers(); await flush();
  assert.equal(h.pending.length, 2);
  assert.deepEqual(JSON.parse(h.pending[1].init.body as string), { provider: 'openai', base_url: 'https://chosen.example/v1', api_key: 'new-draft-key' });
  h.pending[1].resolve({ models: [{ id: 'chosen-model', label: 'chosen-model' }] }); await flush();
  h.element('llm-model').value = 'chosen-model';
  const refreshed = h.controller.load(); h.pending[2].resolve({ ...config, revision: 4 }); await refreshed;
  assert.equal(h.element('llm-provider').value, 'openai'); assert.equal(h.element('llm-api-key').value, 'new-draft-key');
  assert.equal(h.element('llm-model').value, 'chosen-model');
});

test('changed endpoint clears credential input and does not inherit a stored credential', async () => {
  const h = harness(); await start(h, { provider: 'openai', base_url: 'https://example.test/v1', model: 'remote', revision: 7, has_api_key: true });
  assert.equal(JSON.parse(h.pending[1].init.body as string).api_key, null);
  h.element('llm-api-key').value = 'fresh-secret'; h.element('llm-base-url').value = 'https://other.test/v1'; h.element('llm-base-url').fire('input');
  assert.equal(h.element('llm-api-key').value, ''); h.flushTimers(); await flush();
  const body = JSON.parse(h.pending.at(-1)!.init.body as string) as Record<string, unknown>;
  assert.equal(body.api_key, ''); assert.equal(body.base_url, 'https://other.test/v1');
  assert.match(h.element('llm-active-model').textContent, /remote/u);
});

test('credentials travel only in same-origin request body and are cleared after application', async () => {
  const h = harness(); await start(h); h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  h.element('llm-base-url').value = 'https://example.test/v1'; h.element('llm-base-url').fire('input');
  h.element('llm-api-key').value = 'sk-only-memory'; h.element('llm-api-key').fire('input'); h.flushTimers(); await flush();
  const discovered = h.pending.at(-1)!; assert.equal(discovered.path, '/api/llm/models'); assert.equal(JSON.parse(discovered.init.body as string).api_key, 'sk-only-memory');
  discovered.resolve({ models: [{ id: 'remote-model', label: '<script>literal name</script>' }] }); await flush();
  h.element('llm-model').value = 'remote-model'; const applying = h.controller.apply();
  assert.equal(JSON.parse(h.pending.at(-1)!.init.body as string).api_key, 'sk-only-memory');
  h.pending.at(-1)!.resolve({ provider: 'openai', base_url: 'https://example.test/v1', model: 'remote-model', revision: 1, has_api_key: true }); await applying;
  assert.equal(h.element('llm-api-key').value, ''); assert.equal(JSON.stringify(h.controller.getConfig()).includes('sk-only-memory'), false);
  assert.match(h.element('llm-model').children[1].textContent, /<script>literal name<\/script>/u);
});

test('late discovery cannot replace models after provider changes even if transport ignores abort', async () => {
  const h = harness(); await start(h); const first = h.controller.discover(); const stale = h.pending.at(-1)!;
  h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  assert.equal(stale.init.signal?.aborted, true);
  stale.resolve({ models: [{ id: 'stale-qwen', label: 'stale-qwen' }] }); await first;
  assert.equal(h.element('llm-model').value, ''); assert.equal(h.element('llm-model').children.some(option => option.value === 'stale-qwen'), false);
});

test('an unavailable model service keeps base search usable and enhanced link can be explicitly disabled', async () => {
  const h = harness(); h.controller.setRequested(true); assert.equal(h.element('llm-enhance').disabled, false);
  const loading = h.controller.load(); h.pending[0].resolve(config); await loading; await flush();
  h.pending[1].reject(new Error('连接失败')); await flush();
  assert.equal(h.controller.ready(), false); assert.match(h.element('llm-error').textContent, /连接失败/u);
  h.controller.setRequested(false); assert.deepEqual(plain(h.controller.requestOptions()), {});
});

test('clearing applied configuration clears server model and credential together and turns enhancement off', async () => {
  const h = harness(); await start(h, { ...config, model: 'qwen3.5:2b', revision: 4 }); h.controller.setRequested(true);
  const clearing = h.controller.apply(true); const body = JSON.parse(h.pending.at(-1)!.init.body as string);
  assert.equal(body.api_key, ''); assert.equal(body.model, ''); assert.equal(body.expected_revision, 4);
  h.pending.at(-1)!.resolve({ ...config, revision: 5 }); await clearing;
  assert.equal(h.controller.enabled(), false); assert.equal(h.controller.ready(), false); assert.deepEqual(plain(h.controller.requestOptions()), {});
});

test('runtime refresh during apply cannot strand the settings in a loading state', async () => {
  const h = harness(); await start(h); const applying = h.controller.apply(); const count = h.pending.length;
  await h.controller.load(); assert.equal(h.pending.length, count);
  h.pending.at(-1)!.resolve({ ...config, model: 'qwen3.5:9b', revision: 1 }); await applying;
  assert.equal(h.element('llm-provider').disabled, false); assert.equal(h.controller.ready(), true);
});

test('failed apply retains the old applied model rather than publishing the draft', async () => {
  const h = harness(); await start(h, { ...config, model: 'qwen3.5:2b', revision: 3 });
  h.element('llm-model').value = 'qwen3.5:9b'; const applying = h.controller.apply(); h.pending.at(-1)!.reject(new Error('配置版本冲突')); await applying;
  assert.equal(h.controller.getConfig()?.model, 'qwen3.5:2b'); assert.equal(h.controller.getConfig()?.revision, 3);
  assert.match(h.element('llm-error').textContent, /配置版本冲突/u);
});

test('a configuration response cannot substitute a different model for the requested selection', async () => {
  const h = harness(); await start(h, { ...config, model: 'qwen3.5:2b', revision: 3 });
  h.element('llm-model').value = 'qwen3.5:9b'; const applying = h.controller.apply();
  h.pending.at(-1)!.resolve({ ...config, model: 'qwen3.5:2b', revision: 4 }); await applying;
  assert.equal(h.controller.getConfig()?.model, 'qwen3.5:2b'); assert.equal(h.controller.getConfig()?.revision, 3);
  assert.match(h.element('llm-error').textContent, /响应与本次应用不一致/u);
});

test('visible errors redact the current credential even if a transport returns it in an exception', async () => {
  const h = harness(); await start(h); h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  h.element('llm-base-url').value = 'https://example.test/v1'; h.element('llm-base-url').fire('input');
  h.element('llm-api-key').value = 'never-display-this'; h.element('llm-api-key').fire('input'); h.flushTimers(); await flush();
  h.pending.at(-1)!.reject(new Error('Rejected never-display-this credential')); await flush();
  assert.equal(h.element('llm-error').textContent.includes('never-display-this'), false); assert.match(h.element('llm-error').textContent, /密钥已隐藏/u);
});

test('discovery rejects duplicate IDs, invalid sizes and malformed configuration', () => {
  const h = harness(); assert.throws(() => h.helpers.parseConfig({ ...config, revision: -1 }));
  assert.throws(() => h.helpers.parseModels({ models: [{ id: 'same', label: 'same' }, { id: 'same', label: 'same' }] }));
  assert.throws(() => h.helpers.parseModels({ models: [{ id: 'model', label: 'model', size_bytes: -1 }] }));
  assert.throws(() => h.helpers.parseModels({ data: [] }));
});

test('base URL validation rejects credentials, parameters, fragments and non-HTTP protocols', () => {
  const h = harness();
  for (const value of ['https://user:secret@example.test/v1', 'https://example.test/v1?api_key=secret', 'https://example.test/v1#secret', 'file:///tmp/a', 'https://example.test/a\\b', 'https://example.test/a\nb']) assert.throws(() => h.helpers.endpoint(value));
  assert.equal(h.helpers.endpoint('https://example.test/v1/'), 'https://example.test/v1');
});

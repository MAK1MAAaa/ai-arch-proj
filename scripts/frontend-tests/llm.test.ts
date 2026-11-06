import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';
import ts from 'typescript';

interface Config { provider: 'ollama' | 'openai'; base_url: string; model: string; revision: number; has_api_key: boolean; key_count?: number; active_key_index?: number | null; config_source?: 'default' | 'env' | 'manual' }
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
  title = ''; isConnected = true; blocked = false; parentMenu: Element | null = null; summary: Element | null = null;
  dataset: Record<string, string> = {};
  onFocus = () => undefined; showCalls = 0; queuedClose = false; closeEvents: (() => void)[] = [];
  bounds = { left: 100, top: 100, right: 700, bottom: 700, width: 600, height: 600 };
  children: Element[] = []; attributes = new Map<string, string>(); tagName: string;
  constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); }
  replaceChildren(...children: Element[]): void { this.children = children; if (this.tagName === 'SELECT') this.value = children[0]?.value ?? ''; }
  setAttribute(key: string, value: string): void { this.attributes.set(key, value); }
  focus(): void { this.onFocus(); }
  closest(selector: string): Element | null { return selector.includes('details') ? this.parentMenu?.open === false ? this.parentMenu : null : this.blocked ? this : null; }
  matches(_selector: string): boolean { return this.disabled; }
  querySelector(_selector: string): Element | null { return this.summary; }
  getBoundingClientRect() { return this.bounds; }
  showModal(): void { if (this.open) throw new Error('Already open'); this.showCalls++; this.open = true; }
  close(): void {
    if (!this.open) return;
    this.open = false;
    const dispatch = () => this.dispatchEvent(new Event('close'));
    if (this.queuedClose) this.closeEvents.push(dispatch); else dispatch();
  }
  flushCloseEvents(): void { for (const dispatch of this.closeEvents.splice(0)) dispatch(); }
  fire(name: string, properties: Record<string, unknown> = {}): Event {
    const event = new Event(name, { cancelable: true });
    for (const [key, value] of Object.entries(properties)) Object.defineProperty(event, key, { value });
    this.dispatchEvent(event); return event;
  }
  pressEscape(): void { if (!this.fire('cancel').defaultPrevented) this.close(); }
  set innerHTML(_value: string) { throw new Error('Unsafe innerHTML'); }
}
interface Pending { path: string; init: RequestInit; resolve(value: unknown): void; reject(error: Error): void }
const source = readFileSync('src/archsearch/frontend/llm.ts', 'utf8');
const script = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } }).outputText;
function harness() {
  const ids = ['llm-settings', 'llm-settings-form', 'llm-open-settings', 'llm-close-settings', 'llm-config-summary', 'llm-provider', 'llm-base-url', 'llm-api-key', 'llm-api-key-group', 'llm-key-hint', 'llm-model', 'llm-refresh-models', 'llm-apply', 'llm-clear-config', 'llm-enhance', 'llm-active-model', 'llm-feedback', 'llm-provider-note', 'llm-error'];
  const elements = new Map(ids.map(id => [id, new Element(['llm-provider', 'llm-model'].includes(id) ? 'select' : 'div')]));
  const document = { activeElement: null as Element | null, body: new Element('body'), getElementById: (id: string) => elements.get(id), createElement: (tag: string) => new Element(tag) };
  for (const element of elements.values()) element.onFocus = () => { document.activeElement = element; };
  const window = new EventTarget(); let openings = 0;
  window.addEventListener('archsearch:modelsettingsopen', () => openings++);
  elements.get('llm-provider')!.value = 'ollama'; elements.get('llm-base-url')!.value = 'http://127.0.0.1:11434';
  const pending: Pending[] = []; const timers = new Map<number, () => void>(); let counter = 0; let changes = 0;
  const context = createContext({ URL, AbortController, Error, HTMLElement: Element, Event, document, window,
    setTimeout: (fn: () => void) => { const key = ++counter; timers.set(key, fn); return key; },
    clearTimeout: (key: number) => timers.delete(key),
    get localStorage() { throw new Error('Credentials must not enter localStorage'); },
    get sessionStorage() { throw new Error('Credentials must not enter sessionStorage'); },
  });
  const helpers = runInContext(`${script}\nArchSearchLlm;`, context) as Helpers;
  const controller = helpers.create({ onChange: () => { changes++; }, request: <T>(path: string, init: RequestInit = {}) => new Promise<T>((resolve, reject) => pending.push({ path, init, resolve: value => resolve(value as T), reject })) });
  return { helpers, controller, pending, document, window, openings: () => openings, element: (id: string) => elements.get(id)!, timers, changes: () => changes,
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

test('model settings open once on demand, focus their close action and restore the trigger without applying', () => {
  const h = harness(), trigger = h.element('llm-open-settings'), dialog = h.element('llm-settings');
  assert.equal(dialog.open, false); assert.equal(h.element('llm-active-model').textContent, '未配置');
  trigger.focus(); trigger.fire('click'); h.controller.showSettings();
  assert.equal(dialog.open, true); assert.equal(dialog.showCalls, 1); assert.equal(h.openings(), 1);
  assert.equal(trigger.attributes.get('aria-expanded'), 'true');
  assert.equal(h.document.activeElement, h.element('llm-close-settings'));
  h.element('llm-close-settings').fire('click');
  assert.equal(dialog.open, false); assert.equal(h.document.activeElement, trigger);
  assert.equal(trigger.attributes.get('aria-expanded'), 'false'); assert.equal(h.pending.length, 0);
  assert.equal(h.controller.enabled(), false); assert.deepEqual(plain(h.controller.requestOptions()), {});
});

test('only a click outside the model dialog bounds closes it and native Escape restores focus', () => {
  const h = harness(), dialog = h.element('llm-settings'), trigger = h.element('llm-open-settings');
  trigger.focus(); h.controller.showSettings();
  dialog.fire('click', { clientX: 101, clientY: 101 });
  assert.equal(dialog.open, true, 'Dialog padding is inside the dialog.');
  dialog.fire('click', { clientX: 90, clientY: 90 });
  assert.equal(dialog.open, false); assert.equal(h.document.activeElement, trigger);
  h.controller.showSettings(); dialog.pressEscape();
  assert.equal(dialog.open, false); assert.equal(h.document.activeElement, trigger);
});

test('removed, disabled, hidden or collapsed-menu openers fall back to the visible model trigger', () => {
  const h = harness(), opener = new Element('button'), dialog = h.element('llm-settings');
  opener.onFocus = () => { h.document.activeElement = opener; };
  for (const unavailable of ['removed', 'disabled', 'hidden', 'collapsed'] as const) {
    opener.isConnected = unavailable !== 'removed'; opener.disabled = unavailable === 'disabled'; opener.blocked = unavailable === 'hidden';
    opener.parentMenu = unavailable === 'collapsed' ? new Element('details') : null;
    opener.focus(); h.controller.showSettings(); dialog.pressEscape();
    assert.equal(h.document.activeElement, h.element('llm-open-settings'), unavailable);
  }
  opener.isConnected = true; opener.disabled = false; opener.blocked = false; opener.parentMenu = null;
  opener.focus(); h.controller.showSettings(); dialog.pressEscape();
  assert.equal(h.document.activeElement, opener);
});

test('a queued old close does not steal focus or replace the opener after the model dialog reopens', () => {
  const h = harness(), dialog = h.element('llm-settings'), first = new Element(), second = new Element();
  first.onFocus = () => { h.document.activeElement = first; }; second.onFocus = () => { h.document.activeElement = second; };
  dialog.queuedClose = true;
  first.focus(); h.controller.showSettings(); dialog.close();
  second.focus(); h.controller.showSettings(); dialog.flushCloseEvents();
  assert.equal(dialog.open, true); assert.equal(h.document.activeElement, h.element('llm-close-settings'));
  dialog.close(); dialog.flushCloseEvents(); assert.equal(h.document.activeElement, second);
});

test('closing keeps API drafts and late responses cannot reopen settings or steal subsequent focus', async () => {
  const h = harness(), loading = h.controller.load();
  h.element('llm-open-settings').focus(); h.controller.showSettings();
  h.element('llm-provider').value = 'openai'; h.element('llm-provider').fire('change');
  h.element('llm-base-url').value = 'https://draft.example/v1'; h.element('llm-base-url').fire('input');
  h.element('llm-api-key').value = 'fixture-dialog-draft'; h.element('llm-api-key').fire('input'); h.flushTimers();
  h.element('llm-close-settings').fire('click'); const nextControl = new Element(); h.document.activeElement = nextControl;
  h.pending[0].resolve({ ...config, model: 'qwen3.5:2b', revision: 2 }); await loading;
  h.pending[1].resolve({ models: [{ id: 'draft-model', label: 'draft-model' }] }); await flush();
  assert.equal(h.element('llm-settings').open, false); assert.equal(h.document.activeElement, nextControl);
  assert.equal(h.element('llm-provider').value, 'openai'); assert.equal(h.element('llm-base-url').value, 'https://draft.example/v1');
  assert.equal(h.element('llm-api-key').value, 'fixture-dialog-draft'); assert.equal(h.controller.getConfig()?.model, 'qwen3.5:2b');
  assert.equal(h.controller.enabled(), false); assert.equal(h.pending.filter(call => call.path === '/api/llm/config' && call.init.method === 'POST').length, 0);
});

test('long model names stay short in the toolbar while the full status distinguishes optional LLM from E5', async () => {
  const h = harness(), longModel = 'research-model-' + 'long-context-'.repeat(14);
  await start(h, { ...config, model: longModel, revision: 3 });
  const active = h.element('llm-active-model'), summary = h.element('llm-config-summary');
  assert.ok(active.textContent.length < 40); assert.match(active.textContent, /…$/u);
  assert.equal(active.title.includes(longModel), true); assert.equal(summary.textContent.includes(longModel), true);
  assert.match(summary.textContent, /LLM 增强未开启.*本地 E5/u);
  assert.equal(h.controller.enabled(), false); assert.deepEqual(plain(h.controller.requestOptions()), {});
  h.element('llm-enhance').checked = true; h.element('llm-enhance').fire('change');
  assert.match(summary.textContent, /LLM 增强已开启/u);
  assert.equal(h.element('llm-open-settings').dataset.configured, 'true');
  assert.equal(h.element('llm-open-settings').dataset.enhanced, 'true');
  assert.equal(h.element('llm-open-settings').attributes.get('aria-label')?.includes(longModel), true);
  h.controller.showSettings(); h.element('llm-close-settings').fire('click');
  assert.equal(h.controller.enabled(), true);
  assert.deepEqual(plain(h.controller.requestOptions()), { enhance: true, llm_revision: 3 });
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

test('environment configuration hydrates safe pool metadata and auto discovers without enabling enhancement', async () => {
  const h = harness();
  await start(h, { provider: 'openai', base_url: 'https://env.example/v1', model: 'env-model',
    revision: 7, has_api_key: true, key_count: 2, active_key_index: null, config_source: 'env' });
  assert.equal(h.element('llm-base-url').value, 'https://env.example/v1');
  assert.equal(h.controller.getConfig()?.model, 'env-model');
  assert.equal(h.controller.getConfig()?.key_count, 2);
  assert.equal(h.element('llm-api-key').value, '');
  assert.equal(JSON.parse(h.pending[1].init.body as string).api_key, null);
  assert.equal(h.controller.enabled(), false); assert.deepEqual(plain(h.controller.requestOptions()), {});
  assert.match(h.element('llm-config-summary').textContent, /env-model.*环境配置/u);
  assert.match(h.element('llm-key-hint').textContent, /2 个密钥.*尚未确认.*环境配置/u);
});

test('successful discovery publishes only matching revision slot metadata without changing model or revision', async () => {
  const h = harness();
  await start(h, { provider: 'openai', base_url: 'https://env.example/v1', model: 'env-model',
    revision: 7, has_api_key: true, key_count: 2, active_key_index: null, config_source: 'env' });
  const discovering = h.controller.discover();
  h.pending.at(-1)!.resolve({ models: [{ id: 'env-model', label: 'env-model' }], key_count: 2,
    active_key_index: 1, config_source: 'env', config_revision: 7 }); await discovering;
  assert.equal(h.controller.getConfig()?.active_key_index, 1);
  assert.equal(h.controller.getConfig()?.revision, 7); assert.equal(h.controller.getConfig()?.model, 'env-model');
  assert.match(h.element('llm-key-hint').textContent, /上次成功槽位 2\/2/u);
  h.controller.setRequested(true); assert.deepEqual(plain(h.controller.requestOptions()), { enhance: true, llm_revision: 7 });
});

test('old model-list metadata cannot rewrite a different current configuration revision', async () => {
  const h = harness();
  await start(h, { provider: 'openai', base_url: 'https://env.example/v1', model: 'env-model',
    revision: 7, has_api_key: true, key_count: 2, active_key_index: null, config_source: 'env' });
  const discovering = h.controller.discover();
  h.pending.at(-1)!.resolve({ models: [{ id: 'env-model', label: 'env-model' }], key_count: 2,
    active_key_index: 1, config_source: 'manual', config_revision: 6 }); await discovering;
  assert.equal(h.controller.getConfig()?.active_key_index, null);
  assert.equal(h.controller.getConfig()?.config_source, 'env'); assert.equal(h.controller.getConfig()?.revision, 7);
});

test('a draft single-key override does not replace the applied pool until apply succeeds', async () => {
  const h = harness();
  await start(h, { provider: 'openai', base_url: 'https://env.example/v1', model: 'env-model',
    revision: 7, has_api_key: true, key_count: 2, active_key_index: 1, config_source: 'env' });
  h.element('llm-api-key').value = 'fixture-single-override'; h.element('llm-api-key').fire('input');
  h.flushTimers(); await flush();
  h.pending.at(-1)!.resolve({ models: [{ id: 'chosen-model', label: 'chosen-model' }],
    key_count: 1, active_key_index: 0, config_source: 'manual', config_revision: 7 }); await flush();
  assert.equal(h.controller.getConfig()?.key_count, 2);
  assert.equal(h.controller.getConfig()?.active_key_index, 1);
  h.element('llm-model').value = 'chosen-model'; const applying = h.controller.apply();
  h.pending.at(-1)!.resolve({ provider: 'openai', base_url: 'https://env.example/v1', model: 'chosen-model',
    revision: 8, has_api_key: true, key_count: 1, active_key_index: 0, config_source: 'manual' }); await applying;
  assert.equal(h.controller.getConfig()?.key_count, 1); assert.equal(h.element('llm-api-key').value, '');
  assert.equal(JSON.stringify(h.controller.getConfig()).includes('fixture-single-override'), false);
});

test('clearing an environment pool explains that its local file is unchanged and may reload', async () => {
  const h = harness();
  await start(h, { provider: 'openai', base_url: 'https://env.example/v1', model: 'env-model',
    revision: 7, has_api_key: true, key_count: 2, active_key_index: 1, config_source: 'env' });
  const clearing = h.controller.apply(true);
  assert.equal(JSON.parse(h.pending.at(-1)!.init.body as string).api_key, '');
  h.pending.at(-1)!.resolve({ provider: 'openai', base_url: 'https://env.example/v1', model: '', revision: 8,
    has_api_key: false, key_count: 0, active_key_index: null, config_source: 'manual' }); await clearing;
  assert.equal(h.controller.getConfig()?.key_count, 0); assert.equal(h.controller.enabled(), false);
  assert.match(h.element('llm-feedback').textContent, /\.env 未修改.*重启.*重新读取/u);
});

test('pool metadata rejects invalid count, slot, source and hidden credential properties', () => {
  const h = harness();
  for (const update of [{ key_count: 9 }, { key_count: null }, { key_count: -1 },
    { key_count: 0, active_key_index: 0 }, { key_count: 2, has_api_key: false },
    { key_count: 2, has_api_key: true, active_key_index: 2 }, { config_source: 'untrusted' }]) {
    assert.throws(() => h.helpers.parseConfig({ ...config, ...update }));
  }
  const safe = h.helpers.parseConfig({ ...config, api_keys: ['fixture-private-value'],
    key_count: 0, active_key_index: null, config_source: 'default' });
  assert.equal(JSON.stringify(safe).includes('fixture-private-value'), false);
  assert.equal('api_keys' in safe, false);
});

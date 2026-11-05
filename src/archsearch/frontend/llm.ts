const ArchSearchLlm = (() => {
  "use strict";

  type Provider = "ollama" | "openai";
  type ConfigSource = "default" | "env" | "manual";
  interface PoolMetadata { key_count: number; active_key_index: number | null; config_source: ConfigSource }
  interface PublicConfig extends PoolMetadata { provider: Provider; base_url: string; model: string; revision: number; has_api_key: boolean }
  interface Model { id: string; label: string; size_bytes?: number | null }
  interface RequestOptions { enhance?: true; llm_revision?: number }
  interface Options {
    onChange(): void;
    request?<T>(path: string, options?: RequestInit): Promise<T>;
    debounceMs?: number;
  }

  function record(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function parseConfig(value: unknown): PublicConfig {
    if (!record(value) || !["ollama", "openai"].includes(String(value.provider))
      || typeof value.base_url !== "string" || typeof value.model !== "string"
      || typeof value.has_api_key !== "boolean" || !Number.isSafeInteger(value.revision)
      || (value.revision as number) < 0) throw new Error("模型配置响应无效，请重新加载配置。");
    const pool = parsePool(value, value.has_api_key);
    return { provider: value.provider as Provider, base_url: value.base_url, model: value.model,
      revision: value.revision as number, has_api_key: value.has_api_key, ...pool };
  }

  function parsePool(value: Record<string, unknown>, hasKey?: boolean): PoolMetadata {
    const count = value.key_count === undefined ? (hasKey ? 1 : 0) : value.key_count;
    const active = value.active_key_index ?? null;
    const source = value.config_source ?? "manual";
    if (!Number.isSafeInteger(count) || (count as number) < 0 || (count as number) > 8
      || (hasKey !== undefined && Boolean(count) !== hasKey)
      || (active !== null && (!Number.isSafeInteger(active) || (active as number) < 0 || (active as number) >= (count as number)))
      || !["default", "env", "manual"].includes(String(source))) throw new Error("密钥列表状态响应无效。");
    return { key_count: count as number, active_key_index: active as number | null, config_source: source as ConfigSource };
  }

  function parseModels(value: unknown): { models: Model[]; truncated: boolean; pool: PoolMetadata | null; configRevision: number | null } {
    if (!record(value) || !Array.isArray(value.models) || value.models.length > 500) throw new Error("模型列表响应无效。");
    const ids = new Set<string>();
    const models = value.models.map((item: unknown): Model => {
      if (!record(item) || typeof item.id !== "string" || !item.id.trim() || item.id.length > 512
        || /[\u0000-\u001f\u007f]/u.test(item.id) || typeof item.label !== "string" || item.label.length > 1024
        || ids.has(item.id)) throw new Error("模型列表包含无效或重复编号。");
      if (item.size_bytes !== undefined && item.size_bytes !== null
        && (typeof item.size_bytes !== "number" || !Number.isSafeInteger(item.size_bytes) || item.size_bytes < 0)) throw new Error("模型体积字段无效。");
      ids.add(item.id);
      return { id: item.id, label: item.label, ...(typeof item.size_bytes === "number" ? { size_bytes: item.size_bytes } : {}) };
    });
    const pool = value.key_count === null || value.key_count === undefined ? null : parsePool(value);
    const revision = value.config_revision ?? null;
    if (revision !== null && (!Number.isSafeInteger(revision) || (revision as number) < 0)) throw new Error("模型列表配置版本无效。");
    return { models, truncated: value.truncated === true, pool, configRevision: revision as number | null };
  }

  function endpoint(value: string): string {
    const url = new URL(value.trim());
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /[\u0000-\u0020\u007f\\]/u.test(value.trim())) throw new Error("Base URL 仅支持不含密钥、查询参数和片段的 HTTP(S) 地址。");
    return url.href.replace(/\/+$/u, "");
  }

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(path, { ...options, headers: { "Accept": "application/json", "Content-Type": "application/json", ...options.headers } });
    let data: unknown;
    try { data = await response.json(); }
    catch { throw new Error(`模型服务响应无法读取（HTTP ${response.status}）。`); }
    if (!response.ok) {
      const detail = record(data) ? data.detail : null;
      const text = typeof detail === "string" ? detail : Array.isArray(detail)
        ? detail.map((item: unknown) => record(item) && typeof item.msg === "string" ? item.msg : "配置参数无效").join("；") : null;
      throw new Error(text || `模型请求未完成（HTTP ${response.status}）。`);
    }
    return data as T;
  }

  function create(options: Options) {
    const node = <T extends HTMLElement>(id: string): T => {
      const found = document.getElementById(id);
      if (!found) throw new Error(`模型设置元素缺失：${id}`);
      return found as T;
    };
    const ui = {
      panel: node<HTMLDetailsElement>("llm-settings"), form: node<HTMLFormElement>("llm-settings-form"),
      provider: node<HTMLSelectElement>("llm-provider"), base: node<HTMLInputElement>("llm-base-url"),
      key: node<HTMLInputElement>("llm-api-key"), keyGroup: node<HTMLDivElement>("llm-api-key-group"),
      keyHint: node<HTMLParagraphElement>("llm-key-hint"), model: node<HTMLSelectElement>("llm-model"),
      refresh: node<HTMLButtonElement>("llm-refresh-models"), apply: node<HTMLButtonElement>("llm-apply"),
      clear: node<HTMLButtonElement>("llm-clear-config"), enabled: node<HTMLInputElement>("llm-enhance"),
      active: node<HTMLSpanElement>("llm-active-model"), feedback: node<HTMLParagraphElement>("llm-feedback"),
      privacy: node<HTMLParagraphElement>("llm-provider-note"), error: node<HTMLParagraphElement>("llm-error"),
    };
    const send = options.request ?? request;
    let config: PublicConfig | null = null;
    let models: Model[] = [];
    let discoverySequence = 0;
    let configSequence = 0;
    let discoveryController: AbortController | null = null;
    let discoveryTimer: ReturnType<typeof setTimeout> | null = null;
    let discovering = false;
    let applying = false;
    let draftChanged = false;
    let keyCleared = false;
    let initialized = false;

    function provider(): Provider { return ui.provider.value === "openai" ? "openai" : "ollama"; }
    function sameEndpoint(): boolean {
      try { return config !== null && config.provider === provider() && endpoint(config.base_url) === endpoint(ui.base.value); }
      catch { return false; }
    }
    function keyValue(): string | null {
      return ui.key.value || (!keyCleared && sameEndpoint() ? null : "");
    }
    function safeError(error: unknown): string {
      const message = error instanceof Error ? error.message : "模型请求未完成。";
      return ui.key.value ? message.split(ui.key.value).join("[密钥已隐藏]") : message;
    }
    function notify(): void { render(); options.onChange(); }
    function render(): void {
      const ready = config !== null && Boolean(config.model);
      const source = config?.config_source === "env" ? "环境配置" : config?.config_source === "default" ? "默认设置" : "会话设置";
      ui.enabled.disabled = !ready && !ui.enabled.checked;
      ui.active.textContent = config?.model ? `已应用 ${config.provider === "ollama" ? "Ollama" : "API"} · ${config.model} · ${source}` : "LLM 未配置";
      ui.keyGroup.hidden = provider() !== "openai";
      ui.key.disabled = provider() !== "openai" || applying;
      ui.provider.disabled = applying;
      ui.base.disabled = applying;
      ui.model.disabled = applying || discovering || models.length === 0;
      ui.refresh.disabled = applying || !ui.base.value.trim();
      ui.apply.disabled = applying || discovering || !models.some((item) => item.id === ui.model.value);
      ui.clear.disabled = applying || config === null || (!config.model && !config.has_api_key);
      ui.refresh.textContent = discovering ? "重新获取模型" : "刷新模型列表";
      ui.apply.textContent = applying ? "正在应用" : "应用所选模型";
      ui.form.setAttribute("aria-busy", String(applying || discovering));
      ui.keyHint.textContent = !keyCleared && sameEndpoint() && config?.has_api_key
        ? `当前地址已配置 ${config.key_count} 个密钥；${config.active_key_index === null ? "尚未确认可用槽位" : `上次成功槽位 ${config.active_key_index + 1}/${config.key_count}`}；来源：${source}。留空保留整个列表，填写新值会作为本会话单个密钥替换。`
        : "可留空；填写新值会在本会话中使用单个密钥，不写入分享链接、导出或浏览器存储。";
      ui.privacy.textContent = provider() === "ollama"
        ? "从 Windows 后端连接本机 Ollama；仅列出已有模型，不会自动下载。优先测试 qwen3.5:9b，2b 可作速度优先备选。"
        : "填写 OpenAI 兼容服务地址（通常以 /v1 结尾）；开启增强后只发送查询，不发送资料正文。";
      if (draftChanged && config?.model && !discovering && !applying && ui.error.hidden) ui.feedback.textContent = `草稿尚未应用；下一次增强仍使用 ${config.model}。`;
    }
    function showError(value: string): void { ui.error.textContent = value; ui.error.hidden = !value; }
    function clearModels(): void {
      models = [];
      const empty = document.createElement("option");
      empty.value = ""; empty.textContent = "先获取模型列表";
      ui.model.replaceChildren(empty);
    }
    function invalidateDiscovery(): void {
      discoverySequence += 1;
      discoveryController?.abort(); discoveryController = null;
      if (discoveryTimer !== null) clearTimeout(discoveryTimer);
      discoveryTimer = null; discovering = false;
      clearModels();
    }
    function schedule(): void {
      invalidateDiscovery(); showError(""); draftChanged = true;
      ui.feedback.textContent = ui.base.value.trim() ? "等待连接信息输入完成后获取模型。" : "填写 Base URL 后自动获取模型。";
      notify();
      if (!ui.base.value.trim()) return;
      discoveryTimer = setTimeout(() => { discoveryTimer = null; void discover(); }, options.debounceMs ?? 400);
    }
    async function discover(): Promise<void> {
      invalidateDiscovery(); showError("");
      let base: string;
      try { base = endpoint(ui.base.value); }
      catch (error) { showError(safeError(error)); notify(); return; }
      const sequence = discoverySequence;
      const controller = new AbortController(); discoveryController = controller;
      const appliedPool = provider() === "openai" && sameEndpoint() && keyValue() === null;
      const appliedRevision = config?.revision ?? null;
      discovering = true; ui.feedback.textContent = "正在获取服务端已有模型。"; notify();
      try {
        const data = parseModels(await send<unknown>("/api/llm/models", {
          method: "POST", signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: provider(), base_url: base, api_key: provider() === "openai" ? keyValue() : "" }),
        }));
        if (sequence !== discoverySequence || controller.signal.aborted) return;
        if (appliedPool && config && config.revision === appliedRevision && data.configRevision === appliedRevision && data.pool) {
          if (data.pool.key_count !== config.key_count) throw new Error("模型列表密钥状态与已应用配置不一致。");
          config = { ...config, ...data.pool };
        }
        models = data.models.filter((item) => !ui.key.value || (!item.id.includes(ui.key.value) && !item.label.includes(ui.key.value)));
        const empty = document.createElement("option"); empty.value = ""; empty.textContent = models.length ? "选择一个模型" : "服务未提供可选模型";
        const entries = models.map((item) => {
          const option = document.createElement("option"); option.value = item.id;
          option.textContent = `${item.label}${typeof item.size_bytes === "number" ? ` · 文件 ${(item.size_bytes / 1_000_000_000).toFixed(1)} GB` : ""}`;
          return option;
        });
        ui.model.replaceChildren(empty, ...entries);
        const previous = sameEndpoint() && models.some((item) => item.id === config?.model) ? config?.model : null;
        ui.model.value = previous ?? models.find((item) => item.id === "qwen3.5:9b")?.id
          ?? models.find((item) => item.id === "qwen3.5:2b")?.id ?? "";
        ui.feedback.textContent = models.length ? `已获取 ${models.length} 个模型${data.truncated ? "（列表已截断）" : ""}；选择后点击“应用所选模型”。` : "未发现模型。请在 Ollama 中准备 Qwen 模型后刷新。";
      } catch (error) {
        if (sequence !== discoverySequence || controller.signal.aborted) return;
        showError(`模型列表获取失败：${safeError(error)}`);
        ui.feedback.textContent = "基础检索继续可用；检查服务地址后可以重试。";
      } finally {
        if (sequence === discoverySequence) { discovering = false; discoveryController = null; notify(); }
      }
    }
    async function apply(clear = false): Promise<void> {
      if (applying) return;
      showError("");
      if (!clear && !models.some((item) => item.id === ui.model.value)) { showError("先获取模型列表并选择模型。"); notify(); return; }
      let base: string;
      try { base = clear && config ? config.base_url : endpoint(ui.base.value); }
      catch (error) { showError(safeError(error)); notify(); return; }
      const sequence = ++configSequence;
      applying = true; notify();
      try {
        const body = {
          provider: clear && config ? config.provider : provider(), base_url: base,
          model: clear ? "" : ui.model.value, api_key: clear || provider() === "ollama" ? "" : keyValue(),
          expected_revision: config?.revision ?? 0,
        };
        const saved = parseConfig(await send<unknown>("/api/llm/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
        if (sequence !== configSequence) return;
        if (saved.provider !== body.provider || saved.model !== body.model || endpoint(saved.base_url) !== endpoint(body.base_url)
          || saved.revision !== body.expected_revision + 1 || (clear && saved.has_api_key)) throw new Error("配置响应与本次应用不一致，请刷新配置后重试。");
        config = saved; ui.key.value = ""; keyCleared = false; draftChanged = false;
        ui.provider.value = saved.provider; ui.base.value = saved.base_url;
        if (clear) { invalidateDiscovery(); ui.enabled.checked = false; }
        else ui.model.value = saved.model;
        ui.feedback.textContent = clear ? "已清除运行内存中的模型与密钥；本地 .env 未修改，重启时会重新读取。LLM 增强已关闭。" : `已应用 ${saved.model}；勾选“LLM 增强”后用于下一次检索。`;
      } catch (error) {
        if (sequence === configSequence) showError(`配置未应用：${safeError(error)}`);
      } finally { if (sequence === configSequence) { applying = false; notify(); } }
    }
    async function load(): Promise<void> {
      if (applying) return;
      const sequence = ++configSequence;
      try {
        const value = parseConfig(await send<unknown>("/api/llm/config"));
        if (sequence !== configSequence) return;
        const previous = config;
        config = value;
        const hydrate = !draftChanged && (!initialized || value.provider !== previous?.provider || value.base_url !== previous?.base_url
          || value.model !== previous?.model || value.revision !== previous?.revision);
        initialized = true;
        if (hydrate) {
          showError(""); invalidateDiscovery(); keyCleared = false;
          ui.provider.value = value.provider; ui.base.value = value.base_url; ui.key.value = "";
          ui.feedback.textContent = value.model ? `已加载${value.config_source === "env" ? "环境配置" : "当前会话"}中的 ${value.model}。` : "获取已有模型并应用后，可开启 LLM 增强。";
          notify(); if (ui.base.value.trim()) void discover();
        } else notify();
      } catch (error) {
        if (sequence !== configSequence) return;
        showError(`模型配置加载失败：${safeError(error)}`); notify();
      }
    }

    ui.provider.addEventListener("change", () => {
      ui.base.value = provider() === "ollama" ? "http://127.0.0.1:11434" : "";
      ui.key.value = ""; keyCleared = true; schedule();
    });
    ui.base.addEventListener("input", () => { ui.key.value = ""; keyCleared = true; schedule(); });
    ui.key.addEventListener("input", () => { keyCleared = true; schedule(); });
    ui.model.addEventListener("change", () => { draftChanged = true; showError(""); notify(); });
    ui.refresh.addEventListener("click", () => { void discover(); });
    ui.form.addEventListener("submit", (event) => { event.preventDefault(); void apply(); });
    ui.clear.addEventListener("click", () => { void apply(true); });
    ui.enabled.addEventListener("change", () => { options.onChange(); });
    clearModels(); render();
    return {
      load, discover, apply,
      ready: () => config !== null && Boolean(config.model),
      enabled: () => ui.enabled.checked,
      getConfig: () => config ? { ...config } : null,
      setRequested(value: boolean): void { ui.enabled.checked = value; render(); options.onChange(); },
      requestOptions(): RequestOptions { return ui.enabled.checked ? { enhance: true, ...(config?.model ? { llm_revision: config.revision } : {}) } : {}; },
      showSettings(): void { ui.panel.open = true; },
    };
  }

  return { create, parseConfig, parseModels, endpoint };
})();

const ArchSearchResearch = (() => {
  "use strict";

  interface SearchSpec {
    query: string;
    mode: "semantic" | "bm25";
    type: string | null;
    limit: number;
  }

  interface ParsedLink {
    request: SearchSpec | null;
    error: string | null;
  }

  interface SearchResponse<T> {
    query: string;
    mode: "semantic" | "bm25";
    corpus_version: string;
    elapsed_ms: number;
    total_candidates: number;
    results: T[];
  }

  const parameterNames = ["q", "mode", "type", "limit"] as const;

  function normalizeRequest(request: SearchSpec): SearchSpec {
    const query = request.query.trim();
    if (!query || Array.from(query).length > 500) {
      throw new Error("链接中的 q 必须包含 1 至 500 个字符。");
    }
    if (request.mode !== "semantic" && request.mode !== "bm25") {
      throw new Error("链接中的 mode 仅支持 semantic 或 bm25。");
    }
    if (request.limit !== 10 && request.limit !== 20 && request.limit !== 50) {
      throw new Error("链接中的 limit 仅支持 10、20 或 50。");
    }
    const type = request.type === "" ? null : request.type;
    if (type !== null && (Array.from(type).length > 128 || /[\u0000-\u001f\u007f-\u009f]/u.test(type))) {
      throw new Error("链接中的 type 必须是不超过 128 个字符且不含控制字符的类型 ID。");
    }
    return { query, mode: request.mode, type, limit: request.limit };
  }

  function parseLink(url: URL): ParsedLink {
    const parameters = url.searchParams;
    if (!parameterNames.some((name) => parameters.has(name))) return { request: null, error: null };
    for (const name of parameterNames) {
      if (parameters.getAll(name).length > 1) {
        return { request: null, error: `链接中的 ${name} 参数不能重复。` };
      }
    }
    const mode = parameters.get("mode") ?? "semantic";
    if (mode !== "semantic" && mode !== "bm25") {
      return { request: null, error: "链接中的 mode 仅支持 semantic 或 bm25。" };
    }
    const limit = parameters.get("limit") ?? "10";
    if (limit !== "10" && limit !== "20" && limit !== "50") {
      return { request: null, error: "链接中的 limit 仅支持 10、20 或 50。" };
    }
    try {
      const request = normalizeRequest({
        query: parameters.get("q") ?? "",
        mode,
        type: parameters.get("type"),
        limit: Number(limit),
      });
      return { request, error: null };
    } catch (error) {
      return { request: null, error: error instanceof Error ? error.message : "检索链接参数无效。" };
    }
  }

  function buildLink(base: URL, request: SearchSpec): string {
    const normalized = normalizeRequest(request);
    if (base.protocol !== "http:" && base.protocol !== "https:") {
      throw new Error("检索链接仅支持 HTTP 或 HTTPS 页面。");
    }
    const url = new URL(base.origin);
    url.pathname = base.pathname;
    url.searchParams.set("q", normalized.query);
    url.searchParams.set("mode", normalized.mode);
    url.searchParams.set("type", normalized.type ?? "");
    url.searchParams.set("limit", String(normalized.limit));
    return url.href;
  }

  function createExport<T>(request: SearchSpec, response: SearchResponse<T>, exportedAt: string) {
    const normalized = normalizeRequest(request);
    if (normalized.query !== response.query || normalized.mode !== response.mode) {
      throw new Error("导出请求必须与成功响应的查询和检索方式一致。");
    }
    return {
      schema_version: 1,
      exported_at: exportedAt,
      request: normalized,
      response,
      source: {
        name: "Pleiades: A Gazetteer of Past Places",
        version: "v4.1",
        uri: "https://pleiades.stoa.org/",
        release_uri: "https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1",
        commit: "b6a6790f71c45e4a4ef60fce296c506f28f458bf",
        license: "CC BY 3.0",
        license_uri: "https://creativecommons.org/licenses/by/3.0/",
        attribution: "Copyright The Contributors. Pleiades, Ancient World Mapping Center and Institute for the Study of the Ancient World.",
      },
      provenance: {
        processing: "来源资料经 HTML 转纯文本和空白规范化；别名、类型、分期证据、原文出处和贡献者随结果保留，未生成历史事实或补造坐标。",
        scope: "地中海周边矩形范围内的 500 条演示资料；不代表完整遗址清单或历史边界。",
        coordinates: "repr_point 为 WGS84 [经度, 纬度] 代表点，用于地图定位；不等同于实测发掘坐标，location_precision 不承诺米级精度。",
        scores: "检索分数不是相关概率，不同检索方式的分数不可直接比较；本导出不包含人工相关性判断或评测指标。",
        periods: "分期来自名称或位置记录的来源关联；不等同于建造年代或连续使用证明，start/end 保留原始记录时间范围。",
      },
    };
  }

  return { parseLink, buildLink, createExport };
})();

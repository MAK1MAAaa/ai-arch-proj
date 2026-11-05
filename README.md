# 考古图志 · ArchSearch

本地运行的文化遗址检索与历史地图网页，当前包含3897项资料。

## 日常启动

使用本地 Ollama 增强时，先打开 Ollama 程序，或在另一个终端运行 `ollama serve`；已经运行时无需重复启动。基础检索可以单独运行。在 Windows PowerShell 中执行：

```powershell
cd D:\Github\ai-arch-proj
uv run --no-sync archsearch serve
```

浏览器打开 **http://127.0.0.1:8000/**，运行状态见 **http://127.0.0.1:8000/api/status**。保持终端运行；按 `Ctrl+C` 停止，再执行启动命令即可重启。

## 首次安装或准备数据

需要 Python 3.12 和 uv。在仓库根目录执行：

```powershell
uv sync --locked --dev
uv run --no-sync archsearch prepare
uv run --no-sync archsearch prepare-history
uv run --no-sync archsearch serve
```

首次准备需联网下载固定版本的 E5 模型和历史地图数据；准备完成后，检索及历史地图可离线使用，现代 OSM 瓦片仍需联网。更新语料后重新运行 `prepare` 并重启服务；日常启动无需重复准备。

模型、索引及历史库默认保存在仓库根目录的 `.archsearch/`。基础检索无需 Node.js、pnpm 或 GPU；LLM 通过单独运行的 Ollama 或 API 服务提供。

## 当前检索模型

基础检索为本地 **`intfloat/multilingual-e5-small`**（CPU），可切换 **BM25**。启用 **LLM 增强**后，先改写查询，再融合本地检索排名；资料原文和地图位置不由模型生成。

展开“查询增强与模型设置”，选择 Ollama，等待自动获取模型列表，选择本机已缓存的 **`qwen3.5:9b`** 并“应用所选模型”，再勾选“LLM 增强”检索。`qwen3.5:2b` 可作为速度优先的备选；应用只获取列表，不自动下载模型。

API 配置初始留空。需要时选择“OpenAI 兼容 API”，填写 **Base URL**、**API Key**，从获取的列表选择模型并应用。配置仅保留在服务内存中，重启后需重新设置。操作、实测与限制见[LLM 增强说明](docs/llm-search.md)。

中文专名仍可能漏检，模型改写也可能误译；请核对实际检索词和来源原文。

## 详细说明

地图操作、时间轴、资料来源与许可、评测、API、前端开发及远程访问步骤统一见[使用与开发指南](docs/system-guide.md)。Mac 访问 Windows 的方法见[远程访问](docs/system-guide.md#windows运行mac展示)。

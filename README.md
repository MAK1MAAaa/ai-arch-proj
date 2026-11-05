# 考古图志 · ArchSearch

本地运行的文化遗址检索与历史地图网页，当前包含3897项资料。

## 日常启动

在 Windows PowerShell 中执行：

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

模型、索引及历史库默认保存在仓库根目录的 `.archsearch/`。仅运行网页无需 Node.js、pnpm 或 GPU。

## 当前检索模型

默认使用本地 **`intfloat/multilingual-e5-small`**，通过 CPU 生成向量并按相似度排序，也可手动切换 **BM25** 关键词检索。当前没有接入生成式 LLM、Ollama／Qwen 或外部模型 API，也没有 LLM 查询改写或重排；启动项目无需运行 Ollama 或配置 API 密钥。

中文专名仍可能漏检，可尝试来源原名或先选择国家／地区浏览。

## 详细说明

地图操作、时间轴、资料来源与许可、评测、API、前端开发及远程访问步骤统一见[使用与开发指南](docs/system-guide.md)。Mac 访问 Windows 的方法见[远程访问](docs/system-guide.md#windows运行mac展示)。

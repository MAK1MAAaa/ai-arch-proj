# 考古图志 · ArchSearch

本地运行的文化遗址检索与历史地图网页，当前包含3898项资料，支持现代与历史双图对照。

界面采用顶部检索、左侧“检索结果／全库浏览”和双地图工作区；左右分栏可拖动调整。点击结果定位两图，“资料详情”打开弹窗。历史背景根据明确的遗址年代自动联动，不再提供手动时间轴；区间和未知年代保留证据说明。

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

展开顶部“模型”入口（查询增强与模型设置），选择 Ollama，等待自动获取模型列表，选择本机已缓存的 **`qwen3.5:9b`** 并“应用所选模型”，再勾选“LLM 增强”检索。`qwen3.5:2b` 可作为速度优先的备选；应用只获取列表，不自动下载模型。

首次配置 API 且尚无 `.env` 时，将 [`.env.example`](.env.example) 复制为根目录 `.env`；已有文件直接编辑。填写 `base_url`、`api_keys` JSON 列表和 `model`，重启服务即可加载。多 Key 写成 `api_keys=["你的第一个Key","你的第二个Key"]`；真实 `.env` 不提交 Git。

也可在页面选择“OpenAI 兼容 API”，填写地址与密钥，自动获取模型列表后选择并应用。页面修改只保存在服务内存；重启会重新读取 `.env`。操作、Key 轮换及配置优先级见[LLM 增强说明](docs/llm-search.md)。

可直接试搜“寻找莎士比亚的坟墓”，选择结果后对照现代位置与1616年历史疆域。其他中文专名仍可能漏检，模型改写也可能误译；请核对实际检索词和来源原文。

## 详细说明

双图、年代联动与莎士比亚案例见[地图对照说明](docs/map-comparison.md)。资料来源与许可、评测、API、前端开发及远程访问见[使用与开发指南](docs/system-guide.md)。Mac 访问 Windows 的方法见[远程访问](docs/system-guide.md#windows运行mac展示)。

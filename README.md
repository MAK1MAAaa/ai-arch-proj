# 古迹检索 · ArchSearch

面向古代遗址资料的语义检索与地图可视化课程项目。

首版固定使用 Pleiades v4.1 中地中海周边的 500 条罗马早期帝国（前 30—公元 300 年）地点资料，提供本地多语言语义检索、BM25 对照、原文证据与地图联动。

## 交付流程

初始化 `main` 后，所有功能在 `feature/dev` 开发。每个完整功能批次同步本文档，经过本地检查、独立审查和 CI，再由 GitHub Actions 机器人批准并 squash 合并；`main` 要求 `quality-gate` 和一个批准。

按项目基础与真实数据、检索与 API、地图界面与评测三个批次交付。当前批次交付真实语料和可复现清洗器；检索 API 与界面在后续批次接入。

## 环境与数据验证

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。在仓库根目录执行：

```powershell
uv sync --locked --dev
uv run python -m archsearch.corpus
uv run pytest tests/test_corpus.py
```

已提交的 `src/archsearch/data/` 包含500条规范化地点、所选ID和清洗清单，可直接离线读取。重新从固定官方归档生成：

```powershell
uv run python -m archsearch.corpus --rebuild --download
```

归档缓存位于 `.archsearch/downloads/`。清单记录原始归档与语料SHA256、源版本、筛除计数和加工规则：经纬度矩形 `[-6,29,37,46]`、有效代表点、六类人工遗存、名称或位置的 `roman` 分期证据，再按 `SHA256("mvp-v1:"+id)` 排序取500条。7,849条符合条件；全部原始分期、原文和贡献者继续保留。

依赖固定使用官方PyPI与PyTorch CPU源，模型下载缓存、虚拟环境和索引不进入Git。仓库维护者可运行 `./scripts/github_admin.ps1 -Operation Verify` 回读PR保护设置；该脚本从本机Git Credential Manager读取身份，凭据仅存于进程内存。

## 数据及范围

数据来自 [Pleiades v4.1](https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1)，采用 CC BY 3.0，地点详情保留贡献者与来源。`roman` 指 [罗马早期帝国](https://pleiades.stoa.org/vocabularies/time-periods/roman)。坐标是代表点，不能视为精确发掘坐标。模型和全量下载缓存不提交到 Git。

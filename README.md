# 古迹检索 · ArchSearch

面向古代遗址资料的语义检索与地图可视化课程项目。

首版固定使用 Pleiades v4.1 中地中海周边的 500 条罗马早期帝国（前 30—公元 300 年）地点资料，提供本地多语言语义检索、BM25 对照、原文证据与地图联动。

## 交付流程

初始化 `main` 后，所有功能在 `feature/dev` 开发。每个完整功能批次同步本文档，经过本地检查、独立审查和 CI，再由 GitHub Actions 机器人批准并 squash 合并；`main` 要求 `quality-gate` 和一个批准。

按项目基础与真实数据、检索与 API、地图界面与评测三个批次交付。后续提交会补齐可直接执行的准备、启动、评测和 Tailscale 展示步骤。

## 数据及范围

数据来自 [Pleiades v4.1](https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1)，采用 CC BY 3.0，地点详情保留贡献者与来源。`roman` 指 [罗马早期帝国](https://pleiades.stoa.org/vocabularies/time-periods/roman)。坐标是代表点，不能视为精确发掘坐标。模型和全量下载缓存不提交到 Git。

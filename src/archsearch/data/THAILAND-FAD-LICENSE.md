# 泰国美术厅公共古迹点位

坐标与稳定编号来自泰国文化部美术厅（Fine Arts Department）。官方元数据的许可字段为 `Creative Commons Attributions`。公共访问与地点类别对照泰国旅游局（Tourism Authority of Thailand）的公开旅游目录，其许可字段为 `Open Data Common`。逐条资料按数据页保留许可原文及发布机构。 [美术厅古迹名录](https://data.go.th/th/dataset/gis-finearts) · [旅游局访问名录](https://data.go.th/th/dataset/tourist-attraction1)

2026-11-28 核对美术厅 8,341 行与旅游局 8,848 行，采用可唯一匹配的已登记古迹。纳入需满足泰文原名或别名、三级来源地名、公众访问字段一致，两个来源的点位距离在 150 米内。已另检查库内主代表点、附加点及世界遗产组成地点。共纳入 17 条，均采用美术厅发布的经纬度。

两个相近的 Chai Nat 寺庙各有独立登记与可识别的遗址范围。点位保留为来源代表点，登记日期只用于分辨行政资料，历史阶段采用现有断代未确定状态。 [美术厅的第一处记录](https://www.finearts.go.th/chainatmunimuseum/view/21110) · [美术厅的第二处记录](https://www.finearts.go.th/performing/view/15511)

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort thailand_fad
```

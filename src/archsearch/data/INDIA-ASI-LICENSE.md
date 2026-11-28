# 印度考古调查局公共文化点位

两批从印度考古调查局（ASI）公众售票目录分别核验 18 处和 28 处考古遗址及历史建筑。逐处保留 ASI 名录标识、访问证据和对应地点。近邻地点使用各自的目录身份，世界遗产已有组成点继续沿用原记录。[ASI 公众售票名录](https://asi.nic.in/pages/m_category/isTicketed/monument/HQ) · [ASI 版权政策](https://asi.nic.in/pages/Copyright-Policy/)

几何采用逐条匹配的 Wikidata [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing) 地球 P625 代表点。保留声明 ID、来源版本、原始精度和快照校验值。政府访客资料用于核实身份和开放范围，网页图片、叙述和导览资料保留各自权利。新增点位的断代均保持未确定。

龙树山标记对应现今水库岛上的公共遗址和博物馆，包含部分由原河谷迁建的遗存。地点详情保留迁建范围证据。[印度旅游部访客说明](https://www.incredibleindia.gov.in/en/andhra-pradesh/guntur/nagarjunakonda)

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort india_asi
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort india_asi_next
```

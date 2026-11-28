# 威尔士 Cadw 公共古迹点位

出处为威尔士政府 Cadw 的 [Guardianship Monuments](https://datamap.gov.wales/layers/geonode%3Acadw_guardianshipmonuments)。空间资料适用 [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)，包含 Cadw（Welsh Government）资料及 Crown copyright 与 database right。公众访问另对照 Cadw 管理机构目录。 [Cadw 公众访问目录](https://cadw.gov.wales/visit/places-to-visit)

2026-11-28 冻结官方 WFS 的 133 个点。纳入 111 条可区分的公开古迹，保留登记号、场所原名、威尔士语别名、来源坐标、点位来源和适用许可。临时安全关闭、无法区分的共享编号、欠缺公开访问依据及既有 UNESCO 遗产或组件等 22 条保留在排除范围。五处仅在特定时段、季节或导览开放的古迹有逐项官方依据。实际开放安排以管理机构发布为准。

Tretower 的庄园与城堡各有独立登记及对应坐标。Segontium 和 Castell y Bere 与邻近世界遗产点为不同场所。保留发布点作为代表位置，新点位采用断代未确定状态。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort wales_cadw
```

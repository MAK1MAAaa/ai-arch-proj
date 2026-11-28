# 芬兰文物局 VARK 公共遗址点位

署名为芬兰文物局 Museovirasto（Finnish Heritage Agency）。点位来自国家级重要考古地区名录 VARK 的官方空间服务，空间数据适用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。 [官方空间数据与许可](https://www.museovirasto.fi/en/services-and-guidelines/data-systems/kulttuuriympaeristoen-tietojaerjestelmae/kulttuuriympaeristoen-paikkatietoaineistot)

2026-11-28 从 1,010 条空间点记录中筛选具单一地点对象、有效发布点、稳定 `VARK_ID`、逐条官方登记和公众访问依据的资料。最终纳入 11 条。元数据、机构链接和原始校验见冻结复核。Kierikinkangas 登记地区涵盖不同用途的地点，现有公众活动说明无法确认提供的坐标对应可访范围，暂缓纳入。

地图沿用服务返回的 WGS84 代表点，地点范围、票务和开放时间以主管机构为准。新增记录保留断代未确定状态。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort finland_vark
```

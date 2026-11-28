# 西班牙安达卢西亚文化场所网点位

本批采用安达卢西亚统计与制图研究所（IECA）发布的 DERA 图层 `11_03_Reca_pun`。数据日期为 2022-04-21，发布于 2023-01-30。署名为 Instituto de Estadística y Cartografía de Andalucía、Junta de Andalucía。点图层开放许可为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。 [技术说明第 133 印刷页](https://www.juntadeandalucia.es/institutodeestadisticaycartografia/dega/sites/default/files/docs/094-datos-espaciales-referencia-dera-informacion-basica-datos.pdf#page=135)

2026-11-28 冻结该图层 WFS 输出的 31 条记录。服务按 EPSG:4326 给出坐标，各要素为单坐标 `MultiPoint`。保留原 `id_dera`、原名、场所类别、发布坐标及当地登记字段。RECA 目录记录了公共文化展示的范围，开放安排以管理单位发布为准。 [官方文化场所说明](https://www.juntadeandalucia.es/aaiicc/enclaves/node/352)

纳入 23 条。Dólmenes de Antequera、Madinat al-Zahra 和 Alhambra y Generalife 与既有 UNESCO 身份重叠，Sinagoga de Córdoba 及四处格拉纳达条目与现有遗产的组成或范围可能重叠，保守排除。Castillo de Vélez-Blanco 与邻近的地中海沿岸岩画为不同对象。罗马时期场所继续使用各自来源身份和发布位置。

地图使用名录代表点。地点范围和历史阶段分别保留已有来源口径。可从冻结复核文件重建该批次。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort andalucia_reca
```

# 捷克公共文化点位

本批收录 12 个地区的 28 处国家遗产，采用国家遗产研究所地理门户第 6 图层的主定义点（hlavniPrvek=1）。原始 EPSG:5514 平面坐标经捷克适用的 S-JTSK to WGS 84 (5) 操作转换为 WGS84，经纬度随冻结资料分发。逐处对照公开参观、维修或季节性关闭规则，并核验与世界遗产本体和缓冲区的范围。历史阶段保留未知状态。[NPÚ 第 6 图层](https://geoportal.npu.cz/arcgis/rest/services/Tematicke/CP_UAP_BI/MapServer/6) · [源数据元数据和署名条款](https://geoportal.npu.cz/metadataserver/record/full/A48C43D5-EDF9-4E14-BB5D-730B849D9C52)

czech_public_review.json 及 czech_public_sites.json 中由 NPÚ 数据加工得到的点位和关联的源字段按 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) 分发。改动包括挑选公开场所、标准化字段和坐标转换。数据署名为 **datový podklad: Geoportál památkové péče, Národní památkový ústav, https://geoportal.npu.cz**。各参观页面沿用各自权利。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort czech_public
```

# 墨西哥公共考古遗址点位

坐标及稳定编号来自墨西哥文化秘书处的文化信息系统 SIC 国家考古地点目录。采用发布者的说明许可并保留机构署名。INAH 开放古迹表作为公共开放依据，适用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。 [SIC 数据重用条款](https://sic.cultura.gob.mx/datos.php) · [INAH 开放名录及许可](https://www.datos.gob.mx/es/dataset/zonas_arqueologicas_abiertas_publico)

本批固定 2026-11-28 取得的两份原始快照。SIC 全国目录含 196 条，经核对开放状态、名称、州、可区分身份和唯一坐标，154 条进入逐条访客点核验。128 条通过距离和身份检查，再排除 4 个与既有遗产或同一遗址可能重叠的组件。最终纳入 124 个点，覆盖 29 个来源州级单位。

逐点引用 SIC 原经纬度。INAH 访客门户作为辅助比对，另独立复取 22 条高差值、近邻和名称异写的条目，核对身份、坐标与所取原文片段的校验值。访客页面的图文及坐标用于比对。SIC 与 INAH 代表点差得过大的记录已排除，例如 Cobá。新增资料沿用断代未确定状态。

可从冻结复核文件重建该批次。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort mexico_sic
```

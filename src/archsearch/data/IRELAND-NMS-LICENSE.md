# 爱尔兰国家古迹署公共古迹目录

本批采用爱尔兰国家古迹署公布的 [Monuments to Visit – points of interest](https://data.gov.ie/dataset/monuments-to-visit-points-of-interest)。署名为 National Monuments Service, Department of Housing, Local Government and Heritage, Government of Ireland，适用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。

2026-11-28 取得资源 `483088c5-4ca4-4442-8313-11e66f5d45ae` 的 JSON 快照和 CSV 导出，资源页记录的发布日期为 2021-08-23。两个导出的 94 个 `ENTITY_ID`、`SMRS`、原名及 EPSG:4326 经纬度逐项核对一致。清单保存来源摘要，随库分发的记录只保留必要字段和项目摘要。目录的公共用途由来源定义，具体开放安排以管理机构发布为准。 [资源页和数据字典](https://data.gov.ie/en_GB/dataset/monuments-to-visit-points-of-interest/resource/483088c5-4ca4-4442-8313-11e66f5d45ae?inner_span=True)

纳入 90 条。与已有 `whc:757` 重叠的 Skellig Michael 以及现有 `whc:659` 整体的 Newgrange 和 Knowth 两项组成遗址保留在原世界遗产记录中。以自然洞穴为主体的 Dunmore Cave 超出本批取材范围。点位沿用来源列的经纬度，坐标精度留空。Grianán of Aileach、Dún Aonghasa 和 Céide Fields 三个原字段的乱码参考管理机构现行拼写恢复。部分场所另存来源说明中的地点别名。 [Brú na Bóinne](https://whc.unesco.org/en/list/659/) · [Sceilg Mhichíl](https://whc.unesco.org/en/list/757/)

点位批次记录公开名录中的文化地点身份，年代状态按现有模型保留为断代未确定。可使用 `uv run --no-sync python -X utf8 -m archsearch.target_data --cohort ireland_nms` 从冻结复核文件重建规范化记录和清单。

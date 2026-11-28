# 苏格兰历史环境局公共文化点位

本批从 Historic Environment Scotland（HES）的 Properties in Care 点数据中核验并纳入 31 处。冻结文件保留原始 PIC_ID、名称、地方主管当局、来源 WGS84 代表点、来源快照哈希和逐处访客链接。季节开放和仅局部开放的地点以管理方当天说明为准。[官方数据目录](https://ckan.publishing.service.gov.uk/dataset/properties-in-care1) · [源图层](https://inspire.hes.scot/arcgis/rest/services/HES/Properties_in_care_points/MapServer)

来源归档许可说明为 [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)。来源要求的署名为 **Contains Historic Environment Scotland data © Historic Environment Scotland Scottish Charity No. SC045925 2026**。项目选取部分点位并规范化，访客页面和图片保留各自权利。

独立复核逐处比对原始 PIC 名录、公开访问说明与旧库已有地点。个别访客地址对应登船处或格网字段存在差异，使用同一登记对象复查原代表点。新增点位均采用断代未确定状态。可从冻结复核文件重建。

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort scotland_hes
```

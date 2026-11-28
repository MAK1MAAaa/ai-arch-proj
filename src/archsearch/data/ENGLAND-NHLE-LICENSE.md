# 英格兰国家遗产名录公共点位

本批收录 29 处有指定公众参观范围的文化地点，覆盖英格兰东北、约克郡、西北、中部、东部、东南和西南。每个地点选用 Historic England 国家遗产名录按 `ListEntry` 发布的唯一代表点。源服务按 `outSR=4326` 提供经纬度。English Heritage 的开放和保护信息用于限定参观范围。部分建筑仅开放指定区域或外部观览。新增点位采用断代未确定状态。[国家遗产名录](https://historicengland.org.uk/listing/the-list/) · [English Heritage 参观目录](https://www.english-heritage.org.uk/visit/)

点位及名录标识按 [UK Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) 分发。署名为 **© Historic England 2026. Contains Ordnance Survey data © Crown copyright and database right 2026.** 冻结文件记录逐址点图层响应和公开参观资料的 SHA-256。[Historic England 开放数据条款](https://historicengland.org.uk/terms/website-terms-conditions/open-data-hub/)

```powershell
uv run --no-sync python -X utf8 -m archsearch.target_data --cohort england_nhle
```

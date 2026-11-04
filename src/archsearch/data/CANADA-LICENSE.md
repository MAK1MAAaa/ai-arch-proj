# 加拿大历史遗址资料：来源、许可与加工

本批使用加拿大公园局（Parks Canada / Government of Canada）发布的 [Directory of Federal Heritage Designations 数据集](https://open.canada.ca/data/en/dataset/49d5ba7d-d860-40d9-9183-892979e4acbe)，数据资源 ID 为 `682d1e12-26dd-4d30-bb40-f04658502bcd`。固定版本注明截至 2026-03-31；元数据、原始分页和逐条原字段的 SHA-256 随冻结复核与清单保存。它是来源版本，不是每处遗产当前开放、保护或法律状态的证明。

## 政府开放数据

该发布资源适用 [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)。署名：Parks Canada / Government of Canada — Federal Heritage Designations dataset。

Contains information licensed under the Open Government Licence – Canada.

发布资源中的原始英文描述、别名、纪念铭文、登记字段和缺失状态保留；本项目按来源类型精确选择 `National Historic Site of Canada`，再独立审查文化对象、重复关系和点位。原始建造、认定、出生与去世等日期只保留为来源元数据，不转成经过核验的历史阶段。原文中的旧称、旧观点或提示保留来源语境，不代表本项目赞同。

政府网站单页、图片、提名附件及其他第三方内容不因该数据集许可而统一获得再许可；官方标识、个人资料及其他许可例外仍受原条款约束。本项目不声称加拿大政府或任何原住民社群为项目背书。

## 身份、坐标和地区关联

Wikidata 结构化声明适用 [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing)。`P2526` 是官方历史遗址编号的候选关联，须与政府原记录和对象范围核对，不能仅凭相似名称认定同一地点。采用的地球坐标保留实体 revision、完整原始声明、rank、限定符、声明 ID 和来源响应 SHA；经纬度顺序为 `[longitude, latitude]`。Wikidata 的角度 precision 是原始分辨率信息，不等于米级定位准确度。

另有明确采用的 NRCan 加拿大地名数据库提供者参考点时，保存同名、同省和共同 feature ID 的身份链及原响应。官方名称不一致时，仅经独立复核的精确 `P2526`／`P821` 编号链可以关联同省的同一业务对象；原称和别名不改写，不以模糊名称或距离代替身份核验。只有提供者实际返回的 `outSR=4326` 输出才能按 WGS84 使用；原 NAD83 坐标不直接改标签。原始 named-feature 几何不是本项目重建的遗址范围，不转成古代轮廓或法定保护边界，也不生成几何中心。

以上开放点位来源不扩展许可到 Parks Canada 网页查找器、照片或其他第三方地图。点位表示公开参考位置，可能是来源定义的纪念区域或组成资源，须阅读逐条说明。未获来源证据解决的多个位置冲突或未经核验的坐标保持空值；原址不明或对象迁移时，不以纪念区域、博物馆或新址冒充原址。来源明确认定的纪念区域可以采用其公开参考点，但须注明其角色及原址的不确定状态。

国家、省／地区采用发布资源的字面字段；加拿大机构登记的法国地点仍保留 France。UNESCO 各国页面仅支持现代资料分区关联，不表示本批地点均是世界遗产。相关页面原有权利保持不变。

## 复核和派生文件

`canada_review.json` 保存全量来源决策、原始 28 字段（含内部 `_id`）、证据、行政提示、点位收据和独立代理复核方式；`canada_sites.json` 是可离线加载的派生资料；`canada_manifest.json` 保存原库合同、范围关系、来源校验、处置和新增计数。完整原响应、网页、数据库与模型缓存不进入 Git。

源 `Highlight` 中的 “identified for review” 涉及已有认定的纪念理由或牌文复核，见[公园局复核说明](https://parks.canada.ca/culture/designation/revue-review)。它与本项目是否批准资料入库及断代核验状态独立，不能解读为尚未获认定、已经撤销或已经获得本项目批准。

独立代理核对来源不等于专家或人工确认；本批不新增经过核验的历史阶段。同址不同层、整体与组成部分的关联按原文说明保留，不用代表点重合推断相同范围，也不用不同编号推断空间互不重叠。

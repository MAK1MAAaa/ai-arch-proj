# 澳大利亚国家遗产资料：来源、权利与加工

`australia-nhl-v1`整理澳大利亚国家遗产名录公开空间数据库中的文化对象，将原 1940 条资料追加为 `global-v12` 的 1999 条。本轮独立核对 60 个候选，纳入 59 个对象，保留 1 个待核；新增对象包含来源分类 `Historic` 46 个、`Indigenous` 13 个。它们是正式来源中的文化地点、历史建筑、文化景观或关联范围，不等同于考古发掘点，也不是完整澳大利亚文化遗产清单。国家遗产登记不等于 UNESCO 世界遗产入选；本文件的 NHL 许可说明不覆盖其他批次的来源权利。

## 来源、版本与署名

| 来源 | 本项目使用范围 |
|---|---|
| [National Heritage List Spatial Database (NHL) - public 的固定元数据](https://data.gov.au/data/api/3/action/package_show?id=6e3366ab-48db-4495-a457-7fb67154edc6)及[公开空间服务](https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/National_Heritage_List/FeatureServer/0) | 原始身份、名称、文化分类、登记状态及全部原 15 个属性字段；经独立审核的公开现代登记范围 |
| 各对象的 Australian Government DCCEEW 官方页面 | 逐条核对文化身份、对象范围、原始 Location 与披露限制；只分发事实关联和极短摘录，不分发网页全文、图片或全文译文 |
| [UNESCO 澳大利亚来源地区页面](https://whc.unesco.org/en/statesparties/au/) | 保留可追溯来源地区关联，不将全部国家遗产重标为世界遗产 |
| [联合国统计司 M49 国家或地区表](https://unstats.un.org/unsd/methodology/m49/overview) | 核对 Australia／AU 与 Norfolk Island／NF 的正式国家或地区名称及代码；不表达主权或历史归属判断 |

公开 NHL 数据集标明 **Creative Commons Attribution 3.0 Australia**。再分发相关事实 GIS 和结构化属性时，保留数据集标题、提供者 **Australian Government Department of Climate Change, Energy, the Environment and Water**、来源链接、[许可链接](https://creativecommons.org/licenses/by/3.0/au/)及加工说明；原数据版权标注 **Department of the Environment, 2016** 继续保留。不暗示提供者认可本项目，不增加与该许可冲突的再使用限制。

上述数据集许可不自动覆盖 DCCEEW／UNESCO 官方网页全文、照片、原住民知识或证词、外部评估材料、第三方作品或地图底图。各 `source_refs` 分别保留权利说明；未获统一开放许可的网页引用保持其原权利，不能统一改标为 CC BY、CC0 或 NHL 数据集许可。本批每个非开放来源 URI 的不同英文引文合计最多 11 词。联合国表仅采用事实名称／代码与极短摘录，不主张其整页统一开放。本批不采用 Commonwealth Heritage List（CHL）数据。

冻结依据是本次实际取得的响应及来源文件 SHA-256，不是一个自行推断的数据发行年。CKAN 元数据修改时间、ArcGIS 软件版本、`REGISTER_DATE`、`UPDATED` 和本次快照时间分别保留原含义；登记、编辑、发布年份均不作为建造、使用或毁损年代。

## 对象范围、地区与年代

`PLACE_ID=105665`，Recherche Bay (North East Peninsula) Area，文化身份成立，但现有官方资料没有充分区分其相对既有 Tasmanian Wilderness 整体及已纳入游憩区的准确关系，因此保持 `hold`。它不生成新 Site，也不显示其范围；这不是否认其文化价值。不能仅凭名称、旧代表点是否落入多边形，认定同一对象或新增独立遗址。

59 个新增对象保持来源原名，英／中文描述为空，不补写历史简介、翻译或推测时期；历史阶段均为 `not_reviewed`，阶段和原始分期证据为空。来源和独立代理审核只核对身份、文化资格、范围、权利及公开几何，不是专家或人工考古断代确认。

HMS Sirius（`106167`）保留原官方 Location **Kingston, EXT, Australia**、原 `EXT` 和 AU 关联。同时以[同对象官方 Norfolk Island 文字](https://www.dcceew.gov.au/parks-heritage/heritage/places/national/sirius)及 UN M49 的 Norfolk Island／574／NF／NFK 行追加 NF 国家或地区关联；不覆盖 AU，不把沉船展品所在博物馆当成原船骸，不从坐标或 `EXT` 一般化推断其他对象。此次只新增 NF 标签，不新增来源地区分组。

## 公开现代范围与位置限制

59 个对象没有采用代表点；对应保留 **60 个来源要素、366 个原环、68490 条经纬度记录**。原多边形只作为“现代遗产登记范围”单独展示，不生成质心、不采用某个顶点代替代表点，不改写为古代遗址轮廓、历史政治疆界或访客可进入区域。空代表点表示本批未采用代表点，并不表示实际位置未知或没有公开数字几何。

来源原地理基准为 GDA94（EPSG:4283），WGS84（`outSR=4326`）由提供者服务转换；项目保留提供者返回的经纬度与全部原环，不再重投影、简化或推断内外环拓扑。页面仅以不填色虚线描绘原环，未验证逐处测量精度或完整拓扑。

公开 NHL 可能包含概化到地图图幅的敏感地点，缺少逐行保密标志不代表可以恢复精点。原住民来源中的概化、范围未完全确定、仅选定地点开放及导览限制均保留；本批不细化敏感位置、不额外挖取精点。公开登记范围、文化资格与旅游准入是不同事实。

125 件必要来源文件在维护环境的 `.archsearch/downloads/australia-nhl-v1` 保存并逐件校验 SHA，包括原始响应及明确标识的网页正文派生快照；后者不冒充原始 HTTP 字节。完整来源缓存、模型和评测输出不进入 Git。正常运行只读随项目分发的固定资料和范围侧车，不下载来源；准备命令仅在显式 `--download` 时请求固定公开几何并核验大小与 SHA 后发布。

逐条源审、方案投影及工程报告 SHA-256 分别为 `b67bd41424df6df95c6dc4fe0a3ec352d1d376cc9ffd2d1877c339dd98477b70`、`bb2775051443d346affb14b49d1a3d3eb5ab86dc3a9dc5861fc13441f6f60928`、`43f4bbcf762ef96e906f309fd541f31513e679d404269e5dbee2a9daf0106bb0`。完整验证状态见[本批验证记录](../../../docs/australia-validation.md)。

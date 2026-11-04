# NPS 太平洋历史登记资料：来源、权利与加工

`nps-pacific-v1`依据固定的美国国家公园管理局（NPS）公开历史登记服务及逐条 NPGallery 元数据整理资料。原始池包含 156 个唯一 NRIS 登记号、161 个来源要素；本批新增 133 个文化对象，另有 5 个对象对应既有资料，18 个对象保留待核。来源要素数、地图点数、登记号数与新增遗址数各不相同。本批不是太平洋地区完整清单，NPS 历史登记也不等于 UNESCO 世界遗产入选。

## 来源与版本

| 来源 | 用途与保留内容 |
|---|---|
| [NPS 数据下载说明](https://www.nps.gov/subjects/nationalregister/data-downloads.htm)与[公开地图服务](https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer) | 冻结两个公开图层的登记号、对象名称、State、资源类型、状态、原始要素身份与位置方法；逐条核验后才采用公开同对象几何 |
| [NPGallery 登记入口示例](https://npgallery.nps.gov/AssetDetail/NRIS/08000165) | 逐一核对 156 条实际登记元数据的身份、原对象类型、地区、文化资格与位置披露限制；不下载提名附件 |
| [联合国统计司 M49 完整表](https://unstats.un.org/unsd/methodology/m49/overview) | 将原始 State 字面关联到正式国家或地区名称及 ISO 代码，不从坐标或管理机构推断政治归属 |
| [Piti 原炮位说明](https://www.nps.gov/wapa/planyourvisit/piti-guns-trail.htm)、[公园单元说明](https://www.nps.gov/articles/pacificnational.htm)、[NPS 船骸指引](https://www.nps.gov/articles/abandoned-shipwreck-act-guidelines.htm) | 限定固定原址炮位、公园与组成地点关系，以及两处原沉没遗存的对象范围；不额外导入历史阶段、深度、所有权或位置 |

完整必要来源为 294 件实际原档：156 件 NPGallery HTML、132 件已核验公开对象的几何响应、2 件原属性响应、1 件 UN M49 完整表及 3 件 NPS 范围补证 HTML。逐件保存公开 URI、文件名和实际 SHA-256；原始 HTML、完整多边形及缓存只存本地忽略目录，不进入 Git。规范化资料、审核合同和派生清单随项目分发，普通运行只读取本地文件，不依赖来源网页缓存。

地图说明中的 2020 年、2026 年配置修改时间、数据 profile 日期、各要素编辑日期与 ArcGIS 软件版本分别保留其原含义。冻结的是本次实际取得的服务响应及逐条元数据，不宣称它们等同某个完整地理数据库发行版或始终最新的登记状态；登记、提名、认证和编辑年份均不转为遗址建造或使用年。

## 权利边界与署名

请保留 **National Park Service / National Register of Historic Places** 及具体来源链接。使用范围限于 NPS 政府制作的事实登记字段、公开事实 GIS，以及逐来源极短资格引文；不对原始美国政府作品主张本项目版权。完整条件见 [NPS 权利与免责声明](https://www.nps.gov/aboutus/disclaimer.htm)。

NPS 托管不代表全站内容统一开放。第三方提名材料、捐赠资料、摄影、影像底图、商标和其他权利人的作品不在上述范围内；本批不发布整页 HTML、提名全文、图片或完整译文。原记录的 `ORIGINATOR`、`SOURCE`、`CONSTRANT` 继续保留。范围数字化所引用的 ESRI World Imagery 等来源不构成其底图的再分发许可。不得将本批统一重标为 CC0、CC BY 或其他未获确认的许可；未确认统一许可的元数据和机构补证引用保留 `license=null`。

每个非开放来源 URI 的不同引文跨全部决策与记录合计不超过 25 个英文词；当前实际最大值为 19 词。两处船骸共用的范围补证不复制历史叙述。UN M49 仅保留事实映射及来源引用，地区划分不表达本项目对主权或边界的立场。

## 对象、地区与位置披露

七种原始 State 关联 AS、FM、GU、MH、MP、PW、UM 七个国家或地区代码。新增 AS、GU、MP、UM 四个标签；`nps-pacific`／“NPS太平洋资料分组”是项目明确命名的来源分组，不是 UNESCO 官方分区、洲界或国家边界。

133 个新增对象保持正式原名及来源别名，英文、中文描述均为空，没有生成历史简介或官方中文译名；阶段全部 `not_reviewed`，`phases` 和分期证据保持空。独立代理审查只确认身份、文化资格、范围、来源位置及权利边界，不是专家或人工考古断代确认。

其中 111 个对象具有可采用代表点，22 个代表点为空。111 个对象共保留 112 个原始公开点：Canada Water Wells 的两口井属于同一登记对象，按原始提供者顺序保留，固定首点仅作为项目初始参考，没有来源主点、几何中心或独立遗址数量的主张。另有 21 个对象仅有 22 个公开登记范围，完整原多边形保存在忽略缓存，不自算质心或用村镇、游客服务入口替代。

Tulauta Village 的单条官方元数据明确限制地址披露，优先于公开服务的一般说明。它保留文化身份和空点，本批未请求其点或范围，也不从旧 GIS、Wikidata、附件等其他渠道恢复精点。空代表点表示本批没有采用可核验且可披露的代表点，不表示真实地点未知。`location_disclosure` 记录的是来源位置披露状态，不是旅游准入许可。

已采用参考点可能由来源的 XY 事件或质心方法生成，项目没有再次计算中心。`MAP_METHOD`、`MAP_MTH_OT`、`SRC_SCALE`、`SRC_ACCU`、`IS_EXTANT`、`EXTANT_OTH` 等原值保留：来源标称精度不等于本项目验证的发掘精度，`location_precision` 为 `null`；`Unknown` 不等于不存在，`True` 也不等于已实地确认。Wake 的 GIS `site` 与 NPGallery `DISTRICT` 分类同时保留；Tinian 的地址元数据缺失不改写成真实位置未知。

5 个已有对象只在运行期追加来源地区目录关联，保留旧国家或地区、原分区、坐标、阶段、原来源值及引用前缀，不增加 Site。18 个待核对象不追加目录、不获取几何，包含元数据身份冲突、可移动对象及父子范围关系未确定等情形；不能因本批未纳入而声称其不是文化遗产。

来源合同、逐条源审与整合报告 SHA-256 分别为 `8d567d54e8f4b43c04b7ccdcfef37d89cc3d53ad7e52878d3f2193213c8af99d`、`891b23a18c71b836a48bd507a17a7a77a75f01fd7b84b93d0fada5b5fdef096e`、`7887ba97b6376eb86438ec5a3f50a1d32c8ff1538fc83a3719679836018620e1`。核验方法与当前验证状态见 [NPS 批次验证记录](../../../docs/nps-pacific-validation.md)。

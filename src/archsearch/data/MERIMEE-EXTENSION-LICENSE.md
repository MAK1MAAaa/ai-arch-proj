# Mérimée 法属圭亚那、马约特与圣皮埃尔和密克隆资料

本批`merimee-extension-v1`与既有`merimee-overseas-v1`使用同一固定法国文化部数据集：[Immeubles protégés au titre des Monuments Historiques](https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2)。dataset ID为`5af120e5b595087cfabcde81`，资源ID为`3a52af4a-f9da-4dcc-8110-b07774dfb3bc`；采用[Licence Ouverte / Open Licence2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2-0)，保留法国文化部、原Producteur和Copyright、来源、取得日2026-11-05及加工说明。外链照片、档案和第三方网页不自动适用该数据集许可。

| 原始资料 | 固定SHA-256 |
|---|---|
| [46761行、78字段的原CSV](https://ministere-culture.s3.sbg.io.cloud.ovh.net/POP/merimee.csv) | `d83f5a3beb83221ed55169159fc0ce7c6d3dad66edca205a225cd30c136dd6ec` |
| [官方数据集元数据](https://www.data.gouv.fr/api/1/datasets/5af120e5b595087cfabcde81/) | `d4865cdc53abbbbdcf8db24195c9711b3bab6fde3e6ad4d9f97037e423671496` |
| 独立核验使用的LO2正文 | `e3abcb87edeca051d99be349976a688802f1340f8482a0290ebabea73561fcb8` |

CSV资源更新时钟为`2026-10-29T02:16:04+00:00`，数据集元数据更新时钟为`2026-10-29T02:16:05.361000+00:00`，取得和加工日期为2026-11-05。没有将较新的在线页面覆盖到固定原表，也不将这些时钟当成建造或使用日期。全量归档、API及页面缓存不进入Git；普通安装从随代码分发的规范化原字段和复核事实离线重建。

## 原字段与范围

按原`Region`精确值Guyane91条、Mayotte16条、Saint-Pierre-et-Miquelon16条取得123个候选。四个官方API分页与固定CSV的9594个字段逐值核对；6128处API空串呈`null`时，规范化资料仍保留CSV原空串。原行号只是来源定位依据，项目ID采用原`Reference`，不把API行号当永久业务编号。

代理独立对照来源采用122项限定文化名录范围：GF90、YT16、PM16。`PA97300012`的Susky岩棚记录与`PA97300021`的Mamilipann考古实体整体有关联；保留其原行和组成处置，公开目录只增加完整记录，不继承较早组成记录的坐标或把组成名称当整个范围的别名。Mamilipann记录本身仍是一项来源组合，不按其中多个岩棚或考古编号拆出额外Site。

地籍相同、名称相似或坐标重合不单独证明同一对象。Cayenne的AD10三项按各具名范围保留，不能说空间互斥；Tsingoni清真寺范围明确排除另列宣礼塔；Dzaoudzi医院和医生住宅、Breslar与Dôme等记录保留各自完整原范围及修改文字。法律日期及2026年保护文书修改均不生成历史阶段。

标题、78个原字段、保护范围、观察与历史原文完整保留。未新增中文别名、中文历史摘要或历史阶段，也不把曾经或当前受保护的源表扩大为最新完整法定清单。独立复核指代理对照来源，不是专家或人工确认。

## 点位与现代地区

122项采用原`coordonnees_au_format_WGS84`公开字符串，仅把原纬度、经度顺序转为应用的`[经度,纬度]`。轴顺序依据同一固定全表字段已核验的三个官方POP命名`lat`／`lon`样本；这些是字段语义证据，不冒称取得了本批每处地点的新网页。此次对新个体页面的正常HTTPS访问返回上游TLS握手错误，错误页不作为正文或新坐标证据，未绕过验证。

来源未说明点位生成方法或测量精度，全部精度为`null`，不据小数位数推断精度。没有生成质心、行政中心、历史疆界或考古发掘坐标。本批没有新增缺失点；既有390项未采用代表点的状态不变。

原行没有Pays或Country字段。原COG经[INSEE2026](https://www.insee.fr/fr/information/2560452)原行与[UN M49](https://unstats.un.org/unsd/methodology/m49/overview/)有效表行分别关联GF、YT、PM现代统计区域，不从法国发布机构推导逐行FR。GF归拉丁美洲与加勒比项目分组，YT归非洲，PM依据Northern America归欧洲与北美项目分组。原Region和Departement不改写，也不据坐标判定国家主权或历史政治归属。

23个按统计区域区分的来源市镇选项保留`Commune_forme_editoriale`全文。原`Montsinéry-Tonnegrande`与`Montsinéry-Tonnégrande`虽对应同一COG97313，仍保留两个原拼写选项，不自动纠错或合并；这些选项不是23个经本项目裁定的行政实体。多市镇串不拆分，来源地点字段不转换为新的几何或断代。既有地区证据与原3775条资料的字段、顺序、共享检索文本保持不变。

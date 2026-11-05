# Mérimée 法国海外文化名录资料

来源为法国文化部经 [data.gouv.fr 发布的 Mérimée 历史建筑资料](https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2)，dataset ID 为 `5af120e5b595087cfabcde81`，资源 ID 为 `3a52af4a-f9da-4dcc-8110-b07774dfb3bc`。取得日期为2026-11-05。原数据集声明采用 [Licence Ouverte / Open Licence 2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2-0)。本项目保留法国文化部、每条原 `Producteur`、`Copyright`、来源链接、发布及取得时钟，并说明筛选、格式转换、范围复核和目录关联加工。

许可适用于该数据集提供的信息；不自动覆盖外链照片、原网页、附件或第三方内容。本项目没有分发这些图片或附件。原字段包含的法律声明照原文保留；项目界面和派生目录不替代法律文书、现行保护名录或访问许可。

| 固定原始资料 | SHA-256 |
|---|---|
| [官方完整 CSV](https://ministere-culture.s3.sbg.io.cloud.ovh.net/POP/merimee.csv)，100167145字节、46761行、78字段 | `d83f5a3beb83221ed55169159fc0ce7c6d3dad66edca205a225cd30c136dd6ec` |
| [数据集元数据](https://www.data.gouv.fr/api/1/datasets/5af120e5b595087cfabcde81/) | `d4865cdc53abbbbdcf8db24195c9711b3bab6fde3e6ad4d9f97037e423671496` |
| 独立核验采用的上述 LO2 许可正文 | `e3abcb87edeca051d99be349976a688802f1340f8482a0290ebabea73561fcb8` |

完整CSV、API响应、来源页面和官方地理代码原档只作为本地校验缓存，不进入Git。随代码分发的规范化原行保留78个原字符串、原CSV行序号及校验值；API将空串呈为`null`时，以固定CSV原空串为准，不反写原值。离线重建使用已复核事实，不下载最新资料替换冻结版本。

## 来源范围和身份

筛选原 `Region` 字面值 `Guadeloupe`、`Martinique`、`La Réunion`，完整取得450条候选，分别120、124、206条；11个API分页与固定CSV逐字段核对。来源说明包含“曾经或当前受保护”的建筑，不是截至取得日的现行完整法定名录。

`Reference` 是原Mérimée资料编号。项目身份 `auth:fr-merimee:PA…` 表示经复核的原资料对象及其限定范围，不保证每条记录是一处互不重叠的完整建筑或永久法定不动产。原标题、`Precision_de_la_protection`、`Observations`、地籍及相关编号分别保留。只保护立面、屋顶、楼梯或庭院时，不扩大成整座庄园；较大范围与独立保护的建筑可有包含关系。仅作“参见另一市镇”的记录不重复新增对象，其原行及处置仍可追溯。IA等研究链接不生成额外条目或整体别名。

本批没有生成中文别名或新历史阶段。原建造世纪、保护命令、撤销或修改、创建和更新字段保持原文，不直接变成建造或使用年份。代理独立对照来源的复核不标为人工或专家确认。

## 原坐标、地区与加工

原字段 `coordonnees_au_format_WGS84` 保留字符串。官方POP同一REF页面中的命名 `lat`／`lon` 为其纬度在前、经度在后的顺序提供证据；项目转换为 `[经度, 纬度]`，采用提供者公开点作为参考位置。原发布没有明确点位生成方法或测量精度，项目的精度保持`null`，不推断整体中心、考古发掘位置或法定范围。无坐标继续为`null`，不按地址、市镇或保护编号补中心点。

原行没有 `Pays` 或 `Country` 字段；不从法国发布机构推导逐行FR归属。目录以原 `COG_Insee_lors_de_la_protection` 经 [INSEE 2026 官方地理代码](https://www.insee.fr/fr/information/2560452) 和 [UN M49](https://unstats.un.org/unsd/methodology/m49/overview/) 关联现代统计区域：GP、BL、MF、MQ、RE。原 `Guadeloupe` 分组包含7条现关联BL和1条现关联MF的记录，原Region和Departement不覆盖。该关联服务浏览，不裁定国家主权或历史政治归属。

地区选项使用原 `Commune_forme_editoriale` 全文，多市镇值保留一个组合选项，不拆分或地理编码。选项ID是项目标识，不是法定市镇代码。加勒比资料沿用项目`latin-america-caribbean`分组，留尼汪沿用`africa`分组；这不表示资料属于UNESCO世界遗产。

BM25与E5使用相同原文检索文本；排除理由、交叉检查和独立审批措辞不进入正向检索内容。未确认人工相关性标注时，评测指标继续为`null`。

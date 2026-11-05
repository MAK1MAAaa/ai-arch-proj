# 巴西 Iepha-MG 文化遗产登记资料

来源为 Instituto Estadual do Patrimônio Histórico e Artístico de Minas Gerais（Iepha-MG）经[米纳斯吉拉斯州开放数据门户](https://dados.mg.gov.br/dataset/bens-tombados)发布的 `Patrimônio Cultural Tombado`，dataset ID 为 `a4b4c3d6-6fe3-40e5-8bf9-426625efdbba`。资料于2026-11-05取得。原数据包明确采用 [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)，规范化原字段及本项目加工按该许可署名；没有转载照片、原网页或链接文件全文。

原档固定如下。原CSV、网页和数据包缓存不进入Git；普通运行使用随仓库分发、经独立代理对照来源复核的规范化记录。

| 原始资料 | SHA-256 |
|---|---|
| [CSV](https://dados.mg.gov.br/dataset/a4b4c3d6-6fe3-40e5-8bf9-426625efdbba/resource/41e80d65-e365-44e8-81c9-df4e61914c8e/download/processos-tombo.csv) | `0ef07b94a16da7f01fe43e60fae4ced24546662288e3af93c3e92136b9fbb8df` |
| [数据包及字段定义](https://dados.mg.gov.br/dataset/a4b4c3d6-6fe3-40e5-8bf9-426625efdbba/resource/de160191-1c72-4081-a1cc-e26061489410/download/datapackage.json) | `bd43dcda3ac700a15034af4403b52d9a47a2d050405f7201fec532975d6f49b4` |
| [门户元数据](https://dados.mg.gov.br/api/3/action/package_show?id=a4b4c3d6-6fe3-40e5-8bf9-426625efdbba) | `4a2ad9f3bad1ba21c1b9d23d27044da5bd17acad813c144fa63bab345dbc027d` |
| [来源州与巴西的上下文](https://www.mg.gov.br/pagina/geografia) | `690cf94dc3994bf523f1dbb7f18fdffa32744987f33aba3d585befcf7a0bca82` |

数据包版本字面值为 `0.1`；CSV资源的 `last_modified` 为 `2025-11-04T11:31:28.932619`，门户 `metadata_modified` 为 `2025-11-04T11:31:31.937661`，更新频率为 `por evento`。这些来源管理时钟与本项目取得日分别保留，不补时区，不表示截至取得日的完整法定名录，也不是遗址生命周期。

## 原字段与范围

原CSV为UTF-8（按源声明允许BOM）、分号分隔，153行、九字段。规范化档案保留每行原值、行序号和原行校验，不将原字段转换成新断代。

| 原字段 | 来源含义及处理 |
|---|---|
| `processo_ano` | 保护程序的编号及立案年，原样保留；不是唯一整体编号或建造年。 |
| `denominacao` | 原登记简称，保留在带字段名的原文资料中。 |
| `denominacao_completa` | 保护程序中的完整名称，作为采用范围及资料标题；不把简称提升为整个范围的别名。 |
| `categoria` | BI为不动产、BM为可移动物、CH为历史中心、CP为景观组合。类别本身不替代逐范围文化资格核验。 |
| `classe_subclasse` | 保留文化类别原文；仅有自然分类或资格尚不确定的条目保持待核。 |
| `municipio` | 来源说明为对象所在市镇。地区浏览采用完整原串，多地值不自动拆分。 |
| `distrito` | 原地区字段保留；不用于生成本批地区筛选，缺失标记不作为地区。 |
| `ato_legal` | 原保护法律文书，不转成建造、使用或毁损年份。 |
| `livro_de_tombo` | 原登记簿字段；原值`0`逐字保留，不据此推断未保护或某一法律依据。 |

数据包把`0`列为通用缺失标记，但登记簿字段说明又赋予`0`特定宪法含义，存在字段说明冲突。项目保留原值和不确定性，不以`0`补造法律事实、地区或坐标。

同一程序可有不同完整范围，同一完整范围又可分多行记载。项目按原 `processo_ano` 与原 `denominacao_completa` 的精确组合组织记录，保留全部成员原行；不只按程序编号合并，也不把同一来源组合范围的成员行分别计为新增遗址。`auth:br-iepha-mg:scope-…` 是该原始组合的项目派生身份，不是提供者永久编号或法定登记号。

与既有名录相同的整体不新增；相似名称、同城或范围包含关系本身不等于身份相同。独立登记的建筑与较大历史街区可有范围包含，不能据登记对象条数声称其空间互斥。未能明确核定的范围关系保留在复核处置中。

## 位置、地区与检索

原九字段没有坐标或几何。本批所有采用记录的`repr_point`、`location_precision`均为`null`，没有把市镇、保护编号、登记簿或文字地址转换成定位点。没有采用历史阶段，也没有生成中文别名或将法律日期变成历史阶段。

BR为项目依据官方州／国家上下文建立的现代目录关联；`latin-america-caribbean`是项目沿用的来源报告分组，不表示本批是UNESCO遗产。原`municipio`字段建立登记行与完整资料对象的地区关联；复合登记可关联多个原值，一条多市镇原值保持一个组合选项。地区选项ID为项目标识，不是法定市镇代码，不表示整个范围或所有组成部分均属该地区。

葡萄牙语原字段保留用于BM25和E5共同检索文本，复核的排除理由及既有条目交叉检查不进入正向检索文本。条目采用`names=[]`，原简称保留在带字段名的资料中供检索和复查，不误作整个范围的同义名。

独立复核是代理对照实际来源的记录，不标作人工或专家确认。没有经确认的人工相关性标注时，评测指标仍为`null`。

# 来源省／地区索引

`source-subdivisions-v6` 是独立目录关联，绑定 `global-v18` 的3897个身份及来源国家／地区字段，不修改 Site、Geography、共享检索文本、历史阶段或任何定位点。当前合计202个带国家／地区命名空间的来源地区选项、1836条关联、1834个不同对象。这些选项混合整体省区、来源要素地区及原记录地点等不同角色，不是202个行政实体，也不全部是市镇；关联计数有交叠，不能相加当作遗址总数。

原v5的179个定义、1714条关联、1712个不同对象及全部证据内容和顺序逐值保留：加拿大原13个定义、993条关联覆盖992个对象；香港原17种来源要素地区形成139条关联、覆盖138个整体，两项较晚新增整体没有该空间版本的地区字段；巴西Iepha-MG原67种市镇全文值，139条原行证据形成133条对象／地区关联；Mérimée既有82个按现代统计区域区分的原市镇选项（77种不同原串），449条关联覆盖449项名录范围。v6独立追加GF／YT／PM的23个原市镇全文选项、122条关联，绑定本批单独复核合同，不改既有449项的来源范围。

新加坡原16字段没有地区字段，不由地址、邮编、Point或国家标签生成新的区级关联；其原资料许可见[新加坡来源说明](SINGAPORE-LICENSE.md)。

## 来源与权利

- 986个整体对象的省／地区原字段来自 Parks Canada 的 [Federal Heritage Designations](https://open.canada.ca/data/en/dataset/49d5ba7d-d860-40d9-9183-892979e4acbe) 冻结发布记录（资源 `682d1e12-26dd-4d30-bb40-f04658502bcd`），按已采用的977条和9条同一整体身份提取。保留原行校验和、原发布页面校验和与逐对象来源链接，适用 [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)。既有加拿大来源处置及原字段见 `canada_review.json` 和 `CANADA-LICENSE.md`。
- Fort Conger 的 Nunavut 依据为 [Canadian Register of Historic Places 的原位置字段](https://www.historicplaces.ca/en/rep-reg/place-lieu.aspx?id=16360&pid=0)，保留原身份及页面SHA，不套用Wikidata或其他数据集许可。
- 其余五个原有世界遗产整体的位置依据为 Parks Canada 的 [加拿大世界遗产官方目录](https://parks.canada.ca/culture/spm-whs/sites-canada) 链接的逐对象页面：Grand Pré、Pimachiowin Aki、Tr’ondëk-Klondike、Writing-on-Stone／Áísínai’pi 和 Old Québec。只保留身份、极短的位置事实、来源、原字段与校验信息；原网页、图像及第三方材料保留各自权利，未授予它们统一开放许可。

`Pimachiowin Aki` 的原文 `Manitoba and Ontario` 生成两条整体关联；`Québec` 通过显式来源别名对应目录定义 `Quebec`，不覆盖原文。不会把组成部分的省区继承给整体、按坐标反查省区、推断行政边界，或把认定日期改成使用年代。

香港采用独立的`source_feature_district`角色：先核定来源要素与整体的明确对应，再按原`DISTRICT`字段建立关联；不是认定整体或全部几何属于该区。大潭22项构筑物跨Southern／Wan Chai来源值，任一区筛选均返回完整整体与全部原几何。CSDI字段采用其自定义条款及政府／平台署名，不扩展到古迹办链接全文或图像；详见[香港来源说明](HONG-KONG-LICENSE.md)。原繁体中文`DISTRIC_TC`保留，不翻译生成新地区证据。

巴西采用独立的`source_record_locality`角色，来源为[Iepha-MG原CSV](https://dados.mg.gov.br/dataset/bens-tombados)中的`municipio`字段，按[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)署名及保留加工说明。按已核完整登记范围连接其原行，再采用市镇字段全文；多地原串不自动拆分，复合登记多行的相同地区证据保留，但同一对象／地区只计一条关联。`BR:mg-municipio-…`为原值UTF-8哈希的项目标签，不是法定行政编码。未向现有UNESCO整体、仅自然分类或待核范围继承地区，也不按简称、坐标或地图边界补地区。Brazil目录现有21项未采用本套原字段，清除地区条件仍可查看。

原`Belo Horizonte, Nova Lima e Sabará`保持一个组合选项；选项关联完整`Serra do Curral`登记对象，不将其拆成三个遗址或三个已核地区关系。原`distrito`和`0`未用于生成地区选项；法律文书、立案年和登记簿不产生坐标或历史阶段。具体缺失标记歧义及原字段权利见[巴西来源说明](MINAS-LICENSE.md)。

Mérimée采用独立`source_record_commune`角色，来源为法国文化部原CSV的`Commune_forme_editoriale`全文，按[Licence Ouverte / Open Licence2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2-0)保留法国文化部、原字段署名、来源、取得日2026-11-05及加工说明。每条关联保留全部78个原字段的校验；不把原`Commune_forme_index`或地址猜成另一个现代行政区。既有批次原COG码经INSEE2026原行与UN M49明确关联GP、BL、MF、MQ、RE现代统计区域，保留原Region和Departement；原表旧Guadeloupe分组中的BL7条、MF1条不误归GP，也不从法国发布机构推断逐行FR归属。

`Saint-Denis;La Possession`等多市镇值保持一个组合选项，筛入完整资料对象与其限定范围；不拆分、地理编码、裁切几何或认定全部组成部分的行政区。`<area>:merimee-…`为国家／地区码与原市镇全文哈希派生的项目标识，不是COG或法定市镇编码。名录含曾或现受保护对象，地区证据不证明现行保护、建筑生命周期或历史政权归属。许可、原坐标精度与加工限制见[Mérimée来源说明](MERIMEE-LICENSE.md)。

v6采用相同角色追加`merimee-extension-v1`中GF90、YT16、PM16项资料的原记录关联。GF按UN M49的South America关联拉丁美洲与加勒比项目分组，YT按Eastern Africa关联非洲，PM按Northern America关联欧洲与北美；不将发布机构的FR标签继承给原行。23个选项按统计区域码及原全文区分，不是23个已核行政实体。`Montsinéry-Tonnegrande`与`Montsinéry-Tonnégrande`虽然同为原COG97313，仍保留两个来源拼写，不按COG合并或自动纠错。

Susky`PA97300012`的原组成记录只按已核关系指向Mamilipann`PA97300021`，不重复增加目录对象，也不向整体继承组成名称或坐标。本批122个来源参考点的精度保持`null`，未新增别名或历史阶段；地区索引不生成或修改这些点。具体完整范围、原文权利和点位证据见[本批Mérimée追加来源说明](MERIMEE-EXTENSION-LICENSE.md)。LO2适用于本数据集原字段，不自动扩展至外链照片、档案及第三方网页。

## 固定与重建

`subdivision_review.json` 保存来源复核字段与方法；`subdivisions.json` 保存紧凑的只读成员／证据；`subdivisions_manifest.json` 保存计数、版本及校验绑定。代码另固定 Review、派生文件、独立来源报告和规范化事实的四个SHA，并绑定加拿大、香港、Iepha-MG与两批Mérimée源合同。既有五区域关联使用`merimee_spec_sha256`（`f6b41e4368d1b31082502bf501f93e576cb6718c22a0c9e807b49480a64c9709`）；本批GF／YT／PM使用独立`merimee_extension_spec_sha256`（`1bea70c52cbf37a8264d1919888aa6cd9f7151cbdd3f5e6987b2b776cc6e425d`），不放宽既有来源的区域校验。独立报告是代理对照原来源的核验记录，不是专家或人工确认。

使用 `python -m archsearch.subdivisions --rebuild` 可从随仓库分发的复核字段离线重建；原始网页缓存不进入Git，普通运行不需要它们。正常启动只读取紧凑派生文件，校验失败时仅禁用省区功能；不会静默放宽正在使用的省区条件。

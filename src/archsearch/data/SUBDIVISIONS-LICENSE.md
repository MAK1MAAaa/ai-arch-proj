# 来源省／地区索引

`source-subdivisions-v1` 是独立目录关联，绑定 `global-v13` 的2976个身份及来源国家字段，不修改 Site、Geography、共享检索文本、历史阶段或任何定位点。13个定义、993条关联覆盖全部992个加拿大对象；一个跨省对象按两条关联保留。

## 来源与权利

- 986个整体对象的省／地区原字段来自 Parks Canada 的 [Federal Heritage Designations](https://open.canada.ca/data/en/dataset/49d5ba7d-d860-40d9-9183-892979e4acbe) 冻结发布记录（资源 `682d1e12-26dd-4d30-bb40-f04658502bcd`），按已采用的977条和9条同一整体身份提取。保留原行校验和、原发布页面校验和与逐对象来源链接，适用 [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)。既有加拿大来源处置及原字段见 `canada_review.json` 和 `CANADA-LICENSE.md`。
- Fort Conger 的 Nunavut 依据为 [Canadian Register of Historic Places 的原位置字段](https://www.historicplaces.ca/en/rep-reg/place-lieu.aspx?id=16360&pid=0)，保留原身份及页面SHA，不套用Wikidata或其他数据集许可。
- 其余五个原有世界遗产整体的位置依据为 Parks Canada 的 [加拿大世界遗产官方目录](https://parks.canada.ca/culture/spm-whs/sites-canada) 链接的逐对象页面：Grand Pré、Pimachiowin Aki、Tr’ondëk-Klondike、Writing-on-Stone／Áísínai’pi 和 Old Québec。只保留身份、极短的位置事实、来源、原字段与校验信息；原网页、图像及第三方材料保留各自权利，未授予它们统一开放许可。

`Pimachiowin Aki` 的原文 `Manitoba and Ontario` 生成两条整体关联；`Québec` 通过显式来源别名对应目录定义 `Quebec`，不覆盖原文。不会把组成部分的省区继承给整体、按坐标反查省区、推断行政边界，或把认定日期改成使用年代。

## 固定与重建

`subdivision_review.json` 保存来源复核字段与方法；`subdivisions.json` 保存紧凑的只读成员／证据；`subdivisions_manifest.json` 保存计数、版本及校验绑定。代码另固定 Review、派生文件、独立来源报告和规范化事实的四个SHA。独立报告是代理对照原来源的核验记录，不是专家或人工确认。

使用 `python -m archsearch.subdivisions --rebuild` 可从随仓库分发的复核字段离线重建；原始网页缓存不进入Git，普通运行不需要它们。正常启动只读取紧凑派生文件，校验失败时仅禁用省区功能；不会静默放宽正在使用的省区条件。

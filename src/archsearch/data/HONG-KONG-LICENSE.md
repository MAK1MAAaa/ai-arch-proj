# 香港整体古迹：来源、署名与加工

本批 `hong-kong-monuments-v1` 保留原2976条资料，新增140项经独立代理对照原来源核验的整体。`auth:hk-amo:monuments-N` 是项目对已核官方业务页面的引用，不是永久法律登记编号。证据核验不等于专家或人工确认。

## 两个来源时点

空间资料来自香港发展局／古迹办的 [CSDI原数据集元数据](https://portal.csdi.gov.hk/csdi-webpage/metadata/devb_wb_rcd_1639040299687_46105/html)，数据集ID为`devb_wb_rcd_1639040299687_46105`，固定层`DM_20260130_150858`，修订日期2026-01-30。174个原要素与官方1月名录138个整体分别核对，不能按共同详情URL、相似名称或要素OID自动去重。官方业务页的整体／部件证据及上窰村原范围图只支持对应对象，不将全部CSDI图形认定为法定界线。

[古迹办当前整体目录](https://www.amo.gov.hk/en/historic-buildings/monuments/)及[官方名录](https://www.amo.gov.hk/filemanager/amo/common/form/DM_Mon_List.pdf)固定到2026-10-02。后新增的湾仔洪圣古庙、赤柱清真寺采用各自官方事实与来源指针；1月空间版本没有它们的几何，不以其他建筑、行政中心或求中心补足。

## 使用条款与署名

数据来源：Government of the Hong Kong Special Administrative Region / Common Spatial Data Infrastructure (CSDI) Portal / Antiquities and Monuments Office。承认上述机构的相关知识产权。CSDI发布资料适用其[使用条款](https://portal.csdi.gov.hk/csdi-webpage/doc/TNC)及[署名说明](https://portal.csdi.gov.hk/csdi-webpage/info/FAQ)；允许免费商业及非商业复制、分发须遵守其署名、权利及责任条件，不标作CC、OGL或公共领域。

古迹办网页及其链接资料保留[各自权利](https://www.amo.gov.hk/en/important-notices/index.html)，CSDI授权不扩展到这些外链内容。本项目只采用事实性名称、字段及必要短证据和链接，不分发原历史介绍全文、照片、原PDF或原网页缓存，不声称政府背书或访客可进入。

## 几何、地区和年代

原坐标系香港1980／EPSG:2326，WGS84数据是提供者实际`outSR=4326`响应。174要素、180环、4050条原坐标记录保持原顺序与数值；只画不填色轮廓，不合并、推断内外环或计算中心。统一标为“来源古迹多边形”，不宣称等于法定保护边界、古代轮廓、发掘精度或开放范围。它们不变成代表点或全库点层中的定位记录。

原`DISTRICT`／`DISTRIC_TC`为要素地区。通过显式整体／要素关系形成139项来源地区关联，覆盖138个整体；大潭整体同时关联Southern和Wan Chai，筛选仍保留完整22个构筑物。两个较晚增补保持地区未知，不从名字或大区推测。17个来源值不代表香港行政区总数。

HK代码由固定UN M49原行与来源Hong Kong位置证据关联；项目显示名、分组与原表字段分别保留。只采用15个有效表格单元格，忽略HTML注释中的旧分类。原英文和繁体中文不转写，`DEC_YEAR`／`DEC_YE_TC`不转成生命周期；本批无新历史阶段和代表点。

## 固定与重建

`hong_kong_review.json`保存完整审核事实，`hong_kong_sites.json`和`hong_kong_manifest.json`离线派生；代码以七个外部SHA绑定来源、完整事实及派生版本，重新签派生校验不能替代事实审批。`hong_kong_areas.json`另绑定原要素与逐要素SHA及来源合同。

普通运行只读随仓库分发的本地资料。原始159份核验缓存、完整页和PDF不进入Git；如已有缓存，可按README显式核验和重建几何。缺损香港几何只影响该来源，正常的澳大利亚范围仍可使用。

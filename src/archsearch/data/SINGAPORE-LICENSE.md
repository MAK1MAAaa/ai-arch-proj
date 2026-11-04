# 新加坡NHB古迹资料：来源、许可与加工

本项目的`singapore-monuments-v1`来源于 National Heritage Board 经 [data.gov.sg 的 Monuments (GEOJSON)](https://data.gov.sg/datasets/d_b29c230ec6b609e29ed42f71ca9a8767/view) 发布的数据。资料及原英文`DESCRIPTION`按 [Singapore Open Data Licence version 1.0](https://data.gov.sg/open-data-licence)使用。该许可允许复制、分发和适配数据，要求显著署名及链接最新许可；不授予未获授权的第三方权利、个人数据、商标、专利或设计权。

Contains information from Monuments (GEOJSON), National Heritage Board, accessed on 2026-11-05 from data.gov.sg, made available under the Singapore Open Data Licence version 1.0: https://data.gov.sg/open-data-licence.

取得日期按Asia/Shanghai记录；原下载收据为2026-11-04T21:28:53Z。网页和导出分别保留署名、取得日期与许可链接，项目整理及代理核验不代表NHB官方背书。

## 固定发布与身份

原GeoJSON SHA-256为`a9566c0c0ae061e1ea429bd5e6221a02cb443f6ce0a63d5089647af25624a4d6`，含77个原Point及16个原字段。覆盖标签`Data from Mar 2021`、目录更新`16 Apr 2026`、逐行`FMEL_UPD_D`为独立时钟；原FME值有2021与2026两组，未说明时区。77不是本项目独立证明的当前法定完整名录数量。

逐项对照来源名称、限定范围、原业务链接和既有3116条资料，77项经独立代理复核后收录。三座Singapore River Bridges作为一个复合整体，Changi仅为原入口门、墙与塔楼，Goodwood仅为Tower Block，Chinese High School仅为Clock Tower Building；Former Kandang Kerbau Hospital限定原三个楼块。Former Raffles College限定六座建筑和两处庭院，与既有植物园记录的历史关联及范围讨论留在审计，未扩大为整个现校园，也未声称所有对象空间互不重叠。

项目ID为`auth:sg-nhb:roots-`加原`HYPERLINK`完整UTF-8字符串的SHA-256。该ID表达项目所核业务URI身份，不是法定永久编号；原OBJECTID、URI大小写、完整字段与限定范围另行保留。两条原链接失效时使用另经核实的当前官方入口，原业务URI及其ID不改写。

## 描述、坐标与年代

保留许可数据集中的原英文简介，中文简介和新别名不自动生成。原`PHOTOURL`只作为数据字段保存，未获取或再分发照片；开放数据许可不自动扩展到外链Roots／NHB网页、图片或第三方内容。辅助网页仅保存必要短事实及外链，其权利以各原站为准。

采用原Point作为本项目的公开参考代表位置。[GeoJSON格式契约](https://www.rfc-editor.org/rfc/rfc7946#section-4)按WGS84经度、纬度解释；原文件没有单独CRS或精度声明，未将地址字段`LANDXADDRESSPOINT`／`LANDYADDRESSPOINT`当作经纬度，未自行投影或计算中心。提供者生成方法及误差未知，不宣称点位是整体中心、发掘位置或法定边界。一个复合对象的一个Point不拆成多个构件点。

原16字段没有区级字段，不从街道、邮编、坐标或保护机构推断行政地区或政治归属。SG及项目Asia-Pacific分组保留官方国家／地区上下文；未重写既有国家标签。新增资料没有已核历史阶段，认定、更新及覆盖年份不作建造、使用或毁损日期，也不触发历史地图切年。

## 可复现分发

随代码分发规范化原字段侧车、独立复核、资料和清单四份JSON；分别固定原文件、原行、原Point、全来源事实、独立审查与派生文件SHA。原3116条字段、顺序及共享检索文档不变。所有核验为代理对照来源，不是专家或人工确认。

20份完整来源缓存、原GeoJSON、页面、模型和索引不进入Git。普通安装及离线重建只需上述规范化文件；原缓存核验仅对已保存的固定原文件执行。原公开S3下载在独立复查时返回403，未绕过或伪称重新下载；原200收据和冻结字节独立逐值核验保留，正常下载入口为data.gov.sg数据集页面。更新下载若与固定SHA不同，不自动覆盖已核发布。

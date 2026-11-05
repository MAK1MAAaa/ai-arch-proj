# 现代边界线参照

现代图叠加本地 Natural Earth **1:50m Admin 0 land boundary lines，数据集5.1.0**，用浅色外描边提高深色线在OSM和本地自然轮廓上的辨识度。图层不交互，不遮挡遗址点选择。线层不覆盖海岸以外的海洋划界，不补绘资料未提供的边界。

固定官方发行快照为 [`v5.1.2`](https://github.com/nvkelso/natural-earth-vector/tree/f1890d9f152c896d250a77557a5751a93d494776)，提交 `f1890d9f152c896d250a77557a5751a93d494776`。发行版本与单个主题数据版本不同；此线主题的官方VERSION文件和[下载页](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-boundary-lines-2/)均为5.1.0。

Natural Earth默认按来源的实际控制视图绘制，不代表精确法定国界或本项目对争议归属的判断。保留来源的`FEATURECLA`分类：355条国际边界使用实线，21条争议线、7条控制线、5条不确定线及2条未定边界使用虚线。页面不依据这些线为遗址推定国家、历史政权或政治归属。

素材来自Natural Earth官方维护仓库和官方NACIS下载镜像，遵循[公有领域条款](https://www.naturalearthdata.com/about/terms-of-use/)。保留作者Tom Patterson、Nathaniel Vaughn Kelso及Natural Earth贡献者署名。此为小比例尺概略参照，高倍缩放不能解释为测绘级或实时疆界。

## 可复现来源

归档：`https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_boundary_lines_land.zip`

归档SHA-256：`02f369ae10578c4ce33fc4a08f8cdd69ea11eb39b44d7923e88eb7199aaff8ea`

固定GeoJSON SHA-256：`2faac4f6b34386f3d21b6e018cf151f241f00e5c936d44dd17d7d9bfb147fa48`

完整源URL、版本文件校验、处理说明及派生文件校验见[来源清单](../src/archsearch/static/data/modern-boundaries-source.json)。保留390条来源线记录、382个`NE_ID`、393条线段和19,859个点。来源有8个`NE_ID`各出现两次，独立线记录均保留，以原始顺序生成`record_id`区分。仅删除未使用属性与包围盒，未简化或重绘坐标，未应用其他POV分类过滤。浏览器仅为跨日期变更线显示绘制世界副本，源坐标不变。

在仓库根目录使用已有Node.js和pnpm环境执行：

```powershell
node --experimental-strip-types scripts/build-modern-boundaries.ts --download
```

首次下载到`.archsearch/downloads/modern-boundaries-v5.1.0/`。已有固定缓存时省略`--download`；也可用`--source-cache <目录>`指定缓存。任何源文件校验不匹配都会停止，不静默更换版本。运行网页无需下载、Node.js或额外Python依赖；CI只校验已提交的小型派生线层，不联网获取全量资料。

线层加载失败会单独显示状态并允许重试，现代底图、遗址点和历史图仍可继续使用。

# 协作约定

- 使用专业简体中文，直接说明结果，不使用表情符号。
- 保持Python类型标注、模块职责分离和真实来源证据；变更功能、依赖或启动方式时同步README。
- 数据只使用可追溯记录；代表点不是精确发掘坐标。未完成并确认人工标注前，评测指标必须为null。
- 应用运行在Windows本地，同源FastAPI与静态前端；模型运行期只读取本地文件。

## 检查

在仓库根目录执行：

```powershell
uv run --no-sync ruff check .
uv run --no-sync mypy src
uv run --no-sync pytest
```

前端与工具源码使用TypeScript，包管理统一pnpm。运行 `pnpm install --frozen-lockfile`、`pnpm typecheck`、`pnpm build`、`pnpm test:frontend`与`pnpm test:workflows`。修改前端时编辑`src/archsearch/frontend/`下的`app.ts`或`research.ts`，编译后的对应`static/*.js`及source map须同步提交，不手工编辑生成文件。Leaflet保留原版第三方资源。

CI不得下载模型或全量数据；真实模型与浏览器交互在本地另外验证。

## Git交付

- 初始化完成后，功能变更在`feature/dev`开发，`main`只通过PR更新。
- 每个完整且可验证的变更批次同步README、运行适当检查、独立审查、commit和push，创建或更新`feature/dev → main` PR，并启用仓库的自动squash合并。
- `main`要求`quality-gate`及一个批准，管理员同样适用。审批由默认分支上的Actions机器人核对最新CI与当前head，不以作者身份自行批准，不跳过保护。
- 每次合并后确认PR已合并、远端开发head未变化、本地没有额外提交；备份旧head并保存工作区，再将开发分支对齐main。
- 开发分支的远端同步仅可使用指定旧SHA的`--force-with-lease=refs/heads/feature/dev:<已合并head>`；租约失败停止，不覆盖他人新提交。禁止裸`--force`及main强推。
- 模型、全量归档、索引、评测输出、凭据和虚拟环境不进入Git。凭据仅在内存中使用，输出不得包含令牌。

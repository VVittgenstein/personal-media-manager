# Compact — T-20251212-act-004-category-views

## 1) Scope 对齐（来自 record.json）
- Subtask: `T-20251212-act-004-category-views`（实现 Images/Scattered/Videos/Games/Others 视图列表）
- Priority/Lane: `P0` / `now`
- Depends on:
  - `T-20251212-act-004-spa-shell`
  - `T-20251212-act-001-classify-api`
  - `T-20251212-act-002-album-cover-mosaic`
  - `T-20251212-act-003-ffmpeg-mosaic`
- Acceptance:
  - Images：相册卡片列表（四宫格封面 + 名称）
  - Scattered：散图缩略图扁平列表
  - Videos：视频卡片（有预览图则展示，无则占位）
  - Games：占位或简单列表且不提供执行入口
  - Others：非媒体文件列表（名/类型/大小等基础信息）

## 2) Interface / 行为变更（影响下游对接）
- 前端开始消费后端索引/缩略图 API：
  - `GET /api/albums` → Images 相册网格
  - `GET /api/scattered` + `GET /api/thumb?path=...` → Scattered 缩略图网格
  - `GET /api/videos` + `GET /api/video-mosaic?path=...` → Videos 卡片（预览失败自动占位）
  - `GET /api/others` → Games/ Others 基础表格
- 增加“Refresh index”按钮：通过 `?refresh=1` 触发后端重建索引（同一路由内刷新，不跳页）。

## 3) 已确认事实（代码 + 自测覆盖）
- 自测命令：`python3 -m unittest -q` → `OK`
- 图片/封面/视频预览使用懒加载：仅在进入视口附近时设置 `img.src`，减少一次性请求数量。

## 4) 实现事实快照（实现要点）
- `frontend/spa/app.js`
  - 为 5 个分类路由补齐数据加载与渲染（含 loading/error/empty 状态）
  - 统一 meta bar（条目数/扫描时间/MediaRoot）+ 刷新按钮
  - `IntersectionObserver` 实现图片懒加载（不支持时自动降级为立即加载）
- `frontend/spa/styles.css`
  - 新增 Albums/Thumbnails/Videos 网格与文件表格样式
  - 缩略图容器带占位与加载完成渐显

## 5) 显式限制 / 风险 / TODO（未在本 Subtask 内解决）
- Videos 预览依赖 FFmpeg：未安装/不可用时 `video-mosaic` 会失败，前端会保持占位（不阻塞列表）。
- 相册进入/图片 Overlay 的交互不在此任务范围内（由后续 Overlay 相关任务实现）。

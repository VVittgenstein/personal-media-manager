# Compact — T-20251212-act-006-video-overlay-ui

## 1) Scope 对齐（来自 record.json）
- Subtask: `T-20251212-act-006-video-overlay-ui`（实现视频 Overlay 播放器基础功能）
- Priority/Lane: `P0` / `now`
- Depends on:
  - `T-20251212-act-004-category-views`
- Acceptance:
  - 点击视频卡片弹出 Overlay 并自动播放
  - 提供暂停/音量/进度拖动/全屏等基础控制
  - 关闭 Overlay 后视频停止且资源释放正常

## 2) Interface / 行为变更（影响下游对接）
- 新增后端接口：
  - `GET /api/media?path=<rel_path>` → 200/206 返回视频文件字节流；支持 `Range: bytes=...` 以便拖动进度；非视频类型返回 415（`UNSUPPORTED_MEDIA_TYPE`）。
- 前端交互：
  - Videos：点击视频卡片打开 Overlay，默认自动播放；使用浏览器原生 `video.controls` 提供暂停/音量/进度/全屏控制。
  - Overlay：`Esc`/Close/Backdrop 关闭；关闭时 `pause()` + 清空 `src`/`poster` 并 `load()` 以释放资源；支持 Prev/Next（按钮/`←`/`→`）切换视频。

## 3) 已确认事实（代码 + 自测覆盖）
- 自测命令：`python3 -m unittest -q` → `OK`
- `/api/media`：206 Range、416 Range Not Satisfiable、以及非视频 415 已由 `backend/api/tests/test_server.py` 覆盖。

## 4) 实现事实快照（实现要点）
- `backend/api/server.py`
  - 增加 `/api/media`：在 MediaRoot 沙箱内以流式方式输出视频文件；按需返回 206 + `Content-Range`，并声明 `Accept-Ranges: bytes`。
- `frontend/spa/app.js`
  - 新增 `createVideoOverlay()`：Overlay DOM + 打开/关闭/上一条/下一条 + 键盘事件。
  - Videos 视图将卡片改为按钮并绑定点击事件以打开 Video Overlay；路由切换与 `popstate` 时关闭所有 Overlay。
- `frontend/spa/styles.css`
  - `video-card` 适配按钮元素（重置默认样式并加入 hover/active 反馈）。
  - 增加 `.overlay__video` 样式以在 Overlay 中等比显示并占满可用区域。

## 5) 显式限制 / 风险 / TODO（未在本 Subtask 内解决）
- 编解码支持差异与“不支持格式提示/外部打开/转码建议”由后续 `T-20251212-act-006-format-hints` 覆盖。


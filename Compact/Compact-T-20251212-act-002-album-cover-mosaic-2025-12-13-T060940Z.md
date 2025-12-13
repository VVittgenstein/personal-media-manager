# Compact — T-20251212-act-002-album-cover-mosaic

## 1) Scope 对齐（来自 record.json）
- Subtask: `T-20251212-act-002-album-cover-mosaic`（生成相册 2×2 四宫格封面并随变更更新）
- Priority/Lane: `P0` / `now`
- Depends on: `T-20251212-act-002-image-thumbs`
- Acceptance:
  - 为每个相册随机/均匀选 4 张图拼 2×2 封面
  - 封面生成后缓存复用
  - 相册增删图片后封面可失效并重建

## 2) Interface / 行为变更（影响下游对接）
- 新增 HTTP：
  - `GET /api/album-cover?path=<ALBUM_REL>`：返回 `image/jpeg`（带 `ETag`，支持 `If-None-Match` → `304`）
- 缓存目录：
  - 复用 `--thumb-cache-dir`（默认 OS cache dir），在其下新增 `album-covers/` 子目录

## 3) 已确认事实（代码 + 自测覆盖）
- 自测命令：`python3 -m unittest -q` → `OK`
- `/api/album-cover`：
  - Pillow 未安装时返回 `503` 且错误码为 `PILLOW_NOT_INSTALLED`
  - 相册内容变化（新增图片）后 `ETag` 会变化并触发重建（`backend/api/tests/test_server.py` 覆盖）

## 4) 实现事实快照（代码实现；部分依赖 Pillow 才能在运行时生效）
- 随机选图：
  - 仅从相册目录的“直接子文件”中选择图片
  - 使用 `album_rel_path + album_mtime_ns + album_listing_hash` 生成稳定 seed；同一版本相册封面稳定、目录内容变化时 seed 更新
  - 图片少于 4 张时按 seed 规则补齐到 4 张（允许重复）
- 缓存与失效：
  - `ETag` key = cover spec + album mtime + `album_listing_hash` + 4 张图的（`mtime+size` 或 `sha1`）
  - 缓存文件路径：`<cache>/album-covers/<aa>/<bb>/<etag>.jpg`
- 安全边界：
  - `path` 必须为 MediaRoot 内相对路径；通过 `normalize_rel_path` + `MediaRootSandbox` 拒绝越界与 symlink/junction 逃逸
- 渲染样式：
  - 每个 tile 使用“放大裁切模糊背景 + 前景等比完整可见”策略（避免黑边），拼成 2×2 JPEG

## 5) 显式限制 / 风险 / TODO（未在本 Subtask 内解决）
- 运行时依赖：Pillow 未安装时无法生成封面（对外表现为 `503 PILLOW_NOT_INSTALLED`）
- 缓存治理：未实现 cache 清理/TTL（目录变化会产生陈旧文件残留）
- 相册判定：当前不校验 `path` 是否为“叶子相册目录”，只要目录内有图片即可生成封面


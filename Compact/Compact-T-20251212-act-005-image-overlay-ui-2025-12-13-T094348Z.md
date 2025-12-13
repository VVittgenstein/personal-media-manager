# Compact — T-20251212-act-005-image-overlay-ui

## 1) Scope 对齐（来自 record.json）
- Subtask: `T-20251212-act-005-image-overlay-ui`（实现图片 Overlay 查看器基础交互）
- Priority/Lane: `P0` / `now`
- Depends on:
  - `T-20251212-act-004-category-views`
- Acceptance:
  - 点击相册封面或图片项弹出 Overlay
  - 默认打开相册第一张图
  - 支持按钮/键盘左右切换与关闭
  - 关闭后回到原列表位置并保持上下文

## 2) Interface / 行为变更（影响下游对接）
- 新增后端接口：
  - `GET /api/album-images?path=<album_rel_path>` → 200 返回相册目录下的图片相对路径列表（按名称排序）；相册不存在时返回 404（`NOT_FOUND`）。
- 前端交互：
  - Images：点击相册卡片打开 Overlay，异步加载相册图片列表后默认展示第 1 张。
  - Scattered：点击缩略图打开 Overlay，从当前列表连续左右切换。
  - Overlay：`Esc` 关闭；`←/→` 切换；按钮 Prev/Next/Close 可用；关闭后恢复滚动位置与焦点。

## 3) 已确认事实（代码 + 自测覆盖）
- 自测命令：`python3 -m unittest -q` → `OK`
- `/api/album-images`：相册目录不存在时返回 `404 NOT_FOUND`（`backend/api/tests/test_server.py` 覆盖）。

## 4) 实现事实快照（实现要点）
- `backend/api/server.py`
  - 增加 `/api/album-images`，在 MediaRoot 沙箱内列出指定相册目录下的图片文件；路径解析使用 allow-missing 版本以保证相册缺失时返回 404。
- `frontend/spa/app.js`
  - 新增 `createImageOverlay()`：Overlay DOM + 打开/关闭/上一张/下一张 + 键盘事件。
  - Images/Scattered 视图为卡片/缩略图绑定点击事件以打开 Overlay。
- `frontend/spa/styles.css`
  - 补齐 Overlay 样式（backdrop、header、nav、image stage）。
  - 将相册卡片/缩略图 tile 调整为按钮元素时的样式重置。

## 5) 显式限制 / 风险 / TODO（未在本 Subtask 内解决）
- Overlay 目前使用 `/api/thumb` 缩略图作为查看源；更完整的等比缩放与“黑边”处理由后续 `T-20251212-act-005-image-scaling` 覆盖。
- 未引入基于 URL 的 Overlay 状态（深链接/后退关闭）机制；当前以同页 modal 方式保持列表上下文为主。

## Code Review - T-20251212-act-005-image-overlay-ui - 2025-12-13T10:23:54Z

---review-start---
{
  "findings": [
    {
      "title": "[P2] Allow missing album paths before statting",
      "body": "When `/api/album-images` is called for a non-existent album, `MediaRootSandbox.to_abs_path` requires every path segment to exist and raises `SandboxViolation`, so the handler returns a 400 SANDBOX_VIOLATION before reaching the 404 Not Found branch. Clients will see an invalid-request error instead of the intended not-found response whenever an album folder is missing or was removed. Use the allow-missing sandbox helper (or defer sandbox traversal until after the existence check) so missing albums produce a 404.",
      "confidence_score": 0.49,
      "priority": 2,
      "code_location": {
        "absolute_file_path": "/mnt/z/Project/personal-pron-media-manager/backend/api/server.py",
        "line_range": {
          "start": 276,
          "end": 280
        }
      }
    }
  ],
  "overall_correctness": "patch is incorrect",
  "overall_explanation": "Missing albums currently return a 400 sandbox error instead of 404 due to the allow-missing check being applied too early in the new /api/album-images handler.",
  "overall_confidence_score": 0.49
}
---review-end---

## Review Follow-up (applied)
- 已修复 `backend/api/server.py`：`/api/album-images` 使用 `MediaRootSandbox.to_abs_path_allow_missing()`，相册缺失时不再提前触发 `SANDBOX_VIOLATION`，而是按预期返回 `404 NOT_FOUND`。
- 已新增回归测试：`backend/api/tests/test_server.py` 增加 `test_album_images_missing_album_returns_404`。
- 已更新 `record.json`：补充 `T-20251212-act-005-image-overlay-ui` 的 artifacts，并更新 `updated_at`。

## Code Review - T-20251212-act-005-image-overlay-ui - 2025-12-13T11:33:12Z

---review-start---
{
  "findings": [
    {
      "title": "[P1] Album-images endpoint follows symlinked dirs outside MediaRoot",
      "body": "The new `/api/album-images` handler lstat’s the requested path with `follow_symlinks=False`, but then calls `abs_dir.is_dir()` and `os.scandir(abs_dir)` which both follow symlinks. If a user creates an album entry that is a symlink to an external directory, the endpoint will happily list images outside `MediaRoot`, bypassing the sandbox expectation. Consider rejecting symlinked albums (e.g., `abs_dir.is_dir(follow_symlinks=False)` and/or `abs_dir.is_symlink()` guard) before scanning.",
      "confidence_score": 0.42,
      "priority": 1,
      "code_location": {
        "absolute_file_path": "/mnt/z/Project/personal-pron-media-manager/backend/api/server.py",
        "line_range": {
          "start": 283,
          "end": 294
        }
      }
    }
  ],
  "overall_correctness": "patch is incorrect",
  "overall_explanation": "The album-images endpoint allows traversing symlinked album paths, letting callers list files outside the MediaRoot and defeating sandboxing expectations.",
  "overall_confidence_score": 0.4
}
---review-end---

## Review Follow-up (applied)
- 已修复 `backend/api/server.py`：`/api/album-images` 扫描前拒绝 symlink/reparse point 的相册目录，避免通过软链接跳出 MediaRoot。
- 已新增回归测试：`backend/api/tests/test_server.py` 增加 `test_album_images_rejects_symlinked_album_dir`。
- 已更新 `record.json`：更新 `T-20251212-act-005-image-overlay-ui` 的 `updated_at`。

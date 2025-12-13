# Compact — T-20251212-act-001-scan-inventory

## Scope
- Subtask: `T-20251212-act-001-scan-inventory`（实现 MediaRoot 目录扫描与安全沙箱）
- Type: build, Priority: P0, Lane: now
- Dependency: `T-20251212-act-001-index-schema`（已完成）
- Change set:
  - 新增 `backend/scanner`：递归扫描、默认跳过 `_trash`、symlink/junction 越界防护与可理解告警输出
  - 新增 CLI：`python3 -m backend.scanner ...` 产出 raw inventory JSON
  - 新增自测：`python3 -m unittest -q` 覆盖跳过 `_trash`、可包含 `_trash`、symlink 不遍历、rel_path 规范化与沙箱拒绝 reparse traversal
  - 更新 `record.json`：该任务 `status=done`，并更新 artifacts/updated_at
- Self-test (reported):
  - `python3 -m unittest -q` → OK（5 tests）

## Confirmed Facts (implemented + verified)
- 递归扫描 MediaRoot，输出 “目录/文件” 清单与基础元信息：
  - `rel_path`（统一 `/` 分隔；根目录为 `""`）、`kind`（`"dir"|"file"`）、`size_bytes`（文件）、`mtime_ms`（毫秒）
  - 输出结构：`{ media_root, scanned_at_ms, items[], warnings[], stats{} }`
- 默认跳过 `MediaRoot/_trash/`：
  - 仅当相对路径的第一段为 `_trash`（case-insensitive）时跳过（即只针对根下 `_trash`）
  - CLI 提供 `--include-trash` 可覆盖默认行为
- 安全沙箱与越界保护已落地：
  - 扫描阶段：不跟随 symlink/junction（含 Windows reparse point），遇到 link 记录告警并跳过，不会进入 link 指向的目录/文件
  - 路径校验基元：`MediaRootSandbox` 支持将 `rel_path` 转为绝对路径并拒绝 `..`、盘符、UNC、绝对路径，以及任一路径段为 symlink/reparse point 的 traversal
- 异常鲁棒性（权限不足/不可访问等）：
  - `scandir/stat` 失败不崩溃：记录 `warnings`（如 `SCANDIR_FAILED`、`STAT_FAILED`）并继续扫描其余条目

## Interface / Behavior Changes
- 新增 Python API（供后续 `backend/indexing`、fileops 等模块复用）：
  - `backend.scanner.scan_inventory(media_root, skip_trash=True, trash_dir_name="_trash") -> InventoryResult`
  - `backend.scanner.MediaRootSandbox` / `SandboxViolation`（路径规范化与越界拒绝）
- 新增 CLI（raw inventory 输出口径的事实来源）：
  - `python3 -m backend.scanner --media-root <path> [--output <file>|-] [--include-trash] [--log-level <LEVEL>]`

## Explicit Limits / Risks / TODO
- 当前 inventory 输出为“原始清单”，尚未映射到 `index-schema.md` 的 `Folder/ImageFile/...` 实体；后续 `T-20251212-act-001-classify-api` 需要基于该输出构建索引与分类。
- 异常文件名覆盖有限：自测未覆盖包含不可编码字符/代理项（surrogate）的文件名；JSON 序列化/写盘在极端情况下可能需要额外处理策略。
- link 处理策略为“跳过并告警”，不做“硬失败终止扫描”；若未来需要更强策略（例如遇越界立即失败），需在上游验收口径中明确。


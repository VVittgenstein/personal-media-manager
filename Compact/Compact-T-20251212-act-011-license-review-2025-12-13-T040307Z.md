# Compact — T-20251212-act-011-license-review

## 1) 范围对齐

- Subtask：T-20251212-act-011-license-review（梳理第三方依赖与许可证（含 FFmpeg））
- 验收草案（record.json）：(1) 列出主要依赖及许可证类型；(2) 给出 FFmpeg Windows 集成方式与分发注意事项结论；(3) 输出 LICENSE/NOTICE 草案
- 本次变更：新增 `doc/licenses/dependency-license-list.md`、新增根目录 `NOTICE`、更新 `record.json`
- 自测：`python3 -m json.tool record.json`（OK）；仓库依赖清单探测未发现 `requirements*.txt`/`pyproject.toml`/`package.json` 等；后端 `backend/**/*.py` import 扫描未发现第三方包（仅标准库 + 仓库内模块）

## 2) 已确认事实（代码 + 自测覆盖）

- 依赖与许可证清单草案已落地：`doc/licenses/dependency-license-list.md`
  - 记录仓库当前依赖现状：后端代码为 Python 标准库 + 仓库内模块；未发现 Python 依赖清单（requirements/pyproject）或前端依赖清单（package.json 等）。
  - 给出 FFmpeg（Windows）默认集成策略：外部 CLI 调用；默认不随包分发；用户自装/自提供 `ffmpeg.exe`/`ffprobe.exe`（PATH 或配置路径），并给出最小验证命令示例。
  - 记录“若未来需要随包分发 FFmpeg”的注意事项：优先 LGPL 构建；分发时需随附许可证文本、源码/源码获取方式与构建信息；避免链接方式集成 `libav*`（文档为草案结论）。
  - 记录计划/可选组件的许可证类型占位：Pillow（PIL/HPND）、Video.js（Apache-2.0）、SQLite（Public Domain）等（均未在仓库中实际引入）。
- `NOTICE` 草案已新增：`NOTICE`
  - 声明本项目 MIT（见 `LICENSE`），并以“Draft / not legal advice”形式列出未随仓库分发的运行时依赖（Python、FFmpeg）与计划/可选依赖占位。
- `record.json` 状态已更新（并通过 JSON 校验）
  - `T-20251212-act-011-license-review`：`status` 已置为 `done`，`artifacts` 指向 `doc/licenses/dependency-license-list.md`、`LICENSE`、`NOTICE`。
  - `DEP-001`（FFmpeg）在 `external_dependencies`：`status=decided`，并写入 `doc_url=doc/licenses/dependency-license-list.md` 与默认策略说明。
  - `T-20251212-act-003-ffmpeg-mosaic`：已从 `blocked=true` 解除为 `blocked=false`（`blocked_by` 清空，`unblock_plan` 置空）。

## 3) 接口与行为变更（影响其他模块）

- 工作流依赖解锁：`T-20251212-act-003-ffmpeg-mosaic` 不再被许可证/分发策略阻断，可进入实现阶段。
- 对后续实现的输入约定（来自本次文档结论/验收草案）：视频缩略图能力应依赖外部 `ffmpeg.exe`/`ffprobe.exe` 可执行文件（PATH/配置），并在不可用时返回明确错误与安装/配置指引（实现仍由后续 Subtask 完成）。

## 4) 关键实现要点（事实快照）

- 以“文档 + NOTICE”形式固化依赖与许可证边界：在未引入新第三方依赖前，先明确 FFmpeg 采取外部 CLI、默认不分发的策略，以降低未来分发合规成本与不确定性。
- `record.json` 同步了任务完成态与外部依赖状态，使后续 FFmpeg 集成任务可继续推进。

## 5) 显式限制 / 风险 / TODO（当前边界）

- `doc/licenses/dependency-license-list.md` 与 `NOTICE` 均为草案且声明“不构成法律意见”；未进行自动化 license scan，亦无任何法律审查结论。
- FFmpeg 具体许可证义务取决于所选构建（LGPL vs GPL 等）；当前仅记录推荐策略与分发注意事项，未包含具体下载来源/构建校验/随附许可证文本落地。
- 未来一旦引入第三方 Python/npm 依赖或做二进制分发（含 Python 运行时/FFmpeg），需要补齐：依赖枚举、许可证文本随附、NOTICE 更新与来源追溯材料。
- `record.json` 中风险 `R-20251212-ffmpeg-license` 仍为 high；本 Subtask 覆盖了“策略与文档”部分，但尚未落地运行时检测/提示与实际抽帧实现（由 `T-20251212-act-003-ffmpeg-mosaic` 覆盖）。
- `record.json` 本次存在一定格式/换行层面的 diff 噪音（不影响语义字段更新），Review 时建议聚焦上述状态字段与依赖信息变更。

# Compact — T-20251212-act-010-backend-config

## Scope
- Subtask: `T-20251212-act-010-backend-config`（加入后端基础配置与端口冲突处理）
- Type: build, Priority: P1, Lane: now
- Dependency: none
- Acceptance (record.json):
  - 支持通过配置文件或启动参数指定 MediaRoot
  - 默认端口可配置；占用时自动换端口或提示
  - 启动后输出实际访问 URL

## Change Set（代码改动）
- 新增 `backend/config/backend_config.py`：加载后端运行配置（默认 `config/backend.json`）
- 新增 `config/backend.json`：配置模板（`media_root/host/port`）
- 更新 `backend/api/server.py`：
  - CLI：新增 `--config/--port-conflict/--port-search-limit`；`--media-root/--host/--port` 可由配置补全
  - 端口冲突：`auto` 顺序尝试后续端口；`fail` 端口占用即失败
  - 启动输出：日志 + stdout 打印实际 URL（用于脚本/launcher 消费）
- 测试：
  - 更新 `backend/api/tests/test_server.py`：新增端口冲突（auto/fail）自测
  - 新增 `backend/config/tests/test_backend_config.py`：配置解析与类型校验自测
- 文档同步：`README.md` 增加按配置启动说明
- Meta：`record.json` 将该 subtask 标记为 done，并补充 artifacts/updated_at

## Confirmed Facts（代码 + 自测覆盖）
- 配置读取（`load_backend_config`）：
  - 显式路径不存在会抛 `FileNotFoundError`
  - 可读取 `media_root/host/port`，并对 `port` 类型做校验（非 int 会 `TypeError`）
- 端口绑定（`_bind_http_server`）：
  - `conflict_mode=auto`：当指定端口被占用时会绑定到不同端口
  - `conflict_mode=fail`：当指定端口被占用时会抛 `OSError`
- Self-test:
  - `python3 -m unittest` → OK（25 tests）

## Implemented Behavior（实现但未在单测中逐条断言）
- 配置来源优先级：CLI 参数 > `--config` 指定文件 > 默认 `config/backend.json`（缺失则忽略）
- MediaRoot 必填：若 `--media-root` 与配置 `media_root` 都缺失/空字符串，启动时 argparse 直接报错退出
- 端口占用提示/退出：
  - `--port-conflict=auto` 且发生端口切换时会输出 warning（“port X is in use; using Y instead”）
  - `--port-conflict=fail` 或 auto 扫描失败时，main 捕获端口占用错误并返回退出码 2
- URL 输出：
  - stdout 额外打印一行 `<url>`（实际绑定端口）
  - 若 bind host 为 `0.0.0.0`/`::`，打印 URL 会展示为 `127.0.0.1`

## Explicit Limits / Risks / TODO（显式边界）
- `config/backend.json` 模板中 `media_root` 为空；用户需自行填写或用 `--media-root` 覆盖，否则启动会失败（预期行为）
- `auto` 仅按顺序尝试后续端口且有上限（默认 50）；连续占用时仍可能失败（可用 `--port-search-limit` 调整）
- 仓库当前跟踪 `__pycache__/*.pyc`；运行自测会产生二进制 diff（review 噪音/潜在提交污染风险）

## Interface Impact（可能影响其他模块）
- 启动入口 `python3 -m backend.api` 现在支持从 `config/backend.json` 补全 MediaRoot/端口；后续 `T-20251212-act-010-bat-launcher` 可：
  - 读取同一配置文件并传参启动
  - 或解析 stdout 打印的 URL 打开浏览器（注意 auto 模式下端口可能被改写）


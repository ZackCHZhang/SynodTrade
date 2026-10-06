# quant-webapi

[中文](#中文) | [English](#english)

---

## 中文

Web 控制台的后端（FastAPI）。前端在仓库根目录的 `web/`（React + MUI + Vite），构建后由本服务一起提供。
依赖关系上位于最顶层：`scheduler ← webapi`，可以使用所有包。

### 启动

```bash
python tasks.py web                       # 首次：安装前端依赖并构建 web/dist
poetry run quant-web serve                # http://127.0.0.1:8765
poetry run quant-web serve --db-url sqlite+aiosqlite:///./paper_test.db --port 8000
```

- 选项：`--host`（默认 `127.0.0.1`）、`--port`（默认 8765）、`--configs`（默认 `./configs`）、`--db-url`、`--static`（构建好的前端，默认 `web/dist`）、`--init-db`（建表）、`--log-level`。`.env` 会被加载（`quant-web --env-file ... serve`）。
- 数据库：`--db-url` 或 `QUANT_DATABASE_URL`；都没有时用本地的 `./quant_offline.db`（自动建表）。
- 默认只监听 `127.0.0.1`。控制台没有登录，却可以启动向 paper（如果允许，live）账户下单的运行，**不要对外暴露**。

### 功能

| 模块 | 说明 |
| --- | --- |
| 配置编辑 | 读写 `configs/` 下的流水线、agent、提示词模板、账户、风控规则、LLM 供应商、调度。校验使用运行时完全相同的 Pydantic 模型（包括每个阶段的选项、候选来源和舆情来源的选项），并检查引用（账户、agent 角色、LLM 供应商、风控规则、提示词模板是否存在），还会列出某个 agent / 账户 / 风控规则被哪些流水线引用。 |
| 安全写入 | 保存前校验（语法错误永远拒绝，语义错误可强制保存）；用 etag 检测并发修改（409）；覆盖或删除前备份到 `configs/.web_backups/`；保留文件原有的换行符（CRLF / LF）。 |
| 运行 | 在服务进程内启动流水线（dry_run / paper / 按配置；可选离线、阶段子集、as_of）。离线运行写入单独的沙盒数据库 `./quant_offline.db`，假行情永远不会覆盖正式数据。可以取消运行：连接会被关闭，运行记录标记为失败。 |
| 实时进度 | structlog 处理器把带 `run_id` 的日志事件（含 `pipeline.stage_start` / `stage_done`）推送给浏览器（SSE）。CLI 或独立调度器启动的运行只能看到数据库中的结果。 |
| 调度器 | 预览未来 N 天的运行时间（纽约 / 柏林时间）；在服务进程内启动 / 停止调度器（任务保存在内存）；健康检查（数据库、IB Gateway）。不要同时运行独立的 `quant-scheduler run`。 |
| 数据 | 所有表的只读浏览（分页、排序、过滤、整行查看）；每次运行的选股、舆情、决策、风控、订单、agent 实例和完整的 LLM 请求 / 响应；K 线图；每条流水线的虚拟子账本和 IBKR 账户快照；全局熔断开关。 |

### API 概览

```
GET  /api/meta                         表单生成所需的 JSON Schema、注册表、环境变量是否设置（不含值）
GET  /api/configs                      所有配置文件
GET  /api/configs/{kind}/{name}        内容 + etag + 被谁引用
POST /api/configs/{kind}/{name}/validate
PUT  /api/configs/{kind}/{name}        {text, etag, force}
POST /api/configs/{kind}               {name, text}       DELETE /api/configs/{kind}/{name}
POST /api/jobs                         启动运行；GET /api/jobs；GET /api/jobs/{id}；POST /api/jobs/{id}/cancel
GET  /api/runs?db=main|offline         GET /api/runs/{id}；GET /api/runs/{id}/events（SSE）
GET  /api/llm_calls/{id}
GET  /api/db/tables?db=…               GET /api/db/tables/{table}?offset&limit&sort&desc&filters
GET  /api/db/tables/{table}/rows/{pk}  单行完整内容
GET  /api/market/instruments           GET /api/market/bars?symbol&timeframe&limit
GET  /api/portfolio                    GET /api/overview
GET|PUT /api/system/kill-switch
GET  /api/scheduler/plan?days=7        GET /api/scheduler/status；POST /api/scheduler/{start|stop|reload|check}
```

`kind` 取值：`pipelines`、`agents`、`prompts`、`accounts`、`risk`、`llm_providers`、`schedules`
（后两个是单文件，`name` 与 `kind` 相同）。

其他路径返回前端页面（单页应用）。

---

## English

Backend of the web console (FastAPI). The frontend lives in `web/` at the repository root (React + MUI + Vite) and is served by this service once built.
It sits at the top of the dependency graph (`scheduler ← webapi`) and may use every package.

### Start

```bash
python tasks.py web                       # first time: install frontend dependencies and build web/dist
poetry run quant-web serve                # http://127.0.0.1:8765
poetry run quant-web serve --db-url sqlite+aiosqlite:///./paper_test.db --port 8000
```

- Options: `--host` (default `127.0.0.1`), `--port` (default 8765), `--configs` (default `./configs`), `--db-url`, `--static` (the built frontend, default `web/dist`), `--init-db` (create tables), `--log-level`. `.env` is loaded (`quant-web --env-file ... serve`).
- Database: `--db-url` or `QUANT_DATABASE_URL`; without either, the local `./quant_offline.db` (tables created automatically).
- Listens on `127.0.0.1` only by default. The console has no login yet can start runs that place orders on a paper (and, if allowed, live) account — **do not expose it**.

### Features

| Area | Description |
| --- | --- |
| Config editing | Read and write pipelines, agents, prompt templates, accounts, risk rules, LLM providers and schedules under `configs/`. Validation uses exactly the runtime Pydantic models (including every stage's options and the candidate-source and sentiment-source options) and checks references (accounts, agent roles, LLM providers, risk rules, prompt templates exist); it also lists which pipelines reference an agent / account / risk-rule set. |
| Safe writes | Validate before saving (syntax errors are always refused, semantic errors can be forced); etags detect concurrent edits (409); backups go to `configs/.web_backups/` before overwrite or delete; the file's line endings (CRLF / LF) are kept. |
| Runs | Start pipelines inside the server process (dry_run / paper / as configured; optionally offline, a subset of stages, as_of). Offline runs write to a separate sandbox database `./quant_offline.db`, so fake market data never overwrites real data. Runs can be cancelled: connections are closed and the run is marked failed. |
| Live progress | A structlog processor pushes log events carrying a `run_id` (including `pipeline.stage_start` / `stage_done`) to the browser (SSE). Runs started from the CLI or a separate scheduler show only their database results. |
| Scheduler | Preview the next N days of runs (New York / Berlin time); start / stop a scheduler inside the server process (jobs kept in memory); health checks (database, IB Gateway). Do not also run a separate `quant-scheduler run`. |
| Data | Read-only browsing of every table (paging, sorting, filters, full row view); each run's selection, sentiment, decisions, risk, orders, agent instances and full LLM requests / responses; bar charts; each pipeline's virtual sub-ledger and the IBKR account snapshots; the global kill switch. |

### API overview

```
GET  /api/meta                         JSON Schemas for the forms, registries, which env vars are set (no values)
GET  /api/configs                      every config file
GET  /api/configs/{kind}/{name}        content + etag + who references it
POST /api/configs/{kind}/{name}/validate
PUT  /api/configs/{kind}/{name}        {text, etag, force}
POST /api/configs/{kind}               {name, text}       DELETE /api/configs/{kind}/{name}
POST /api/jobs                         start a run; GET /api/jobs; GET /api/jobs/{id}; POST /api/jobs/{id}/cancel
GET  /api/runs?db=main|offline         GET /api/runs/{id}; GET /api/runs/{id}/events (SSE)
GET  /api/llm_calls/{id}
GET  /api/db/tables?db=…               GET /api/db/tables/{table}?offset&limit&sort&desc&filters
GET  /api/db/tables/{table}/rows/{pk}  one full row
GET  /api/market/instruments           GET /api/market/bars?symbol&timeframe&limit
GET  /api/portfolio                    GET /api/overview
GET|PUT /api/system/kill-switch
GET  /api/scheduler/plan?days=7        GET /api/scheduler/status; POST /api/scheduler/{start|stop|reload|check}
```

`kind` is one of `pipelines`, `agents`, `prompts`, `accounts`, `risk`, `llm_providers`, `schedules`
(the last two are single files; `name` equals `kind`).

Any other path returns the frontend (single-page app).

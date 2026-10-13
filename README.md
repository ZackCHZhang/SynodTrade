# quant-system

[中文](#中文) | [English](#english)

---

## 中文

基于 IBKR 的多 Agent 量化交易系统（Python monorepo）。流水线：**（选股 →）数据更新 → 舆情 → 决策 → 风控 → 交易**。
选股阶段可选，用多个 agent 从候选池和 IBKR 扫描器里挑出本次交易的股票（见 `packages/selection/README.md`）。

默认只以 paper / dry-run 运行；实盘需同时满足 `mode: live` 与环境变量 `QUANT_ALLOW_LIVE=1`。

### 结构

```
configs/      运行时 YAML 配置（不打包）
packages/     每个子目录是一个独立 Poetry 包（quant-<name>，源码在 src/quant_<name>/）
web/          Web 控制台前端（React + MUI + Vite），后端是 packages/webapi
scripts/      手动运行的 IBKR 检查脚本（ibkr_check.py 只读；paper_order_smoke.py 向 paper 账户下一笔测试单）
tests/        跨包集成测试（默认不运行）
tasks.py      跨平台任务入口（Makefile 只是它的封装）
```

包依赖（由 import-linter 在 `lint` 中强制检查）：

```
core ← database ← {market_data, selection, sentiment, decision, risk, trading} ← account_sync ← pipeline ← scheduler ← webapi
```

中间层的业务包之间禁止互相 import；需要跨包协作时，在 `quant_core.interfaces` 里定义协议（例如 `BarsRefresher`、`CandidateSource`），由 pipeline 注入实现。

### 仓库自带的配置

| 目录 | 内容 |
|---|---|
| `configs/pipelines/` | `long_term_stocks`（AAPL/MSFT/GOOGL/NVDA，每日）、`etf_allocation`（6 只 ETF，每周一）、`demo_all_modules`（包含选股在内的全部模块） |
| `configs/agents/` | 66 个 agent 配置：选股 22、舆情 2、决策 21、风控 21。同一角色的 agent 共用一个实现和一个提示词模板（`configs/agents/prompts/*_v1.j2`），区别只在 `persona` 和 `params.instructions` |
| `configs/risk/` | `default`、`etf` 两套硬规则 |
| `configs/accounts/` | `ibkr_main`、`ibkr_etf`（不同的 client id，两条流水线可以同时运行） |
| `configs/llm_providers.yaml` | `anthropic`、`deepseek` |
| `configs/schedules.yaml` | 调度：`long_term_stocks` 每个交易日开盘后 30 分钟；`etf_allocation` 每周一 11:00（纽约） |
| `configs/account_sync.yaml` | 账户同步：每次 paper/live 运行前先从 IBKR 同步订单成交与持仓，Web 控制台每 20 分钟自动同步（见 `packages/account_sync/README.md`） |

### 快速开始

```bash
python tasks.py install
poetry run quant validate                                  # 校验 configs/
poetry run quant run -p long_term_stocks --offline         # 无需网关、API key，完整跑一遍（dry-run）
```

真正运行时：
1. 在 `.env` 中填写 IBKR 账户、LLM 的 API key 和数据库地址（模板见 `.env.example`）。命令行默认读取当前目录的 `.env`（`--env-file` 可改，`QUANT_NO_DOTENV=1` 可关闭）。
2. 启动 Postgres 和 IB Gateway，执行 `poetry run quant-db upgrade` 建表。
3. 先用 `quant run -p long_term_stocks --dry-run` 检查结果，确认无误后按配置中的 `mode` 运行（自带的三条流水线都是 `mode: paper`）。
4. 订单是否成交由账户同步负责：流水线第 1 步自动同步；Web 控制台运行时每 20 分钟同步一次（"账户同步"页面可改）；也可以手动 `quant-sync once`。
5. 定时运行：用 `quant-scheduler plan` 查看排程，再用 `quant-scheduler run` 启动；也可以用 `docker compose up -d` 一次性启动 postgres、ib-gateway 和 scheduler（见 `packages/scheduler/README.md`）。

各包的详细说明见 `packages/*/README.md`。

### Web 控制台

```bash
python tasks.py web                 # 安装前端依赖并构建 web/dist（需要 Node.js）
poetry run quant-web serve          # http://127.0.0.1:8765
```

可视化编辑 `configs/` 下的所有 YAML（流水线与各阶段、agent、提示词模板、风控规则、账户、LLM 供应商、调度），
启动流水线并实时查看进度和日志，启停调度器，浏览数据库中的所有数据（运行、LLM 调用、订单、持仓、K 线）。
控制台没有登录且能下单，默认只监听本机，不要对外暴露。界面目前只有中文。详见 `packages/webapi/README.md` 和 `web/README.md`。

### 开发环境

需要 Python 3.12 与 Poetry 2.x。根目录一个共享 venv（`.venv/`），所有包以 editable 方式安装。

```bash
poetry env use <python3.12 路径>
python tasks.py install     # 或 make install
python tasks.py check       # lint + mypy --strict + 单元测试
python tasks.py test-core   # 单个包的测试 + 覆盖率（test-<包名>）
python tasks.py cov         # 全部测试 + 覆盖率
python tasks.py integration # 需要真实外部服务的测试
```

单元测试禁止访问外网（pytest-socket，只允许 loopback）；需要真实 IBKR/Reddit/LLM/Postgres 的测试标记为
`@pytest.mark.integration`，或放在 `tests/integration/`。

### 本地基础设施

```bash
cp .env.example .env   # 填写密钥
docker compose up -d postgres   # 或 make up
```

注意：`ib_async` 连接的是 **TWS / IB Gateway 的 socket API**（paper 端口 4002/7497），
不是 Client Portal Web API（端口 5000）。

### 当前限制（与代码实际行为一致）

- **没有回测 / 历史回放模式。** 所有读取都支持 `as_of`，`quant run --as-of` 可以指定时间点，但没有逐日回放和绩效统计。
- **Agent 只能看到代码提供的数据。** 决策 agent 看到的是 `quant_core.indicators` 的价格类指标、最近 K 线、舆情摘要和历史决策；风控 agent 只看到其中 6 个指标；选股 agent 只看到价格 / 成交量类指标。系统里**没有基本面、财报日历、ATR、跳空统计、相关性**等数据，部分 agent 的 `instructions`（例如 `piotroski_screen`、`volatility_position_sizer`、`earnings_event_risk`、`gap_risk_monitor`）提到了这些数据，模型只能根据已有信息推断。
- **订单只有一种定价方式**：立即成交型限价单（买一 / 卖一价加减 `limit_offset_bps`）。

---

## English

A multi-agent quantitative trading system on IBKR (Python monorepo). Pipeline: **(selection →) data update → sentiment → decision → risk → trading**.
The selection stage is optional: several agents pick this run's stocks from a candidate pool and IBKR market scanners (see `packages/selection/README.md`).

By default everything runs in paper / dry-run. Live trading requires both `mode: live` and the environment variable `QUANT_ALLOW_LIVE=1`.

### Layout

```
configs/      runtime YAML configuration (not packaged)
packages/     each subfolder is a separate Poetry package (quant-<name>, sources in src/quant_<name>/)
web/          web console frontend (React + MUI + Vite); its backend is packages/webapi
scripts/      manual IBKR scripts (ibkr_check.py is read-only; paper_order_smoke.py places one test order on a paper account)
tests/        cross-package integration tests (not run by default)
tasks.py      cross-platform task runner (the Makefile only wraps it)
```

Package dependencies (enforced by import-linter during `lint`):

```
core ← database ← {market_data, selection, sentiment, decision, risk, trading} ← account_sync ← pipeline ← scheduler ← webapi
```

Business packages in the middle layer must not import each other. When they need to cooperate, a protocol is defined in `quant_core.interfaces` (e.g. `BarsRefresher`, `CandidateSource`) and the pipeline injects the implementation.

### Bundled configuration

| Folder | Contents |
|---|---|
| `configs/pipelines/` | `long_term_stocks` (AAPL/MSFT/GOOGL/NVDA, daily), `etf_allocation` (6 ETFs, Mondays), `demo_all_modules` (every module, including selection) |
| `configs/agents/` | 66 agent configs: 22 selection, 2 sentiment, 21 decision, 21 risk. Agents of one role share one implementation and one prompt template (`configs/agents/prompts/*_v1.j2`); they differ only in `persona` and `params.instructions` |
| `configs/risk/` | two hard-rule sets: `default`, `etf` |
| `configs/accounts/` | `ibkr_main`, `ibkr_etf` (different client ids, so both pipelines can run at the same time) |
| `configs/llm_providers.yaml` | `anthropic`, `deepseek` |
| `configs/schedules.yaml` | `long_term_stocks` 30 minutes after every open; `etf_allocation` Mondays 11:00 New York |

### Quick start

```bash
python tasks.py install
poetry run quant validate                                  # validate configs/
poetry run quant run -p long_term_stocks --offline         # full run without gateway or API keys (dry-run)
```

For real runs:
1. Fill in the IBKR account, LLM API keys and the database URL in `.env` (template: `.env.example`). The CLIs read `./.env` by default (`--env-file` to change it, `QUANT_NO_DOTENV=1` to disable it).
2. Start Postgres and IB Gateway, then create the tables with `poetry run quant-db upgrade`.
3. Check the result with `quant run -p long_term_stocks --dry-run` first, then run with the config's `mode` (all three bundled pipelines use `mode: paper`).
4. Scheduled runs: preview with `quant-scheduler plan`, start with `quant-scheduler run`; or start postgres, ib-gateway and the scheduler together with `docker compose up -d` (see `packages/scheduler/README.md`).

Each package is described in detail in `packages/*/README.md`.

### Web console

```bash
python tasks.py web                 # install frontend dependencies and build web/dist (needs Node.js)
poetry run quant-web serve          # http://127.0.0.1:8765
```

Edit every YAML under `configs/` visually (pipelines and stages, agents, prompt templates, risk rules, accounts, LLM providers, schedules),
start pipelines and follow progress and logs live, start / stop the scheduler, and browse everything in the database (runs, LLM calls, orders, positions, bars).
The console has no login and can place orders; it listens on localhost only by default — do not expose it. The UI is Chinese only for now. See `packages/webapi/README.md` and `web/README.md`.

### Development environment

Requires Python 3.12 and Poetry 2.x. One shared venv at the root (`.venv/`), with every package installed in editable mode.

```bash
poetry env use <path to python3.12>
python tasks.py install     # or: make install
python tasks.py check       # lint + mypy --strict + unit tests
python tasks.py test-core   # one package's tests + coverage (test-<package>)
python tasks.py cov         # all tests + coverage
python tasks.py integration # tests that need real external services
```

Unit tests may not reach the network (pytest-socket, loopback only). Tests that need real IBKR / Reddit / LLM / Postgres are marked
`@pytest.mark.integration` or live in `tests/integration/`.

### Local infrastructure

```bash
cp .env.example .env   # fill in secrets
docker compose up -d postgres   # or: make up
```

Note: `ib_async` talks to the **TWS / IB Gateway socket API** (paper ports 4002/7497),
not to the Client Portal Web API (port 5000).

### Current limitations (as implemented)

- **No backtest / historical replay mode.** Every read supports `as_of` and `quant run --as-of` sets the point in time, but there is no day-by-day replay or performance report.
- **Agents only see data the code provides.** Decision agents get the price-based indicators from `quant_core.indicators`, recent bars, sentiment summaries and past decisions; risk agents get only 6 of those indicators; selection agents get only price / volume metrics. The system has **no fundamentals, earnings calendar, ATR, gap statistics or correlations**. Some agents' `instructions` (e.g. `piotroski_screen`, `volatility_position_sizer`, `earnings_event_risk`, `gap_risk_monitor`) mention such data; the model can only infer it from what it is shown.
- **One order pricing style only**: a marketable limit order (ask / bid plus or minus `limit_offset_bps`).

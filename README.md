# quant-system

基于 IBKR 的多 Agent 量化交易系统（Python monorepo）。流水线：**（选股 →）数据更新 → 舆情 → 决策 → 风控 → 交易**。选股阶段可选，用多个 agent 从候选池和 IBKR 扫描器里挑出本次交易的股票（见 `packages/selection/README.md`）。

默认只以 paper / dry-run 运行；实盘需同时满足 `mode: live` 与环境变量 `QUANT_ALLOW_LIVE=1`。

## 结构

```
configs/      运行时 YAML 配置（不打包）
packages/     每个子目录是一个独立 Poetry 包（quant-<name>，源码在 src/quant_<name>/）
tests/        跨包集成测试（默认不运行）
tasks.py      跨平台任务入口（Makefile 只是它的封装）
```

包依赖（由 import-linter 在 `lint` 中强制检查）：

```
core ← database ← {market_data, selection, sentiment, decision, risk, trading} ← pipeline ← scheduler
```

中间层的业务包之间禁止互相 import。

## 快速开始

```bash
python tasks.py install
poetry run quant validate                                  # 校验 configs/
poetry run quant run -p long_term_stocks --offline         # 无需网关、API key，完整跑一遍（dry-run）
```

真正运行时：
1. 在 `.env` 中填写 IBKR 账户、LLM 的 API key 和数据库地址。
2. 启动 Postgres 和 IB Gateway，执行 `poetry run quant-db upgrade` 建表。
3. 先用 `quant run -p long_term_stocks --dry-run` 检查结果，确认无误后按配置中的 `mode`（默认 paper）运行。
4. 定时运行：用 `quant-scheduler plan` 查看排程，再用 `quant-scheduler run` 启动；也可以用 `docker compose up -d` 一次性启动 postgres、ib-gateway 和 scheduler（见 `packages/scheduler/README.md`）。

各包的详细说明见 `packages/*/README.md`。

## 开发环境

需要 Python 3.12 与 Poetry 2.x。根目录一个共享 venv（`.venv/`），所有包以 editable 方式安装。

```bash
poetry env use <python3.12 路径>
python tasks.py install     # 或 make install
python tasks.py check       # lint + mypy --strict + 单元测试
python tasks.py test-core   # 单个包的测试 + 覆盖率
python tasks.py cov         # 全部测试 + 覆盖率
python tasks.py integration # 需要真实外部服务的测试
```

单元测试禁止访问外网（pytest-socket，只允许 loopback）；需要真实 IBKR/Reddit/LLM/Postgres 的测试标记为
`@pytest.mark.integration`，或放在 `tests/integration/`。

## 本地基础设施

```bash
cp .env.example .env   # 填写密钥
docker compose up -d postgres
```

注意：`ib_async` 连接的是 **TWS / IB Gateway 的 socket API**（paper 端口 4002/7497），
不是 Client Portal Web API（端口 5000）。

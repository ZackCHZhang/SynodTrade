# quant-system

基于 IBKR 的多 Agent 量化交易系统（Python monorepo）。流水线：**数据更新 → 舆情 → 决策 → 风控 → 交易**。

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
core ← database ← {market_data, sentiment, decision, risk, trading} ← pipeline ← scheduler
```

中间层的业务包之间禁止互相 import。

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

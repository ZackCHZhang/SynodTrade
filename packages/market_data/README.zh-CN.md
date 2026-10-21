# synodtrade-market-data

[English](README.md) | **简体中文**

行情和账户数据更新：从 IBKR 拉取历史 K 线、实时报价、账户资金和持仓，写入数据库。依赖 `synodtrade-core`、`synodtrade-database`。

## 公开接口

- `MarketDataProvider`（协议）：`connect` / `disconnect` / `is_healthy` / `resolve_instrument` / `fetch_bars` / `fetch_quotes` / `fetch_account`
  - `IBKRMarketDataProvider`：基于 `ib_async`，连接 **TWS 或 IB Gateway 的 socket API**（paper 端口 4002/7497），**只读连接**（`readonly=True`），永远不会下单。
  - `FakeMarketDataProvider`：数据全部在内存中，可以用 `from_fixture_dir()` 从 fixture 目录加载；`generate_daily_bars()` 按固定种子生成可复现的日线。用于测试和离线运行。
- `DataUpdater`：
  - `update(...)`：增量更新 K 线、报价和账户，返回 `UpdateReport`（写入数量和各标的的错误）。
  - `update_bars(...)`：只更新任意标的的 K 线；它实现了 core 的 `BarsRefresher` 协议，选股阶段用它拉取候选股的日线。
- `DataUpdateStage`：流水线阶段 `data_update`。通过 entry point `synodtrade.stages` 注册，工厂函数是 `build_data_update_stage(config, services)`，需要的服务有：
  - `repos`：`Repositories`
  - `market_data`：`MarketDataProvider`
  - `account`：`AccountConfig`（可选，用于记录账户快照）

## 行为

- **增量更新**：只拉数据库里缺少的部分。
  - 数据库里没有数据：拉取整个回看窗口。
  - 最新的一根 K 线总是重新拉取，因为上次写入时它可能还没收盘。
  - 只有当数据库里最早的数据明显晚于窗口起点时，才补拉前面的部分。这里留了余量（至少 4 天，或 2 个周期），窗口起点落在周末时就不会天天重复请求。
  - 中间的缺口不检测，因为判断是否缺数据需要交易所日历。
  - 如果某只股票上市时间晚于窗口起点，每次运行都会多发一个请求去补前面的数据，但这个请求拿不到数据。
- **请求频率**：`PacingLimiter` 控制在 10 分钟内最多 50 个历史数据请求、同一合约 2 秒内最多 5 个，都低于 IBKR 的上限（60 个 / 6 个），目的是根本不触发 pacing violation。一次请求的最大跨度按 K 线周期划分：1 分钟线 1 天、5 分钟线 7 天、15 分钟线 14 天、1 小时线 30 天、日线和周线 365 天。连接错误和超时最多重试 3 次，指数退避。
- **K 线时间**：日线和周线的 `ts` 是交易所时区（纽约）当天 00:00，换算成 UTC 存储。根据数据库层的规则，**当天的日线要到当天结束后才能读到**，所以盘中运行的决策只会用到已收盘的 K 线。
- **报价**：IBKR 用 NaN、-1 或 0 表示"没有价格"，一律转成 `None`；买价高于卖价（倒挂）的报价只保留 `last`。paper 账户通常没有实时行情订阅，所以默认 `market_data_type=3`（延迟行情）。
  - 如果连延迟行情也拿不到（例如 paper 账户没开"行情共享"，TWS 不报错，只返回 NaN），就退回到最近一根 1 分钟 TRADES K 线：`last` 取收盘价，`ts` 取该 K 线的结束时间，买卖价留空。这个价格大约延迟 15 分钟，所以 `demo_all_modules` 流水线把 `limit_offset_bps` 放宽到 25。
- **账户币种**：账户快照统一换算成美元。账户基础货币由 `NetLiquidation` 那一行的币种决定（例如欧元账户），只保留这个币种的数值，再乘以 IDEALPRO 汇率（`EURUSD` 这类货币对最近一根日线的 MIDPOINT 收盘价；没有这个货币对就用反向货币对取倒数），结果保留两位小数。换算用的汇率写在日志 `ibkr.account_fx` 里。
- **标的**：`con_id` 第一次通过 IBKR 查询，之后缓存在 `instruments` 表中。
- **失败处理**：一个标的失败不影响其他标的；报价和账户失败也分别记录。只要有任何错误，阶段默认就失败（`fail_on_error: true`），整次运行随之终止，不会进入交易：宁可不交易，也不用过期数据做决策。

## 配置项（`configs/pipelines/*.yaml` 的 `data_update` 阶段）

```yaml
- type: data_update
  timeframes: [1d]        # 1m 5m 15m 1h 1d 1w；默认 [1d]
  lookback_days: 365      # 1–3650，默认 365
  quotes: true            # 记录报价快照
  account: true           # 记录账户和持仓快照（需要 account 服务）
  fail_on_error: true
```

连接参数来自 `configs/accounts/*.yaml`（`host` / `port` / `client_id`）。IBKR 的 client id 分配：行情用账户配置里的 `client_id`，交易用 +1，新闻（舆情数据源）用 +2，选股扫描器用 +3。

## 运行测试

```bash
python tasks.py test-market_data
```

连接真实 paper 网关的测试需要手动开启：

```bash
set SYNODTRADE_TEST_IBKR=1        # Linux/macOS: export
set IBKR_PORT=4002
python tasks.py integration
```

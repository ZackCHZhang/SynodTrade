# quant-market-data

行情和账户数据更新：从 IBKR 拉取历史 K 线、实时报价、账户资金和持仓，写入数据库。依赖 `quant-core`、`quant-database`。

## 公开接口

- `MarketDataProvider`（协议）：`connect` / `disconnect` / `is_healthy` / `resolve_instrument` / `fetch_bars` / `fetch_quotes` / `fetch_account`
  - `IBKRMarketDataProvider`：基于 `ib_async`，连接 **TWS 或 IB Gateway 的 socket API**（paper 端口 4002/7497），**只读连接**，永远不会下单。
  - `FakeMarketDataProvider`：数据全部在内存中，可以从 fixture 目录加载；`generate_daily_bars()` 按固定种子生成可复现的日线。用于测试和 dry-run。
- `DataUpdater.update(...)`：增量更新，返回 `UpdateReport`（写入数量和各标的的错误）。
- `DataUpdateStage`：流水线阶段 `data_update`。通过 entry point `quant.stages` 注册，工厂函数是 `build_data_update_stage(config, services)`，需要的服务有：
  - `repos`：`Repositories`
  - `market_data`：`MarketDataProvider`
  - `account`：`AccountConfig`（可选，用于记录账户快照）

## 行为

- **增量更新**：只拉数据库里缺少的部分。
  - 数据库里没有数据：拉取整个回看窗口。
  - 最新的一根 K 线总是重新拉取，因为上次写入时它可能还没收盘。
  - 只有当数据库里最早的数据明显晚于窗口起点时，才补拉前面的部分。这里留了几天余量，窗口起点落在周末时就不会天天重复请求。
  - 中间的缺口不检测，因为判断是否缺数据需要交易所日历。
  - 如果某只股票上市时间晚于窗口起点，每次运行都会多发一个请求去补前面的数据，但这个请求拿不到数据。
- **请求频率**：`PacingLimiter` 控制在 10 分钟内最多 50 个历史数据请求、同一合约 2 秒内最多 5 个，都低于 IBKR 的上限（60 个 / 6 个），目的是根本不触发 pacing violation。一次请求的最大跨度按 K 线周期划分，例如日线每次最多 365 天。超时和断线最多重试 3 次，指数退避。
- **K 线时间**：日线和周线的 `ts` 是交易所时区（纽约）当天 00:00，换算成 UTC 存储。根据数据库层的规则，**当天的日线要到当天结束后才能读到**，所以盘中运行的决策只会用到已收盘的 K 线。
- **报价**：IBKR 用 NaN、-1 或 0 表示"没有价格"，一律转成 `None`；买价高于卖价（倒挂）的报价只保留 `last`。paper 账户通常没有实时行情订阅，所以默认 `market_data_type=3`（延迟行情）。
- **标的**：`con_id` 第一次通过 IBKR 查询，之后缓存在 `instruments` 表中。
- **失败处理**：一个标的失败不影响其他标的；报价和账户失败也分别记录。只要有任何错误，阶段默认就失败（`fail_on_error: true`），整次运行随之终止，不会进入交易：宁可不交易，也不用过期数据做决策。

## 配置项（`configs/pipelines/*.yaml` 的 `data_update` 阶段）

```yaml
- type: data_update
  timeframes: [1d]        # 1m 5m 15m 1h 1d 1w
  lookback_days: 365
  quotes: true            # 记录报价快照
  account: true           # 记录账户和持仓快照（需要 account 服务）
  fail_on_error: true
```

连接参数来自 `configs/accounts/*.yaml`（`host` / `port` / `client_id`）。行情连接使用账户配置里的 `client_id`；交易连接（第 8 阶段）会使用另一个 client id。

## 运行测试

```bash
python tasks.py test-market_data
```

连接真实 paper 网关的测试需要手动开启：

```bash
set QUANT_TEST_IBKR=1
set IBKR_PORT=4002
python tasks.py integration
```

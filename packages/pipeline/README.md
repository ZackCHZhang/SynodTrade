# quant-pipeline

主流程编排：从 `configs/pipelines/<name>.yaml` 组装流水线，每次运行生成 `run_id` 并贯穿全程，执行失败策略，提供命令行 `quant`。依赖所有业务包。

## 命令行

```bash
quant run -p long_term_stocks                  # 按配置里的 mode 运行（paper / live / dry_run）
quant run -p long_term_stocks --dry-run        # 强制 dry-run：记录订单，但绝不发送
quant run -p long_term_stocks --stages data,sentiment   # 只跑部分阶段（data = data_update）
quant run -p long_term_stocks --offline        # 无网关、无 API key、不联网：假数据 + 中性假 LLM，强制 dry-run
quant run -p long_term_stocks --as-of 2026-10-01T10:00:00-04:00
quant validate [-p NAME]                       # 校验流水线及其引用的全部配置
quant kill-switch on --reason "..." | off | status
```

- 数据库：`--db-url` 或 `QUANT_DATABASE_URL`。`--offline` 未指定数据库时使用本地 `./quant_offline.db`，并自动建表；`--init-db` 可为其他数据库建表（开发用，生产环境请用 `quant-db upgrade`）。
- 配置目录：`--configs`，默认是 `./configs`。
- 输出：运行摘要（JSON）打印到 stdout，日志（JSON）写到 stderr。运行失败时退出码为 1，方便调度器判断。

## 一次运行（`PipelineRunner.run`）

1. 校验流水线配置及其引用的一切（账户、agent、prompt 模板、LLM 厂商）。
2. 确定运行模式：`--dry-run` 或 `--offline` 时为 dry_run，否则取配置中的值。live 模式必须设置 `QUANT_ALLOW_LIVE=1`，否则直接拒绝，数据库中也不会留下任何运行记录。
3. **防重入**：同一条流水线已有未结束、且开始于 `max_run_minutes`（默认 180 分钟）以内的运行时，抛出 `PipelineBusyError`；更早的未结束运行视为进程已崩溃，标记为 FAILED 后继续。
4. 写入 `pipeline_runs` 记录，包括 `run_id`、运行模式、`as_of`、`config_hash`，以及配置快照（流水线和全部 agent 配置）。
5. **只装配所选阶段需要的服务**：
   - 数据库仓库、ConfigStore、LLM 厂商池、流水线配置、账户配置；
   - 包含 `data_update` 阶段时，才创建行情源（IBKR）；
   - 包含 `trading` 阶段时，才用 `create_broker(mode)` 创建券商，所以只跑 `data,sentiment` 时不会连接券商；
   - 用到的 LLM 厂商会先检查 API key，缺失时立即失败。
6. 通过注册表（entry point `quant.stages`）按顺序创建并运行各阶段。**每条日志都自动带上 `run_id` 和 `pipeline`。**
7. **失败策略**：
   - 某阶段抛出异常：`on_error: skip` 的阶段（例如舆情）记录错误后继续；
   - 默认是 `abort`：立即终止，**后续阶段（包括交易）都不再执行**，运行记为 FAILED；
   - 装配阶段（配置、凭据）出错也记为失败。
8. 关闭连接（各阶段的 `aclose`、行情源、券商、LLM 客户端），写入最终状态和摘要（每个阶段的状态和耗时、各类记录数量、最终动作、订单状态、错误列表）。

**覆盖服务**：`PipelineRunner(store, db, overrides={...})` 可以替换任意服务，例如 `broker`、`market_data`、`llm`、`sentiment_sources`、`market_clock`。测试就是这样注入假对象的。

## 离线模式（`--offline`）

各模块用下面的假实现替换，除此之外整条链路与正常运行完全相同（prompt 渲染、结构化输出校验、风控规则、下单、写库），适合检查配置和部署是否正常：

| 模块 | 离线时使用 |
|---|---|
| 行情 | 截至 `as_of` 的生成日线，每只股票约 300 根 |
| 舆情数据源 | 存在，但没有数据 |
| LLM | `schema_reply` 根据要求的输出格式返回中性结果：舆情 0、决策 HOLD、风控维持原提案。**无论它返回什么都不会促成交易** |
| 券商 | DryRunBroker |

## 运行测试

```bash
python tasks.py test-pipeline
```

端到端测试（`test_full_dry_run_end_to_end`）使用仓库里的真实配置，以及假行情、假舆情、假 LLM（全部给出买入）和模拟券商，完整跑一次 dry-run。然后逐项核对数据库：运行记录、agent 实例（2 + 3 + 1 个）、舆情结果、12 条决策、4 条聚合决策、12 条风控记录、4 笔订单和成交、18 次 LLM 调用。所有记录都属于同一个 `run_id`，子账本也相应更新。

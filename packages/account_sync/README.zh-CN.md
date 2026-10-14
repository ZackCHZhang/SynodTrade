# quant-account-sync

[English](README.md) | **简体中文**

账户同步：把 IBKR 账户的真实状态同步进数据库。解决的问题是：下单后数据库里只有"已提交"，并不知道到底成交没有。

每次同步（一个 IBKR 账户一次连接，client id = 账户 client_id + 4，不和流水线的连接冲突）：

1. **未完成的订单**（pending_submit / submitted / partially_filled）：从 IBKR 读取状态、成交数量和每笔成交（含佣金），写回 `orders` / `fills`。IBKR 查不到的订单（不在挂单里、不在已完成订单里、也没有成交记录），在 `gone_after_minutes` 内没有变化就按"已取消"关闭；有部分成交但已不再挂单的，按已成交数量关闭。
2. **迟到的成交**：最近 `recheck_days` 天内已关闭的订单再查一次成交记录。比如之前因为查不到被标成"已取消"、实际上成交了的订单，会补上成交并改成 filled（同步报告里会有警告）。
3. **账户与持仓快照**：净值、现金、购买力、持仓，写入 `account_snapshots` / `position_snapshots`。
4. **核对**：IBKR 持仓 vs 各流水线虚拟账本之和；IBKR 上有、数据库里没有的挂单（手工下的单，或者另一个数据库下的单）。

正在运行的流水线的订单不动（它自己的 trading 阶段在跟踪）。每次同步的结果存进 `account_syncs` 表。

## 什么时候同步

- **流水线第一步**：paper / live 模式的实时运行（没有 `--as-of`），在任何阶段之前先同步这条流水线的账户（同账户的其他流水线一起同步），运行详情里显示为第 1 步"账户同步"。`--offline`、`--dry-run` 和指定 `--as-of` 的回放不同步。
- **定时**：Web 控制台进程里每 `interval_minutes`（默认 20 分钟）同步一次所有账户；在"账户同步"页面可以修改、关闭、手动立即同步。没有 Web 控制台时可以用 `quant-sync loop`。
- **手动**：`quant-sync once`，或 Web 页面上的"立即同步"。

## 配置 `configs/account_sync.yaml`

```yaml
enabled: true                  # 定时同步（Web 控制台 / quant-sync loop）
interval_minutes: 20
before_pipeline: true          # 每次 paper/live 运行前先同步
required_before_pipeline: false  # true：同步失败时整个运行失败（默认只记录，继续运行）
gone_after_minutes: 30         # IBKR 查不到的挂单，多久没变化就按已取消关闭
recheck_days: 3                # 最近几天内关闭的订单再检查迟到的成交
snapshot: true                 # 保存账户与持仓快照
accounts: []                   # 只同步这些账户配置；空 = 所有流水线用到的账户
```

文件不存在时使用上面的默认值。

## 命令行

```bash
quant-sync once  --db-url sqlite+aiosqlite:///./paper_test.db   # 同步一次，打印变化
quant-sync loop  --db-url ...                                    # 按 interval_minutes 持续同步
```

注意：IBKR 默认只保留当天的成交记录（TWS 可以在 Global Configuration > API > Settings 里改成最多 7 天）。同步间隔越短，越不会漏掉成交明细。

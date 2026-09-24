# quant-trading

交易执行：仓位→订单、幂等、Broker（IBKR / DryRun）、订单跟踪

## 职责

> 第 1 阶段仅为骨架，具体内容随后续阶段补全。

## 依赖

`quant-core`, `quant-database`

## 公开接口

（待实现）

## 配置项

（待实现）

## 运行测试

在仓库根目录：

```bash
python tasks.py test-trading        # 或 make test-trading
poetry run pytest packages/trading  # 等价
```

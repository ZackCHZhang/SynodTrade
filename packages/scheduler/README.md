# quant-scheduler

调度器：交易日历、定时唤醒流水线、防重入、健康检查

## 职责

> 第 1 阶段仅为骨架，具体内容随后续阶段补全。

## 依赖

`quant-core`, `quant-database`, `quant-pipeline`

## 公开接口

（待实现）

## 配置项

（待实现）

## 运行测试

在仓库根目录：

```bash
python tasks.py test-scheduler        # 或 make test-scheduler
poetry run pytest packages/scheduler  # 等价
```

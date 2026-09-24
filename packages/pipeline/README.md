# quant-pipeline

主流程编排：从 YAML 构建流水线、多实例化、失败策略、CLI

## 职责

> 第 1 阶段仅为骨架，具体内容随后续阶段补全。

## 依赖

`quant-core`, `quant-database`, `quant-market-data`, `quant-sentiment`, `quant-decision`, `quant-risk`, `quant-trading`

## 公开接口

（待实现）

## 配置项

（待实现）

## 运行测试

在仓库根目录：

```bash
python tasks.py test-pipeline        # 或 make test-pipeline
poetry run pytest packages/pipeline  # 等价
```

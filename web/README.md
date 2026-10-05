# web — Quant 控制台前端

React 19 + TypeScript + MUI 9 + Vite。后端是 `packages/webapi`（`quant-web`）。

## 使用

```bash
# 仓库根目录
python tasks.py web            # npm install + 构建到 web/dist
poetry run quant-web serve     # 打开 http://127.0.0.1:8765
```

## 开发

```bash
poetry run quant-web serve     # API，端口 8765
cd web
npm install
npm run dev                    # http://localhost:5173，/api 代理到 8765（QUANT_WEB_API 可改）
npm run typecheck
```

## 页面

- **总览**：熔断开关、调度器状态、正在运行的任务、最近运行、每条流水线的净值。
- **运行记录 / 运行详情**：阶段进度条、实时日志（SSE）、选股 / 舆情 / 决策 / 风控 / 订单 / agent 实例 / LLM 调用 / 配置快照。
- **调度器**：启动 / 停止内置调度器、下次运行时间、未来 N 天的计划、健康检查、立即运行。
- **配置**：流水线（可视化流程 + 每个阶段的 agent 实例、模型、选项）、Agent、提示词模板、风控规则、账户、LLM 供应商、调度。
  每个编辑器都有「可视化编辑」和「YAML」两个标签页，内容实时同步，服务端实时校验。
- **数据**：持仓与账户、行情（K 线 + 均线）、数据库（所有表）。

## 表单如何写回 YAML

表单修改的是解析后的数据；`src/lib/yamlPatch.ts` 把数据变化转换成对原文件文本的最小修改，
未改动的行保持字节不变（对齐的注释、`[a, b]` 写法、多行 flow map、CRLF 换行都保留）。
结果会重新解析并与目标数据比对，不一致或遇到不支持的改动时，退回 `yaml` 库的整体序列化
（`src/lib/yamlDoc.ts`，仍保留注释，但会规范化空白）。

表单字段由服务端提供的 Pydantic JSON Schema 生成（`src/components/SchemaForm.tsx`），
所以新增的配置项会自动出现在表单里；中文标签和说明在 `src/lib/labels.ts`。

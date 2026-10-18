## AI Test Lab 做什么

AI Test Lab 接收 OpenAPI 规格，执行以下步骤：

1. 解析规格。
2. 分析接口、参数、认证声明和依赖关系。
3. 生成候选测试计划（Scenario / Step / Assertion）。
4. 让计划通过校验，进入可审核状态。

模型负责提出计划；后端校验和执行由确定性逻辑负责。

## 使用流程

1. 打开项目的 AI Test Lab。
2. 粘贴/导入 OpenAPI 文档。
3. 触发分析。
4. 等待任务完成，查看理解结果和分析摘要。
5. 生成测试计划。
6. 检查计划，再前往审批。

界面会显示任务状态、错误和可重试状态。任务失败时不要重复提交同一请求来“碰运气”，先查看错误信息。

## 模型与确定性模式

默认可以通过 DeepSeek 配置运行分析/规划。没有 API Key 或希望离线演示时，可在启动后端前设置：

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

确定性路径不需要外部模型，但它的计划覆盖范围由本地规则决定，不等同于任意模型输出。

## security 语义

OpenAPI 的 `security` 会被区分为：

- 未声明 security
- 显式 public
- 需要认证
- 允许匿名（可选 requirement）

这些 facts 会影响确定性 Planner 是否生成认证场景。它们不替代真实授权测试，也不意味着执行器能自动猜测所有认证方式。

## 下一步

计划生成后，阅读 [计划与审批](/learn/plans-and-approval)。
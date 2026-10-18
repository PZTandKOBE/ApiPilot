## Run 列表

项目 Runs 页面列出历史 Run。进入详情可以查看：

- Run 状态和实际使用的 `planId`
- 创建、开始、结束时间和耗时
- Scenario / Step / Assertion 状态
- 失败信息和已保存证据
- 变量数量和 Initial/Runtime variables 区分
- 报告入口

## 排查失败

建议顺序：

1. 先看 Run 总体状态和失败信息。
2. 定位第一个失败 Step，而不是只看最后一个断言。
3. 检查 HTTP 方法/路径、状态码和断言期望。
4. 检查该步骤依赖的运行时变量是否已成功 Extract。
5. 查看已保存证据；请求/响应正文和 headers 默认不在历史中。

不要把 Run 历史当成完整的网络抓包记录。ApiPilot 只展示实际持久化的数据。

## 报告

`passed`、`failed`、`cancelled` 的 Run 可以生成 PDF。生成操作不会重新执行 Run；报告只读取已保存的 Run detail。

详见 [PDF 测试报告](/learn/pdf-reports)。
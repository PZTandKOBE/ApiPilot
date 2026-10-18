## 启动 Run

已批准计划可以被创建为 Run。Run 由后端执行器执行，不在浏览器里发送目标请求。

创建后可以观察：

- Run 总体状态：`queued`、`running`、`passed`、`failed`、`cancelled`
- 每个 Scenario / Step 的状态
- 断言结果
- 已保存的证据字段
- 运行事件流

## 多请求与运行时变量

一个 Run 可以包含多个请求步骤。执行器支持：

- 从响应中 Extract 变量（例如 token 或资源 id）。
- 后续步骤使用运行时变量。
- 同一 Run 内运行时值优先于初始环境变量。
- 缺失变量会在发 HTTP 前失败，不会静默发送空值。

Run 详情区分 **Initial variables** 与 **Runtime variables**。运行时变量只显示名称和作用域，值不写入 Run 历史。

## 断言

当前支持 `status`、`header`、`field` 常用断言。`schema` 断言尚未实现，执行时会跳过。

断言失败会把 Run 标记为失败，但目标 API 的 4xx/5xx 不一定等于平台错误；测试是否通过由断言规则决定。

## 取消与事件

Run 支持取消；取消状态会被持久化。事件通过 SSE 推送，并支持用 `Last-Event-ID` 续传。

运行中的进程恢复仍有已知限制：后端没有 executor lease/heartbeat，无法可靠识别一个 `running` Run 的进程是否已经死亡。

## 下一步

查看 [运行历史](/learn/run-history)，或对终态 Run 生成 [PDF 报告](/learn/pdf-reports)。
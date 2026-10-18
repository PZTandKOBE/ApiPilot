## 创建项目

进入控制台的 Projects 页面，填写项目名称和可选的 Base URL。

Base URL 是 Run 发送请求时使用的基础地址。它应该指向你自己的测试环境，而不是任意外部服务。ApiPilot 对目标地址有 SSRF 防护；内网/本地测试地址是否可用取决于当前配置。

## 导入 OpenAPI

项目内使用 AI Test Lab 导入或粘贴 OpenAPI 文档。当前重点是 JSON 文档；实际解析结果以界面显示为准。

导入后检查：

- 文档标题和版本
- 接口数量和路径
- 认证/security 声明
- 请求参数与响应状态

如果解析失败，先确认 JSON 语法和文件内容，再查看 [故障排查](/learn/troubleshooting)。

## 项目范围

Project 是大部分资源的边界：

- 计划、Run 和报告都属于一个项目。
- 报告查询/下载会按项目校验，跨项目访问返回 404。
- 项目 API Client 的请求通过后端安全代理发送，不由浏览器直接连接目标地址。

## 下一步

规格可以作为 [AI Test Lab](/learn/ai-test-lab) 的输入；生成计划后进入 [计划与审批](/learn/plans-and-approval)。
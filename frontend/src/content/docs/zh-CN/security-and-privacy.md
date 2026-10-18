## 秘密与配置

- 数据库密码、模型 API Key、Token 只放在 `backend/.env` 或部署环境的 secret 中。
- 不要提交 `.env`、真实 Key、证书或带凭证的日志。
- 文档和示例只使用占位符。
- 仓库默认忽略 `.env`；提交前仍应人工检查。

## 身份

当前使用 Guest-first 身份：

- 前端通过 `X-Guest-Session` 请求头认证。
- 后端按 Guest Session 校验项目和资源访问。
- 注册/登录不是当前实现的一部分；登录界面不代表真实账户系统。
- Guest Session 不应转发给被测目标 API。

## 报告脱敏

PDF 报告生成器会处理：

- URL userinfo 和查询参数值
- Authorization / Bearer / Basic
- Cookie / Token / Password / Secret 形式的值
- JWT、常见 API Key 形态
- 变量只显示数量，不显示值
- 字段/header 断言的实际值默认不显示，status actual 可显示

报告只使用已持久化 Run detail；不会补造请求/响应正文或 headers。

## 项目隔离

报告生成、列表、查看和下载都按项目校验。跨项目 report id 不可读取；不存在时返回 404，避免泄露资源是否存在。

## 数据生命周期

- Run 历史、事件、证据和报告按数据库策略保存。
- Collections / Request History 仍在浏览器 localStorage，不提供跨设备同步。
- 删除/归档策略尚未作为产品功能实现；不要依赖自动清理。

## 目标 API 安全

项目 API Client 通过后端 HTTP 代理发送请求，包含 SSRF 地址校验、DNS/IP 检查、TLS 校验和大小限制。它不是生产级 WAF，也不保证所有内网测试地址都可用。

## 下一步

配置项见 [配置](/learn/configuration)；能力边界见 [常见问题](/learn/faq)。
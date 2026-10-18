## 闭环

~~~text
终态 Run
  → Generate & save PDF
  → 服务端生成真实 PDF
  → 保存 PDF 字节 + 元数据
  → Test Reports 列表
  → 在线查看 / 下载 / 打印
~~~

只有 `passed`、`failed`、`cancelled` 可以生成报告。`queued` / `running` 会被拒绝。

## 生成

打开终态 Run 的 PDF 报告预览，点击 **Generate & save PDF**。成功后可以：

- 直接打开已保存报告；
- 进入侧边栏 **Test Reports**；
- 刷新页面后从服务端列表重新读取。

报告正文来自 Run detail。生成报告不会重新请求被测 API，也不会重新调用 AI。

## 报告中心

报告中心按项目列出已保存记录，显示报告名、Run ID、Run 状态、生成时间和文件大小。支持：

- **Open PDF**：在线查看。
- **Download**：下载 PDF。
- **Print**：在浏览器 PDF 查看器中打印。

打开/下载需要 Guest Session 和项目访问权限。

## 服务端实现

- 生成器：`backend/src/backend/services/report_pdf.py`
- 数据库表：`run_reports`
- PDF 列：`content`（bytea）
- migration：`c33a1b2c3d4e_create_run_reports.py`
- API：
  - `POST /api/projects/{project_id}/runs/{run_id}/reports`
  - `GET /api/projects/{project_id}/reports`
  - `GET /api/projects/{project_id}/reports/{report_id}/file`
  - `GET /api/projects/{project_id}/reports/{report_id}/download`

## 报告不含什么

Run 没有持久化请求/响应正文、headers、环境变量值或运行时变量值，因此报告不会补造这些内容。URL 查询值、Authorization/Cookie/Token 等形式会被脱敏；字段/header 断言的实际值默认不显示。

更多见 [安全与隐私](/learn/security-and-privacy)。
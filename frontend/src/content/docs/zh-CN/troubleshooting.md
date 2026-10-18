## 启动失败或页面空白

检查：

1. 后端进程是否仍在运行，默认地址是否为 `http://127.0.0.1:8000`。
2. 前端控制台/网络面板是否出现 CORS 错误。
3. `VITE_API_BASE_URL` 是否指向实际后端。
4. 后端 `CORS_ALLOW_ORIGINS` 是否包含实际前端 origin。

修改环境变量后需要重启进程。

## 数据库表不存在

典型错误：

~~~text
UndefinedTableError: relation "run_reports" does not exist
~~~

说明应用数据库没有执行最新 migration。在 `backend/` 目录执行：

~~~powershell
uv run alembic current
uv run alembic upgrade head
~~~

不要手工建表绕过 Alembic。确认 `alembic current` 与 `alembic heads` 一致。

## 模型调用失败

- 检查 `DEEPSEEK_API_KEY` 是否配置（不要打印/提交它）。
- 检查 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。
- 如果只是本地验证，改用确定性模式：

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

- 确认网络/代理允许访问模型服务。

## 计划生成失败

- 普通首次生成在已有计划时返回冲突，这是预期保护；使用界面的“重新生成”并确认新版本。
- 检查规格 JSON 是否有效、是否包含足够接口信息。
- 检查任务错误；不要通过重复提交掩盖可复现错误。

## Run 失败

- 先看第一个失败 Step 和断言。
- 检查目标 API 是否可达、Base URL 是否正确。
- 检查 Extract 变量是否成功；缺失变量会在请求前失败。
- 请求/响应正文通常没有持久化，历史只能显示已保存证据。

## PDF 保存失败

- 确认 Run 是终态；运行中不能生成。
- 确认迁移已应用到实际应用数据库。
- 查看后端错误；生成失败不应留下成功报告。
- 不要手工修改 `run_reports` 行来“修复”文件。

## 类型检查失败

前端类型检查当前有一个既有错误：

~~~text
ConsoleLayout.vue(114,10): TS18047
~~~

它与文档中心/业务测试失败不是同一件事。运行 `npm test` 仍可验证测试。

## 仍然无法解决

收集：命令、退出码、错误信封/堆栈（不要包含密钥）、数据库 revision 和复现步骤。不要提交 `.env`。
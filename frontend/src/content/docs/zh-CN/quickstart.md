这条路径从本地代码开始，以生成第一份 PDF 报告结束。命令以仓库当前配置为准。

## 1. 准备环境

你需要：

- Python 3.12+ 与 `uv`
- Node.js、npm
- PostgreSQL

创建数据库后，在 `backend/` 目录创建 `.env`，至少配置：

~~~dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=your_database
~~~

真实模型调用还需要 `DEEPSEEK_API_KEY`；不调用模型时可以使用下面的确定性模式。

## 2. 安装、迁移并启动后端

~~~powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
~~~

默认后端地址是 `http://127.0.0.1:8000`。应用启动不会自动执行 migration。

## 3. 启动前端

另开终端：

~~~powershell
cd frontend
npm install
npm run dev
~~~

打开 Vite 输出的地址（默认 `http://localhost:5173`），点击首页的 **Try Us** 进入控制台。

## 4. 跑通第一个测试

1. 创建项目，填入被测 API 的 Base URL。
2. 在 AI Test Lab 粘贴一份 OpenAPI JSON 文档。
3. 分析规格并生成测试计划。
4. 检查 Scenario、Step、Assertion 和风险信息。
5. 批准计划；只有已批准的计划可以创建正式 Run。
6. 启动 Run，观察步骤、断言和事件状态。
7. 等待 Run 进入 `passed`、`failed` 或 `cancelled`。
8. 在 Run 详情打开报告预览，点击 **Generate & save PDF**。
9. 在侧边栏 **Test Reports** 打开报告，查看、下载或打印。

## 5. 命令行验证

后端测试使用隔离库 `aiata_c4_test`：

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run pytest tests/ -q
~~~

前端：

~~~powershell
cd frontend
npm test
~~~

## 接下来

- [项目与 API 规格](/learn/projects-and-specs)
- [AI Test Lab](/learn/ai-test-lab)
- [PDF 测试报告](/learn/pdf-reports)
- [故障排查](/learn/troubleshooting)
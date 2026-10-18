## 组件

ApiPilot 由两个本地应用组成：

- `frontend/`：Vue 3 控制台，使用 Vite 开发服务器。
- `backend/`：FastAPI 服务，使用异步 SQLAlchemy 访问 PostgreSQL。

默认开发地址：

| 组件 | 默认地址 |
|---|---|
| 前端 | `http://localhost:5173` |
| 后端 | `http://127.0.0.1:8000` |

## 数据库

先创建空数据库。ApiPilot 不提供自动建库，也不会在启动时自动运行 migration。

后端连接变量：

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

把真实值放在 `backend/.env`。不要提交该文件。

## 后端安装与启动

~~~powershell
cd backend
uv sync
uv run alembic upgrade head
uv run alembic current
uv run uvicorn main:app --reload
~~~

新库从零执行 migration；已有库先备份并确认 revision，再执行 `upgrade head`。

## 前端安装与启动

~~~powershell
cd frontend
npm install
npm run dev
~~~

如果前端 origin 不是 5173，需要：

1. 设置 `VITE_API_BASE_URL` 指向上游后端。
2. 设置后端 `CORS_ALLOW_ORIGINS`，包含实际前端 origin。
3. 重启对应进程。

## 更新已有部署

1. 拉取新代码并审查 migration。
2. 后端执行 `uv sync` 和 `uv run alembic upgrade head`。
3. 重启后端。
4. 前端执行 `npm install`、重新构建或重启开发服务器。

项目目前没有 Docker 或 CI 配置，因此更新不是自动完成的。

## 测试

测试使用独立数据库。不要把测试指向开发库：

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run pytest tests/ -q
~~~

更多配置见 [配置](/learn/configuration)；启动失败见 [故障排查](/learn/troubleshooting)。
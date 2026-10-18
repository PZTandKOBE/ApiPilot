## 配置文件位置

后端从 `backend/.env` 读取环境变量。Alembic 使用与后端相同的数据库配置，不需要另写一份连接串。

前端使用 Vite 环境变量；可在 `frontend/.env` 或 shell 中设置。

不要提交任何真实密钥、数据库密码或 Token。

## 数据库变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `POSTGRES_HOST` | `127.0.0.1` | PostgreSQL 主机 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_USER` | 无 | 数据库用户 |
| `POSTGRES_PASSWORD` | 无 | 数据库密码 |
| `POSTGRES_DB` | 无 | 目标数据库名 |

这些名字来自 `backend/src/backend/db/database.py`。

## 模型变量

真实模型调用可选：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 无 | API Key；不要提交 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 模型服务地址 |
| `DEEPSEEK_MODEL` | 按客户端配置 | 模型名 |

需要完全离线、确定性运行分析/计划时：

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

默认自动化测试不走真实模型；live 测试是显式 opt-in。

## 前端与 CORS

前端默认调用 `http://127.0.0.1:8000`。后端默认允许：

- `http://localhost:5173`
- `http://127.0.0.1:5173`

如果改用其他端口：

~~~dotenv
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
~~~

~~~powershell
$env:CORS_ALLOW_ORIGINS = 'http://localhost:5174'
~~~

修改环境变量后要重启对应进程。

## 报告相关配置

PDF 报告使用 PostgreSQL 表 `run_reports`，由 migration `c33a1b2c3d4e` 创建。报告内容保存在数据库，不依赖一个本地文件目录。

## 测试环境

后端测试 fixture 会强制使用 `aiata_c4_test`。运行前确认该库存在且迁移完成，并不要把它指向开发业务库。
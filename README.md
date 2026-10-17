# ApiPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#当前状态与规划)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg)](https://fastapi.tiangolo.com/)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776ab.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169e1.svg)](https://www.postgresql.org/)

**ApiPilot 是一个 AI 辅助的 API 自动化测试平台。** 它围绕 OpenAPI 规格分析、测试计划生成与审批、API 测试执行、运行结果查看，以及可持久化的 PDF 测试报告展开。

> **项目状态：Early Development / Alpha。** 当前已交付 AI 测试计划、Run 执行、运行时变量、SSE 事件流和 PDF 测试报告等能力，但项目仍在持续开发，**不是成熟的生产级产品**。默认测试不依赖真实模型。独立的可视化工作流模块尚未开发。

## 目录

- [项目简介](#项目简介)
- [当前已实现](#当前已实现)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [测试](#测试)
- [PDF 测试报告闭环](#pdf-测试报告闭环)
- [项目结构](#项目结构)
- [文档入口](#文档入口)
- [当前状态与规划](#当前状态与规划)
- [已知限制](#已知限制)
- [许可证](#许可证)
- [English Summary](#english-summary)

## 项目简介

ApiPilot 把 API 测试的主要步骤放进一个工作台：

1. 创建项目，导入或粘贴 OpenAPI 规格，查看接口、参数、认证声明和依赖关系。
2. 使用 AI 分析规格，生成可审核的测试计划。
3. 审批或拒绝计划；对已有计划显式重新生成新版本。
4. 由后端确定性执行器发送请求、提取运行时变量并运行断言。
5. 查看 Run 状态、步骤、断言、证据和历史结果。
6. 对已结束的 Run 生成真实 PDF 报告，保存 PDF 与元数据，并在报告中心查看、下载或打印。

LLM 负责分析和生成候选计划；HTTP 请求执行、断言判断、运行状态、事件持久化和报告生成由后端确定性逻辑负责。

## 当前已实现

### 项目与 API 规格

- Guest Session 身份，以及项目创建、列表和项目概览。
- 在项目内导入/粘贴 OpenAPI 规格，展示解析摘要和接口信息。
- 项目 API Client，通过后端安全 HTTP 代理发送请求，而不是让浏览器直接访问任意目标地址。
- 目标地址校验、SSRF 防护、DNS/IP 检查、TLS 校验、禁止自动跟随重定向和请求/响应大小限制。
- Collections 与 Request History 的基础前端能力；**当前保存在浏览器 localStorage，不是服务端持久化**。

### AI 测试计划

- OpenAPI 规格分析、任务状态读取、测试计划生成和审核流程。
- 测试计划以 Scenario、Step、Assertion 组织。
- 支持 `draft`、`in_review`、`approved`、`rejected` 等状态；未批准的计划不能进入正式 Run。
- 支持计划批准/拒绝，以及显式重新生成计划版本。
- 重新生成会创建新的计划行（如 `plan_slug_v2`），旧计划和历史 Run 保持不变；当前版本由最高 version 派生。
- 计划列表和详情显示 version、当前版本标记和关联 Run 数量。
- OpenAPI security facts 会区分“未声明 security”“显式 public”和“需要认证”，用于确定性 Planner 决定是否生成认证场景。
- Run 详情区分 **Initial variables** 与 **Runtime variables**；运行时变量由成功的 Extract 步骤派生，只显示名称/作用域，不暴露值。

### API 测试执行与 Run

- 后端 Run Executor 执行 HTTP 请求，支持多请求流程、环境变量替换、运行时变量提取和步骤证据。
- 支持 `status`、`header`、`field` 常用断言；`schema` 断言尚未实现，执行时会跳过。
- 保存 Run、Scenario、Step、Assertion、事件和部分执行证据。
- 通过 SSE 推送运行事件，支持 `Last-Event-ID` 断线续传。
- 前端可查看 Run 列表、详情、步骤状态、断言结果、证据、取消结果和历史记录。
- 取消请求有明确的状态机；Run 启动恢复覆盖“启动前遗留的 queued Run”，但已进入 `running` 的进程恢复仍有已知缺口（见[已知限制](#已知限制)）。

### PDF 测试报告

- 报告中心按项目列出已保存报告，显示 Run ID、Run 状态、生成时间和文件大小。
- 对终态 Run（`passed` / `failed` / `cancelled`）生成**真实 PDF 字节**并保存到 PostgreSQL。
- PDF 与元数据写入同一行、同一事务；不依赖文件系统路径。
- 支持在线查看、下载和再次打印。
- 报告只使用已保存的 Run detail，不重新调用 AI、不重新请求被测 API，也不伪造未持久化的请求/响应正文或 headers。
- 报告生成和读取均按项目隔离；跨项目访问返回 404。

## 技术栈

| 层级 | 实际使用 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、Tailwind CSS |
| 后端 | Python 3.12+、FastAPI、Pydantic、SQLAlchemy 2（异步）、Alembic、HTTPX、asyncio |
| 数据库 | PostgreSQL；异步驱动 asyncpg |
| PDF | ReportLab；内置 `STSong-Light` CID 字体用于中文 PDF |
| 测试 | Vitest、pytest；PDF 测试使用 PyMuPDF/PyPDF（dev 依赖） |
| AI | DeepSeek HTTP client；模型调用为可选配置，默认测试使用 stub/确定性路径 |

具体版本以 [frontend/package.json](frontend/package.json) 和 [backend/pyproject.toml](backend/pyproject.toml) 为准。

## 快速开始

### 前置条件

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Node.js 与 npm（前端使用 Vite 8）
- PostgreSQL，以及一个可创建/迁移的本地数据库
- 可选：DeepSeek API Key（只有需要真实模型分析/生成时才需要）

本项目不包含 Docker 或 CI 配置。

### 1. 准备数据库

先使用 PostgreSQL 管理工具创建一个空数据库。ApiPilot 不会在应用启动时自动建库或自动执行 migration。

### 2. 配置后端

在 `backend/` 目录创建 `.env`，配置数据库连接和可选模型参数。变量名以实际配置代码为准：

~~~dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=your_database

# 可选：真实 DeepSeek 调用
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
~~~

**不要把 `.env`、真实 API Key、数据库密码或 Guest Session Token 提交到 Git。** 仓库通过 `.gitignore` 排除本地 `.env`；提交前可自行检查：

~~~powershell
git check-ignore -v backend/.env
~~~

如需让本地前端使用非默认端口，可设置后端 `CORS_ALLOW_ORIGINS`（逗号分隔）。默认允许 Vite 的 5173 端口来源。

### 3. 安装后端依赖并迁移

~~~powershell
cd backend
uv sync
uv run alembic upgrade head
uv run alembic current
~~~

- **新数据库：** 创建空库后执行 `upgrade head`，从零建立 schema。
- **已有数据库：** 先备份并确认当前 revision，再执行 `upgrade head` 升级；不要假设应用启动会自动迁移。
- 数据库连接由 `backend/.env` 和 `backend/src/backend/db/database.py` 决定；Alembic 复用同一个应用数据库配置。

### 4. 启动后端

~~~powershell
cd backend
uv run uvicorn main:app --reload
~~~

默认监听 `http://127.0.0.1:8000`。

### 5. 启动前端

另开终端：

~~~powershell
cd frontend
npm install
npm run dev
~~~

Vite 默认在 `http://localhost:5173` 启动。前端默认调用 `http://127.0.0.1:8000`；如后端地址不同，在 `frontend/.env` 或 shell 中设置：

~~~dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
~~~

然后让后端 `CORS_ALLOW_ORIGINS` 包含实际前端 origin。

### 可选：不调用真实模型

需要在本地走确定性分析/计划路径时，可在启动后端前设置：

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

真实 DeepSeek 路径和 live 测试默认不启用；具体开关见 [docs/PROJECT_PROGRESS.md](docs/PROJECT_PROGRESS.md)。

## 测试

### 后端

测试必须使用隔离测试库。仓库的 `backend/tests/conftest.py` 会强制使用 `aiata_c4_test`；该库必须已存在并完成 migration。

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run pytest tests/ -q
~~~

最近一次验证结果：**152 passed, 3 skipped**，退出码 **0**。

不要把这个测试库指向开发/业务数据库。运行会创建和清理测试夹具。

### 前端

~~~powershell
cd frontend
npm test
~~~

最近一次验证结果：**27 个测试文件，338 项测试通过，0 失败**，退出码 **0**。

类型检查：

~~~powershell
cd frontend
npx vue-tsc -b --pretty false
~~~

当前会报告一个**既有**类型错误：

~~~text
src/layouts/ConsoleLayout.vue(114,10): error TS18047:
'projectStore.activeProject' is possibly 'null'.
~~~

该问题尚未修复，因此 `npm run verify` 目前会在类型检查阶段失败；这不代表测试断言失败。

### 浏览器 E2E（可选）

仓库包含 `frontend/e2e/` 下的受控浏览器 E2E harness；它需要 Chrome、隔离测试库和本地后端。运行方式与环境边界见 [frontend/e2e/README.md](frontend/e2e/README.md)。

## PDF 测试报告闭环

当前流程：

~~~text
已结束的 Run
  → POST /api/projects/{project_id}/runs/{run_id}/reports
  → 服务端读取已保存的 Run detail
  → ReportLab 生成真实 PDF 字节
  → 同一个 run_reports 行保存 PDF + 元数据
  → GET /api/projects/{project_id}/reports
  → 报告中心列表
  → 在线查看 / 下载 / 打印
~~~

### 数据与限制

- 报告使用 `backend/src/backend/services/report_pdf.py` 生成。
- PDF 字节保存在 PostgreSQL 表 `run_reports` 的 `content` 列，元数据包括文件名、字节数、SHA-256 和生成时间。
- 数据库 migration 为 `c33a1b2c3d4e_create_run_reports.py`，父 revision 为 `a4c1e8b27d93`。
- 只有终态 Run 可以生成报告；`queued` / `running` 返回 409 `report-not-ready`。
- 报告读取/下载使用 report UUID 和 project 范围查询，不使用文件系统路径或用户提供的文件名。
- 报告会移除 URL userinfo/查询参数值、Authorization/Bearer/Basic、JWT、API Key、Cookie、token/password/secret 形式的值；变量只显示数量，字段/header 断言的实际值默认不显示。
- Run 没有持久化请求/响应正文、headers、环境变量值或运行时变量值，因此报告不会包含这些内容，也不会为了补全报告重新执行请求或调用 AI。

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/runs/{run_id}/reports | 生成并保存报告 |
| GET | /api/projects/{project_id}/reports | 列出已保存报告 |
| GET | /api/projects/{project_id}/reports/{report_id}/file | 在线查看 PDF |
| GET | /api/projects/{project_id}/reports/{report_id}/download | 下载 PDF |

所有报告路由都要求当前 Guest Session 拥有对应项目。

## 项目结构

~~~text
.
├── backend/
│   ├── src/backend/
│   │   ├── api/            # FastAPI 路由、错误信封
│   │   ├── services/       # 代理、Agent 管线、Run 执行、PDF 报告
│   │   ├── db/models/      # SQLAlchemy 模型
│   │   ├── schemas/        # Pydantic schema
│   │   └── prompts/        # Agent 提示词
│   ├── alembic/versions/   # 数据库迁移
│   ├── tests/              # pytest 测试与隔离测试库 fixture
│   ├── scripts/            # 本地验证脚本与开发工具（谨慎运行）
│   ├── dosc/               # 早期数据库/管线契约资料
│   ├── main.py             # uvicorn 入口
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/                # Vue 控制台、组件、stores、services
│   ├── tests/              # Vitest 测试
│   ├── e2e/                # 受控浏览器 E2E harness
│   ├── docs/               # 前端架构与 REST 契约
│   ├── public/
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.ts
├── docs/                   # 项目进度与正式契约
│   ├── PROJECT_PROGRESS.md
│   ├── agent-pipeline-contract.md
│   └── identity-access-contract.md
├── devtools/
│   └── mock_orders_api.py  # 本地 Orders 模拟服务
├── LICENSE
└── README.md
~~~

## 文档入口

- [项目进度与验证记录](docs/PROJECT_PROGRESS.md)
- [Agent 管线契约](docs/agent-pipeline-contract.md)
- [身份与访问契约](docs/identity-access-contract.md)
- [前端架构](frontend/docs/phase-6-architecture.md)
- [前端后端 REST 契约](frontend/docs/phase-6.2-backend-rest-contract.md)
- [浏览器 E2E harness](frontend/e2e/README.md)

## 当前状态与规划

### 已实现

- 项目、OpenAPI 规格分析与安全 API 代理。
- AI 测试计划生成、审批、拒绝和显式版本化重新生成。
- Run 执行、多请求流程、运行时变量提取、常用断言、SSE 事件、取消和历史查看。
- Run detail 的 Initial/Runtime variables 区分。
- 报告中心，以及从终态 Run 生成、保存、查看、下载和打印 PDF 报告。
- 报告脱敏与项目访问隔离。

### 暂缓

- **独立可视化工作流模块：尚未开发。** 没有画布编辑器、条件分支编排或工作流专属版本系统；当前只有测试计划中的 Scenario/Step/Assertion 结构，不能把这些能力描述成可视化工作流。

### 后续方向

后续工作取决于实际项目进展，不在 README 中承诺具体日期或未实现能力。可能的方向包括：完善运行恢复 lease/heartbeat、补充 schema 断言、改善报告中心检索/分页，以及更完整的浏览器端到端验证。

## 已知限制

- 项目仍在 Alpha 阶段，不应直接用于关键生产测试。
- 完整 AI 分析 → 计划 → Run 的浏览器端到端流程仍缺少一个自动化的全链路验收；已有单元、集成、SSR 和局部浏览器 harness，但不等于整条链路已验收。
- Run 启动恢复没有 executor lease/heartbeat；`running` Run 在进程崩溃后的识别仍有缺口。
- `schema` 断言尚未实现，执行时会跳过。
- Collections / Request History 仍只保存在浏览器 localStorage。
- 注册/登录仍不属于 Guest-first 阶段；现有登录界面不是真实身份系统。
- 报告中心暂无搜索、分页、模板或批量导出。
- 前端类型检查仍有一个既有 `ConsoleLayout.vue(114,10)` TS18047 错误。
- 尚未配置 Docker 或 CI 流水线。

## 许可证

本项目以 **MIT License** 开源发布，版权归 **PZTandKOBE** 所有。

~~~text
Copyright (c) 2026 PZTandKOBE
~~~

MIT 是宽松许可证：你可以自由使用、修改、分发本项目，包括用于商业用途，条件是保留版权声明与许可证全文。完整条款见仓库根目录的 [LICENSE](LICENSE)。

## English Summary

**ApiPilot** is an early-stage AI-assisted API testing platform built with Vue 3, TypeScript, FastAPI, async SQLAlchemy, PostgreSQL, and Alembic. It covers OpenAPI analysis, reviewable AI-generated test plans with versioned regeneration, deterministic run execution with multi-request flows and runtime variables, SSE run events, cancellation, and a persisted PDF report center.

Terminal runs can generate real PDF bytes on the server, store them in the `run_reports` PostgreSQL table together with metadata, and expose project-scoped list, inline-view, and download APIs. Reports use only persisted run data; they do not re-run requests or call the AI provider.

The project is **not production-ready yet**. The standalone visual workflow/canvas module has not been built. Run recovery for already-running processes, schema assertions, server-side Collections/History, and a fully automated end-to-end browser acceptance of the complete AI-to-run flow remain incomplete. See the Chinese sections above for setup, testing, report details, and limitations.

## License

Released under the **MIT License**. Copyright (c) 2026 PZTandKOBE. See [LICENSE](LICENSE) for the full text.

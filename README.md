<p align="center">
  <img src="frontend/public/brand/ApiPilot_Banner.png" alt="ApiPilot" width="500" />
</p>

# ApiPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: First Release](https://img.shields.io/badge/status-first%20release-blue.svg)](#当前状态与规划)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg)](https://fastapi.tiangolo.com/)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776ab.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169e1.svg)](https://www.postgresql.org/)

**ApiPilot 是一个 AI 辅助的 API 自动化测试平台。** 它围绕 OpenAPI 规格分析、测试计划生成与审批、API 测试执行、运行结果查看，以及可持久化的 PDF 测试报告展开。

> **项目状态：首个可运行版本（First Release）。** 当前已经具备从项目与 OpenAPI 规格、Agent 分析、测试计划生成与人工审核、后端确定性执行，到 Run 结果、PDF 报告和项目内通知的完整核心工作流。本文档只描述当前已经实现并经过测试的能力；项目仍在持续完善，**不宣称已经达到生产级可靠性**，具体边界见[已知限制](#已知限制-1)。

## 目录

- [ApiPilot](#apipilot)
  - [目录](#目录)
  - [项目简介](#项目简介)
  - [当前已实现](#当前已实现)
    - [项目与 API 规格](#项目与-api-规格)
    - [AI 测试计划](#ai-测试计划)
    - [API 测试执行与 Run](#api-测试执行与-run)
    - [PDF 测试报告](#pdf-测试报告)
    - [项目生命周期与通知](#项目生命周期与通知)
    - [账号、会话与游客](#账号会话与游客)
    - [Learn Us 文档中心](#learn-us-文档中心)
  - [技术栈](#技术栈)
  - [快速开始](#快速开始)
    - [前置条件](#前置条件)
    - [1. 准备数据库](#1-准备数据库)
    - [2. 配置后端](#2-配置后端)
    - [3. 安装后端依赖并迁移](#3-安装后端依赖并迁移)
    - [4. 启动后端](#4-启动后端)
    - [5. 启动前端](#5-启动前端)
    - [可选：不调用真实模型](#可选不调用真实模型)
  - [身份认证与 OAuth](#身份认证与-oauth)
    - [两种部署模式](#两种部署模式)
    - [配置](#配置)
    - [GitHub OAuth App](#github-oauth-app)
    - [Google OAuth / OIDC](#google-oauth--oidc)
    - [登录流程](#登录流程)
    - [已知限制](#已知限制)
  - [测试](#测试)
    - [后端](#后端)
    - [前端](#前端)
    - [浏览器 E2E（可选）](#浏览器-e2e可选)
  - [PDF 测试报告闭环](#pdf-测试报告闭环)
    - [数据与限制](#数据与限制)
    - [API](#api)
  - [Learn Us 文档中心](#learn-us-文档中心-1)
  - [项目结构](#项目结构)
  - [文档入口](#文档入口)
  - [当前状态与规划](#当前状态与规划)
    - [已实现](#已实现)
    - [暂缓](#暂缓)
    - [后续方向](#后续方向)
  - [已知限制](#已知限制-1)
  - [许可证](#许可证)
  - [English Summary](#english-summary)
  - [License](#license)

## 项目简介

ApiPilot 把 API 测试的主要步骤放进一个工作台：

1. 创建或编辑项目，配置环境，导入或粘贴 OpenAPI 规格，查看接口、参数、认证声明和依赖关系。
2. 使用 AI 分析规格，生成可审核的测试计划。
3. 审批或拒绝计划；对已有计划显式重新生成新版本。
4. 由后端确定性执行器发送请求、提取运行时变量并运行断言。
5. 查看 Run 状态、步骤、断言、证据和历史结果。
6. 对已结束的 Run 生成真实 PDF 报告，保存 PDF 与元数据，并在报告中心查看、下载或打印。

LLM 负责分析和生成候选计划；HTTP 请求执行、断言判断、运行状态、事件持久化和报告生成由后端确定性逻辑负责。

## 当前已实现

### 项目与 API 规格

- Guest Session 身份，以及项目创建、列表、概览、编辑和删除。
- 项目内环境创建、编辑、切换和多环境变量管理。
- 首页右上角 GitHub 仓库入口：https://github.com/PZTandKOBE/ApiPilot。
- 在项目内导入/粘贴 OpenAPI 规格，展示解析摘要、真实接口数据和认证信息。
- 项目 API Client，通过后端安全 HTTP 代理发送请求，而不是让浏览器直接访问任意目标地址。
- 目标地址校验、SSRF 防护、DNS/IP 检查、TLS 校验、禁止自动跟随重定向和请求/响应大小限制。
- Collections 与 Request History 的基础前端能力；**当前保存在浏览器 localStorage，不是服务端持久化**。

### AI 测试计划

- AI Test Lab（Agent Lab）覆盖 OpenAPI 规格分析、任务状态读取、测试计划生成和审核流程。
- Agent 任务列表展示最近任务、任务状态和关联计划；分析结果通过五步分析审阅界面呈现。
- 测试计划以 Scenario、Step、Assertion 组织。
- 支持 `draft`、`in_review`、`approved`、`rejected` 等状态；未批准的计划不能进入正式 Run。
- 支持计划批准/拒绝、编辑、显式重新生成版本，以及删除计划。
- 重新生成会创建新的计划行（如 `plan_slug_v2`），旧计划和历史 Run 保持不变；当前版本由最高 version 派生。
- 删除计划会停用该计划的全部版本，但保留历史 Run 和已生成报告，便于追溯。
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

### 项目生命周期与通知

- 项目编辑支持名称和基础信息调整；项目删除会清理该项目的环境、规格、计划、Run、事件和报告等项目所属数据。
- 测试计划删除采用保留历史的生命周期：计划版本退出可用列表，已结束 Run 和已生成 PDF 报告仍可按原项目读取。
- 顶部通知中心汇总当前项目最近完成的 Agent 任务、待审核计划和已生成报告；通知从现有项目数据派生，未读状态保存在浏览器本地。
- 删除操作前端均有明确确认与错误反馈；跨项目或已删除项目的访问返回 404，不暴露其他项目数据。

### 账号、会话与游客

- GitHub OAuth 与 Google OIDC 登录；首次登录自动创建 ApiPilot 账号。
- 账号会话使用服务端保存的随机 token 哈希和 HttpOnly Cookie；支持当前用户接口、退出登录和刷新恢复。
- 稳定身份键为 provider + provider_subject；邮箱不是身份，不会因 provider 返回同一邮箱而自动合并账号。
- official_cloud 默认要求账号；设置 AUTH_OFFICIAL_GUEST_ENABLED=true 后，登录页同时提供 GitHub、Google 和游客体验。
- 官方游客使用独立 Guest Session、guest_session_id 项目归属和服务器端限额；游客项目不会自动转移给登录账号。
- 已登录账号使用 user_id 项目归属；跨账号和跨游客访问均返回 404。
- 游客可从顶部菜单退出游客模式；只撤销当前 Guest Session，不删除项目或历史 Run。

### Learn Us 文档中心

- 首页 Learn Us 进入独立的 /learn 文档中心，支持中英文切换、本地全文搜索、分组导航、本页目录、代码复制、标题锚点、前后篇导航和持久化明暗主题。
- 文档由 frontend/src/content/docs 下的 Markdown 文件提供，registry 显式注册 slug、标题、摘要和顺序。
- 搜索和渲染均在浏览器本地完成，不依赖外部搜索服务；Markdown 不执行原始 HTML。

## 技术栈

| 层级 | 实际使用 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、Tailwind CSS |
| 后端 | Python 3.12+、FastAPI、Pydantic、SQLAlchemy 2（异步）、Alembic、HTTPX、asyncio |
| 数据库 | PostgreSQL；异步驱动 asyncpg |
| PDF | ReportLab；内置 `STSong-Light` CID 字体用于中文 PDF |
| 认证 | Authlib OAuth/OIDC、itsdangerous 签名 Cookie；账号 Session 使用 SHA-256 token 哈希 |
| 测试 | Vitest、pytest；PDF 测试使用 PyMuPDF/PyPDF（dev 依赖） |
| AI | DeepSeek HTTP client；模型调用为可选配置，默认测试使用 stub/确定性路径 |

具体版本以 [frontend/package.json](frontend/package.json) 和 [backend/pyproject.toml](backend/pyproject.toml) 为准。

## 快速开始

### 前置条件

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Node.js **20.19+** 或 **22.12+**、npm（前端使用 Vite 8）
- PostgreSQL，以及一个可创建/迁移的本地数据库
- 可选：DeepSeek API Key（只有需要真实模型分析/生成时才需要）

本项目不包含 Docker 或 CI 配置。

### 1. 准备数据库

先使用 PostgreSQL 管理工具创建一个空数据库。ApiPilot 不会在应用启动时自动建库或自动执行 migration。

### 2. 配置后端

在 `backend/` 目录从 `.env.example` 复制并创建 `.env`，配置数据库连接和可选模型参数。变量名以实际配置代码为准：

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

Vite 默认在 `http://localhost:5173` 启动；使用 OAuth 登录时建议打开 `http://127.0.0.1:5173`，使前端与 `http://127.0.0.1:8000` 处于同一站点，Lax Cookie 才会发送。前端默认调用 `http://127.0.0.1:8000`；如后端地址不同，在 `frontend/.env` 或 shell 中设置：

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

真实 DeepSeek 路径和 live 测试默认不启用；分析器和 Planner 的选择由 `AGENT_ANALYZER`、`AGENT_PLANNER` 环境变量控制。

## 身份认证与 OAuth

### 两种部署模式

| DEPLOYMENT_MODE | 行为 |
|---|---|
| self_hosted（默认） | 保留现有 Guest Session；不要求 OAuth 凭据；控制台可直接使用 |
| official_cloud | 默认要求账号；开启 AUTH_OFFICIAL_GUEST_ENABLED 后可选择账号或游客；游客使用独立 Guest Session 和服务端限额；账号 Project/Run/Report 继续按 user_id 隔离 |

official_cloud 的游客体验默认关闭。开启后，游客可创建独立 Guest Session、项目、受限的 Run 和 AI 任务；游客项目不会自动转到后续登录的账号。

### 配置

从 backend/.env.example 复制并填写占位符。OAuth 相关变量：

| 变量 | 说明 |
|---|---|
| DEPLOYMENT_MODE | self_hosted 或 official_cloud |
| AUTH_PUBLIC_BASE_URL | 后端公开地址，用于推导 callback URI |
| AUTH_FRONTEND_BASE_URL | 登录成功/失败后跳转的前端 origin |
| AUTH_SESSION_SECRET | 高熵随机字符串，用于签署短期 OAuth state cookie |
| AUTH_COOKIE_SECURE | HTTPS 生产环境为 true；本地 HTTP 才显式设 false |
| GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET | GitHub OAuth App 凭据 |
| GITHUB_REDIRECT_URI | 可覆盖默认 callback；必须与 GitHub App 完全一致 |
| GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET | Google OAuth Web client 凭据 |
| GOOGLE_REDIRECT_URI | 可覆盖默认 callback；必须与 Google Console 完全一致 |
| GOOGLE_OIDC_DISCOVERY_URL | 默认 Google OIDC discovery |
| AUTH_SESSION_TTL_SECONDS | 账号会话有效期，默认 14 天 |
| AUTH_STATE_TTL_SECONDS | OAuth state 有效期，默认 10 分钟 |
| AUTH_OFFICIAL_GUEST_ENABLED | official_cloud 是否允许游客体验；默认 false |
| AUTH_OFFICIAL_GUEST_MAX_PROJECTS | 每个官方云游客最多项目数，默认 3 |
| AUTH_OFFICIAL_GUEST_MAX_RUNS | 每个官方云游客最多 Run 数，默认 10 |
| AUTH_OFFICIAL_GUEST_MAX_AGENT_TASKS | 每个官方云游客最多 AI Agent 任务数，默认 1 |
| AUTH_OFFICIAL_GUEST_DAILY_AGENT_TASKS | 所有官方云游客每日 AI Agent 任务总上限，默认 10 |

本地开发建议同时使用 127.0.0.1 打开前端和后端，避免 localhost 与 127.0.0.1 造成 Lax Cookie 不发送：

~~~powershell
cd frontend
npm run dev -- --host 127.0.0.1
~~~

然后打开 http://127.0.0.1:5173。若前端/后端不同源，CORS_ALLOW_ORIGINS 必须包含实际前端 origin。

### GitHub OAuth App

1. 在 GitHub Settings → Developer settings → OAuth Apps 新建 OAuth App。
2. Homepage URL 填部署前端地址。
3. Authorization callback URL 填：
   http://127.0.0.1:8000/api/auth/callback/github
4. 将 Client ID/Secret 写入后端环境变量；只申请 read:user，不请求 repo/gist。
5. 使用 GITHUB_REDIRECT_URI 时，必须与页面中的回调地址完全一致。

### Google OAuth / OIDC

1. 在 Google Cloud Console 创建 OAuth Web application。
2. Authorized redirect URI 填：
   http://127.0.0.1:8000/api/auth/callback/google
3. 将 Client ID/Secret 写入后端环境变量。
4. Scope 为 openid email profile；后端使用 Authlib 验证 ID token 的签名、issuer、audience、expiry 和 nonce。

认证 migration 为 d4e5f6a7b8c9（父 revision c33a1b2c3d4e）；它在 ai_api_testing 和 aiata_c4_test 均已应用。后续 schema 变更仍应显式执行 upgrade head，不要在应用启动时自动迁移。

### 登录流程

~~~text
GET /api/auth/login/{provider}?next=/console
  → provider authorization (state + PKCE；Google 另含 nonce)
  → GET /api/auth/callback/{provider}
  → validate one-time DB state
  → exchange code / validate OIDC ID token
  → identity (provider, subject) → User
  → internal account guest identity → HttpOnly session cookie
  → redirect to safe frontend path
~~~

- 首次登录自动创建账号；同一 provider subject 再次登录回到同一账号。
- Email 不是主身份；不同 provider 使用同一 email 不会自动合并账号。
- 账号会话 Cookie 为 HttpOnly、SameSite=Lax、Path=/；生产 HTTPS 使用 Secure。
- 服务端只保存会话 token 的 SHA-256；provider access/ID token 不进入数据库、localStorage 或 URL。
- 登录回跳只允许站内相对路径；state 事务在数据库中一次性消费。
- API 写操作还有 Origin 校验作为 Cookie 的第二道 CSRF 防护。

游客流程：

~~~text
POST /api/guest-sessions
  → server issues an opaque Guest Session token
  → browser stores it local-only and sends X-Guest-Session
  → Guest Session owns projects through guest_session_id
  → refresh reuses the same token; explicit exit revokes only that session
~~~

official_cloud 本地开启游客体验只需设置：

~~~dotenv
DEPLOYMENT_MODE=official_cloud
AUTH_OFFICIAL_GUEST_ENABLED=true
~~~

服务端限额由 AUTH_OFFICIAL_GUEST_MAX_* 与 AUTH_OFFICIAL_GUEST_DAILY_AGENT_TASKS 控制；不要把游客体验建立在仅隐藏前端按钮上。

### 已知限制

- 真实 GitHub/Google OAuth 尚未使用真实凭据做端到端验收；provider 交换在测试中被 mock。
- V1 不自动认领登录前已有的 Guest 项目；登录账号从自己的 user_id 项目开始。后续需要明确、安全的账号关联流程。
- 注册/登录页覆盖 OAuth；邮箱密码、MFA 和账号解绑仍未实现。
- official_cloud 游客使用数据库计数限额，不包含独立的计费/套餐系统；游客会话创建本身仍建议在反向代理层限速。
- official_cloud 且游客关闭、未配置任何 provider 时，登录页会明确显示未配置，受保护 API 返回 401。
- 用户可从游客菜单明确退出游客模式；退出只撤销当前 Guest Session，不删除项目和运行记录。

## 测试

### 后端

测试必须使用隔离测试库。仓库的 `backend/tests/conftest.py` 会强制使用 `aiata_c4_test`；该库必须已存在并完成 migration。

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run python -m pytest tests/ -q
~~~

测试结果以本次命令的实际输出为准，不在 README 中维护容易失效的精确数量。后端测试包含 API、权限隔离、Agent 管线、Run 执行/恢复和 PDF 报告等集成测试。

不要把这个测试库指向开发/业务数据库。`conftest.py` 会强制使用隔离库，运行会创建和清理测试夹具。

### 前端

~~~powershell
cd frontend
npm test
~~~

前端测试包含组件/页面交互、Store、服务传输和 SSR 渲染。测试结果以本次命令的实际输出为准。

类型检查：

~~~powershell
cd frontend
npx vue-tsc -b --pretty false
~~~

类型检查应与测试一起作为发布前检查运行。`npm run build` 会先执行 `vue-tsc`，再执行 Vite 生产构建。

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

所有报告路由都要求当前已验证身份（账号或 Guest Session）拥有对应项目。

## Learn Us 文档中心

首页的 **Learn Us** 现在进入独立的文档中心，而不是滚动到营销区。

- 入口：`/learn`；文章路径：`/learn/{slug}`。
- 左侧按 Get started / Use ApiPilot / Reference 分组导航，右侧生成 H2/H3 本页目录。
- 文章来自 `frontend/src/content/docs/{zh-CN,en-US}` 下的 Markdown 文件；`registry.ts` 显式注册标题、slug、分组、顺序和摘要。
- 支持中英文切换、标题/摘要/正文的本地搜索、`Ctrl/Cmd+K`、代码一键复制、标题锚点复制、前后篇导航。
- Light / Dark 只作用于文档根节点；用户选择保存到 localStorage，未选择时遵循系统偏好。Try Us 控制台主题不受影响。
- Markdown 渲染不执行原始 HTML，并限制链接协议；不依赖外部搜索服务。

文章覆盖：概览、快速开始、本地部署、配置、项目与 API 规格、AI Test Lab、计划与审批、运行测试、运行历史、PDF 报告、故障排查、安全与隐私、FAQ。

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
│   ├── main.py             # uvicorn 入口
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/                # Vue 控制台、组件、stores、services
│   │   ├── content/docs/   # Learn Us Markdown 内容与显式注册表
│   │   └── components/learn/ # Learn Us 顶栏、导航、搜索
│   ├── tests/              # Vitest 测试
│   ├── e2e/                # 受控浏览器 E2E harness
│   ├── public/
│   ├── README.md           # 前端开发与测试说明
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.ts
├── devtools/
│   └── mock_orders_api.py  # 本地 Orders 模拟服务
├── LICENSE
└── README.md
~~~

## 文档入口

- [前端开发与测试说明](frontend/README.md)
- [浏览器 E2E harness](frontend/e2e/README.md)
- [前端 Learn Us 产品文档内容](frontend/src/content/docs/zh-CN)

## 当前状态与规划

### 已实现

- 项目列表、创建、编辑、概览、删除，以及多环境创建、编辑和切换。
- 项目、OpenAPI 规格分析与安全 API 代理。
- Agent 任务列表、任务状态、五步分析审阅和人工审核流程。
- AI 测试计划生成、审批、拒绝、编辑和显式版本化重新生成；计划删除保留历史 Run 与报告。
- Run 执行、多请求流程、运行时变量提取、常用断言、SSE 事件、取消和历史查看。
- Run detail 的 Initial/Runtime variables 区分。
- 报告中心，以及从终态 Run 生成、保存、查看、下载和打印 PDF 报告。
- 报告脱敏与项目访问隔离。
- GitHub / Google OAuth、账号 Session、真实账号菜单和退出登录。
- official_cloud 游客体验、独立 Guest Session、服务端项目/Run/AI 任务限额。
- Learn Us 文档中心：中英文 Markdown、分组导航、搜索、代码复制、锚点、前后篇和持久化明暗主题。
- 顶部应用内通知中心，汇总 Agent 任务、待审核计划和已生成报告。

### 暂缓

- **独立可视化工作流模块：尚未开发。** 没有画布编辑器、条件分支编排或工作流专属版本系统；当前只有测试计划中的 Scenario/Step/Assertion 结构，不能把这些能力描述成可视化工作流。

### 后续方向

后续工作取决于实际项目进展，不在 README 中承诺具体日期或未实现能力。可能的方向包括：完善运行恢复 lease/heartbeat、补充 schema 断言、改善报告中心检索/分页，以及更完整的浏览器端到端验证。

## 已知限制

- 项目处于首个可运行版本阶段，尚未完成生产级可靠性验证，不应直接用于关键生产测试。
- 完整 AI 分析 → 计划 → Run 的浏览器端到端流程仍缺少一个自动化的全链路验收；已有单元、集成、SSR 和局部浏览器 harness，但不等于整条链路已验收。
- Run 启动恢复没有 executor lease/heartbeat；`running` Run 在进程崩溃后的识别仍有缺口。
- `schema` 断言尚未实现，执行时会跳过。
- Collections / Request History 仍只保存在浏览器 localStorage。
- GitHub / Google OAuth 的真实 provider 端到端流程尚未在本次发布中手工验收；自动化测试验证了 state、PKCE、OIDC 声明校验、Cookie 和回调契约，provider 交换使用 mock。
- official_cloud 游客限额是数据库计数上限，不是独立计费系统；游客会话创建本身仍建议由反向代理限速。
- 报告中心暂无搜索、分页、模板或批量导出。
- 尚未配置 Docker 或 CI 流水线。

## 许可证

本项目以 **MIT License** 开源发布，版权归 **S1eepEarly** 所有。

~~~text
Copyright (c) 2026 S1eepEarly
~~~

MIT 是宽松许可证：你可以自由使用、修改、分发本项目，包括用于商业用途，条件是保留版权声明与许可证全文。完整条款见仓库根目录的 [LICENSE](LICENSE)。

## English Summary

**ApiPilot** is a first-release AI-assisted API testing platform built with Vue 3, TypeScript, FastAPI, async SQLAlchemy, PostgreSQL, Alembic, and Authlib. It covers project and environment management, OpenAPI analysis, reviewable AI-generated test plans with versioned regeneration, deterministic run execution with multi-request flows and runtime variables, SSE run events, cancellation, a persisted PDF report center, in-app notifications, and a Learn Us documentation center in Chinese and English.

Terminal runs can generate real PDF bytes on the server, store them in the `run_reports` PostgreSQL table together with metadata, and expose project-scoped list, inline-view, and download APIs. Reports use only persisted run data; they do not re-run requests or call the AI provider.

GitHub OAuth and Google OIDC accounts use server-side sessions and HttpOnly cookies. `self_hosted` keeps the original Guest Session behavior. `official_cloud` can require accounts or, with `AUTH_OFFICIAL_GUEST_ENABLED=true`, offer a sandboxed guest experience with per-guest project/run/AI-task caps and a global daily guest AI-task cap. Guest projects are isolated by `guest_session_id` and are not transferred to later account logins.

This is the first release of the complete core workflow, but it is **not presented as a production-hardened platform**. The standalone visual workflow/canvas module has not been built. Run recovery for already-running processes, schema assertions, server-side Collections/History, and a fully automated end-to-end browser acceptance of the complete AI-to-run flow remain incomplete. Real GitHub/Google provider login has not been manually accepted end-to-end in this release; automated tests use mocked provider exchanges. See the Chinese sections above for setup, testing, report details, and limitations.

## License

Released under the **MIT License**. Copyright (c) 2026 S1eepEarly. See [LICENSE](LICENSE) for the full text.

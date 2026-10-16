# Identity & Access Contract

> **状态：已冻结的安全契约；Phase 8.5 Step 1–4 均已交付并验收完成。** 本文件是
> Phase 8.5 Step 1 的产出，冻结的是"调用方是谁、凭什么读一条资源、读不到时说什么"，
> 不是某个函数。**其中「等待架构评审」「不含任何实现」指的是本文件在 Step 1 时的
> 初始状态，现已不再适用**：Step 1–4 的实现已经交付并通过验收，见下方进度表与 §10；
> §6 的安全契约与 §8 的正式验收条件未因结项而改动。
>
> 上游决策（架构负责人已定，本文件不复议）：**MVP 采用 Guest-first 身份**、
> **凭证经 `X-Guest-Session` 请求头传递**、**Project 所有权是资源授权核心**、
> **默认拒绝且不允许旁路**。
>
> 本文件只描述规则。**Phase 8.5 的四个 Step 均已交付并验收完成**（见下方进度表与
> §10 验收记录）；§6 的安全契约、§8 的正式验收条件与「后续独立阶段 — User
> Authentication」的规定**均未因结项而改动**。
>
> **阅读提示**：§1～§5 是 Step 1 冻结时对当时实现的实测记录，保留原样以说明这些规则
> 的由来。其中若干处描述的是**当时**的状态，与今天的实现不同——凡此类内容均已就地标注
> 为历史快照，并给出当前状态；请勿再把它们当作现状。

## 实施进度（随每个 Step 更新）

| Step | 内容 | 状态 |
|---|---|---|
| **Step 1** Contract Freeze | 冻结调用方身份、资源归属规则与错误语义（本文件） | **已完成** —— 本文件即其产出（§6 安全契约、§8 实施路线） |
| **Step 2** Backend Guest Identity Foundation | token 哈希存储、expires_at NOT NULL、revoked_at、签发/校验/续期/撤销服务、CurrentGuestSessionDep 身份依赖、require_guest_project_access 所有权检查、migration a4c1e8b27d93 | **已完成**（backend/scripts/verify_guest_session.py） |
| **Step 3** Business API Authorization | 9 条业务路由接授权（含 SSE） | **已完成** —— 见 §10.1，本阶段验收 PASS |
| **Step 4** Frontend Guest Session Integration | 会话引导、头注入、SSE 改 fetch 流、Project 引导、401 文案 key | **已完成** —— 见 §10.2，本阶段验收 PASS |
| 后续 | User Authentication | 未开始（§6.7 定义的后续独立阶段，不属于 Phase 8.5 的验收范围） |

**历史快照，且已过时（Step 1 冻结时的事实，保留以便追溯）**：

> 9 条业务路由**仍未**要求身份；前端**仍未**发送凭证；
> X-Guest-Session 目前只被 DELETE /api/guest-sessions/current 这一条路由读取。
> 8.4 Step 2 的越权测量结论（跨用户 / 跨 Guest 读取仍返回 200）**未被修复**，也未被修改。

**当前状态（Phase 8.5 结项后）**：

* **所有业务路由都要求身份**：每个 operation 都依赖 `CurrentGuestSessionDep`；无凭证、
  伪造凭证、过期或已撤销凭证一律 **401 `guest-session-required`**，访问他人资源一律
  **404**，与「资源不存在」完全同形（§6.4）。跨用户 / 跨 Guest 读取返回 200 的缺口
  **已修复**：该结论现由 `verify_agent_audit_access.py` 与 SSE 授权矩阵实测为准。
* **前端全程携带凭证**：`services/http.ts` 是访问本服务的唯一出口，`X-Guest-Session`
  在那里单点注入（§10.2）；SSE 亦改为可带请求头的 fetch 流。
* `X-Guest-Session` 已不再只有一条路由读取——它现在是全服务的调用方身份来源。

---

## 0. 依据：本文件引用的真实代码与数据

| 依据 | 位置 |
|---|---|
| 应用装配（唯一注册点） | `backend/src/backend/app.py`（CORS + `runs.router` + `agent.router`） |
| 请求依赖 | `backend/src/backend/api/deps.py`（**只有** `SessionDep`） |
| 路由实现 | `backend/src/backend/api/routers/{agent,runs}.py` |
| 业务服务 | `backend/src/backend/services/{agent,agent_audit,runs,run_executor,agent_plan,agent_analyzer,llm}.py` |
| 错误封装 | `backend/src/backend/api/errors.py`、`backend/src/backend/schemas/common.py` |
| 模型 | `backend/src/backend/db/models/{user,project,agent,result}.py` |
| 实测行为 | `backend/scripts/verify_agent_audit_access.py`（8.4 Step 2：42 检查 / 6 测量 / 3 结论） |
| 数据库 | 第 3 节的 FK 链为 `information_schema` 实测导出（24 张 public 表） |
| 前端 | `frontend/src/services/http.ts`、`services/api/{agent,run}.ts`、`stores/project.ts`、`services/mock/projects.ts` |

**复查方式**（任何一条结论都可被机器复核）：

    # 路由清单（8 path / 9 operation）
    .\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'src');from backend.app import create_app;import json;print(json.dumps(sorted(create_app().openapi()['paths']),indent=1))"

    # 行为测量
    .\.venv\Scripts\python.exe scripts\verify_agent_audit_access.py

---

## 1. 现状：为什么现在没有"调用方身份"

### 1.1 三个事实

1. **HTTP 层没有任何身份依赖。** `api/deps.py` 只导出 `SessionDep`；全后端
   `grep "Depends("@ 只有这一处。9 个 operation 全部只按路径/查询参数里的**业务 id**
   寻址。
2. **Guest 凭证存在但无人读取。** `guest_sessions.session_token` 有唯一约束，
   但**没有任何业务代码读它**（全仓库仅 `db/models/user.py` 定义处出现）；
   `expires_at` / `last_seen_at` 同样**从未被读写**——没有过期检查、没有续期、
   没有撤销。
3. **前端对本服务不发任何凭证。** `services/http.ts` 的唯一 `fetch` 只带
   `Content-Type`；`services/api/run.ts` 的 SSE 用 `new EventSource(url)`，
   连自定义头都带不了。

### 1.2 为什么 `projects` 的 CHECK 约束不是授权

`ck_projects_owner_xor`（`user_id XOR guest_session_id`，实测存在于数据库）保证的是
**数据自洽**：一条 project 不会同时属于两个所有者、也不会没有所有者。它回答不了
"**这个请求**来自谁"。缺少调用方身份时，任何按 id 的读取都无法回答"你是否有权"——
把约束当授权，等于把"数据写得对"当成"访问控制做过了"。

### 1.3 现在的行为（8.4 Step 2 实测，未变）

* 4 位所有者（2 用户 + 2 Guest）各自的 task / audit 都能被自己读到 —— **200**；
* 跨用户、跨 Guest、Guest↔用户共 6 组越权读取，在**无凭证 / `X-Guest-Session` /
  `Authorization: Bearer` / `?guestSession=`** 四种形态下**全部 200**；
* task 路由与 audit 路由行为**完全一致**：缺口是全服务级的，不是审计特有的。

---

## 2. 完整 API 路由矩阵

### 2.1 实际注册的路由

> **历史快照（Step 1 冻结时的实测记录，请勿当作现状）。** 以下两行描述的是
> Phase 8.5 Step 1 当时的装配情况与路由规模，保留用于说明规则的由来。**当前实测值
> 见 §10.1**：`app.py` 装配 4 个 router（`agent` / `runs` / `guest_sessions` /
> `projects`），OpenAPI 为 **12 条 path / 14 个 operation**。

`app.py` 只装配两个 router；`api/routers/` 下也只有 `agent.py` 与 `runs.py`。
OpenAPI 实测：**8 个 path / 9 个 operation**。

| # | Method | URL | 前端是否调用 | 当前是否校验身份 |
|---|---|---|---|---|
| 1 | POST | `/api/projects/{project_id}/agent/tasks` | 是（`api/agent.ts:212`） | **否** |
| 2 | GET | `/api/agent/tasks/{task_id}` | 是（`api/agent.ts:223`） | **否** |
| 3 | GET | `/api/agent/tasks/{task_id}/audit` | **否**（8.4 Step 1 新增，运维/审查用） | **否** |
| 4 | POST | `/api/projects/{project_id}/runs` | 是（`api/run.ts:169`） | **否** |
| 5 | GET | `/api/projects/{project_id}/runs` | 是（`api/run.ts:177`） | **否** |
| 6 | GET | `/api/runs/{run_id}` | 是（`api/run.ts:187,197`） | **否** |
| 7 | POST | `/api/runs/{run_id}/cancel` | 是（`api/run.ts:205`） | **否** |
| 8 | GET | `/api/runs/{run_id}/events?fromSeq=` | 是（`api/run.ts:222`） | **否** |
| 9 | GET | `/api/runs/{run_id}/events/stream`（SSE） | 是（`api/run.ts:236`，`EventSource`） | **否** |

### 2.2 矩阵（10 列）

| # | 读/写的数据 | 需要身份 | 当前鉴权 | 资源→Project | 应检查的所有权 | 前端发凭证 | 推荐授权规则 |
|---|---|---|---|---|---|---|---|
| 1 | 写 `agent_tasks`、可能新建 `api_specs`、写 `test_plans/scenarios/steps/assertions`、写 `agent_task_audits`；读 `environments` | 是 | 无 | 路径即 `projects.public_id`；环境经 `environments.project_id` | project 存在 **且** `project.guest_session_id == caller.id` | 否 | Guest 且 project 属本人 → 允许；否则 **404**（不区分"不存在"与"不是你的"） |
| 2 | 读 `agent_tasks` + 计划树（`test_plans→scenarios→steps/assertions`） | 是 | 无 | `agent_tasks.project_id` | task → project → owner | 否 | 同上；非本人 → **404** |
| 3 | 读 `agent_task_audits`（understanding、PlanDesign、provider/model/prompt、usage、失败三元组） | 是 | 无 | `agent_task_audits.task_id → agent_tasks.project_id` | audit → task → project → owner | 否 | 同上；非本人 → **404** |
| 4 | 写 `test_runs` + `run_scenarios/steps/assertions/evidence`、`run_events`；可能新建 `api_specs`/`test_plans` | 是 | 无 | 路径 `projects.public_id`；payload 的 `planId` 亦指向 `test_plans.project_id` | project owner **且** plan 属于同一 project | 否 | Guest 且 project 属本人 → 允许；否则 **404**。**注意**：审批仍只信 payload（既有边界，本契约不改） |
| 5 | 读 `test_runs`（列表 + 聚合摘要） | 是 | 无 | 路径 `projects.public_id` | project → owner | 否 | 同上 |
| 6 | 读 `test_runs` + `run_scenarios/steps/assertions/evidence` | 是 | 无 | `test_runs.project_id` | run → project → owner | 否 | 同上；非本人 → **404** |
| 7 | 改 `test_runs.status`（取消）+ 事件 | 是 | 无 | `test_runs.project_id` | run → project → owner | 否 | 同上；非本人 → **404**（不允许取消别人的运行） |
| 8 | 读 `run_events` | 是 | 无 | `run_events.run_id → test_runs.project_id` | run → project → owner | 否 | 同上 |
| 9 | 读 `run_events`（SSE 流） | 是 | 无 | 同 #8 | 同 #8 | **否（且无法带）** | 同 #8。**`Last-Event-ID` 不是凭证**；`EventSource` 不能带头（见 §5.1 第 7 条） |

### 2.3 分类

> **历史快照（Step 1 冻结时）。** 下表与紧随其后的三处「9 条」写的都是当时的 operation
> 数量。**当前实际是 14 个 operation**（见 §10.1 的逐条授权矩阵）；下表的分类与授权
> 结论未变，只有计数是旧的。

| 分类 | 路由 |
|---|---|
| **公开（白名单，仅这些）** | 存活/健康类端点（**当前不存在**）；将来的 `POST /api/guest/sessions`（签发） |
| **Guest Session 签发** | **尚不存在** —— Step 2 新建 |
| **需要 Guest 身份的业务接口** | 上表 9 条全部 |
| **未来由登录用户访问** | 同样是这 9 条（用户认证是后续独立阶段；届时判定换成 `project.user_id == caller.id`） |
| **无法根据当前代码判断** | 无（9 条路由全部定位到实现与资源关系） |

**不能把"暂时没有认证依赖的路由"当作公开接口。** 当时 9 条路由都缺依赖，这是缺陷，
不是设计。**该缺陷已修复**：Phase 8.5 Step 3 给全部业务 operation 接上了授权（后续新增的
guest_sessions / projects operation 同样受保护），当前实测为 14 个 operation，见 §10.1。

### 2.4 调查范围内、但项目中不存在的接口

§三 列出的资源里，以下**没有 REST 路由**（有些连表都没有）。它们只能通过上表间接
访问，或目前完全不可访问：

| 资源 | 表 | 路由 |
|---|---|---|
| Projects | `projects` | **无**（不能创建、不能列举、不能读单个） |
| API Specs / Endpoints | `api_specs` / `api_endpoints` | **无**（spec 由任务创建流程隐式落库） |
| Environments / Variables / Auth | `environments` / `environment_variables` / `environment_auths` | **无** |
| Request Collections / Saved Requests / History | `request_collections` / `saved_requests` / `api_request_history` | **无** |
| Test Plans / Scenarios / Steps / Assertions | `test_plans` / `test_scenarios` / `test_steps` / `test_assertions` | **无独立路由**（经 #2 的响应读出） |
| Run Scenarios / Steps / Assertions / Evidence | `run_scenarios` / `run_steps` / `run_assertions` / `run_evidence` | **无独立路由**（经 #6 的响应读出） |
| Run Events | `run_events` | 经 #8（重放）与 #9（流） |
| Agent Task 列表 | `agent_tasks` | **无**（只有创建与按 id 读） |
| Agent Audit 列表 | `agent_task_audits` | **无**（只有按 task id 读） |

---

## 3. 资源 → Project 归属图

24 张 public 表全部可回溯到 `projects`（下表为 `information_schema` 实测 FK 链）。

### 3.1 直接挂在 `project_id`（一跳）

`agent_tasks` · `api_specs` · `api_request_history` · `environments` ·
`request_collections` · `saved_requests` · `test_plans` · `test_runs`

### 3.2 需要中间实体

| 资源 | 链路 |
|---|---|
| `agent_task_audits` | → `agent_tasks` → `projects` |
| `api_endpoints` | → `api_specs` → `projects` |
| `environment_variables` / `environment_auths` | → `environments` → `projects` |
| `test_scenarios` | → `test_plans` → `projects` |
| `test_steps` | → `test_scenarios` → `test_plans` → `projects`（另有 `endpoint_id` → `api_endpoints` → `api_specs` → `projects`） |
| `test_assertions` | → `test_scenarios` → `test_plans` → `projects`（`step_id` 恒 NULL） |
| `run_scenarios` | → `test_runs` → `projects` |
| `run_steps` | → `run_scenarios` → `test_runs` → `projects` |
| `run_assertions` | → `run_scenarios` / `run_steps` → `test_runs` → `projects` |
| `run_evidence` | → `test_runs` / `run_steps` → `projects` |
| `run_events` | → `test_runs` → `projects` |
| `saved_requests` | 同时有直接 `project_id`，也有 `collection_id`/`environment_id`（三者一致属实现约束） |

### 3.3 授权查询的唯一形态

对任何资源 R，实现时的归属判定必须是**一条从 R 出发的 join**，而不是"R 存在即可"：

    R ──(真实外键链)──> projects ──> guest_session_id == caller.id

* 不得只校验 audit 行、run 行、task 行**存在**；
* 不得因为 id 是合法 UUID 就跳过归属；
* 不得让任何资源"默认属于当前 Guest"。

---

## 4. GuestSession 模型审查

### 4.1 实测字段与约束

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | uuid | PK |
| session_token | varchar(255) | **已在 Step 2 移除**：明文列不再存在（migration a4c1e8b27d93） |
| token_hash | varchar(64) | **NOT NULL + UNIQUE**（Step 2 新增）：token 的 SHA-256 十六进制摘要；原始 token 只存在于签发响应与浏览器 |
| revoked_at | timestamptz | 可空（Step 2 新增）；非空 = 已撤销，撤销后不可续期、不可复活 |
| `expires_at` | timestamptz | **可空；NULL = 永不过期**；**没有任何代码读写** |
| `last_seen_at` | timestamptz | NOT NULL，默认 `now()`；**没有任何代码读写** |
| `created_at` | timestamptz | NOT NULL |

**没有** `revoked_at` / `status` / `user_agent` / `ip` 等字段。

### 4.2 十个问题的回答

| # | 问题 | 结论 |
|---|---|---|
| 1 | 是否有唯一 ID？ | **有**，uuid PK；`projects.guest_session_id` 指向它 |
| 2 | `session_token` 的类型/长度/约束？ | `varchar(255)`，NOT NULL，UNIQUE；**明文**；无额外校验（长度/字符集/熵） |
| 3 | 是否有过期、撤销、状态字段？ | **过期字段存在但无人执行**（NULL = 永不过期）；**撤销与状态字段不存在** → 撤销能力今天为 0 |
| 4 | 是否有签发接口？ | **没有**。`guest_sessions` 行目前只由验证脚本的夹具直接插入 |
| 5 | `projects.guest_session_id` 是否为真外键？ | **是**：`fk_projects_guest_session_id_guest_sessions`，`ON DELETE NO ACTION` |
| 6 | Task / Audit / Run 如何关联 Project？ | Task 直接 `project_id`；Audit 经 `task_id → agent_tasks.project_id`；Run 直接 `project_id`（另有 `plan_id`/`spec_id`/`environment_id` 指向同一 project） |
| 7 | 哪些资源必须经中间实体？ | 见 §3.2：endpoints→specs、variables/auths→environments、plan 子表→plans、run 子表/事件/证据→runs、audit→tasks |
| 8 | 对存量开发数据的兼容影响 | 现存只有 1 个 project（`prj_orders`），所有者是**夹具 token** `dev-guest-session`（`expires_at` 为 NULL）；前端 mock 的 `prj_payments` 在服务端**没有行**（今天调用即 404）。启用授权后：13 个验证脚本（不发凭证）全部 401；前端 7 个请求点 + SSE 全部 401。**`dev-guest-session` 是低熵、共享、写在测试夹具里的字符串，绝不能作为生产凭证保留**（这正是"对所有 Guest 默认返回同一个开发 token"的禁止项） |
| 9 | 是否需要 migration？ | **需要**（见 §7）：token 不明文入库、撤销能力缺失、`last_seen_at` 从未更新。三件事都要改表结构 |
| 10 | 可安全复用的身份/错误/依赖/归属函数？ | **身份类：没有**（无 `Depends`、无归属校验函数）。**可复用**：`AppError` + `register_exception_handlers` + `ERROR_RESPONSES`（错误封装）、`SessionDep`（会话）、`RUN_MESSAGE_KEYS`（**封闭**的可渲染 key 白名单）、`services/runs.py::_lookup_project` 的**存在性**查询模式（可扩展为归属查询，但不能当授权用） |

### 4.3 凭证安全存储的可行性

* 唯一约束在 `session_token` 上 → 改成存**哈希**同样可查（哈希值唯一），不需要额外索引策略；
* 建议形态（Step 2 定稿）：`token_hash`（sha-256，定长）+ 明文只在响应体出现一次 + 可选的短前缀用于日志识别；
* 现有列若保留，必须明确它是**历史列**还是**被重命名**；这属于 Step 2 的迁移设计，本契约只要求"原始 token 不以明文长期保存"。

---

## 5. 前端链路审查

### 5.1 九个问题的回答

| # | 问题 | 结论 |
|---|---|---|
| 1 | `projectId` 从哪来？ | `stores/project.ts`：`projects = ref(MOCK_PROJECTS)`（**前端静态数据**），`activeProjectId` 由 `usePersistedRef` 存 localStorage，默认 `MOCK_PROJECTS[0].id` = `prj_orders` |
| 2 | Project 来自 Mock / localStorage / 后端 / 静态？ | **Mock（前端静态）+ localStorage 记住选择**；**从不来自后端** |
| 3 | 是否存在服务端 Project 创建接口？ | **不存在**（也没有列表、读取接口）。服务端 `projects` 行今天只能由夹具/直接插库产生 |
| 4 | 任务的 Spec ID 是否对应后端真实 Spec？ | **能对应，但靠推导而不是查询**：前端发 `specDocument` + 自己算出的 `specId`；后端独立推导并校验（不一致即 400），需要时**自行落库** `api_specs`。没有"读 spec"接口 |
| 5 | 现有 HTTP 封装能否统一注入 `X-Guest-Session`？ | **能**：`services/http.ts` 是访问本服务的**唯一** `fetch` 出口，7 个调用点全经它。注入是一处改动 |
| 6 | 获取 Session 如何避免递归？ | 会话获取**不能**再走 `request()`。建议独立 `services/session.ts`：直接 `fetch` 调签发端点 + 模块级缓存（+ 单飞），契约要求**封装层不得因为缺凭证而递归调用自身** |
| 7 | SSE 的 `EventSource` 能否采用既定凭证传递？ | **不能**。`EventSource` 无法设置请求头，而契约要求在头里传 `X-Guest-Session`；query 传凭证被决策 B 禁止，cookie 是新机制（不在决策内）。**唯一可行方向：把流改成 fetch + 流式读取** —— 服务端已支持 `fromSeq` 与 `Last-Event-ID`，前端已有帧解析器（`parseFrame`），但需自行实现重连与 `Last-Event-ID` 续传（原本由 `EventSource` 自动完成） |
| 8 | 引入身份验证后哪些请求会立即失败？ | **全部**：7 个 `request()` 调用点 + SSE 流；另外 `prj_payments`（前端有、服务端无）即使带凭证也会 404 |
| 9 | 让当前 Agent 链路继续工作，最少还缺什么？ | ①**Guest Session 签发端点**；②**Project 创建/列举**（否则前端只能继续硬编码 id）；③前端**会话引导**；④**SSE 传输改造**；⑤一个**可渲染的 401 文案 key**（§6.4）；⑥测试夹具改为携带真实 token（仅测试面） |

### 5.2 两条不同的 HTTP 缝（不要混淆）

* `services/http.ts` —— 前端访问**本服务**（FastAPI）的缝，本次身份改造的对象；
* `services/transport.ts` —— "API Client"功能**代用户请求被测 API**的缝（mock → 将来的代理），
  它带的 `Authorization` 属于**被测系统的凭证**，与本服务的调用方身份无关。

改造范围只涉及前者。

---

## 6. 安全契约（冻结）

### 6.1 身份

* MVP 第一阶段**只有一种有效身份**：经服务端验证的 **Guest Session**。
* 其他身份（登录用户、API Key、服务间调用）**暂不实现**，也不得被"顺便"支持。
* `Authorization: Bearer …` **不构成**本服务的身份；未经验证的它必须被忽略（而不是被信任）。

### 6.2 凭证传递

* 头名：`X-Guest-Session: <opaque-session-token>`，**唯一**允许的传递方式。
* 禁止：query 参数传凭证；把 `task_id` / `run_id` / `project_id` 当作身份；cookie（除非未来重新决策）。
* 服务端必须**验证** token（存在、未过期、未撤销），而不是"格式看起来对就放行"。
* token 必须高熵、不可预测；**原始 token 不明文长期入库**（哈希存储）。
* 凭证**不得**出现在日志、错误信息、审计表与任何响应体里（与 8.4 Step 1 的审计秘密规则一致）。

### 6.3 Project 所有权规则（核心）

对于任一受保护资源 R：

    Authenticated Guest Session → R → …FK chain… → Project → Ownership Check

必须同时满足：①project 存在；②`projects.guest_session_id` == 已验证 Guest 的 id；
③该 project **不是** `user_id` 所有；④确认过程基于**真实外键链**（§3），不是"R 存在"。

不得以任何形式让资源"默认属于当前 Guest"，也不得跳过归属检查。

### 6.4 错误语义（默认拒绝）

| 情形 | 状态码 | code | messageKey | 说明 |
|---|---|---|---|---|
| 缺少凭证 / 凭证无效 / 已过期 / 已撤销 | **401** | `guest-session-required`（**唯一新增 code**） | `console.runs.errors.unauthorized`（**唯一新增 key**） | 不透露资源是否存在 |
| 凭证有效，但资源不属于本人 | **404** | 沿用既有 `task-not-found` / `run-not-found` 等 | 沿用既有 `console.runs.errors.notFound` | **与"不存在"完全同形**，不暴露他人资源是否存在 |
| 资源确实不存在 | **404** | 沿用既有语义 | 沿用既有 | 与上一条不可区分，这是刻意的 |
| 业务校验失败（既有） | 400 / 409 / 422 | 沿用既有 | 沿用既有 | 本契约不改 |

**两条实现约束**：

1. `messageKey` 必须在**前端字典**里存在，否则用户看到点号字符串（`locale.ts` 未命中时
   返回 key 本身）；后端还有一层封闭白名单 `RUN_MESSAGE_KEYS` —— 新增 key 必须**同时**进这两处。
2. **顺序约束（重要）**：一旦某条路由开始返回 401，**未携带凭证的前端会立刻失败**。因此
   "后端开始强制"与"前端开始携带凭证 + 字典补 key"必须**同批落地**（见 §8）。
   同一批里安全的顺序是：**先让前端带凭证（后端仍宽松）→ 再打开后端强制**。

### 6.5 公开路由（白名单）

只有以下路由允许匿名访问，且必须**逐条列出**：

| 路由 | 状态 |
|---|---|
| 存活/健康类端点 | **当前不存在**（将来若加，属公开） |
| `POST /api/guest/sessions`（签发 Guest 凭证） | **尚不存在**，Step 2 新建，公开 |
| `GET /api/guest/sessions/me`（可选：校验/续期） | **尚不存在**，Step 2 视需要决定 |

**其余一律需要 Guest 身份。** "这条路由还没加依赖"不构成公开理由。

### 6.6 明确禁止的旁路

* 默认接受任何 `task_id` / `run_id` / `project_id`；
* 把"未知资源"视为当前 Guest 所有；
* 对所有 Guest 返回同一个开发 token，或保留任何硬编码/共享凭证；
* 在生产路径保留"跳过鉴权"的开关或测试旁路（测试若要绕过，只能通过**真实签发的 token**）；
* 认为"前端不显示入口"就等于后端安全；
* 只在 audit 一条路由上加检查就宣称已隔离（task 响应里有整棵计划树，run 响应里有执行结果）。

### 6.7 登录用户边界（未来，本次只定义不实现）

* 用户认证（注册/登录/密码/JWT/OAuth）**不在本阶段**；`users` 表存在**不代表**已有用户身份能力。
* 未来接入保持同一形状：资源 → project，只是判定从 `guest_session_id` 换成 `user_id`；
  `ck_projects_owner_xor` 保证两者互斥，因此"用户读 Guest 项目"与"Guest 读用户项目"都必须是 404。
* 预留点：身份依赖应返回一个**联合的调用方**（例如 `Caller{kind: guest|user, id}`），
  使将来新增用户身份不必重写每条路由的授权判断。**本步骤不实现它**，只要求 Step 2 的接口形状不要堵死这条路。

---

## 7. 数据库影响

**需要 migration（Step 2 负责）**，理由与范围：

| 需求 | 现状 | 需要的结构变化 |
|---|---|---|
| 原始 token 不明文长期保存 | `session_token` 明文 varchar(255) | 新增 `token_hash`（定长、唯一）+ 决定 `session_token` 的去留（重命名或退役） |
| 撤销能力 | **没有**撤销字段 | 新增 `revoked_at`（或 `status`） |
| ~~过期/续期~~ | **已在 Step 2 实现**：expires_at 变为 NOT NULL，TTL 30 天，活跃续期（每 24 小时最多一次写入），last_seen_at 在续期时更新 | — |
| 存量夹具 token | `dev-guest-session` 明文、低熵、共享 | 迁移时必须**废弃**，不得升格为生产凭证 |

**不需要**的结构变化：`projects`（`guest_session_id` + XOR + FK 已就绪）、
`agent_tasks` / `agent_task_audits` / `test_*` / `run_*`（FK 链完整，归属可推导）。
**不得**为鉴权给每张表加冗余 `guest_session_id` 列。

---

## 8. 下一阶段实施路线（只给顺序与依赖，不实施）

### Step 2 — Backend Guest Identity Foundation

* 迁移：token 哈希、撤销、last_seen（§7）。
* 签发端点（公开）：产生高熵 token，**只在响应里返回一次**明文。
* 统一身份依赖：从 `X-Guest-Session` 解析 → 验证（存在/未过期/未撤销）→ 注入调用方；
  缺失/无效 → 401（唯一新 code + 新 key）。
* 统一归属检查：一个可复用的 **project 归属判定**（§3.3 的一条 join），供所有路由使用。
* 测试：真实签发 → 真实访问；伪造 / 过期 / 撤销 token 各一条。
* **依赖**：无（可独立开始）。**不碰**既有 9 条路由的授权（那是 Step 3）。

### Step 3 — Business API Authorization

* 按 §2.2 给 9 条 operation 接上授权（含 SSE）；错误语义按 §6.4。
* **依赖 Step 2**；**与 Step 4 强耦合**（见下）。
* 既有 13 个验证脚本必须改为携带真实 token（测试面改造，属本 Step 的一部分）。

### Step 4 — Frontend Guest Session Integration

* 会话引导（首次访问签发 + 缓存 + 单飞）、`http.ts` 注入 `X-Guest-Session`、
  **SSE 改 fetch 流 + `Last-Event-ID` 续传**、Project 创建/列举接入（§5.1 第 9 条）、
  字典补 401 key。
* **依赖 Step 2**。

### 后续独立阶段 — User Authentication

* 登录用户的身份验证与所有权授权（§6.7）。

### 必须向架构评审报告的排序事实

1. **Step 3 与 Step 4 不能分开上线**：只做 Step 3，前端（7 个请求点 + SSE）立刻全 401；
   只做 Step 4，凭证发出去却没人校验，安全性没有变化。建议把两者作为**一个发布单元**，
   或采用"先前端带凭证、后后端强制"的双开关窗口。
2. **Project 引导是缺失功能，不是鉴权细节**：前端项目 id 来自 mock，服务端没有创建/列举接口；
   若 Step 4 不能创建 project，"前端能用"就只能靠继续硬编码服务端预置 id。建议 Step 2 或 Step 4
   内含最小 Project 引导接口。
3. **SSE 传输改造是既定凭证传递方式的直接后果**（`EventSource` 无法带头），不是可选优化。
4. 审计接口在 Step 4 之前**没有前端调用方**，因此它可以先于前端被保护（不涉及 401 文案问题）；
   但这**不能**被当作"项目已安全"。

---

## 9. 待架构评审确认的问题

1. **过期策略**：Guest 默认 TTL 是多少？滑动续期还是固定？NULL（永不过期）是否允许出现在生产？
2. **撤销语义**：谁可以撤销（客户端登出？服务端？），撤销后 401 还是 404？
3. **Project 引导归属**：创建/列举 Project 的接口放 Step 2（身份地基）还是 Step 4（前端接入）？
4. **401 文案 key 的命名与归属**：放进 `console.runs.errors.*` 还是新建 `console.auth.errors.*` 命名空间？
5. **`Authorization` 头的处置**：明确忽略（推荐），还是遇到就 400（更严格但更容易误伤代理）？
6. **健康检查端点**是否需要（部署探针）；若需要，它是公开白名单的第一条。
7. **审计接口的前端可见性**：Step 4 是否把它接进 UI？这决定它是否需要 401 文案与错误映射。
8. **测试夹具的凭证**：验证脚本改为"真实签发"（每次测试多一次签发调用），
   还是允许测试直接插 `guest_sessions` 行并携带该 token（推荐：**直接插行**，因为签发端点本身也有测试）。

---

## 10. Phase 8.5 验收记录与已知局限

本节由结项文档任务追加，只记录**结果**。它不改写 §6 的安全契约、§8 的正式验收条件，
也不改变「后续独立阶段 — User Authentication」的定位：注册用户认证仍然不是 Phase 8.5
的一部分，**不构成**本阶段的阻塞项。

### 10.1 Step 3 — Business API Authorization（验收 PASS）

按 §8 的三项条款逐条交付：

| §8 条款 | 交付与证据 |
|---|---|
| 按 §2.2 给 9 条 operation 接上授权（含 SSE） | 每个 operation 依赖 `CurrentGuestSessionDep`；`guest_access.require_guest_project_access` / `require_guest_run_project` 沿真实外键链判定归属 |
| 错误语义按 §6.4 | 无凭证 / 伪造 / 过期 / 已撤销 → **401 `guest-session-required`**；他人资源 → **404**，与「不存在」同一代码路径、同一 `messageKey`，**不可区分** |
| 既有 13 个验证脚本改为携带真实 token | 14 个调用本服务的脚本均携带 `X-Guest-Session`；其中 13 个实测通过（`verify_guest_session.py` 本身是签发方，不属被改造对象） |

覆盖的访问控制面：**Guest → Project → Agent（task / audit）→ Run（create / list / detail / cancel）→ SSE 事件流**。
SSE 的拒绝在**响应开始之前**判定，因此无凭证或跨访客得到的是普通 JSON 错误信封，
而不是一个已开启的流（`api/routers/runs.py` 的 `stream_run_events`）。

**SSE `Last-Event-ID` 恢复契约**：前端在重连请求上发送 `Last-Event-ID: <最后已处理的 seq>`，
后端 `_stream_from_seq` 从 **`received + 1`** 继续、查询为 `seq >= from_seq`（inclusive），两端语义闭合，
既不重发也不跳过。该行为由运行时探针证实，并有回归测试保护（见 10.3）。

**回归保护（Task B12–B14）**：B12 解决了 15 项历史前端失败（测试与当前实现对齐，未放宽断言）；
B13 以只读审计确认 SSE 重连与会话头契约；B14 补充了「重连携带 `Last-Event-ID`」的前端断言与
「无凭证 / 未知凭证 / 跨 Guest」三类后端 SSE 授权断言。

### 10.2 Step 4 — Frontend Guest Session Integration（验收 PASS）

| §8 条款 | 实现位置 |
|---|---|
| 会话引导（首次访问签发 + 缓存 + 单飞） | `frontend/src/services/session.ts` —— `ensureSession()` 共享同一 in-flight promise；token 存 `localStorage['aiata.guestSession.token']`；签发走自己的 `fetch`，不递归经过 `request()` |
| `http.ts` 注入 `X-Guest-Session` | `frontend/src/services/http.ts` —— 全服务唯一出口，`:147` 单点注入；401 时清 token、重签并**恰好重试一次** |
| SSE 改 fetch 流 + `Last-Event-ID` 续传 | `frontend/src/services/api/run.ts` —— `response.body.getReader()` 自行解析 SSE 帧；`:349` 在已有收据时发送 `Last-Event-ID`；掉线重拨有上限 |
| Project 创建 / 列举接入（§5.1 第 9 条 ②） | 前端 `services/api/projects.ts` + `stores/project.ts`（空列表自动创建首个）+ `ProjectCreateDialog.vue` / `ProjectsView.vue`；后端 `api/routers/projects.py`（查询按 `guest_session_id` 过滤即授权，创建时 owner 取自已验证会话，请求体无 owner 字段） |
| 字典补 401 key | `console.runs.errors.unauthorized` 同时存在于 `locales/console/en-US.ts`、`zh-CN.ts`、`i18n/console-schema.ts` 与后端 `api/errors.py` 的 `RUN_MESSAGE_KEYS`（§6.4 约束 1） |

**依赖已满足**：Step 4 依赖 Step 2（身份地基、migration `a4c1e8b27d93`），并依赖 Step 3 的后端强制；
§8 排序事实 1 要求的「Step 3 与 Step 4 同批落地」在交付态上成立——后端强制与前端带凭证同时存在于工作区。

### 10.3 测试状态（区分正式验收、历史结果与未运行项）

| 项目 | 状态 | 说明 |
|---|---|---|
| 前端全量 Vitest | **22 个文件 / 300 项 / 0 失败** | 结项时实测 |
| TypeScript 检查（`tsc --noEmit -p tsconfig.app.json`） | **通过（EXIT=0）** | 结项时实测 |
| 后端九个自定义验证套件 | **833 项检查 / 0 失败** | **历史结果**：最后一次已知运行（Task B14）。B17 审计**未重跑**，因为这些脚本会插入 Guest Session 行且设计上不清理 |
| 真实浏览器端到端（Task B11） | **32/32 通过** | 真实 Chrome → 真实 FastAPI → 受控上游 → 真实前端显示的闭环；**不是** Step 3/4 的正式验收条件，作为凭证注入与 SSE 改造的运行时佐证 |
| 后端 pytest 全量 | **未运行** | 项目未安装 pytest，`backend/` 下无 pytest 用例。上表的数字来自**自定义验证脚本**，**不是** pytest 测试 |

> **不要把上表的历史数字读作刚刚重新运行的结果。** 只有前端全量、TypeScript 与
> 契约自身的静态陈述是在结项时重新核实的。

### 10.4 尚未关闭的事项（均非 Step 3 / Step 4 的正式验收条件）

以下各项**不得**被读作已完成，但同样**不得**被升级为 Phase 8.5 的阻塞项——
契约全文没有任何条款要求它们，§8 的正式验收条件也不包含它们。

1. **`ProjectSwitcher` 缺少自动化组件交互测试（证据局限）**。本项目的 Vitest 以 node 环境 +
   SSR 方式编译单文件组件（模块只有 `ssrRender`、没有 `render`），且未安装 DOM 测试环境或
   `@vue/test-utils`，因此无法在现有约束下可靠驱动组件交互；Task B16 因此未能交付测试。
   已人工在浏览器确认**基础项目切换**与 **Overview** 路由正常；
   **切换时是否保留 API Client 等子路由，尚未单独验证**。
2. **「13 个验证脚本」缺少名单（证据局限）**。§8 Step 3 提到「既有 13 个验证脚本」，
   但契约未逐一列明是哪 13 个。后续审计以「调用本服务且携带凭证」为口径推断该名单，
   数量吻合，但**名单本身是推断**而非原文。
3. **后端完整 pytest 套件未执行（未运行项）**。见 10.3。
4. **`guest_sessions` 计数未恢复（后续技术债）**。审计过程中该表由 40 增至 47——
   每个会插入自己身份行的验证脚本各留下一行，且设计上不删除。这些是空会话，
   未持有任何 Project；**未做清理，也不声称已恢复原数量**。
5. **纯注释类技术债（不影响行为）**：`services/api/run.ts` 的白名单注释写「八个」而集合有九项；
   `api/errors.py` 的 `RUN_MESSAGE_KEYS` 注释写「九个」而集合有十项。两处均只影响注释可读性。


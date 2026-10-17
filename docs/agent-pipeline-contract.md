# Agent Pipeline Contract（Phase 8.1 Step 1）

> **状态：契约冻结（Contract Freeze），未实现。**
> 本文只做两件事：把**当前真实代码里已经成立**的契约写成文字，把**本阶段确认的边界**固定下来。
> 本文**不实现** LangGraph、LLM、OpenAPI Parser、AI Test Plan Generator，也不改数据库。
>
> 架构方向（Prompt Engineering → Agent/LLM → Test Plan → Approve → Deterministic Run Executor → HTTP → Result/Evidence/Event）
> 已由项目负责人确认。**本文不重新设计总体架构**，只回答"这条链上各段的输入、输出、权限边界是什么"。
>
> 每一处断言都对应仓库里的真实代码，见 §0。
>
> **身份与访问控制另有一份契约**：`docs/identity-access-contract.md`（Phase 8.5 Step 1）。
> 本文只描述 Agent 链路的输入/输出/权限边界；"调用方是谁、凭什么读一条资源、读不到时说什么"
> 由那份契约冻结。两者冲突时以各自的范围为准：本文不改身份规则，那份契约不改 Agent 契约。

---

## 0. 依据：本文引用的真实代码

本文所有结论均来自下列文件（编号为撰写时核对的真实行号，随代码演进可能漂移）。

| 文件 | 核对内容 | 本文引用处 |
|---|---|---|
| `backend/src/backend/db/models/agent.py` | `AgentTask`(:59-100)、`TestPlan`(:103-182)、`TestScenario`(:185-221)、`TestStep`(:224-277)、`TestAssertion`(:280-325)；模块 docstring`:8-18`；断言 key 命名要求`:287-291` | §2 §3 §5 §6 |
| `backend/src/backend/db/models/project.py` | `ApiSpec`(:171-236)、`ApiEndpoint`(:238-279)、`Environment`(:281-348)、`EnvironmentVariable`(:350-383)、`EnvironmentAuth`(:385-429) | §3 §6 §9 |
| `backend/src/backend/db/models/result.py` | `TestRun`(:160-245)、`RunScenario`(:247-319)、`RunStep`(:321-408)、`RunAssertion`(:410-490)、`RunEvidence`(:492-543)、`RunEvent`(:545-607) | §6 §9 |
| `backend/src/backend/schemas/run.py` | 枚举`:91-99`、`PlanStep`:113-127、`PlanAssertion`:129-137、`PlanScenario`:139-150、`PlanPayload`:152-177、`RunCreateRequest`:179-207；回显规则`:5-19`；变量值不外传`:26-32` | §3 §5 §6 |
| `backend/src/backend/services/runs.py` | 计划物化 `_get_or_create_plan`:602-707、`_load_plan_tree`:710-758（复用不重写:616-619）、`_checkpoint_step_key`:766-780、运行快照 `_insert_run_tree`:783-861、spec 身份 `_get_or_create_spec`:527-576、审批闸门 `_check_approval`:375-386 | §4 §6 §8 §9 |
| `backend/src/backend/services/spec_identity.py` | slug 公式`:7`、`derive_spec_identity`:243-268、`probe_document`:190-217（服务端**没有** YAML 解析器） | §3 §5 |
| `backend/src/backend/services/run_executor.py` | 执行器真实消费面（Phase 7.3） | §9 |
| `backend/src/backend/api/routers/runs.py` | 全部 6 条路由：:189 :216 :249 :279 :308 :390 | §2 |
| `backend/src/backend/app.py` | 路由装配`:49-74`；docstring "four routes" 已过期（实为 6 条） | §2 |
| `backend/dosc/ai-api-testing-agent-database-schema-v1.md` | `agent_tasks`:757-791、`test_workflows` 延后:882-895、计划/结果关系:1625-1666、Agent 与手动边界:1669-1705、认证/变量边界:1709-1756 | §2 §3 §6 §10 |
| `frontend/src/services/agent.ts` | `AgentService` 边界`:78-97`、`createAgentService` 现状与 TODO`:99-105`、handoff 文档合成`:145-226` | §2 §4 §7 |
| `frontend/src/types/agent.ts` | `ApiSpec`:63-76、`ApiEndpoint`:82-104、`ApiAuthentication`:116-127、`ApiDependency`:152-161、`ApiRisk`:166-191、`AgentActionSummary`:214-221、`AnalysisProgress`:236-239、`ApiUnderstanding`:242-251、`TestStep`:268-281、`TestAssertion`:286-293、`TestScenario`:295-304、`TestPlan`:309-330、`PIPELINE_STEPS`:343-352 | §2 §3 §4 §5 |
| `frontend/src/stores/agent.ts` | 持久化键`:28-31`、理解不持久化`:41-46`、审批边界`:47-49`、`generatePlan`:283-306、`approvePlan`/`rejectPlan`:308-337 | §2 §4 §6 §7 |
| `frontend/src/services/mock/agent/*` | `index.ts` 服务组装:29-37,:44-88；`plan.ts` 步骤/断言 id 生成:73-153、场景构造:159-448、计划 id:519 | §5 §12 |
| `frontend/docs/phase-6-architecture.md` | D1（请求合成在后端，前端不得给 `TestStep` 加执行字段）`:19`；最小 create-run 载荷`:116-130` | §2 §7 §9 |
| `frontend/docs/phase-6.2-backend-rest-contract.md` | REST 总览`:100-110`、Run/Plan 关系`:575-588`、Project/Spec/Plan CRUD 裁决`:708-746`、暂不做清单`:767-784` | §2 §9 §10 |

**核对结论：现有代码与"Prompt Engineering → Agent → Plan → Approve → Executor"这条目标链在结构上相容，但今天只实现了后两段（Approve 的 UI 侧 + Executor）。前三段（Spec 理解、Test Design、计划持久化）目前整体运行在浏览器里，且完全没有 Prompt Engineering 资产。**

---

## 1. Purpose

本文冻结 **Agent Pipeline Contract**，即：

> 一份 OpenAPI / API Spec 从进入系统到被 Deterministic Executor 执行之前，
> **谁读什么、谁产出什么、产出必须长什么样、谁不许做什么**。

它要解决的问题只有一个：让"AI 生成的测试设计"成为**执行器可以直接消费的结构化对象**，而不是自然语言。

明确不在本文范围：

- 不实现 Agent Runtime（LangGraph / LLM 客户端 / 图状态机）
- 不实现 OpenAPI Parser 的服务端版本（今天解析在前端）
- 不实现 AI Test Plan Generator 的服务端版本
- 不改数据库、不改 Run REST / Run Event / SSE / `run_executor.py`
- 不新增 Prompt / Skill / Subagent

本文是 **Phase 8.2 及以后的输入**：后续每一步实现都必须能在这份契约里找到落点。

---

## 2. Current Architecture

### 2.1 今天真实存在的三段

```text
[1] 浏览器（真的在跑）
    OpenAPI 文本 ──parseSpec──► ApiSpec + ApiEndpoint[] + ApiResource[] + ApiAuthentication
                 ──analyze───► ApiUnderstanding（endpoints/resources/auth/dependencies/risks/findings）
                 ──generatePlan──► TestPlan（status 只能是 draft）
                 ──approvePlan（人类点击）──► status = approved
    持久化：localStorage（aiata.console.agentSpecs / aiata.console.agentPlans）

[2] 后端（真的在跑）
    POST /api/projects/{projectId}/runs
      body = { projectId, planId, plan（整份计划）, specId, specDocument, environmentId, variables, baseUrl }
      ├─ _check_approval：payload.plan.status !== 'approved' → 409 not-approved
      ├─ _check_identity / _check_spec_identity：五处身份必须一致；specId 的 slug 会被重算复核
      ├─ _get_or_create_spec：按 (project_id, slug) 复用或新建 api_specs
      ├─ _get_or_create_plan：把 payload 的整棵计划树物化进 test_plans/test_scenarios/test_steps/test_assertions
      ├─ _insert_run_tree：把整棵计划树快照成 run_scenarios/run_steps/run_assertions
      └─ create_run 提交后 schedule_run → Deterministic Executor

[3] 执行器（真的在跑，Phase 7.3）
    queued → running → 逐场景/逐步骤 → HTTP → 断言 → 结果 → 事件 → passed/failed
```

关键事实（全部可核验）：

1. **服务端现在会生成计划，但 run 侧仍然不查表。** Phase 8.2 Step 2 之前，计划只能来自浏览器（`schemas/run.py:105-107`：*"plans are generated in the browser today"*）。现在 `POST /api/projects/{projectId}/agent/tasks` 在服务端跑完整条确定性管线并把结果落库（`services/agent_plan.py` + `services/agent.py`）。**`create_run` 的输入契约不变**：run 仍然带着整份 `plan` 进来。
2. **后端当前有 4 个 router 模块、13 条 API 路径、15 个 OpenAPI operation。**（本节写于 Phase 8.2，当时的数字是「9 条路由：run 6 条 + agent 3 条」；Phase 8.5 Step 2/4 之后又装入了 `guest_sessions.router` 与 `projects.router`，因此这里更新为当前实测值——`create_app()` 生成的 OpenAPI 实测：routers 4、paths 13、operations 15，构成是 runs 6 + agent 4 + guest_sessions 2 + projects 3。**新增的 5 个 operation 不属于本契约的 Agent 管线范围。**）`app.py` 装配 `runs.router`、`agent.router`、`guest_sessions.router` 与 `projects.router`。Agent 侧是 `POST /api/projects/{project_id}/agent/tasks`、`GET /api/projects/{project_id}/plans`（C31）、`GET /api/agent/tasks/{task_id}`（Phase 8.2 Step 2）与 `GET /api/agent/tasks/{task_id}/audit`（Phase 8.4 Step 1）；集合挂项目、条目由自己的 id 寻址，与 run 同一条地址规则。仍然没有 `/api/plans/*`、`/api/specs/*`，也没有 `.../tasks/{id}/run`。
3. **`agent_tasks` 已被服务端真正使用。** 模型是 `db/models/agent.py:59-100`，解引用面是 `db/models/__init__.py` 的导出与 `db/models/project.py:142/224/336` 三条反向关系。Phase 8.2 Step 2 起 `services/agent.py` 为每次任务写一行（`pending → analyzing → completed/failed`），并把结果计划的 `test_plans.agent_task_id` 指回它。**前端曾经零引用，Phase 8.2 Step 3 起已接入**：`createAgentService()` 默认走服务端 HTTP 实现（见 §4.1）；`frontend/src` 中如今只剩一处提及 `agent_tasks.prompt` 的文案注释（`frontend/src/i18n/console-schema.ts:378`），不再有对该表的读写。
4. **`api_endpoints` 从未物化。** `runs.py:672-676`：*"No api_endpoints are materialised, so there is nothing for this to point at."* 数据库 `api_endpoints` = 0 行。理解结果（endpoints/dependencies/risks）**没有任何持久化位置**，它是文档的纯函数，每次加载重算（`stores/agent.ts:41-46`）。
5. **审批是客户端写 localStorage。** `stores/agent.ts:318-330`。后端只复核 payload 里的 `status` 字符串（`runs.py:375-386`），**审批的权威在客户端**。
6. **`TestStep` 不携带执行字段。** `db/models/agent.py:8-12`：*"`test_steps` describes a *test-plan operation*, not an HTTP request. It carries `endpoint_id` and a `config` blob; it does not carry headers, a body or an auth scheme."* 与前端 D1（`frontend/docs/phase-6-architecture.md:19`）一致。
7. **执行器只读运行快照。** `run_executor.py` 的全部输入是 `run_scenarios`/`run_steps`/`run_assertions` + `test_runs`（base_url、variables）+ 环境变量与认证。唯一一条读计划侧的例外：`extract` 步骤经 `run_steps.source_step_id` 读 `test_steps.produces`（原因见 §6.3）。
8. **快照里的 method/path 以 payload 为准，缺失时回落到 `test_steps.config`。** Phase 8.2 Step 1 之前它只能来自 payload（`PlanStep.method` / `PlanStep.path` 直抄），而 `test_steps` 落库时 `config={}`。现在 `request` 步骤的目标会写进 `test_steps.config`（`{"method", "path"}`），创建 run 时若 payload 未给出就从计划侧恢复——见 §6.3 G1（**已实施**）。`endpoint_id` 仍恒为 NULL。

### 2.2 目标架构与现状的差距（Contract Gap）

| 目标链的一段 | 今天的实现位置 | 是否有服务端契约 | 缺口 |
|---|---|---|---|
| OpenAPI / API Spec | 浏览器 `mock/agent/parse.ts`；服务端 `services/agent_plan.py`（**JSON only**） | ✅（部分） | 服务端只解析 JSON；YAML 仍只能在前端解析（见 §10 D5） |
| AI Understanding | 浏览器 `mock/agent/analyze.ts`；服务端 **DeepSeek analyze**（8.3 Step 1，`services/agent_analyzer.py` + `services/llm.py`），确定性规则 `agent_plan.analyze` 仍在（`AGENT_ANALYZER=deterministic`） | ✅（部分） | 仍不持久化；模型只产出 understanding，不参与 generate_plan；见 §7.3 |
| Test Plan Draft | 浏览器 `mock/agent/plan.ts`；服务端**两种实现**：规则引擎 `agent_plan.generate_plan`，或 **DeepSeek 设计 + 运行时补全 key**（8.3 Step 2，`services/agent_analyzer.py` 的 `generate_plan`，`AGENT_PLANNER` 选择，默认 deepseek） | ✅ | 两种实现的产出都必须是同一份 §5 契约；模型不产出 id/index/method/path，由运行时按 §5.3 的公式生成 |
| User Approve | 浏览器 store + localStorage | ⚠️ 仅 payload 复核 | 无服务端权威、无审批接口、无审计（**8.2 Step 3 后仍未改变**：审批只改写本地那份计划对象） |
| Deterministic Run Executor | 后端 `run_executor.py`（已完成） | ✅ | 无 |

**一句话：Phase 8.3 Step 1 之后，第三行（AI Understanding）在服务端由 **DeepSeek** 产出，第一行（parse）与第三行之后的每一段（generate_plan / validate / persist）仍是确定性代码；第四行（审批权威）仍在前端；第五行（执行器）一个字未改，仍然没有任何模型调用。**

---

## 3. Input Contract

### 3.1 输入真源：`agent_tasks` 的四个业务列

`agent_tasks` 是数据库里唯一为"一次 Agent 任务"预留的行，它的列就是输入契约的骨架：

| 列 | 类型 | 可空 | 语义（`dosc/...-v1.md:771-780`） | 契约含义 |
|---|---|---|---|---|
| `project_id` | UUID | 否 | 所属项目 | 租户与隔离边界 |
| `spec_id` | UUID | 否 | 使用的 API Spec | 任务锚定在**它实际读过的那份文档**（`NO ACTION` 外键） |
| `environment_id` | UUID | 是 | 目标环境 | 决定 base_url、变量、认证的来源 |
| `prompt` | TEXT | 否 | 用户给 Agent 的任务要求（例："分析订单系统，重点测试支付失败、重复支付和鉴权异常。"） | 唯一的人类意图入口 |
| `status` | VARCHAR(30) | 否 | `pending / analyzing / completed / failed` | 任务生命周期，默认 `pending` |

由此得到 **`AgentTaskInput`（本阶段冻结）**：

```jsonc
{
  "projectId": "prj_orders",            // agent_tasks.project_id
  "specId": "spec_orders_platform_api_pkqkbr",  // agent_tasks.spec_id（= "spec_" + slug，见 §5.3）
  "specDocument": "<OpenAPI/Swagger 原文>",      // 解析的唯一依据；服务端今天只在 create-run 里见过它
  "environmentId": "env_orders_staging",         // agent_tasks.environment_id，可空
  "prompt": "分析订单系统，重点测试支付失败、重复支付和鉴权异常。",  // agent_tasks.prompt
  "variables": { "<name>": "<value>" }           // 可选：环境变量的运行期覆盖，仅传名与值，不落库
}
```

**输入不变量：**

- **I1 文档原文是唯一的结构真源。** `ApiSpec`（前端类型 `types/agent.ts:63-76`）不含 schema，派生出的 endpoints 故意不持久化（`stores/agent.ts:96-104`：*"the metadata in `ApiSpec` carries no schemas"*）。因此**任何"理解"步骤都必须拿到文档原文**，不能只给 `specId`。
- **I2 `specId` 是可重算的，不是权威。** `spec_identity.py:7`：`slug = f"{slugify(title or filename)}_{hashString(content)}"`；服务端会用文档重算并与 `specId` 比对（`verified` 标志，`:228-241`）。**如果 `prompt` 里指定的 spec 与文档不一致，以文档为准，并把差异报告出来。**
- **I3 `environmentId` 只影响"跑在哪"，不影响"测什么"。** 环境提供 base_url / 变量 / 认证（`dosc:1709-1756`）。计划本身不得内嵌环境相关的值。
- **I4 变量值不进入任何持久化对象。** `schemas/run.py:26-32`：`test_runs` 只存 `variable_keys`（名字），值只在请求里出现一次。
- **I5 `prompt` 是自然语言，但它的产物必须是结构化对象。** 见 §5：`prompt` 不得成为"直接执行"的指令通道。

### 3.2 今天实际走的输入：`RunCreateRequest`

Phase 8.1 之前，Agent 产物进入系统的**唯一**通道是 create-run：

| 字段 | 别名 | 落点 |
|---|---|---|
| `project_id` | `projectId` | path 与 body 两处，必须一致（`_check_identity`） |
| `plan_id` | `planId` | `test_plans.public_id` |
| `plan` | `plan` | 整棵计划树（`PlanPayload`） |
| `spec_id` | `specId` | 与文档重算结果比对后解析成 `api_specs` 行 |
| `spec_document` | `specDocument` | `api_specs.content` |
| `environment_id` | `environmentId` | `test_runs.environment_id` |
| `variables` | `variables` | 运行期变量（值不落库） |
| `base_url` | `baseUrl` | `test_runs.base_url` |

契约立场（与 `phase-6.2-backend-rest-contract.md:736` 一致）：**这是"一次性把计划与文档一起交出去"的通道，本轮保持不变。** Phase 8.x 若把计划生成搬到服务端，`plan` 可以退化为 `planId` 引用，但那是一次独立重构，不由本文顺手改。

---

## 4. Agent Processing Contract

### 4.1 处理边界就是既有 `AgentService` 的四个操作

前端已经把 Agent 的能力边界写成了一个接口（`services/agent.ts:78-97`），**Phase 8.x 的服务端实现必须保持这四个操作的语义**：

| # | 操作 | 输入 | 输出 | LLM 是否必需 | 确定性要求 |
|---|---|---|---|---|---|
| 1 | `parseSpec` | `SpecInput{projectId, filename, content, source}` | `ParsedSpec{spec, endpoints, resources, authentication}` | **否**（纯结构解析） | 同一文本 → 逐字节相同的输出 |
| 2 | `analyze` | `ParsedSpec` + 进度回调 | `ApiUnderstanding` | 是（可先用规则实现） | 同一文档 → 同一理解；不得依赖时间/随机 |
| 3 | `generatePlan` | `ApiUnderstanding` + `ApiSpec` + `PlanSource` | `TestPlan`，**status 恒为 `draft`** | 是 | 同上；且必须通过与 §5 的字段契约校验 |
| 4 | （人类）approve / reject | `TestPlan.id` + （拒绝时）理由 | `status: approved / rejected` | 否 | **不是 Agent 的能力**，见 §8 |

**Phase 8.2 Step 3 起前端已连上服务端。** `createAgentService()` 默认返回 `createHttpAgentService()`（仅 `VITE_AGENT_SERVICE=mock` 或测试环境走 mock），**接口形状也随之从三个操作变成一个任务**：服务端在一次请求里跑完 parse → analyze → generate → validate → persist，前端拿回任务、计划树与（只有该次响应携带的）understanding。`services/agent_plan.py` 与 `services/agent.py` 是服务端那一半；`mock/agent/**` 仍在，作为测试/开发用的等价实现，并镜像服务端的两条规则（一个文档一份计划、未知任务 id 报错）。

### 4.2 `analyze` 的输出形状（理解契约）

`ApiUnderstanding`（`types/agent.ts:242-251`）的每一部分都必须能追溯到文档：

| 字段 | 内容 | 生成规则（现状，来自 `mock/agent/analyze.ts`） |
|---|---|---|
| `endpoints` | `ApiEndpoint[]` | 每个 operation 一条：`id` / `method` / `path` / `resourceId` / `summary` / `requiresAuth` / `securityDeclared` / `securitySchemes` / `securityOptional` / `pathParams` / `requiredBodyProps` / `constrainedBodyProps` / `responseStatuses` / `responseProps` |
| `resources` | `ApiResource[]` | 按 tag（无 tag 则路径首段）分组，`endpointIds` 指向 endpoints |
| `authentication` | `ApiAuthentication` | `scheme ∈ {none, bearer, apiKey, basic, oauth2}`；`tokenSourceEndpointId` 指登录端点；`tokenField` 指令牌所在响应字段 |
| `dependencies` | `ApiDependency[]` | `kind ∈ {token, identity, reference, lifecycle, sub-resource}`，`binding` 是跨边携带的值名 |
| `risks` | `ApiRisk[]` | `category ∈ {authentication, dependency, validation, negative-coverage, idempotency, authorization}`，`level ∈ {low, medium, high}` |
| `findings` | `AgentActionSummary[]` | 只写**决策**（`decisionSummary`），不写推理过程；`result ∈ {succeeded, failed, skipped}` |
| `analyzedAt` | ISO 时间戳 | **无表可落**（见 §6.3） |

**理解是中间产物，不是交付物。** 它必须能被重新计算（今天正是如此：两边都不持久化），因此它**不得**承载任何"只有这一次才有"的信息（例如随机生成的 id、运行期值）。`dependencies[].binding` 是**变量名**，不是变量值。

**服务端实现的取舍（Phase 8.2 Step 2）：** 只解析 JSON；依赖只推导 `token`（登录端点 → 受保护端点）与 `lifecycle`（创建 → 子项）；风险只推导 `authentication` / `dependency` / `negative-coverage` 三类；`findings` 与 risks 的文案用字面量（`{text}`），因为它们是任务诊断而不是控制台渲染的句子。生成器的**文案 key** 则必须是前端字典里已有的（见 §5.4 P1），由校验器的 `message-key` 规则强制。

### 4.3 阶段与 `agent_tasks.status` 的对应

`dosc:778` 定义了四个状态，本契约把它固定为**唯一合法取值**（数据库没有 CHECK 约束，靠服务层保证）：

```text
pending   ──► analyzing ──► completed
                   │
                   └──────► failed
```

| 状态 | 含义 | 何时写 |
|---|---|---|
| `pending` | 任务已创建，尚未开始 | 收到 `AgentTaskInput` 并落 `agent_tasks` 行时 |
| `analyzing` | 正在理解 / 设计 | 进入 `analyze` 之前 |
| `completed` | 已产出计划草稿（`test_plans` 行已写，`agent_task_id` 指向本任务） | `generatePlan` 通过 §5 校验并落库之后 |
| `failed` | 未产出计划 | 解析失败 / 校验失败 / 计划冲突；**原因随创建响应返回**（错误信封或 `failure`），任务行本身无列可存（§13 G4）：`GET` 一个失败任务只答 `status` |

**禁止**：`completed` 不等于 `approved`。计划状态与任务状态是两个正交的词表（`draft/in_review/approved/rejected` vs `pending/analyzing/completed/failed`），不得互相赋值。


### 4.4 OpenAPI security facts（C32）

`ApiEndpoint` 保留有效 security 声明的三个事实，同时保留原有的 `requiresAuth` 兼容字段：

| 字段 | 含义 |
|---|---|
| `securityDeclared` | operation 或 document 根部确实声明了 `security`；operation 的空列表也算声明 |
| `securitySchemes` | 有效 security requirement 中出现的 scheme 名，按文档顺序去重 |
| `securityOptional` | 任一 requirement 是空对象 `{}`，表示允许匿名访问 |

规则：

- operation 级 `security` 覆盖 document 根部，`security: []` 是**显式 public**，不是“继承 root”。
- `requiresAuth=true` 只在至少一个非空 requirement 且没有匿名 `{}` 时成立；仅有 `{}` 或 `[]` 时为 false。
- 完全没有 security 声明时 `securityDeclared=false`，与显式 public 的 `securityDeclared=true` 区分。
- 这些字段进入 `specification_facts` 与 `understanding_facts`，模型必须原样回显；`domain_issues` 比较它们，不能由模型重写。
- 确定性 Planner 只在 token source 与**受保护的** identity endpoint 同时存在时生成 authentication scenario；public、optional 或未声明的 identity 不生成该场景。普通 public endpoint 仍由 smoke 覆盖，不因变量存在而臆造认证场景。

---

## 5. Output Contract

### 5.1 输出形状

Agent 的唯一交付物是一棵 **TestPlan 树**，前后端各有一份同名镜像，二者逐字段对应：

```text
TestPlan                 ←→ backend PlanPayload（schemas/run.py:152-177）
├── id, projectId, specId, name, goal, riskLevel, status, source, generatedAt
├── approvedAt, rejectedAt, rejectionReason
└── scenarios[]          ←→ PlanScenario（:139-150）
    ├── id, index, name, description, riskLevel, expected
    ├── steps[]          ←→ PlanStep（:113-127）
    │   └── id, index, kind, description, endpointId, method, path, produces, consumes
    └── assertions[]     ←→ PlanAssertion（:129-137）
        └── id, kind, target, expected, description
```

### 5.2 字段级契约

**TestPlan**

| 字段 | 类型 | 约束 | 落点 |
|---|---|---|---|
| `id` | string | `plan_<spec.slug>`（`mock/agent/plan.ts:519`）；项目内唯一 | `test_plans.public_id` |
| `projectId` | string | 必须等于输入 | 校验用，另存 `test_plans.project_id` |
| `specId` | string | 必须是 `spec_` + 文档 slug | 解析为 `test_plans.spec_id` |
| `name` | `LocalizedText` | 应用自撰 → i18n key；用户改名 → 字面量 | `test_plans.name` (JSONB) |
| `goal` | `LocalizedText` | — | `test_plans.description`（唯一散文列） |
| `riskLevel` | `low\|medium\|high` | — | `test_plans.risk_level` |
| `status` | `draft\|in_review\|approved\|rejected` | **Agent 只能产出 `draft`** | `test_plans.status` |
| `source` | `generated\|handoff` | — | `test_plans.source` |
| `generatedAt` | ISO 时间戳 | **无列可落**（`schemas/run.py:155-159`），仅校验格式 | 丢弃 |
| `version` / `isCurrent` / `runCount` | `test_plans.version` / 该文档最高 version / 指向该计划的 `test_runs` 数 | C31；旧计划 `version=1` |
| `approvedAt`/`rejectedAt`/`rejectionReason` | — | 由人类审批写入，不由 Agent 写 | 同名列 |

**TestScenario**

| 字段 | 约束 | 落点 |
|---|---|---|
| `id` | `scenario_key`，**plan 内唯一** | `test_scenarios.scenario_key`（`UNIQUE(plan_id, scenario_key)`） |
| `index` | 场景内执行顺序，**plan 内稠密唯一** | `sort_order` |
| `name` / `description` / `expected` | `LocalizedText` | 三个 JSONB 列 |
| `riskLevel` | `low\|medium\|high` | `risk_level` |
| `steps` / `assertions` | 见下 | 子表 |

**TestStep**

| 字段 | 约束 | 落点 |
|---|---|---|
| `id` | `step_key`，**scenario 内唯一** | `test_steps.step_key`（`UNIQUE(scenario_id, step_key)`） |
| `index` | 场景内执行顺序，**scenario 内稠密唯一** | `sort_order` |
| `kind` | `request\|extract\|assert` | `step_type` |
| `description` | `LocalizedText`（`test_steps` 没有 `name`，只有 `description`） | `description` JSONB |
| `endpointId` | 前端自己的端点 id（如 `ep_post_api_orders`），**不是 UUID**；今天不落库 | `endpoint_id` = NULL |
| `method` | `GET\|POST\|PUT\|PATCH\|DELETE`；`request` 步骤必需，其余为 `null` | `test_steps.config.method`（**仅 `request` 步骤**），再由快照读回 `run_steps.method` |
| `path` | 文档路径原文，可含 `{{var}}` | `test_steps.config.path`（**仅 `request` 步骤**），再由快照读回 `run_steps.path` |
| `produces` | 变量名（`extract` 步骤必需） | `test_steps.produces`（**执行器唯一的计划侧读取**） |
| `consumes` | 变量名数组 | `test_steps.consumes` (JSONB) |

**TestAssertion**

| 字段 | 约束 | 落点 |
|---|---|---|
| `id` | `assertion_key`，**scenario 内唯一**（`UNIQUE(scenario_id, assertion_key)`） | `assertion_key` |
| `kind` | `status\|field\|schema\|header` | `assertion_type` |
| `target` | 带点路径：`status` / `body.<path>` / `header.<Name>`（`schemas/run.py:134`） | `target` (VARCHAR(255)) |
| `expected` | **字符串**（`PlanAssertion.expected: str`，Pydantic 不会把 int 强转） | `expected_value` (JSONB，实际存 JSON 字符串) |
| `description` | `LocalizedText` | `description` JSONB |
| `stepId` | 可选。指向本 scenario 内一个 `assert` 步骤；计划生成时按**真实 endpoint 关联**分组产生（C30-M）。旧计划没有该字段 | `test_assertions.step_id`；快照写入 `run_assertions.run_step_id`。缺失时回退到 `_checkpoint_step_key` |

**`expected` 的两种语义（C30-K / C30-M）：** 普通断言仍把 `expected` 当字符串做相等比较；
`field` 断言在 `expected == "present"` 时表示"该字段必须存在"，只要路径解析成功就通过，
实际值（包括 JSON `null`、`""`、`0`、`false`）记录为 `actual`。这是为兼容旧计划保留的哨兵值，
不需要数据库迁移；缺失字段或缺失父对象仍然失败。详细布局见 §6.4。

### 5.3 id 与 key 的生成契约（最重要的一节）

`step_key` / `assertion_key` / `scenario_key` **不是内部主键，而是对外契约本身**：

- 前端按 **id 相等**匹配行，没有任何位置回退（`schemas/run.py:5-19`；`utils/runState.ts` 的匹配逻辑）。
- 后端回显的是**计划里的 key**，不是行 UUID（`RunStepResponse.id` ← `run_steps.step_key`，`RunAssertionResponse.id` ← `run_assertions.assertion_key`）。
- 事件里的 `stepId` / `assertionId` 用的也是同一套 key（`run_executor.py` 写事件时用 `step_key` / `assertion_key`）。

⇒ **AI 生成的 key 一旦落库就不可变；任何"服务端重新生成 id"的做法都会让详情页静默失去更新。**（`phase-6.2-backend-rest-contract.md:827` 已把这条写成后端建议第 5 条。）

现状的 key 形状（可复用，不必重新发明）：

| 对象 | 现状形状 | 出处 |
|---|---|---|
| `specId` | `spec_` + `slug`，`slug = slugify(title) + '_' + hash(content)` | `spec_identity.py:7` |
| `plan.id` | v1 `plan_{spec.slug}`；n≥2 `plan_{spec.slug}_v{n}` | `test_plans.public_id` / `version`；C31 |
| `scenario.id` | `scenario_authentication` / `scenario_lifecycle_${endpoint.id}` / `scenario_dependent_${endpoint.id}` / `scenario_negative_${endpoint.id}` / `scenario_smoke_${endpoint.id}` | `plan.ts:176/220/284/389/420` |
| `request` 步骤 | `${endpoint.id}__${index}` | `plan.ts:82` |
| `extract` 步骤 | `${endpoint.id}__extract_${variable}` | `plan.ts:101` |
| `assert` 步骤 | `assert__${index}` | `plan.ts:116` |
| `assertion.id` | `${endpoint.id}__status` 等 | `plan.ts:146` |
| `endpoint.id` | `ep_${method}_${slugify(path)}` | `mock/agent/parse.ts`（`createEndpointId`） |

**命名硬约束（来自模型层，`db/models/agent.py:287-291`）：**
`assertion_key` 在**整个 scenario 内唯一**，而不是每个步骤内唯一。因此生成器**必须给 key 加命名空间**（推荐 `{step_key}.{name}`），否则两个步骤都产出 `status_200` 时第二次插入就是 `UniqueViolation`。现状的 `${endpoint.id}__status` 天然满足这条（因为它带端点前缀），但**新增断言种类时必须显式检查**。

### 5.4 `LocalizedText` 规则

`LocalizedText = { key, params? } | { text }`（`types/agent.ts:31-41`），落库为 JSONB，**不能用 VARCHAR**（`dosc:1793-1816`）。

| 来源 | 形态 | 理由 |
|---|---|---|
| 应用自撰（生成器的固定文案） | `{ key: 'console.aiTest.…', params: {...} }` | key **必须已存在于** `frontend/src/locales/console/{en-US,zh-CN}.ts`，否则用户看到点号字符串 |
| 来自文档 / 模型自由文本 / 用户改名 | `{ text: "…" }` | 无法翻译的东西不许伪装成 key |

**约束 P1**：Agent 产出的每一个 `key` 都必须是字典里已存在的 key。今天没有任何服务端字典，所以**服务端生成的文案只能走 `{ text }`，或复用已存在的 3 个 evidence key**（`console.runs.evidence.endpoint/extracted/checked`）。这条决定了 Phase 8.x 若要服务端生成计划，必须先解决"文案从哪来"。

---

### 5.5 读回形状（Phase 8.2 Step 3 的最小 Contract 变化）

**变化**：任务响应里的 `plan` 从"计数摘要"（`scenarios` / `steps` / `assertions` 三个整数）变成**完整计划树**，并新增 `understanding`（仅创建响应携带）。

**为什么必须变**：Agent Lab 的 review 界面逐行渲染 scenarios / steps / assertions。计数摘要让它无从渲染，前端只剩下两条路——自己造行（禁止），或把摘要强转成 `TestPlan`（禁止）。§5 已经固定了这棵树的形状，读回来照它序列化即可。

**为什么这是最小方案**：只改一个响应模型的字段形状，**零 schema 变更、零新接口**（C31 追加的版本集合读取见 6.5 节）；两个端点都返回同一棵树，因此创建之后不需要再读一次。

| 读回字段 | 来源 | 说明 |
|---|---|---|
| `id` / `projectId` / `specId` | `test_plans.public_id` / 任务的项目 / `spec_` + `api_specs.slug` | 稳定 key，不是行 UUID |
| `name` / `goal` | `test_plans.name` / `description` | JSONB，`LocalizedText` |
| `status` / `riskLevel` / `source` | 同名列 | `status` 只可能是 `draft` |
| `generatedAt` | `test_plans.created_at` | payload 的 `generatedAt` 无列（§6.1） |
| `version` / `isCurrent` / `runCount` | `test_plans.version` / 该文档最高 version / 指向该计划的 `test_runs` 数 | C31；旧计划 `version=1` |
| `scenarios[].{id,index,name,description,riskLevel,expected}` | `test_scenarios` 同名列 | 按 `sort_order` |
| `scenarios[].steps[].{id,index,kind,description,produces,consumes}` | `test_steps` 同名列 | 按 `sort_order` |
| `scenarios[].steps[].method` / `path` | `test_steps.config` | **G1 的读回**，与 run 快照同一规则 |
| `scenarios[].steps[].endpointId` | — | 恒 `null`：计划侧的 endpoint id 是前端字符串，而该列是 `api_endpoints` 的外键，那张表从未物化 |
| `scenarios[].assertions[].{id,kind,target,expected,description,stepId}` | `test_assertions` 同名列；`stepId` ← `test_steps.step_key`（LEFT JOIN `test_assertions.step_id`） | 按 `assertion_key`（该表没有 `sort_order`）；旧计划 `stepId=null` |
| `understanding` | 内存 | 只有创建响应有；不落库，`GET` 一律 `null`（§13 G11） |

## 6. Test Plan Mapping

### 6.1 计划侧落库映射（`_get_or_create_plan`，逐字段）

| payload | 目标列 | 备注 |
|---|---|---|
| `plan.id` | `test_plans.public_id` | 整个字符串（含 `plan_` 前缀），`UNIQUE(project_id, public_id)` |
| `plan.name` | `test_plans.name` (JSONB) | `model_dump()` |
| `plan.goal` | `test_plans.description` (JSONB) | **`goal` 没有自己的列** |
| `plan.status` | `test_plans.status` | — |
| `plan.riskLevel` | `test_plans.risk_level` | — |
| `plan.source` | `test_plans.source` | — |
| `plan.approvedAt` / `rejectedAt` / `rejectionReason` | 同名列 | — |
| `plan.generatedAt` | — | **无列，丢弃** |
| （无） | `test_plans.agent_task_id` | **不由 create-run 写**（恒 NULL）；Agent 路径必须自己写 |
| `plan.version`（Agent 分配） | `test_plans.version` | v1=1；重新生成 n≥2，见 6.5 节 |
| `scenario.id` | `test_scenarios.scenario_key` | — |
| `scenario.name` / `description` / `expected` | 三个 JSONB 列 | — |
| `scenario.riskLevel` | `test_scenarios.risk_level` | — |
| `scenario.index` | `test_scenarios.sort_order` | — |
| `step.id` | `test_steps.step_key` | — |
| `step.description` | `test_steps.description` (JSONB) | — |
| `step.kind` | `test_steps.step_type` | — |
| `step.produces` | `test_steps.produces` | — |
| `step.consumes` | `test_steps.consumes` (JSONB) | — |
| `step.index` | `test_steps.sort_order` | — |
| `step.method` / `step.path` | `test_steps.config`（**仅 `request` 步骤**） | 写成 `{"method": ..., "path": ...}`；值缺失时不写该键（见 §6.3 G1，**Phase 8.2 Step 1 已实施**） |
| `step.endpointId` | `test_steps.endpoint_id` = **NULL** | 前端的 `endpointId` 不是 UUID，且 `api_endpoints` 为空 |
| （无） | `test_steps.config` = `{}`（`extract` / `assert` 步骤） | 列 NOT NULL；非 `request` 步骤没有请求可描述，保持空对象 |
| （无） | `test_steps.depends_on` = JSON `null` | payload 无 `dependsOn`；写入的是 Python `None`，SQLAlchemy 落到 JSONB 上是 **JSON 标量 `null`，不是 SQL NULL**（全库 7 行实测 `depends_on::text = 'null'`）。消费方必须把 JSON `null` 与 SQL NULL 等价处理 |
| `assertion.id` | `test_assertions.assertion_key` | — |
| `assertion.kind` | `test_assertions.assertion_type` | — |
| `assertion.target` | `test_assertions.target` | — |
| `assertion.expected` | `test_assertions.expected_value` | 存成 JSON 字符串（`\"200\"`） |
| `assertion.description` | `test_assertions.description` | — |
| `assertion.stepId` | `test_assertions.step_id`（可空） | 解析到刚写入的 `test_steps` 行；旧计划没有该字段 ⇒ NULL，仍按 scenario 级回退 |

**复用语义（`runs.py:616-619`）：** 同一个 `(project_id, public_id)` 第二次出现时，**复用已存的行、不重写**，并按稳定 key 反查 id；payload 里有而库里没有的场景拿不到 `source_scenario_id`（写 NULL，不伪造）。

### 6.2 运行快照映射（`_insert_run_tree`，执行器的真实输入）

| payload | 快照列 | 备注 |
|---|---|---|
| `scenario.id` | `run_scenarios.scenario_key` | 事件的 `scenarioId` |
| `scenario.name` / `riskLevel` / `index` | `name` / `risk_level` / `sort_order` | `status` 初始 `pending` |
| `step.id` | `run_steps.step_key` | 事件的 `stepId` |
| `step.description` / `kind` / `index` | `description` / `step_type` / `sort_order` | `status` 初始 `pending` |
| **`step.method` / `step.path`** | `run_steps.method` / `run_steps.path` | **从 payload 直抄**，不 join `test_steps`（`runs.py:823-827` 注释："Snapshots, copied rather than joined"） |
| `assertion.id` / `kind` / `target` / `expected` / `description` | `assertion_key` / `assertion_type` / `target` / `expected_value` / `description` | `status` 初始 `skipped` |
| `assertion.stepId` | `run_assertions.run_step_id` | 计划的绑定优先：断言挂到它指名的 `assert` 步骤；缺失/无效时回退 `_checkpoint_step_key`（第一个 `assert` 步骤，否则最后一个步骤，否则 NULL） |
| `step.id`（经 `source_step_id`） | `run_steps.source_step_id` | 唯一一条**回指计划侧**的链路，供 `extract` 读 `test_steps.produces` |

**版本与历史 Run：** 重新生成只新增 `test_plans` 行，不改任何已有 `test_runs.plan_id`；Run 的 `planId` 因此始终指向它实际执行的版本。执行器读取运行快照，不读当前计划。

### 6.3 三处结构性事实（Phase 8.x 必须先看这一节）

**G1 — `test_steps` 存不下 method/path，但执行器要 method/path。（Phase 8.2 Step 1 已实施）**
问题：计划与文档原先**必须搭同一次 create-run 请求**进来，快照才能从 payload 抄到 method/path，`test_steps` 只是个"档案"。一旦 Agent 在**服务端**生成计划并先落库、之后再单独创建 run，快照就只能从 `test_steps` 取 method/path —— 而那里**没有**，每个 `request` 步骤都会失败。

**已实施的机制（零 schema 变更）：** `test_steps.config`（JSONB、NOT NULL、默认 `'{}'`）承载 request 步骤的目标：

- **写入**：物化计划时，`kind == "request"` 的步骤写 `{"method": <PlanStep.method>, "path": <PlanStep.path>}`；值缺失时不写该键。`extract` / `assert` 步骤保持 `{}`——它们没有请求可描述。
- **读回**：构建运行快照时，**payload 优先，计划侧兜底**。payload 给了就用 payload（今日前端流程逐字节不变）；payload 没给就从 `config` 取值，并沿用列宽限制（method ≤ 20、path ≤ 1000），非字符串或超长视为缺失。
- **作用域**：只有 `request` 步骤参与回填；非 request 步骤的快照字段保持"照抄 payload"的原有语义。
- **无迁移、无新列**：`test_steps` 的列集合不变（验证脚本会断言 `method`/`path` 仍不是列、`config` 仍是 jsonb）。
- **未回填历史行**：既有计划树的 `config` 仍是 `{}`（复用路径**不重写**计划树），它们靠 payload 继续工作；只有新物化的计划才带目标。

**G2 — 断言可以精确挂在"哪个 assert 步骤"（C30-M 已实施，兼容旧计划）。**
`PlanAssertion.stepId` 是可选字段；两条 Planner 都按真实 endpoint 关联把同一请求的断言归入紧跟该请求的 assert 步骤，写入 `test_assertions.step_id`，运行快照再写入 `run_assertions.run_step_id`。执行器在该步骤读取当时的响应，因此 POST 的 201 不会读到 GET 的 200。旧计划没有 `stepId`，仍走 `_checkpoint_step_key` 的 scenario 级回退，无需迁移。

**G3 — `depends_on` / `consumes` 只是记录，执行器不读。**
执行顺序**只由 `sort_order` 决定**（`run_executor.py` 按 `sort_order` 推进）。`test_steps.depends_on` 在 payload 里根本没有来源（`_get_or_create_plan` 写 `None`，落库为 JSON `null`，实测全库 7 行皆如此；**没有 SQL NULL**）；`consumes` 落了库但执行器不消费。⇒ **AI 想表达"B 必须在 A 之后"，唯一有效手段是把 `index` 排对**，写 `dependsOn` 没有执行效果（`db/models/agent.py:14-18` 已说明它是 "document-ordered reference the database cannot police"）。

### 6.4 断言与响应的绑定（C30-M）

1. **存在性语义。** `field` 断言的 `expected="present"` 表示"字段必须存在"，不是与字符串 `"present"` 比较。
   路径解析成功即通过，`actual` 记录真实值；缺失字段或缺失父对象失败。JSON `null`、`""`、`0`、`false` 都算存在。
2. **与相等断言的区别。** 其他 `expected` 仍按普通字符串相等比较。`present` 是历史计划已经在用的哨兵值，
   执行器继续按存在性处理，不需要迁移已有计划。
3. **一组断言只读所属请求的响应。** 每条断言通过 `stepId` 挂在场景内的一个 `assert` 步骤上；
   执行器在该步骤使用当前请求的响应判定，而不是场景最后一次响应。
4. **断言步骤紧跟对应请求。** 多请求场景中，`assert` 步骤必须放在它所断言的请求之后；
   同一请求的多条断言共用一个 `assert` 步骤。
5. **禁止跨请求聚合。** 不得把所有请求的断言放进一个只读取最后响应的步骤；旧计划如果仍是这种布局，
   会保留原有语义，但新生成的计划不得再这样组织。
6. **典型生命周期布局。**

   ```text
   POST /orders → POST assertions → Extract orderId → GET /orders/{orderId} → GET assertions
   ```
7. **生成侧规则。** 分组依据是生成时真实存在的 endpoint 关联（`endpoint_id` → 该 endpoint 的 request 步骤），
   不得解析 `ep_post_orders__status` 之类的断言 key 反推来源；两条 Planner
   （确定性 `generate_plan` 与模型 `design_to_plan`）共用 `agent_plan.arrange_assertion_steps`。

### 6.5 计划重新生成与版本管理（C31）

**版本标识。** 第一个计划继续使用历史兼容的 `plan_{slug}`，`test_plans.version = 1`；第 n 个版本（n ≥ 2）使用 `plan_{slug}_v{n}`，`version = n`。版本号在同一个 `(project_id, spec_id)` 序列内单调递增，不同项目、不同文档各自独立。`test_plans.version` 列在 C31 之前已经存在，因此本功能**没有新列、没有 migration**。

**分配与并发。** Agent 重新生成在持久化事务内先取 `pg_advisory_xact_lock`，再读取当前最大 version 并分配下一个；`UNIQUE(project_id, public_id)` 是最后的兜底。计划校验失败时事务回滚，不留下半棵树，也不消耗版本号。

**API。** `AgentTaskCreateRequest.regenerate` 默认 `false`：普通首次生成遇到已存在计划仍然返回 409 `plan-exists`，旧契约不变。显式 `regenerate=true` 跳过该拒绝并创建新版本。`GET /api/projects/{project_id}/plans` 返回项目内所有未删除的计划树，每项带 `version`、`isCurrent`、`runCount`；`isCurrent` 是该文档的最高 version，**独立于审批状态**。

**审批与历史。** 新版本由 Planner 产生，状态始终 `draft`，不继承旧版本的 `approved`；旧版本的审批状态不变。`test_runs.plan_id` 不因生成新版本而改变，Run 的 `planId` 明确指向它实际执行的版本。前端从已有计划发起重新生成，先确认再调用；失败保留旧计划，旧版本可在计划列表或详情页按 id 查看。

**读回兼容。** `AgentPlanResponse` 增加 `version` / `isCurrent` / `runCount`；`PlanPayload` 接受这些可选读回字段，但 create-run 不以它们选择版本——已有 plan 行才是权威。

---


### 6.6 运行时变量作用域（C32）

每个 Run 创建一个 `RunExecutionContext`，同一个 context 传给所有 `_run_scenario()`：

- `variables` 是 Run 启动时从 environment 读取一次的映射；`runtime` 初始为空。
- `extract` 成功后写入 `runtime[produces]`；后续步骤和**同一 Run 的后续场景**都读取同一个 `runtime`。
- 替换时 runtime 优先于 environment；这正是 Extract 覆盖用户输入值的语义。
- 缺失变量不会被替换为空串或原样发送：resolver 收集名字，步骤在发 HTTP 之前失败，错误码是 `missing-runtime-variable`。
- `runtime` 只存在于进程内；不写 `environment_variables`、不写 `test_runs`、不进入事件 payload。Run 历史只保存名字，不保存值。
- 前端 Run 详情的 `variableKeys` 是运行前的初始变量名；运行时变量名从成功的 `extract` 步骤 evidence 派生，单独显示为 Runtime variables，并说明其作用域是整个 Run。
- 没有新增 schema 列或 migration；旧计划的执行路径不变。

### 6.7 断言与提取描述（C32）

- `arrange_assertion_steps()` 不再复用模型的单个 scenario-level assert description。每个 request 后的 assert step 使用 `console.aiTest.step.assertRequestResponse`，参数是该方法与路径，只描述它实际读取的响应。
- extract step 使用 `console.aiTest.step.extractVariableFrom`，描述变量名、来源 method 和 path，供读者理解下游使用。
- assertion 的 description 由 kind/target/expected 生成：status 用 `statusIs`，field present 用 `fieldPresent`，field 等值用 `fieldIs`，header 用 `headerIs`。模型提供的 assertion description 只作为设计输入，不直接成为计划行文案。
- 这不改变 assertion 的 target、expected、执行顺序、C30-M 的多请求绑定或 run snapshot；只修正展示语义。

## 7. Prompt Engineering Boundary

**本 Step 不修改现有 Prompt Engineering**，因为**当前项目不存在 Agent Pipeline 的 Prompt 资产**。

核验结果（本次实际搜索，不是推断）：

| 检查项 | 结果 |
|---|---|
| 项目内 Prompt / Agent Instruction 文件 | **不存在**。`D:\Aiapi_test` 下全部 `.md` 只有 6 个：`backend/dosc/ai-api-testing-agent-database-schema-v1.md`、`frontend/docs/phase-6-architecture.md`、`frontend/docs/phase-6.2-backend-rest-contract.md`、`frontend/README.md`、`frontend/src/components/effects/README.md`、`.agents/skills/taste-skill/SKILL.md`（UI 设计技能，与 Agent Pipeline 无关） |
| `engineering-backend-architect` / `engineering-frontend-developer` | **在 `D:\Aiapi_test` 与 `D:\Deepseek\deepseek-harness` 中都不存在**（对两个目录全量 grep 均零命中）。这两个名字在本仓库没有对应实现 |
| 产品侧 Prompt 模板 / 表 / 列 | 只有 `agent_tasks.prompt`（TEXT，用户手写的任务要求），0 行数据；**没有** prompt_templates 表、没有 prompt 文件、没有 LLM 客户端 |
| Skill / Subagent（本项目新增） | 无。`.agents/skills/` 下只有 `taste-skill`（仓库自带） |

因此本 Step 的产出是**边界定义，而不是 Prompt 内容**：

### 7.1 边界划分

| 归属 | 负责什么 | 存放位置 | 今天的状态 |
|---|---|---|---|
| **Prompt Engineering** | "让 Agent 产出符合 §5 的输出"：任务陈述（`agent_tasks.prompt`）、系统提示、输出 schema 的提示、few-shot | 未来的 Prompt 资产（本文只定义它必须产出什么） | 未建立 |
| **Runtime** | 身份识别、校验、持久化、状态机、审批、调度执行器 | 后端服务层（`agent_tasks` / `test_plans` / Run REST） | 部分存在（仅 Run 侧） |

### 7.2 从现在起必须遵守的 Prompt 规则（契约，不实现）

- **P1 输出契约优先于文风。** Prompt 的第一职责是让输出**能被 §5 的字段契约校验通过**；任何"更自然的表达"如果破坏字段契约，就是错的。
- **P2 敏感值绝不入 Prompt。** 变量值、token、Cookie、`Authorization` 头**不得**出现在 prompt 文本里（与 `run_executor.py` 的既有安全不变量一致：值不落 `run_events`/`run_steps`/`run_assertions`/`run_evidence`）。Prompt 里只能出现**变量名**。
- **P3 Prompt 不得包含执行指令。** "请调用 /api/orders 并检查状态码"这类指令属于 Agent 的**输出**（结构化 step/assertion），不属于 Prompt 的**指令**。LLM 不执行 HTTP（§8）。
- **P4 人类意图只从 `agent_tasks.prompt` 进入。** 不接受从其他字段（如文档注释）间接注入的任务指令。
- **P5 未支持的字段不许出现在输出里。** 见 §10：Request Body / Query Params / Schema Assertion 在 v1 是 **Deferred**，Prompt 必须让模型**不产出**依赖它们的计划，或明确标注。

### 7.3 Phase 8.3 Step 1：Prompt Engineering v1 已建立

**资产**：`backend/src/backend/prompts/analyze-v1.md`（front matter 里带 `version: 1`）。它随服务端包一起发布——运行时找不到的 Prompt 不算资产——所以它在包内，而不是仓库根的 `agent/prompts/`（本仓库没有该目录；这条路径按"以真实代码为准"微调）。

| 规则 | 今天的实现 |
|---|---|
| **P1 输出契约优先** | schema 由 `AgentUnderstandingResponse.model_json_schema()` 生成（`extra="forbid"`），模型必须返回 §5 的 understanding，没有别的产物 |
| **P2 敏感值绝不入 Prompt** | 送给模型的只有 parse 后的事实与文档自身的 summary/description；变量只以**名字**出现。`scripts/verify_agent_analyze.py` 用哨兵值实测"没有值到达模型，也没有值到达计划表" |
| **P3 Prompt 不得包含执行指令** | Prompt 明说：不写计划、不发 HTTP、不批准任何东西；模型只能产出 understanding（§8、§9） |
| **P4 人类意图只从 `agent_tasks.prompt` 进入** | 请求分三个独立 turn：instructions（system）/ human task（user）/ specification facts（user）。文档原文另放 `documentation` 段，**只作为数据**；模型说明文档可能包含"ignore previous instructions"这类文字，那些是文档内容 |
| **P5 未支持的字段不许出现在输出里** | Prompt 要求把 body / query / schema 只记为风险；计划侧仍由 `generate_plan` 决定（Test D 实测步骤/断言词汇表未变） |

**两层验证**（§13 的落地）：`AgentUnderstandingResponse.model_validate`（字段、类型、未知字段即失败）→ `agent_analyzer.domain_issues`（引用的 endpoint 必须存在、依赖 id 形状、risk 类别与等级、finding 必须带证据）。任一层不过：`analyze-failed`，任务 `failed`，四张计划表**零写入**。

**事实不由模型决定**：三个 fact 段必须与 parse 一致（不一致就拒绝），而且即便一致，服务端也**取 parse 的值**。模型真正的贡献是 dependencies / risks / findings。

**没有 LangGraph**：编排仍是 `services/agent.py` 里的顺序代码（parse → analyze → generate → validate → persist），本 Step 没有引入任何图/编排框架，也没有新增 Skill 或 Subagent。

### 7.5 Phase 8.3 Step 2：计划阶段也由模型设计，key 由运行时补全

**资产**：`backend/src/backend/prompts/generate-plan-v1.md`（front matter `stage: generate_plan`）。输入只有**三段**：instructions、`agent_tasks.prompt`、以及 analyze 的产物（understanding 里已含 parse 事实，所以原始 OpenAPI 文档**不**再发送——token 与注入面都因此变小）。

| 谁负责什么 | 内容 |
|---|---|
| **模型** | 设计：`name`/`goal`/`riskLevel`/`scenarios`（每个 scenario 有 `name/description/expected/riskLevel/steps/assertions`）；step 只有 `request/extract/assert` 三种；assertion 只有 `status/field/header` 三种，并指明它读哪个 endpoint 的响应 |
| **运行时（代码）** | `plan.id`、scenario/step/assertion 的**key**、`index`、`status=draft`、`source`、`generatedAt`、`projectId`/`specId`；request step 的 `method`/`path`**取文档事实**（模型回显必须一致，否则拒绝） |
| **既有边界** | `validate_plan()` 一字未改：它仍是"LLM → 计划"之间唯一的确定性关卡（index 稠密、key 唯一、变量来源、无 schema 断言、无秘密） |

**Provider schema 的关键性质**（`scripts/verify_deepseek_schema.py` 实测）：发给 DeepSeek 的 schema 里**没有** `id`/`index`/`status`/`source`/`generatedAt`/`projectId`/`specId` 可填，也没有 `body`/`query`/`schema` 字段——"模型不能发明 key"与"模型不能设计执行器做不到的事"因此是**结构性的**，不是靠叮嘱。断言 `expected` 在 schema 里就是 `string`（数字直接是类型错误）。

**两个 stage 各自有开关**：`AGENT_ANALYZER` 与 `AGENT_PLANNER`（都取 `deepseek` 或 `deterministic`，默认 `deepseek`，未知值报错）。测试与 CI 显式钉住 `deterministic`。

### 7.4 Phase 8.3 Step 1-A：Provider Strict Schema Adapter

DeepSeek 的 `json_schema` 只接受**封闭**子集：每个 object 的 `required` 必须列出全部属性，且 `additionalProperties` 必须为 `false`。Pydantic 生成的契约 schema 里既有可选字段，又有开放字典（`LocalizedMessage.params`），因此第一次真机调用被拒：

`HTTP 400  Required properties must match all properties in the object`

修法**不是改契约**，而是在发送前加一层 provider adapter（`services/llm.py` 的 `strict_schema()`）：

| 变换 | 内容 |
|---|---|
| 对象封闭 | 递归（**跟随 `$ref` 进入 `$defs`**）把每个 object 的 `required` 补成全部属性、`additionalProperties` 置 `false`。可选字段仍然是可空的：`anyOf: [..., {"type":"null"}]` 保留，语义从"可以缺失"变成"必须出现、可以为 null" |
| 分支剪枝 | 含类型化字典（`additionalProperties: {schema}`）的联合分支无法表达 → 剪掉，并回收只有它引用的 `$defs` 条目。`LocalizedText` 因此在此 provider 上只剩字面形式 `{"text": ...}` |
| 不删信息 | 不删属性、类型、enum、数组 item、对象层级；剪枝后仍无法表达（非联合位置的开放字典）则**明确报错**，不静默弱化 |

**Domain Contract 未改变**：`AgentUnderstandingResponse.model_json_schema()` 逐字节不变，模型仍接受 `{key, params}` 形式的本地化消息（随包测试脚本 `verify_deepseek_schema.py` 实测）。改变的只是"模型被允许产出什么形状"。`analyze-v1.md` 因此新增一段 Text fields：本阶段的自由文本一律 `{"text": "..."}`。

### 7.6 Phase 8.4 Step 1：审计（`agent_task_audits`）

**一条任务一行**，与任务**同一个 commit** 创建（`task_id` 唯一，`ON DELETE CASCADE`）：任务在第一条语句上就失败，也一定有地方记录它失败在哪。这是"记录者"，不是第二条流水线——它不提交、不调用模型、不生成计划，只把流水线已经知道的事实写下来。

| 列 | 内容 |
|---|---|
| `status` | 流水线当前 stage：`pending / analyzing / parse / analyze / generate / validate / persist / completed / failed`（在流水线自己的 commit 边界上持久化） |
| `failure_stage / failure_code / failure_message` | 失败时的 stage、**复用既有错误码**（`analyze-failed` / `plan-invalid` / …）、≤500 字的一句摘要（**不存 traceback**） |
| `analyzer_provider / model / prompt` · `planner_provider / model / prompt` | 每个 stage 的真实身份：`deepseek` + 模型名 + prompt 资产名（如 `analyze-v1`），或 `deterministic` + null |
| `understanding` (JSONB) | **通过 Pydantic + domain 校验后**的理解结果，与创建响应里那份**同一个序列化器** |
| `plan_design` (JSONB) | 通过校验的 **PlanDesign**（补全 key 之前）；规则引擎没有独立设计，所以为 null |
| `usage` (JSONB) | `{analyze: {...}, generatePlan: {...}}`，只存 provider 真实报过的计数（`inputTokens / cachedInputTokens / outputTokens / reasoningTokens / totalTokens`）；deterministic 不写、更不编造 |

**不存**：文档、Prompt 原文、请求/响应正文、HTTP 头、任何凭据、provider 的原始响应元数据。写库前还有一道针对"本次任务声明的运行期值"的精确替换（`_without_secrets`），只替换**确切的值**，不粗暴脱敏业务文本。

**失败时审计仍然完整**：`_fail` 会先 rollback（写入事务的既有规则），所以审计从流水线的 `_Progress` 里**重新写入**已经产出的 understanding / PlanDesign / usage，再写失败三元组——"失败在 validate"恰恰是最需要知道"模型当时理解了什么、设计了什么"的时刻。

**读回**：`GET /api/agent/tasks/{task_id}/audit`。未知任务 = 既有的 `task-not-found` 404；任务存在但没有记录（8.4 之前的旧任务）= `audit-not-found` 404——两个不同的事实给两个不同的答案。

**调用次数不变**：usage 取自既有响应的 `usage` 字段，不额外请求：analyze 仍是 1 次、generate_plan 仍是 1 次。

**访问控制（8.4 Step 2 实测，别误读）**：审计接口**没有**调用方鉴权——它与任务接口一样，拿到 task id 就能读（§13 G14）。已确认的是：审计**不会越出它自己那条任务/项目**（@taskId@ 对应唯一任务，understanding 的 `specId` 属于该项目的 spec），任务删除时审计随之级联删除；而"谁能读"这件事在服务端**尚不存在**，本 Step 只测量与记录，没有发明凭证机制。

---

## 8. Agent Permission Boundary

### 8.1 Agent 允许做（Allowed）

| # | 允许 | 依据 |
|---|---|---|
| A1 | 读取 `api_specs.content` 与由它派生的 endpoints / resources / authentication | 解析是纯函数 |
| A2 | 生成 `ApiUnderstanding`（含 dependencies / risks / findings） | 现状 `analyze` |
| A3 | 生成 `TestPlan` 草稿，含 scenarios / steps / assertions | 现状 `generatePlan` |
| A4 | 生成稳定 key（`plan_*` / `scenario_*` / `step_key` / `assertion_key`） | §5.3；必须确定性 |
| A5 | 生成 `LocalizedText`，但 key 必须已存在（或退化为 `{text}`） | §5.4 P1 |
| A6 | 写 `agent_tasks`（任务行）与 `test_plans`（草稿行，`agent_task_id` 指向任务） | 表结构已预留 |
| A7 | 在 `agent_tasks.status` 上走 `pending → analyzing → completed/failed` | §4.3 |
| A8 | 声明"这条断言/步骤我建议但当前执行器不支持"（表达为**不产出**或标注），供人类决策 | §10 |

### 8.2 Agent 禁止做（Forbidden）

| # | 禁止 | 理由 |
|---|---|---|
| F1 | **发 HTTP 请求 / 决定请求内容** | LLM ≠ HTTP Executor。执行器的输入是快照，快照只由计划物化产生 |
| F2 | 决定数据库状态（`test_runs` / `run_*` / `run_events`） | 与 7.3 不变量冲突：只有执行器写运行时状态 |
| F3 | **把计划置为 `approved`** | `types/agent.ts:309-314`：只有 `approvePlan()`（人类动作）能产生 `approved` |
| F4 | 绕过审批创建 run | `_check_approval` 是服务端闸门（409 `not-approved`） |
| F5 | 写 `test_workflows` / 新建层级 | 该表按设计延后（`dosc:882-895`），当前数据库不存在 |
| F6 | 修改已冻结的 Run Snapshot / Run Event 契约 | Phase 7.2-D/E、7.3 已冻结 |
| F7 | 产出自然语言形式的"动作"（如"发送一个请求看看效果"） | 无法被 `run_executor.py` 消费，等于没有产出 |
| F8 | 在输出里携带变量值 / token / cookie | 与既有安全不变量冲突（§7.2 P2） |
| F9 | 单方面修改 `test_plans` 的非草稿字段（`approved_at` / `rejected_at` / `rejection_reason`） | 审批是人类的 |
| F10 | 依赖未支持的能力来构造计划（body / query / schema 断言）而不声明 | §10；否则计划会在执行期静默失败 |

**审批边界的现状与目标（必须说清楚）：** 今天"审批"是客户端写 localStorage，`_check_approval` 信任 payload —— 前端文档已经指出"审批对话框是 UI 边界，不是安全边界"（`phase-6-architecture.md:129-130`）。**把审批的权威搬到服务端是一个独立且更大的决策**（`phase-6.2-backend-rest-contract.md:716` 已明确不塞进 6.2）。本文不改变它，只把它记录为 Phase 8.x 的头号待决问题。

---

## 9. Deterministic Executor Boundary

### 9.1 执行器真实消费面（Phase 7.3 已冻结）

| 执行器读取 | 来源 | 说明 |
|---|---|---|
| 场景顺序 | `run_scenarios.sort_order` | 升序 |
| 步骤顺序 | `run_steps.sort_order` | 升序 |
| 请求 | `run_steps.method` + `run_steps.path`（`{{var}}` 解析：运行期变量 > 环境变量） | 快照列；缺失时由 create 路径从 `test_steps.config` 恢复后写入，见 §6.3 G1 |
| 步骤类型 | `run_steps.step_type` ∈ `request/extract/assert` | `assert` 步骤不发请求 |
| 提取变量名 | `test_steps.produces`（经 `run_steps.source_step_id`） | **唯一的计划侧读取** |
| 断言 | `run_assertions.assertion_type` / `target` / `expected_value` | `status`/`field`/`header` 执行；`schema` → `skipped` |
| 认证 | `environment_auths`（`is_default AND is_enabled`） | `none/bearer/basic/apiKey` |
| base URL | `test_runs.base_url` | 快照 |
| 变量 | `environment_variables` + create-run 的 `variables` | 值只在内存 |

**执行器不读**：`api_specs` / `api_endpoints`（`api_endpoints` 永远为空）、`test_plans`、`test_scenarios`（除 `produces` 那一条）、任何 LLM 产物。

### 9.2 AI 输出必须满足的可执行性规则

| # | 规则 | 违反的后果 |
|---|---|---|
| E1 | `request` 步骤必须同时有 `method` 与 `path`；`method ∈ {GET,POST,PUT,PATCH,DELETE}` | 快照缺字段 → 步骤失败 |
| E2 | `extract` 步骤必须设置 `produces`（变量名） | 提取值为空 → 后续 `{{var}}` 解析失败 |
| E3 | 路径/断言里用到的每个 `{{var}}`，必须由环境变量或某个更早的 `extract` 提供 | `this run has no value for: <key>`（既有错误语义） |
| E4 | 断言 `target` 只能是 `status` / `body.<path>` / `header.<Name>` | 目标无法解析 → 断言失败 |
| E5 | 断言 `expected` 必须是**字符串** | Pydantic 422（`PlanAssertion.expected: str`） |
| E6 | 同一 scenario 内 `step.id` 唯一、`assertion.id` 唯一；同一 plan 内 `scenario.id` 唯一 | `UniqueViolation` |
| E7 | `index` 决定执行顺序，必须显式、稠密、与期望顺序一致 | 顺序错误（`dependsOn` 无执行效果，见 G3） |
| E8 | 断言只能依赖**已经被执行过**的响应（同场景更早的步骤），且执行器在该断言所属 `assert` 步骤读取当时的响应 | 断言拿到空响应 → `skipped`/失败；跨请求聚合会读错响应（§6.4） |
| E9 | **不依赖请求体**：POST/PUT/PATCH 在 v1 发送**空 body** | 计划里"创建资源"类场景会在执行期失败 |
| E10 | **不使用 query 参数**（执行器尚未支持） | 参数丢失 → 断言失败 |
| E11 | `schema` 断言会被判为 `skipped`，不得当作有效覆盖 | 覆盖率虚高 |
| E12 | 计划里不得出现环境/密钥相关的**值**（只允许变量名） | 安全不变量破口 |

> **E9/E10/E11 是本契约里"AI 能力"与"执行器能力"之间最紧的三处约束。** 它们不是建议：AI 若忽略它们，产出的计划在 7.3 执行器上**必然失败或空转**。Phase 8.x 要么让生成器避开，要么先扩展执行器（那是 7.x 的后续步骤，不是 8.1）。

---

## 10. Unsupported / Deferred Capabilities

**Deferred / Unsupported 是契约的一部分，不是待办清单的省略。** 以下能力当前**不存在**，AI 输出不得假设其存在：

| # | 能力 | 现状 | 证据 |
|---|---|---|---|
| D1 | **Request Body 合成与发送** | v1 发送空 body | 7.3 契约；`test_steps` 无 body 字段（`db/models/agent.py:8-12`） |
| D2 | **Query Params** | 执行器不支持 | `run_steps` 无 params 列 |
| D3 | **Schema 断言** | 一律 `skipped`（不引入 `jsonschema`） | 7.3 |
| D4 | **Cookie 认证** | 只支持 `none/bearer/basic/apiKey` | 7.3；`environment_auths.auth_type` |
| D5 | 服务端 **YAML** 解析 | 服务端只解析 JSON（8.2 Step 2 起）；YAML 文档只会得到 `parse-failed` | `services/agent_plan.py` 的 `decode_document`；`spec_identity.probe_document` 只标注不解析 |
| D6 | ~~计划版本化 / 重新生成~~ | **已实现（C31）**：`regenerate=true` 创建 `plan_{slug}_v{n}`，旧计划与历史 Run 保留；普通首次生成遇到已存在计划仍是 409 | 6.5 节；`services/agent.py` |
| D7 | 服务端审批权威 | 审批在 localStorage | `stores/agent.ts:318-330`；`_check_approval` 只信 payload |
| D8 | ~~`agent_tasks` 落库与任务生命周期~~ | **已实现并已接入前端**（8.2 Step 2 + Step 3）：每任务一行、四状态机、`agent_task_id` 回指 | `services/agent.py`；`frontend/src/services/api/agent.ts` |
| D9 | Understanding 持久化 / 流式进度 | 两边都不落库；服务端一次算完即弃，进度仍只有浏览器定时器 | `services/agent.py` 的 `_generate`；`stores/agent.ts:41-46` |
| D10 | ~~LLM 客户端 / Prompt 资产~~ | **已实现**（8.3 Step 1）：`services/llm.py` 的 DeepSeek 客户端 + `prompts/analyze-v1.md`；**LangGraph 仍然不存在**，管线由 `services/agent.py` 直接编排 | §7.3；`scripts/verify_llm_client.py` |
| D16 | 重试 / 队列 / 异步任务 | 单次调用、单个 timeout，**不重试**（先证明一次请求是对的） | `services/llm.py` 的 `DEFAULT_TIMEOUT_SECONDS`；无 Celery/Redis/Kafka |
| D17 | ~~token 用量~~ | **已实现**（8.4 Step 1）：按 stage（`analyze` / `generatePlan`）存进 `agent_task_audits.usage`，只存 provider 真实报过的计数；**成本计算仍未实现**（没有统一价格配置） | `services/agent_audit.py`；`schemas/agent_audit.py` |
| D18 | ~~计划阶段不可审计~~ | **已实现**（8.4 Step 1）：`agent_task_audits.plan_design` 保存经 Pydantic 校验的 **PlanDesign**（补全 key 之前的样子），`understanding` 保存校验后的分析结果；仍**不可重放**（任务重跑要再花钱），也没有 attempt/retry 维度 | `db/models/agent.py` 的 `AgentTaskAudit`；§7.6 |
| D20 | 审计是 1:1，没有 attempt | 一个任务一行（`task_id` 唯一）；重试/队列/worker 仍未设计，将来要多 attempt 时先改这条约束 | `AgentTaskAudit` 的 `unique=True` |
| D19 | ~~断言无法挂到具体 step~~ | **已实现（C30-M）**：`PlanAssertion.stepId` → `test_assertions.step_id` → `run_assertions.run_step_id`；旧计划仍走 scenario 级回退 | §6.3 G2 |
| D11 | `test_workflows`（Workflow 层） | 表不存在，按设计延后 | `dosc:882-895`；数据库核验 |
| D12 | Adaptive Testing、PDF Report、CLI | 未实现 | `phase-6.2-...:767-784` |
| D13 | ~~断言精确挂到某个步骤~~ | **已实现（C30-M）**：可选 `stepId`；旧计划 NULL 时回退 | §6.3 G2 |
| D14 | 幂等性 / 并发执行的模型 | 无互斥逻辑 | `phase-6.2-...:814` |
| D15 | ~~前端 Agent 错误码~~ | **已实现**（8.2 Step 3）：`plan-exists` / `task-not-found` / `plan-invalid` 三个码，以及 `console.aiTest.errors.{planExists,taskNotFound,loadFailed}` 三条文案 | `frontend/src/services/agentError.ts`；两个 locale |

---

## 11. Future LangGraph Position

本文不引入 LangGraph，只固定它将来**必须落在哪里**，避免后续实现改变既有契约。

```text
                    ┌──────────────── Agent Runtime（未来）────────────────┐
AgentTaskInput ───► │  node: load_spec       （读 api_specs.content）      │
                    │  node: parse           （确定性，可无 LLM）           │
                    │  node: analyze         （LLM）                       │
                    │  node: design_plan     （LLM）                       │
                    │  node: validate        （★ 对照 §5 字段契约）         │
                    │  node: persist         （写 test_plans 树 + agent_task_id）
                    └───────────────────────────┬──────────────────────────┘
                                                ▼
                                    TestPlan (status = draft)
                                                ▼
                                    User Approve（人类，权威待定）
                                                ▼
                          create_run（既有 REST，契约不变）→ 快照 → Executor
```

固定的四条：

1. **图的输入输出与 §3/§5 完全一致。** LangGraph 是这四个操作的**实现方式**，不是新契约；`AgentService` 的四方法语义不变（`services/agent.ts:78-97`）。
2. **`validate` 节点是强制节点。** LLM 的自由输出必须先通过 §5 校验（字段、类型、key 唯一性、E1–E12），**校验不过不得落库**；失败写 `agent_tasks.status = failed`。
3. **`persist` 是唯一的写库节点。** 图的其他节点不得写 `test_plans` / `test_scenarios` / `test_steps` / `test_assertions`；更不得写 `test_runs` / `run_*`。
4. **`agent_tasks` 是任务的锚。** 每次任务一行（`pending → analyzing → completed/failed`），计划经 `test_plans.agent_task_id` 回指；`agent_tasks.spec_id` 固定它读过的文档版本。

**位置说明（Phase 8.2 Step 2 后）：** 图上除 LLM 之外的所有节点都已经在服务端存在，而且是**按这个顺序**执行的：`load_spec` / `parse` / `analyze` / `design_plan` 在 `services/agent_plan.py`（纯函数），`validate` 与 `persist` 由 `services/agent.py` 的 `process_task` 串起来，`validate → persist` 的顺序是代码结构而非约定。浏览器里那条函数链（`mock/agent/index.ts:44-88`）仍在原位，前端尚未切换。**LangGraph 要替换的是"谁按这个顺序调用"，不是这个顺序本身**；缺的仍然只有 LLM 与 Prompt 资产。

---

## 12. Example Pipeline

```text
① API Spec                     api_specs.content（OpenAPI 3.x / Swagger 2.x 原文）
                               specId = "spec_" + slugify(title) + "_" + hash(content)
        │
        ▼
② Spec Understanding           parseSpec → ApiSpec + ApiEndpoint[] + ApiResource[] + ApiAuthentication
                               analyze   → ApiUnderstanding{endpoints, resources, authentication,
                                                             dependencies, risks, findings}
                               （今天：浏览器规则引擎 + 服务端确定性实现；未来：LLM，形状不变）
        │
        ▼
③ Test Design                  generatePlan → TestPlan(status = draft)
                               scenarios[].steps[]{id,index,kind,description,endpointId,
                                                   method,path,produces,consumes}
                               scenarios[].assertions[]{id,kind,target,expected,description}
        │
        ▼
④ Persistence                  test_plans(public_id = plan.id, agent_task_id = <任务>)
                               └ test_scenarios(scenario_key = id, sort_order = index)
                                 ├ test_steps(step_key = id, step_type = kind, produces, consumes)
                                 └ test_assertions(assertion_key = id, assertion_type = kind,
                                                   target, expected_value = expected)
                               ★ 必须通过 §5 校验后才落库（8.2 Step 2 起由服务端强制：
                                 validate 不通过 → 四张计划表零写入、任务 failed）；
                                 config 承载 request 步骤的 {"method","path"}（8.2 Step 1），
                                 depends_on/endpoint_id/step_id 仍没有来源（见 §6.1、§6.3）
        │
        ▼
⑤ User Approval                TestPlan.status: draft → in_review → approved
                               approvedAt / rejectedAt / rejectionReason 由人类写
                               ★ Agent 永远不能产生 approved（F3）：服务端只写 draft，审批仍在客户端 store（§8.2）
        │
        ▼
⑥ Run Creation                 POST /api/projects/{projectId}/runs
                               body = { planId, plan, specId, specDocument,
                                        environmentId, variables, baseUrl }
                               服务端：_check_approval → _check_identity →
                                       _get_or_create_spec → _get_or_create_plan →
                                       _insert_run_tree（快照；method/path 取 payload，
                                        缺失时从 test_steps.config 恢复）
        │
        ▼
⑦ Deterministic Executor       queued → running → 逐场景/逐步骤
                               HTTP（httpx，10s 超时）→ 断言 → 结果 → 证据 → 事件
                               status: passed / failed / cancelled
        │
        ▼
⑧ Result / Evidence / Event     run_steps / run_assertions / run_evidence / run_events
                               SSE：8 类事件（run.started / step.started / step.completed /
                               step.failed / assertion.completed / run.completed /
                               run.failed / run.cancelled），seq 每 run 从 1 稠密递增
```

**这条链上"AI 能碰到的东西"止于 ④ 之前的 ③**：进入 ⑤ 之后，计划是**不可变输入**，进入 ⑦ 之后，一切状态由执行器独占写入。

---

## 13. 契约缺口与最小修复方向（G1 已实施，其余仅分析）

> G2 已在 C30-M 实施（见 6.3 / 6.4 节）；其余缺口仍是分析。

| # | 缺口 | 影响 | 最小方案（供 8.2+ 决策） | 是否要改数据库 |
|---|---|---|---|---|
| G1 | `test_steps` 无法表达 method/path（§6.3） | ~~计划一旦先在服务端落库，执行器快照就没有请求信息~~ → **已解决** | **已实施（Phase 8.2 Step 1）**：写入既有 `config` JSONB、快照回填，零 schema 变更；改动 `services/runs.py` + 新增 `scripts/verify_plan_step_config.py` | **否** |
| G2 | ~~断言无法表达步骤挂点（§6.3）~~ → **已解决（C30-M）** | 断言通过可选 `stepId` 挂到所属 assert 步骤；旧计划仍走 scenario 级回退 | **已实施**：`PlanAssertion.stepId` + `test_assertions.step_id` + `run_assertions.run_step_id` | **否**（复用既有列） |
| G3 | `dependsOn` 无执行语义（§6.3） | 写了不生效，顺序只认 `index` | 契约层明确"顺序只由 index 表达"；或后续让执行器读 `depends_on` | 否 |
| G4 | ~~任务失败无处记录~~ → **已解决**（8.4 Step 1） | 失败写进 `agent_task_audits`：`failure_stage` / `failure_code`（复用既有错误码）/ `failure_message`（≤500 字，无 traceback），待办任务与失败任务都能读 | 已实施（不扩 `agent_tasks`） | 否 |
| G5 | 审批权威在客户端（§8.2） | 服务端只复核字符串，不是安全边界 | 独立决策：审批上移 + `POST /api/plans/{id}/approve` | 否 |
| G6 | 理解结果无持久化位置 | 每次重算；无法审计"当时为什么这么设计" | 当前不建；将来单独评估 | **可能需要** |
| G7 | 服务端无法产出 `LocalizedText.key` | 服务端生成的文案只能 `{text}` | 要么接受 `{text}`，要么把字典作为服务端资产 | 否 |
| G8 | `generatedAt` 无列 | 生成时刻不可恢复（`created_at` 是落库时刻） | 可接受；若必须则需新列 | **可能需要** |
| G9 | ~~前端没有 `plan-exists` / `task-not-found` 错误码~~ → **已解决**（8.2 Step 3） | 409 / 404 / 422 各有自己的码与可渲染句子 | 已实施 | 否 |
| G10 | ~~计划无法版本化 / 重新生成~~ → **已解决（C31）** | 新版本使用独立 public id 与 `test_plans.version`；普通首次生成保持 409，显式 regenerate 创建 v2+ | 已实施：`GET /api/projects/{project_id}/plans` 读取版本集合；无新列 | **否** |
| G11 | 前端刷新后理解面板为空 | **部分解决**（8.4 Step 1）：understanding 现在随任务落库（审计表）并可从 `.../audit` 读回，**但任务响应仍不返回它**——前端 UI 未接，也不在本 Step 范围内 | 前端接入是一个独立小 Step | 否 |
| G12 | 前端没有 prompt 输入框 | 任务要求仍由 i18n 模板生成并存进 `agent_tasks.prompt`；**8.3 Step 1 起模型真的读它了**（§7.3），所以"这句话怎么写"第一次有了实际效果 | 前端加输入框，独立小 Step | 否 |
| G13 | 409 的句子与前端词汇不一致 | 服务端按"阶段"给句子（`errors.generateFailed `），而前端为 `plan-exists` 另有更具体的 `errors.planExists`；今天界面显示前者 | 服务端 `_STAGE_MESSAGE_KEYS` 加一行 `plan-exists`（1 行 + 1 处测试），**本 Step 不改**（属 Step 2 的措辞决定） | 否 |
| G14 | **服务端没有任何调用方身份与授权机制**（8.4 Step 2 实测） | 整个 HTTP 层只有 `SessionDep`（`api/deps.py`）；`runs` 6 条与 `agent` 3 条路由都只靠 id 寻址，**谁的 id 都能读**。`projects.user_id XOR guest_session_id` 是**数据不变量**，不是请求级规则；`guest_sessions.session_token` 存在但**没有任何代码读取**；前端 `services/http.ts` 对本服务不发任何凭证。实测（`scripts/verify_agent_audit_access.py`）：跨用户 / 跨 Guest / Guest↔用户 六组探测，**无凭证、header、Bearer、query 四种形态全部 200**，task 与 audit 表现完全一致 | 需要产品决策：①凭证如何传递（guest token 放哪个 header？登录用户怎么标识？）②无权访问返回 404 还是 403 ③覆盖到哪些路由（只保护 audit 是无意义的：task 响应里已经有计划树）。**本 Step 只审查与测量，不发明机制** | 否（纯服务端代码） |
| G15 | **G14 的后续安全阶段已立项**（Phase 8.5 Step 1 冻结契约） | 规则见 `docs/identity-access-contract.md`：Guest-first 身份、`X-Guest-Session` 头、Project 所有权为核心、默认拒绝（401 / 404 同形）、公开路由白名单。实施拆为 **Step 2**（后端身份地基 + migration：token 哈希/撤销/last_seen）、**Step 3**（9 条业务路由接授权，含 SSE）、**Step 4**（前端会话引导 + 头注入 + SSE 改 fetch 流 + Project 引导），登录用户认证再后续 | 8.5 S1 产出文档；**8.5 S2 已实施身份地基**（token 哈希、签发/校验/续期/撤销、CurrentGuestSessionDep、require_guest_project_access，migration a4c1e8b27d93，85/85）。**9 条业务路由仍未接授权，前端仍未发凭证**；Step 3 与 Step 4 必须同批上线 | **可能**（Step 2 的 token 哈希/撤销） |

**结论：Agent Pipeline Contract 在当前数据库结构上成立，并且已经在服务端跑通**：Phase 8.2 Step 1 让已保存的计划能独立提供 `request` 步骤的 method/path，Step 2 让服务端自己产出这样一份计划（解析 → 理解 → 生成 → **校验** → 持久化），落 `draft` 并把 `agent_tasks` / `test_plans.agent_task_id` 这条关系真正用起来。**没有 LLM、没有 LangGraph、没有服务端审批权威、没有数据库变更。** 剩余缺口（G2–G10）仍按上表处理。

---

## 14. 一页速查（Cheat Sheet）

| 问题 | 答案 |
|---|---|
| Agent 输入什么？ | §3.1 `AgentTaskInput`：`projectId` / `specId` / `specDocument` / `environmentId?` / `prompt` / `variables?` |
| Agent 输出什么？ | §5 一棵 `TestPlan` 树（`status` 恒 `draft`），前端类型 = 后端 `PlanPayload` |
| 谁在跑 analyze？ | 默认 **DeepSeek**（`services/agent_analyzer.py` → `services/llm.py`，Responses API + JSON Schema）；`AGENT_ANALYZER=deterministic` 时跑 8.2 的规则引擎。两者产出同一个 `Understanding`，之后每一段都一样 |
| 谁在跑 generate_plan？ | 默认 **DeepSeek 设计 + 运行时补全 key**（`AGENT_PLANNER` 可选 `deterministic` 走 8.2 的规则引擎）。两条路都产出 §5 契约，都过同一个 `validate_plan()` |
| 落到哪四张表？ | `test_plans` / `test_scenarios` / `test_steps` / `test_assertions`（逐字段见 §6.1） |
| 执行器读什么？ | 只读 `run_*` 快照；唯一计划侧读取是 `test_steps.produces`（§9.1）。create 路径另读 `test_steps.config` 补快照的 method/path |
| Agent 能做什么？ | §8.1 A1–A8（读文档、出理解、出草稿、写任务与草稿、走任务状态机） |
| Agent 不能做什么？ | §8.2 F1–F10（发请求、改运行状态、自行批准、新建层级、携带密钥、输出自然语言动作……） |
| 怎么保证可执行？ | §9.2 E1–E12（id 稳定与回显、method/path 齐全、`{{var}}` 可解析、`expected` 是字符串、顺序靠 index、不依赖 body/query/schema） |
| Prompt 与 Runtime 的边界？ | §7：Prompt 只负责"产出符合 §5 的对象"，Runtime 负责身份/校验/持久化/审批/执行；值不进 Prompt |
| Agent API 是什么？ | `POST /api/projects/{project_id}/agent/tasks`（创建并执行一个任务）、`GET /api/agent/tasks/{task_id}`、`GET /api/agent/tasks/{task_id}/audit`；没有 `.../run` 子资源，管线在一次请求内跑完（§2.1 事实 2）。响应携带**完整计划树**，以及只有创建响应才有的 understanding（§5.5） |
| 审计在哪看？ | `GET /api/agent/tasks/{task_id}/audit`：谁跑的每个 stage（provider/model/prompt 版本）、understanding、PlanDesign、逐 stage 的 token 计数、失败时的 stage/code/一句摘要（§7.6） |
| 前端怎么用它？ | `services/api/agent.ts` 把任务响应映射成 `AgentTaskResult{taskId,status,understanding,plan}`；store 仍按 Spec → Understanding → TestPlan → Approval 呈现（8.2 Step 3）。刷新不会重新生成计划：understanding 不落库，计划从存储或 `GET` 读回 |
| 本阶段改了什么？ | 8.1：只新增本文档。8.2 Step 1（G1）：`services/runs.py` 写入/回填 `test_steps.config` + 新增 `scripts/verify_plan_step_config.py`。8.2 Step 2：新增 `services/agent_plan.py` / `services/agent.py` / `schemas/agent.py` / `api/routers/agent.py` + `scripts/verify_agent_foundation.py`，`app.py` 加一条路由，`services/runs.py` 抽出 `_create_plan_tree` 供复用。8.2 Step 3：任务响应改为**完整计划树 + understanding**（§5.5），前端 `services/agent.ts` 改成任务型接口、新增 `services/api/agent.ts`、`stores/agent.ts` 走任务、`AiTestLabView` 的计划区不再被 understanding 门控，新增两个前端 spec。8.3 Step 1：**analyze 改由 DeepSeek 产出**（新增 `services/llm.py`、`services/agent_analyzer.py`、`prompts/analyze-v1.md`、三个 verify 脚本；`services/agent.py` 只改一处调用），parse / generate_plan / validate / persist / Executor / 数据库 / 前端**一字未改**。8.3 Step 1-A：真机发现契约 schema 不符合 DeepSeek 的 strict 子集，新增 **provider strict schema adapter**（`llm.py` 的 `strict_schema()`）+ `scripts/verify_deepseek_schema.py`；**Domain Contract、数据库、Executor、前端依旧未改**。8.3 Step 2：**计划阶段也由 DeepSeek 设计**（新增 `prompts/generate-plan-v1.md`、`services/agent_analyzer.py` 的 plan 阶段、`scripts/verify_agent_generate_plan.py` 与 `verify_deepseek_generate_plan.py`；`agent_plan.py` 只抽出共享 key 公式），模型**不产出任何 key**，`validate_plan` / persist / Executor / 数据库 / 前端未改。8.4 Step 1：新增 **`agent_task_audits`**（migration `f3498529f573`）+ `services/agent_audit.py` + `schemas/agent_audit.py` + `GET .../audit` + `scripts/verify_agent_audit.py`；两个 stage 的**调用次数、Executor、Run Event/SSE、前端**未改。**八次里只有这一次动了数据库（新增一张审计表）** |

---

**架构由项目负责人确认，本任务不重新设计总体架构。**

## Request bodies on a plan step

`PlanStep` (and the `AgentStepResponse` mirror) carry two optional fields:

- `body` — the JSON request body the step sends, exactly as the plan states it.
  Any JSON value is valid: object, array, string, number, boolean or `null`.
- `body_present` — whether `body` is a body at all. Default `false`.

Both defaults keep every pre-existing plan readable: a plan that predates these
fields has no body, which is exactly what `body_present: false` means. The two
fields exist because `body: null` alone cannot distinguish "this step sends the
JSON literal `null`" from "this step sends nothing", and those are different HTTP
requests.

**Generation.** For `application/json` request bodies the deterministic planner
derives the body from the parsed OpenAPI `requestBody` schema, never from the
model: an explicit `example`, `default`, `const`, `examples[].value`, or an `enum`
member wins; otherwise `object` is filled from its `required` properties (recursively),
`string` gets a non-empty value honouring `minLength`/`format`, `integer`/`number`
honour `minimum`, `array` takes one item from `items`. When a schema cannot be
satisfied honestly the step is left with no body (`body_present: false`) rather than
with an empty object that is certain to be rejected. multipart, form-urlencoded and
binary bodies are **not** supported and are not claimed to be.

**Persistence and execution.** The body is stored in the existing
`test_steps.config` JSONB blob as `body` plus `bodyPresent`. No column was added.
`run_steps` does not snapshot the body; the executor reads it through the existing
`run_steps.source_step_id` link, the same way it already reads `produces`. When
`bodyPresent` is true the executor passes the value as the JSON body of the request;
when it is false the request carries no body, which is the pre-existing behaviour.

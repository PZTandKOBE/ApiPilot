# Phase 6.2 Backend REST Contract

> 状态：**只读分析，未改任何代码。**
> 本文的每一条字段都回源码逐行核实，行号写在断言旁边。
> 代码沉默的地方一律进「待确认问题」（§16），不补猜测。
> 与 `phase-6-architecture.md` 的关系：那篇定的是 D1–D5；这篇把 D5 的 REST 半边落到具体 endpoint 与字段。

---

## 1. 文档目的

回答一个问题：**如果现在写 FastAPI，为了让 Run 功能从 Mock 切到真实 Backend，最少需要哪些 REST 能力，每个能力的载荷长什么样。**

三条约束贯穿全文：

1. **契约由代码倒推，不由惯例倒推。** `CreateRunInput`（`src/services/run.ts:49-59`）里的字段就是请求体，`RunDetail`（`src/types/run.ts:212-216`）就是详情响应。代码里没有的字段不进契约。
2. **接口声明 ≠ 需求。** `RunService` 上有一个方法没有任何生产调用方（§4），本文把它标成发现，不把它升级成需求。
3. **Mock 与真实 Backend 的每一处差异都写下来**（§12）。那是本文最有价值的部分——Mock 是"能跑通"的证明，不是"能上线"的证明。

---

## 2. 当前前端 Run 功能概况

| 项 | 现状 | 证据 |
|---|---|---|
| 类型 | `src/types/run.ts`：5 个 run 状态、5 个步骤状态、3 个断言状态、8 个事件名 | `types/run.ts:49-77`、`:236-246` |
| 服务边界 | `RunService` 五个方法，工厂返回 Mock | `services/run.ts:96-130`、`:139` |
| Store | `stores/runs.ts`，Pinia setup store，**不持久化** | `stores/runs.ts:38-47`（D3） |
| 视图 | `RunsView.vue`（列表）、`RunDetailView.vue`（详情） | `router/index.ts:113-125` |
| 组件 | `components/console/Run/*` 共 7 个 | 目录 |
| 执行 | **不存在**。Mock 在创建时把"会发生什么"一次性写成脚本 | `services/mock/run/script.ts:215-291` |
| 流 | 形状已定，传输未实现（无 `EventSource`） | `services/run.ts:129`；D5 |

前端实际参与的路径：**创建 → 读快照 → 订阅事件 → 取消**，四个动作全在 `stores/runs.ts` 里，组件只调用 store。

---

## 3. Frontend → Backend 数据关系

### 3.1 链路与连接字段

| 跳 | 连接字段 | 在哪写死 | id 从哪来 | 跨刷新是否稳定 |
|---|---|---|---|---|
| Project → Test Plan | `TestPlan.projectId` | `types/agent.ts:317`；`agentStore.projectPlans` 按此过滤 `stores/agent.ts:111-113` | `prj_orders` 等**编译期常量** | 稳定（常量，服务端从未见过） |
| Test Plan → Run | `Run.planId` | `types/run.ts:169`；创建时从 `input.planId` 抄 `mock/run/script.ts:41` | `plan_${spec.slug}` `mock/agent/plan.ts:519` | 稳定：由文档内容派生，同文档同 id |
| Spec → Plan | `TestPlan.specId` / `ApiSpec.id` | `types/agent.ts:318`、`:64` | `spec_${slug}`，`slug = ${slugify(title\|filename)}_${hashString(content)}` `mock/agent/parse.ts:564-566`、`:600` | 稳定：同文档重新上传保持同 id（`parse.ts:564` 注释即此意） |
| Run → RunScenario | `RunScenario.id` = `TestScenario.id` | `types/run.ts:139`；`script.ts:119` | `scenario_lifecycle_${endpointId}` 等 `mock/agent/plan.ts:176/220/284/389/420` | 稳定（由 endpoint id 派生） |
| RunScenario → RunStep | `RunStep.scenarioId` + `RunStep.id` = `TestStep.id` | `types/run.ts:115-116`；`script.ts:70-71` | `${endpoint.id}__${index}`、`${endpoint.id}__extract_${var}`、`assert__${index}` `mock/agent/plan.ts:82/101/116` | 稳定，但 `assert__${index}` 是**下标派生**（见 `phase-6-architecture.md` §7.2） |
| RunScenario → RunAssertion | `RunAssertion.scenarioId`、`RunAssertion.id` = `TestAssertion.id` | `types/run.ts:99-100`；`script.ts:90-91` | 计划生成器给出 | 稳定 |
| RunAssertion → RunStep（弱） | `RunAssertion.stepId = checkpointOf(scenario)` | `script.ts:94`、`:110-113`、`:123` | 该 scenario 里第一个 `kind==='assert'` 的步骤，否则最后一个步骤，否则 `null` | 稳定 |

**关键约定（后端必须遵守）**：`RunStep.id` 与 `RunAssertion.id` 是**回显**，不是新生成的。类型注释写得很直白——"the join key, echoed back by the server"（`types/run.ts:98`、`:117`）。后端一旦重命名这两个 id，详情页将渲染出一个所有状态都不更新的空壳（`utils/runState.ts:84-106` 的 `updateStep`/`updateAssertion` 靠 id 相等匹配，匹配不到就静默不改）。

### 3.2 唯一 session-scoped 的 id

```
runIdFrom = `run_${plan.id.replace(/^plan_/, '')}__${ordinal}`   script.ts:294-295
ordinal   = 服务实例内的自增计数器                                 mock/run/index.ts:77, :162
```

`ordinal` 随 `createMockRunService()` 重建而清零（`stores/runs.ts:39` 每次 store 实例化都调一次工厂）。**结论：Mock 的 run id 不跨刷新、不跨标签页、不跨进程。** 前端只把它当不透明字符串用（URL 参数 `router/index.ts:120`、`route.params.runId` `RunDetailView.vue:38-41`），所以真实 Backend 可以自由选择 id 格式，唯一硬约束是**URL 安全**（它进 path）。

---

## 4. Phase 6.2 Backend 必要能力

先从代码数调用方，再谈能力。`RunService` 五个方法在生产代码里的调用点：

| 方法 | 生产调用点 | 判断 |
|---|---|---|
| `createRun` | `stores/runs.ts:282` ← `RunsView.vue:44` ← 按钮 `RunsView.vue:60-68` | **真实需要** |
| `getRunDetail` | `stores/runs.ts:317` ← `loadRun` ← `openRun`（`RunDetailView.vue:44`）、`createRun`（`:289`） | **真实需要** |
| `cancelRun` | `stores/runs.ts:353` ← `RunDetailView.vue:112` ← 按钮 `:162` | **真实需要** |
| `subscribe` | `stores/runs.ts:195`（由 `loadRun` 在非终止态时调用 `:329-331`） | 需要，但本文只分析形状（§11），**Phase 6.2 不做传输**（§15） |
| `getRun` | **`src/` 内零调用**；全仓库唯一调用点是 `tests/run/service.spec.ts:400` | **不是需求**，见下 |

**最少能力（4 项 REST）**：

1. `POST /api/projects/{projectId}/runs` —— 接受完整载荷并建 run。依据 `stores/runs.ts:268-279`。
2. `GET /api/runs/{runId}` —— 返回 `RunDetail`（run + scenarios + `lastSeq`）。依据 `stores/runs.ts:317`；这是 D3 的刷新恢复路径，**必须**含 scenarios（`types/run.ts:199-211` 的注释解释了为什么不能靠本地计划 join）。
3. `POST /api/runs/{runId}/cancel` —— 依据 `stores/runs.ts:353`。
4. `GET /api/projects/{projectId}/runs` —— 依据 `stores/runs.ts:81-85`。**这是本文最重要的一条**：见 §7。

**明确不做的能力，以及为什么：**

| 不做 | 为什么 |
|---|---|
| `GET /api/runs/{runId}` 的"轻量版"（只回 `TestRun`） | 接口声明了 `getRun`（`services/run.ts:107`），但**没有任何生产代码调用它**。为了让声明"有用"而多开一个 endpoint 是让接口反过来驱动需求。`RunDetail.run` 本身就是 `TestRun`（`types/run.ts:213`），一个详情接口同时满足两者。 |
| Evidence / Report 独立接口 | 证据已经在详情载荷里逐步骤内嵌（§13）。 |
| Plan / Project / Spec 的 CRUD | 前端没有任何 service 方法或 store action 会调它们（§13）。 |
| SSE 传输 | 形状分析在 §11，实现是后续阶段；本文只固化载荷形状。 |
| 分页、鉴权、多租户 | 无代码依据，见 §16。 |

**诚实说明一处断裂**：上面第 4 项（列表）**前端今天没有任何代码会去调它**。`store.runs` 只在 `upsertRun`（`stores/runs.ts:126-131`）里被写，而 `upsertRun` 的四个调用点（`:170`、`:284`、`:319`、`:357`）全部要求"这个 run 已经知道 id"。见 §7。

---

## 5. REST API 总览

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/projects/{projectId}/runs` | 用完整载荷创建一次 run 并启动执行 |
| GET | `/api/projects/{projectId}/runs` | 列出某项目下的 run（列表页刷新后恢复） |
| GET | `/api/runs/{runId}` | run 快照：状态 + scenarios + `lastSeq` |
| POST | `/api/runs/{runId}/cancel` | 请求取消一个非终止态 run |

地址规则（不是惯例，是为了让两个动作不打架）：**集合操作挂在项目下，条目操作由 run 自己的 id 寻址。**
`POST/GET /api/projects/{projectId}/runs` 是同一个集合资源，路径必须一致；而 `GET /api/runs/{runId}` 与 `POST /api/runs/{runId}/cancel` 用的是 run 的全局唯一 id，正好对应 store 里 `getRunDetail(runId)`、`cancelRun(runId)` 的签名（`stores/runs.ts:317`、`:353`）——不需要为了地址多传一个 projectId。

约定：请求与响应均为 `application/json; charset=utf-8`；所有时间戳为 ISO-8601 且**必须带 `Z` 或固定 offset**（列表排序是字符串比较，见 §7）；`runId` 必须 URL 安全。

---

## 6. Run Create

### Endpoint

| 项 | 值 |
|---|---|
| Method | `POST` |
| Path | `/api/projects/{projectId}/runs` |
| 用途 | 把"一份计划 + 一份文档 + 一套环境变量"交给后端，建一条 run 记录并开始执行 |
| 依据 | Path 形状来自 `services/run.ts:135` 的 `TODO(backend phase)`；触发点 `stores/runs.ts:282` |

### Request

**Path Parameters**

| 参数 | 类型 | 说明 |
|---|---|---|
| `projectId` | string | 项目 id，如 `prj_orders`（`mock/projects.ts:13`） |

**Query Parameters**：无

**Request Body**（字段逐一来自 `CreateRunInput`，`services/run.ts:49-59`；构造点 `stores/runs.ts:268-279`）

| 字段 | 类型 | 来源 | 备注 |
|---|---|---|---|
| `projectId` | string | `stores/runs.ts:269` ← `projectStore.activeProjectId` | **与 path 重复**。前端今天会发；是否忽略由后端定（§14） |
| `planId` | string | `stores/runs.ts:270` ← `agentStore.activePlan.id` | `plan_${spec.slug}` |
| `plan` | `TestPlan` | `stores/runs.ts:272` ← `agentStore.activePlan` | **整份计划**：scenarios / steps / assertions 全在里面（`types/agent.ts:315-330`） |
| `specId` | string | `stores/runs.ts:273` ← `agentStore.currentSpec.id` | 元数据 id，不是文档 |
| `specDocument` | string | `stores/runs.ts:275` ← `agentStore.currentSpecDocument` | **OpenAPI 原文**。`ApiSpec` 不含 schema（`types/agent.ts:63-76`），合成请求必须靠原文 |
| `environmentId` | string | `stores/runs.ts:276` ← `projectStore.activeEnvironment.id` | 如 `env_orders_staging` |
| `variables` | `Record<string,string>` | `stores/runs.ts:277` ← `projectStore.variables` | 展开后的 `{{name}} → value`（`stores/project.ts:69-76`）。**含明文密钥** |
| `baseUrl` | string | `stores/runs.ts:278` ← `environment.baseUrl` | 与 `variables.baseUrl` 取值相同（`mock/projects.ts:25`） |

**载荷的三个特点（后端设计时必须知道）**：

1. **大**：`plan` 是一整棵 scenarios→steps→assertions 树；`specDocument` 是整份 OpenAPI 文本。两者都无压缩、无分块。
2. **冗余**：`projectId` 同时在 path 与 body；`plan.projectId` / `plan.specId` 又与顶层 `planId` / `specId` / `projectId` 重复；`specId` 与 `specDocument` 同时存在（`specId` 是 `specDocument` 的哈希派生，见 `mock/agent/parse.ts:564-566`）。
3. **敏感**：`variables` 的值里有 token（`mock/projects.ts:26`），且前端**已经丢弃了 `secret` 标志**（`types/project.ts:19` 有定义，`stores/project.ts:73-75` 的 `Object.fromEntries` 只保留 key/value）——所以后端**无法从载荷判断哪个值是密钥**。

**JSON 示例**（形状与 `stores/runs.ts:268-279` 一致；值取自 `mock/projects.ts` 与 `mock/agent/parse.ts` 的实际产物）

```json
{
  "projectId": "prj_orders",
  "planId": "plan_orders_openapi_1a2b3c4d",
  "plan": {
    "id": "plan_orders_openapi_1a2b3c4d",
    "projectId": "prj_orders",
    "specId": "spec_orders_openapi_1a2b3c4d",
    "name": { "text": "Orders API — checkout flow" },
    "goal": { "text": "Verify the order lifecycle end to end." },
    "riskLevel": "high",
    "status": "approved",
    "source": "generated",
    "generatedAt": "2026-09-19T08:00:00.000Z",
    "approvedAt": "2026-09-19T08:05:00.000Z",
    "rejectedAt": null,
    "rejectionReason": null,
    "scenarios": [
      {
        "id": "scenario_lifecycle_ep_post_api_orders",
        "index": 1,
        "name": { "key": "console.aiTest.plan.scenario.lifecycle" },
        "description": { "key": "console.aiTest.plan.scenario.lifecycleHint" },
        "riskLevel": "high",
        "expected": { "key": "console.aiTest.plan.expected.lifecycle" },
        "steps": [
          {
            "id": "ep_post_api_orders__0",
            "index": 0,
            "kind": "request",
            "description": { "text": "Create an order" },
            "endpointId": "ep_post_api_orders",
            "method": "POST",
            "path": "/api/orders",
            "produces": null,
            "consumes": []
          }
        ],
        "assertions": [
          {
            "id": "assertion_status_0",
            "kind": "status",
            "target": "status",
            "expected": "201",
            "description": { "text": "Order creation returns 201" }
          }
        ]
      }
    ]
  },
  "specId": "spec_orders_openapi_1a2b3c4d",
  "specDocument": "{\n  \"openapi\": \"3.0.3\",\n  \"info\": { \"title\": \"Orders API\", \"version\": \"1.0.0\" },\n  \"paths\": { … }\n}",
  "environmentId": "env_orders_staging",
  "variables": {
    "baseUrl": "https://api.stg.example.com",
    "order_id": "order_90021",
    "token": "stg_88d0fe13c4"
  },
  "baseUrl": "https://api.stg.example.com"
}
```

**后端必须自行复核的两件事**（前端都只做了 UI 层检查，`stores/runs.ts:252-263` 与 `mock/run/index.ts:154-160` 的注释都明说了"审批对话框是 UI 边界，不是安全边界"）：

1. `plan.status === 'approved'`。
2. `variables` 与 `baseUrl` 的一致性——前端不校验（`stores/runs.ts:278` 直接取 `environment.baseUrl`）。

### Response

**成功状态码**：`201 Created`

**Response Body**：`TestRun`（`types/run.ts:166-197`）。依据：Mock 的 `createRun` 返回 `stateOf(script).run`（`mock/run/index.ts:185`），store 直接 `upsertRun(run)`（`stores/runs.ts:284`）。

```json
{
  "id": "run_orders_openapi_1a2b3c4d__7",
  "projectId": "prj_orders",
  "planId": "plan_orders_openapi_1a2b3c4d",
  "planName": { "text": "Orders API — checkout flow" },
  "specId": "spec_orders_openapi_1a2b3c4d",
  "environmentId": "env_orders_staging",
  "baseUrl": "https://api.stg.example.com",
  "variableKeys": ["baseUrl", "order_id", "token"],
  "status": "queued",
  "createdAt": "2026-09-19T09:00:00.000Z",
  "startedAt": null,
  "finishedAt": null,
  "durationMs": null,
  "failure": null,
  "summary": {
    "scenarios": 4,
    "steps": 0,
    "assertions": 0,
    "passedSteps": 0,
    "failedSteps": 0,
    "passedAssertions": 0,
    "failedAssertions": 0
  }
}
```

**响应契约要点**：

- `status` 必须是五个之一（`types/run.ts:49-55`），否则 `isRunStatus` 守卫失败（`:63-64`）。
- **`variableKeys` 只回名字，绝不回值**（`types/run.ts:182-189` 明确定义）。前端把整份载荷当权威，后端若把 `variables` 原样回显，密钥会进入浏览器内存与可能的日志。
- `planName` 是 `LocalizedText`（`types/agent.ts:41`），可能是 `{ key }` 也可能是 `{ text }`。计划名可被用户改名，改后是 `{ text }`（`stores/agent.ts:353-359`）。
- `createdAt` 用于列表排序（`stores/runs.ts:84`，字符串比较）。

### Errors

| HTTP | 场景 | 前端期望的 `RunErrorCode` | 前端消费点 |
|---|---|---|---|
| 400 | 载荷缺字段 / `specDocument` 非法 | `create-failed` | `stores/runs.ts:293` → `RunErrorNote.vue:29` |
| 403 或 409 | `plan.status !== 'approved'` | `not-approved` | `stores/runs.ts:254-262`；i18n key `console.runs.errors.notApproved` 带 `{plan}` 参数（`src/locales/console/en-US.ts:587`） |
| 404 | `projectId` 未知 | `create-failed` | 同上 |
| 413 | `specDocument` 超限 | `create-failed` | 同上 |

**错误体必须能被映射成 `RunError`**：`{ code, messageKey, params? }`（`services/runError.ts:24-28`）。前端渲染的是 `t(messageKey, params)`，**不是 `code`**（`components/console/Run/RunErrorNote.vue:29`，注释 `:11-13` 明确说明）。见 §16 的"未知 key 会原样显示"风险。

---

## 7. Run List

### Endpoint

| 项 | 值 |
|---|---|
| Method | `GET` |
| Path | `/api/projects/{projectId}/runs` |
| 用途 | 让列表页在**刷新之后**仍能显示这个项目跑过什么 |
| 依据 | `stores/runs.ts:81-85` 的 `projectRuns` 计算属性 + `RunsView.vue:79`、`:92` |

**先说最重要的一条发现：前端今天无法从服务端列出 run。**

- `RunsView.vue:92` 渲染 `store.projectRuns`；`projectRuns` 是 `store.runs` 的过滤+排序结果（`stores/runs.ts:81-85`）。
- `store.runs`（`stores/runs.ts:47`）**只有一个写入函数** `upsertRun`（`:126-131`），其四个调用点分别是 `applyEvent`（`:170`）、`createRun`（`:284`）、`loadRun`（`:319`）、`cancelRun`（`:357`）——全部要求"这个 run 已经知道 id"。
- Store 里**没有任何 list action**，`RunService` 里**没有任何 list 方法**（`services/run.ts:96-130`）。

后果：刷新页面后 `runs` 为空 → `RunsView.vue:79` 走 `v-if="store.projectRuns.length === 0"` → 用户看到"还没有 run"的空态（`console.runs.empty`），而服务端可能存着几十条。列表页在**不刷新**的会话内是对的，一刷新就是错的。

这同时意味着：**这个接口建好之后，前端还需要一个 `listRuns` action 才能真正用上它**——那是前端改动，不在本文范围（§14 记录为待办）。

### Request

**Path Parameters**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `projectId` | string | 是 | 服务端**必须**按它过滤。前端拿到结果后还会自己再筛一遍（`projectRuns` 按 `run.projectId === activeProjectId` 过滤，`stores/runs.ts:83`），但那只是防御——不靠服务端过滤就等于每次全量下发 |

**Query Parameters**：无

**Request Body**：无

### Response

**成功状态码**：`200 OK`

**Response Body**：`TestRun[]`（`types/run.ts:166-197`）。**不含 scenarios**——这是刻意的：`types/run.ts:159-165` 的注释写明"列表不该为它不会绘制的载荷付费"，`RunDetailView` 也只在打开时才拉详情（`stores/runs.ts:49-55`）。

```json
[
  {
    "id": "run_orders_openapi_1a2b3c4d__7",
    "projectId": "prj_orders",
    "planId": "plan_orders_openapi_1a2b3c4d",
    "planName": { "text": "Orders API — checkout flow" },
    "specId": "spec_orders_openapi_1a2b3c4d",
    "environmentId": "env_orders_staging",
    "baseUrl": "https://api.stg.example.com",
    "variableKeys": ["baseUrl", "order_id", "token"],
    "status": "passed",
    "createdAt": "2026-09-19T09:00:00.000Z",
    "startedAt": "2026-09-19T09:00:01.120Z",
    "finishedAt": "2026-09-19T09:00:04.480Z",
    "durationMs": 3360,
    "failure": null,
    "summary": {
      "scenarios": 4,
      "steps": 11,
      "assertions": 9,
      "passedSteps": 11,
      "failedSteps": 0,
      "passedAssertions": 9,
      "failedAssertions": 0
    }
  }
]
```

**响应契约要点**：

- 列表**必须由服务端排序**（`createdAt` 降序，新→旧）。前端会再排一次（`stores/runs.ts:84` 的 `b.createdAt.localeCompare(a.createdAt)`），但那句是**字符串比较**：如果服务端下发 `+08:00` 偏移而另一条下发 `Z`，字典序会给出错误的先后。**统一 `Z`**。
- `summary` 必须由服务端算对。列表页的三个数字直接读它（`RunsView.vue:34-35`）。注意：前端在有事件流时**会用自己的折叠结果覆盖它**（`utils/runState.ts:65-69` 的 `withSummary`），所以在详情页里服务端的 summary 是过渡值；但在列表页——没有订阅、只有快照——服务端的值是**唯一**来源。
- `planName` 必须是 run 创建时冻结的副本（`types/run.ts:170` 注释；Mock 在 `script.ts:41-44` 抄了一份）。计划改名/重新生成后，历史 run 的名称不能跟着变。

### Errors

| HTTP | 场景 | 前端期望 |
|---|---|---|
| 200 + `[]` | 项目没有 run | 正常空态（`RunsView.vue:79-89`） |
| 4xx/5xx | 任意失败 | `console.runs.errors.loadFailed` 一类的 key；但**今天的代码路径不存在**，错误呈现方式由新 action 决定 |

### 分页

`Phase 6.2 暂不需要分页`

依据：前端没有任何分页 UI、没有分页状态、没有 `page`/`limit` 的消费方；`RunsView.vue:92` 一次性 `v-for` 整个数组。

---

## 8. Run Detail

### Endpoint

| 项 | 值 |
|---|---|
| Method | `GET` |
| Path | `/api/runs/{runId}` |
| 用途 | 一次 run 的完整快照：状态 + 全部 scenarios/steps/assertions + 流的高水位 |
| 依据 | `stores/runs.ts:317`（`loadRun` 里唯一的服务调用）；类型 `types/run.ts:212-216` |

### Request

**Path Parameters**

| 参数 | 类型 | 说明 |
|---|---|---|
| `runId` | string | 必须 URL 安全；前端从 `route.params.runId` 取出（`RunDetailView.vue:38-41`） |

**Query Parameters**：无

**Request Body**：无

### Response

**成功状态码**：`200 OK`

**Response Body**：`RunDetail` = `{ run, scenarios, lastSeq }`（`types/run.ts:212-216`）。

```json
{
  "run": {
    "id": "run_orders_openapi_1a2b3c4d__7",
    "projectId": "prj_orders",
    "planId": "plan_orders_openapi_1a2b3c4d",
    "planName": { "text": "Orders API — checkout flow" },
    "specId": "spec_orders_openapi_1a2b3c4d",
    "environmentId": "env_orders_staging",
    "baseUrl": "https://api.stg.example.com",
    "variableKeys": ["baseUrl", "order_id", "token"],
    "status": "running",
    "createdAt": "2026-09-19T09:00:00.000Z",
    "startedAt": "2026-09-19T09:00:01.120Z",
    "finishedAt": null,
    "durationMs": null,
    "failure": null,
    "summary": { "scenarios": 4, "steps": 11, "assertions": 9, "passedSteps": 3, "failedSteps": 0, "passedAssertions": 0, "failedAssertions": 0 }
  },
  "scenarios": [
    {
      "id": "scenario_lifecycle_ep_post_api_orders",
      "index": 1,
      "name": { "key": "console.aiTest.plan.scenario.lifecycle" },
      "riskLevel": "high",
      "status": "running",
      "steps": [
        {
          "id": "ep_post_api_orders__0",
          "scenarioId": "scenario_lifecycle_ep_post_api_orders",
          "index": 0,
          "kind": "request",
          "description": { "text": "Create an order" },
          "endpointId": "ep_post_api_orders",
          "method": "POST",
          "path": "/api/orders",
          "status": "passed",
          "durationMs": 142,
          "failure": null,
          "evidence": [
            { "label": { "key": "console.runs.evidence.endpoint" }, "value": "POST /api/orders" }
          ]
        }
      ],
      "assertions": [
        {
          "id": "assertion_status_0",
          "scenarioId": "scenario_lifecycle_ep_post_api_orders",
          "stepId": "assert__1",
          "kind": "status",
          "target": "status",
          "expected": "201",
          "actual": "201",
          "status": "passed",
          "description": { "text": "Order creation returns 201" }
        }
      ]
    }
  ],
  "lastSeq": 12
}
```

**字段分级**

**「当前真正需要」**（详情页今天就在画）：

| 字段 | 渲染点 |
|---|---|
| `run.status` | `RunDetailView.vue:160`（`RunStatusTag`） |
| `run.planName` | `:146`、`:197` |
| `run.environmentId` | `:204` |
| `run.baseUrl` | `:211` |
| `run.variableKeys` | `:220`（空数组时显示 `console.common.none`） |
| `run.createdAt` / `finishedAt` / `durationMs` | `:230` / `:236` / `:244`（后两个为 `null` 时整项不渲染） |
| `run.failure` | `:250-252` → `RunFailureNote.vue:29`、`:33` |
| `scenarios[].id` | `RunScenarioCard.vue:58`（`:key`） |
| `scenarios[].index` / `name` / `riskLevel` / `status` | `:33` / `:36` / `:41` / `:42` |
| `scenarios[].steps[].id` | `RunStepRow.vue` 的 `:key`（`RunScenarioCard.vue:55`） |
| `steps[].index` / `kind` / `method` / `path` / `status` / `description` | `RunStepRow.vue:56` / `:63` / `:70-74` / `:75` / `:84` / `:88` |
| `steps[].durationMs` | `:48-50`、`:78-83`（`null` 则不渲染） |
| `steps[].evidence[]` | `:94-111`（`label` 经 `localize`，`value` 原样等宽显示） |
| `steps[].failure` | `:113` |
| `assertions[].status` / `description` / `expected` / `actual` | `RunAssertionRow.vue:26` / `:28` / `:36` / `:46`（`actual === null` 渲染 `—`） |
| `lastSeq` | `stores/runs.ts:323`（高水位）、`:199`（`fromSeq`） |

**「类型里有、当前未使用」**（后端仍应下发，理由见括号）：

| 字段 | 状态 |
|---|---|
| `run.projectId` | 只被 store 用于过滤（`stores/runs.ts:83`），不渲染 |
| `run.planId` / `run.specId` | 全仓库的 Run 视图/组件内零渲染 |
| `run.startedAt` | 只被 reducer 写入（`utils/runState.ts:157`），零渲染 |
| `run.summary.passedSteps` / `failedSteps` / `passedAssertions` / `failedAssertions` | 列表只用 `scenarios`/`steps`/`assertions` 三个（`RunsView.vue:34-35`），四个 pass/fail 计数**无渲染点** |
| `steps[].endpointId` | 零渲染（渲染的是 `method` + `path`） |
| `steps[].scenarioId` | reducer 用它定位（`utils/runState.ts:90-93`），UI 不读 |
| `assertions[].kind` / `target` / `stepId` | `RunAssertionRow.vue` 只画 status/description/expected/actual |
| `assertions[].scenarioId` | reducer 定位用（`utils/runState.ts:101-105`） |

**保留这些字段的理由**：`summary` 的四个计数是列表的排序/统计扩展点；`scenarioId`/`stepId` 是 reducer 的定位键——**删掉它们，`applyRunEvent` 就无法把事件落到正确的步骤上**（`utils/runState.ts:84-106`）。所以"未使用"≠"可以省略"。

### Errors

| HTTP | 场景 | 前端行为 | 证据 |
|---|---|---|---|
| 404 | run 不存在 | 页面显示 not-found 空态（`console.runs.notFound`），**不是**错误条 | `stores/runs.ts:325` 写 `error`；`RunDetailView.vue:72-74` 的 `notFound` 只依赖 `detail === null && !loading`。Mock 抛 `run-not-found`（`mock/run/index.ts:65-70`） |
| 5xx / 网络失败 | 服务不可达 | `store.error` → `RunErrorNote` | `RunDetailView.vue:186-190` |

---

## 9. Run Cancel

### Endpoint

| 项 | 值 |
|---|---|
| Method | `POST` |
| Path | `/api/runs/{runId}/cancel` |
| 用途 | 请求停止一个非终止态 run，返回它此刻的状态 |
| 依据 | `stores/runs.ts:353`；按钮与确认框 `RunDetailView.vue:96-113`、`:162` |

### Request

**Path Parameters**

| 参数 | 类型 | 说明 |
|---|---|---|
| `runId` | string | 同上 |

**Query Parameters**：无

**Request Body**：无（`services/run.ts:118-123` 的签名只接受 `runId`）

### Response

**成功状态码**：`200 OK`

**Response Body**：`TestRun`（`services/run.ts:123` 明确"Returns the run as it stands"）。

```json
{
  "id": "run_orders_openapi_1a2b3c4d__7",
  "projectId": "prj_orders",
  "planId": "plan_orders_openapi_1a2b3c4d",
  "planName": { "text": "Orders API — checkout flow" },
  "specId": "spec_orders_openapi_1a2b3c4d",
  "environmentId": "env_orders_staging",
  "baseUrl": "https://api.stg.example.com",
  "variableKeys": ["baseUrl", "order_id", "token"],
  "status": "cancelled",
  "createdAt": "2026-09-19T09:00:00.000Z",
  "startedAt": "2026-09-19T09:00:01.120Z",
  "finishedAt": "2026-09-19T09:00:02.600Z",
  "durationMs": 1480,
  "failure": null,
  "summary": { "scenarios": 4, "steps": 11, "assertions": 9, "passedSteps": 1, "failedSteps": 0, "passedAssertions": 0, "failedAssertions": 0 }
}
```

**取消流程是否已经打通？** 端到端**是通的**，但有一处依赖需要后端知道：

1. UI 把关：按钮在 `cancelling || detail === null || isTerminalRunStatus(status)` 时禁用（`RunDetailView.vue:79-81`、`:162`）。
2. 确认框是决策本身，取消对话框读作"否"（`:100-108`）。
3. `store.cancelRun` 只做 `upsertRun`，**不更新 `details`**（`stores/runs.ts:353-358`）。注释（`:355-356`）说明原因：终止事件已经沿流送达，这个响应只是对账。
4. 详情页读的是 `details`（`RunDetailView.vue:57-61`），所以**如果终止事件没到，取消响应本身不会让页面变成 cancelled**。真实 Backend 必须保证 `run.cancelled` 事件送达，或前端在取消后主动重取快照。见 §16。
5. `applyEvent` 在 run 进入终止态时自动 `unsubscribe`（`stores/runs.ts:172`）。

**取消一个已经终止的 run**：Mock 直接返回当前状态、不抛错、不二次转换（`mock/run/index.ts:200-202` 及注释），测试锁定该行为（`tests/run/service.spec.ts:320-328`：一个 `passed` 的 run 取消后仍是 `passed`）。**建议后端保持一致**——理由不是兼容性，而是 UI 已经禁用了按钮，这条路径只可能由竞态触发，此时返回 409 只会把一个无害的竞态变成用户可见的错误。

### Errors

| HTTP | 场景 | 前端期望的 `code` | 证据 |
|---|---|---|---|
| 404 | run 不存在 | `run-not-found` | `mock/run/index.ts:65-70`、`:92-96` |
| 409 | （可选）run 已终止 | 建议改为 `200` + 当前状态，见上 | `mock/run/index.ts:202` |
| 5xx | 取消失败 | `cancel-failed` | 声明于 `services/runError.ts:18`，**但今天没有任何代码构造它**（§16）；fallback key `console.runs.errors.cancelFailed` 在 `stores/runs.ts:360` |

---

## 10. Run / Test Plan 关系

一句话：**Run 是计划的一次执行记录，不是计划的一部分。**

| 维度 | 事实 | 证据 |
|---|---|---|
| 所有权 | Run 归 Backend（D3）。前端只在内存里缓存它正在看的那些 | `stores/runs.ts:22-27`、`:46-55` |
| 引用方式 | Run 持有 `planId` + **冻结的** `planName`，不持有计划对象 | `types/run.ts:169-170` |
| 步骤来源 | run 的步骤从服务端载荷来，**从不 join 本地计划** | 类型注释 `types/run.ts:16-19`；`RunScenarioCard.vue:14-17`；store `loadRun` 只写 `detail`（`stores/runs.ts:317-322`） |
| 理由 | 计划会被同 id 原地替换（`stores/agent.ts:280-282` 的"同 id 即同文档，重新生成覆盖"），join 本地计划会把已完成的 run 重绘成从未跑过的步骤 | `stores/agent.ts:121-123`、`types/run.ts:203-210` |
| 计划的生命周期 | 生成于浏览器（`services/agent.ts:105`）、审批于浏览器（`stores/agent.ts:318-330`）、持久化于 `localStorage`（`stores/agent.ts:30`、`:65-67`） | 三处 |
| 对后端的含义 | **后端从未见过任何一份 plan**，`planId` 对它是一个不透明字符串。它拿到的只有 `CreateRunInput.plan` 这一整份对象 | `services/run.ts:31-38` 的注释即为这条 |

**由此推出的一条硬约束**：后端回显的 `RunStep.id` / `RunScenario.id` / `RunAssertion.id` 必须与请求里 `plan` 的 id **逐字节相同**（`types/run.ts:98`、`:117`；匹配逻辑 `utils/runState.ts:84-106`）。前端不按"第几个"匹配，只按 id 相等匹配。

---

## 11. RunEvent 与未来 SSE

> **本节只做形状分析，不实现任何东西。**

### 11.1 事件形状是否够用

现有形状（`types/run.ts:257-343`）：每种事件 = `{ type, runId, seq, at }` + 该类型的载荷；步骤类事件再加 `scenarioId` + `stepId`（`:264-267`）。共 8 个判别成员（`:236-245`）。

对 store → reducer 这条链，**8 个事件名与它携带的载荷足以驱动全部状态迁移**：

| reducer 分支 | 需要事件里的什么 | 位置 |
|---|---|---|
| `run.started` | `startedAt` | `utils/runState.ts:154-158` |
| `step.started` / `step.completed` / `step.failed` | `scenarioId`+`stepId`（定位）、`durationMs`、`evidence`、`failure` | `:160-203` |
| `assertion.completed` | `scenarioId`+`assertionId`（定位）、`status`、`expected`、`actual` | `:205-219` |
| `run.completed` / `run.failed` / `run.cancelled` | `finishedAt`、`durationMs`、`failure` | `:221-256` |

三条约束（后端必须满足）：`seq` 在一次 run 内**严格递增**（`:149` 的 `event.seq <= detail.lastSeq` 丢弃规则）；`runId` 与快照一致（`:147`）；终止事件之后不再有非终止事件（`:148` 的"完成后吸收迟到事件"）。

### 11.2 resume 路径：`lastSeq` 怎么到达服务端

前端侧是明确的：

1. 快照带来 `lastSeq`（`types/run.ts:215`）。
2. Store 写高水位 `Math.max(旧值, detail.lastSeq)`（`stores/runs.ts:323`）——只进不退。
3. 订阅时作为 `fromSeq` 交出：`fromSeq: lastSeq.get(runId) ?? 0`（`stores/runs.ts:199`）。
4. 服务契约定义语义："Events at or below this `seq` are not re-delivered"（`services/run.ts:86-91`）。

**但传输层是空白的**：`subscribe` 是一个 TS 方法（`services/run.ts:129`），代码里没有 `EventSource`、没有 URL、没有 query 约定。这就是 `疑似缺口` 的第一条。

### 11.3 一条真实的硬要求：服务端必须能**回放**

前端**不缓冲**事件：`applyEvent` 在没有对应 detail 时直接丢弃（`stores/runs.ts:159-160`），注释说明这是刻意的（"the next snapshot will carry everything up to a later seq"）。这意味着：

> **服务端必须为整个 run 生命周期保留可回放的事件序列，并支持从任意 `fromSeq` 重放。** 只推"当前正在发生"的实时流是不够的：快照与订阅之间有一条缝，缝里的事件会永久丢失。

Mock 正是这么做的（`mock/run/index.ts:245-252`：把 `seq > fromSeq` 的已发生事件全部补发），并且它因此要求"脚本在第一个事件送达前就已写完整份"（`script.ts:206-214` 的注释）。**这是 Mock 给真实 Backend 的最有价值的一条规格。**

同理，终止事件必须**持久化**：`loadRun` 在 run 已终止时不会订阅（`stores/runs.ts:329-331`），所以已结束的 run 只能靠快照显示结果。

### 11.4 `疑似缺口`

以下是事件/流形状在后续阶段**可能需要**、而当前类型里**不存在**的东西（**本阶段不添加，仅记录**）：

1. **`fromSeq` 的传输格式未定义。** 浏览器原生 `EventSource` 不能自定义 header、不能带 body，所以只能走 query（如 `?fromSeq=N`）。代码里没有任何一行规定它，这是 Phase 6.3 要拍的第一件事。
2. **失败步骤没有证据通道。** `StepFailedEvent`（`types/run.ts:299-303`）只有 `durationMs` + `failure`，没有 `evidence`；reducer 在 `step.failed` 分支也不写 evidence（`utils/runState.ts:189-203`）。一个有 500 响应体的失败步骤，今天在 UI 上只能显示一句 `failure.detail`（`RunStepRow.vue:113`），无法展示"返回了什么"。
3. **没有流内的心跳/保活/重连提示。** 都是传输层问题，类型里没有位置放。
4. **没有"服务端执行器崩溃"的区分。** 流中断走的是 out-of-band 的 `onError`（`services/run.ts:84`）；store 收到后只清订阅、留一个 `error`（`stores/runs.ts:201-205`），页面会停在"following"直到刷新。要么靠服务端保证任何终止都发一条终止事件，要么后续补一个事件类型。
5. **事件不带 `summary`。** 前端自己重算（`utils/runState.ts:46-63`），这是对的；但列表页没有流，只能靠 REST 的 `summary`（§7）——两处必须算得出同一个数。
6. **`seq` 的作用域未写明**（是否跨 run 唯一）。前端只做"同 run 内单调递增"的假设（`utils/runState.ts:149`），所以后端可以让 `seq` 从 1 开始 per run。

---

## 12. 当前 Mock 暗含的 Backend 行为

### 12.1 Mock 的行为

| 行为 | 做法 | 位置 |
|---|---|---|
| run id | `run_${planId去掉plan_前缀}__${ordinal}`，`ordinal` 是服务实例内的自增计数 | `script.ts:294-295`；`mock/run/index.ts:77`、`:162` |
| 创建即启动 | `createRun` 内部 `schedule(script)`，不等订阅者 | `mock/run/index.ts:182-183` |
| 状态迁移 | 初始 `queued` → `run.started` → `running` → 三个终止事件分别落到 `passed`/`failed`/`cancelled`；**没有反向迁移**，终止后一切事件被吸收 | `script.ts:51`；`utils/runState.ts:154-158`、`:221-256`、`:148` |
| `seq` 分配 | 生产者 `emit` 分配，从 1 开始密集递增，0 表示"什么都还没发生" | `script.ts:129`、`:162-165` |
| 取消时的 `seq` | 截断未发生的脚本，用 `emitted + 1` 追加 `run.cancelled` | `mock/run/index.ts:209-220` |
| 步骤/断言产出 | 从计划的 `scenarios` 一次性构造，`status` 初始 `pending`/`skipped` | `script.ts:68-130` |
| join | 事件里的 `stepId`/`assertionId` 就是计划的 `TestStep.id`/`TestAssertion.id`（回显） | `script.ts:70`、`:90` |
| 断言挂点 | `checkpointOf(scenario)`：第一个 `kind==='assert'` 的步骤，否则最后一个步骤，否则 `null` | `script.ts:110-113`、`:123` |
| `planId`/`projectId`/`environmentId` | 创建时从 `CreateRunInput` 抄进 `TestRun`，**事件从不携带它们** | `script.ts:38-66` |
| 错误暴露 | REST 方法抛 `RunServiceError`（`run-not-found`、`not-approved`）；`subscribe` 对未知 run 走 `onError` 而不是抛 | `mock/run/index.ts:65-70`、`:94`、`:156`、`:230-234` |
| 终止判定 | 唯一的失败原因：`kind === 'request' && endpointId === null` → `step.failed` + `run.failed`，其余场景被跳过；否则 `run.completed` | `script.ts:144-147`、`:234-256`、`:278-288` |
| 快照 | `getRunDetail` 用**与客户端同一个 reducer** 折叠已发生事件 | `mock/run/index.ts:81-90` |
| 时长 | `120 + index * 40` ms，由步骤位置**算出**，不是测得 | `script.ts:33` |
| 断言实测值 | `status` 直接回显 `expected`；`header`/`field` 回 `'present'`；其余回 `'matches'` | `script.ts:193-204` |
| 证据 | 从计划自身字段生成：`${method} ${path}`、`produces` 名、断言条数 | `script.ts:168-190` |
| 时间戳 | 浏览器时钟 `new Date().toISOString()` | `script.ts:35` |

### 12.2 Mock 与真实 Backend 的差异

| 位置 | Mock 的做法 | 真实 Backend 必须怎么做 |
|---|---|---|
| `script.ts:294-295` + `mock/run/index.ts:77` | run id 由计划 id + 实例内计数器拼出，**进程重启即重置** | 服务端签发全局唯一、可持久、URL 安全的 id；前端只把它当不透明字符串（`RunDetailView.vue:38-41`） |
| `mock/run/index.ts:75` | 全部 run 存在一个 `new Map()` 里，实例销毁即全部消失 | 必须持久化：刷新页面后 `GET /api/runs/{id}` 与 `GET /api/projects/{projectId}/runs` 都要答得出来（`stores/runs.ts:317`） |
| `mock/run/index.ts:182-183` | 创建时立刻 `schedule()` 启动，**在上一条 HTTP 响应返回前**就已推进 | 必须异步执行：`create` 返回时 run 只需"存在且可读"；前端紧接着就会拉快照（`stores/runs.ts:289`），此时 run 可能还是 `queued` |
| `script.ts:33` | 步骤耗时按位置编造 | 实测每个请求的耗时 |
| `script.ts:193-204` | 断言的 `actual` 编造（`'present'` / `'matches'`） | 从真实响应里取值；`actual: null` 表示"没有可比的东西"（`types/run.ts:107-108`，UI 渲染 `—`，`RunAssertionRow.vue:46`） |
| `script.ts:168-190` | evidence 从计划字段编造（"Requested POST /api/orders"实际从未发出） | 真实请求/响应产物。`AgentEvidence.value` 是 `string`（`types/agent.ts:197-201`），`label` 是 `LocalizedText`——**服务端要么用前端字典里已有的 key，要么用 `{ text }` 原文**。今天的 evidence key 只有三个（`console.runs.evidence.endpoint/extracted/checked`，`src/locales/console/en-US.ts:595-600`） |
| `script.ts:35` | `at`/`startedAt`/`finishedAt` 取浏览器时钟 | 服务端时钟。类型注释明确 `at` 是"when the **server** observed the event"（`types/run.ts:252-256`） |
| `script.ts:144-147` | 唯一的失败原因，`detail` 是硬编码英文 `'the step names no endpoint'` | 真实失败原因有很多种。`failure.detail` 是原样显示的机器语言（`RunFailureNote.vue:33-35`），可以是任意字符串；但 `failure.message` 若用 `{ key }`，该 key **必须存在于前端字典**（今天只有 `console.runs.failure.notExecutable`，`en-US.ts:604`），否则用户看到的是 key 本身 |
| `types/run.ts:299-303` | `step.failed` 不带 evidence | 同上 §11.4 第 2 条：想报告失败的响应体，今天的形状里没有位置 |
| `script.ts:215-291` | 整份脚本在第一个事件前写死，因此可以任意截断（`:209`） | 事件只能**边发生边产生**；"未来"不能预先知道，取消不能靠截断 |
| `mock/run/index.ts:62`、`:104-112` | 订阅者集合在内存里，同一 run 支持多订阅者 | 真实 fan-out：两个浏览器标签页是两个客户端，各自可带不同的 `fromSeq`（`stores/runs.ts:199`） |
| `mock/run/index.ts:245-252` | 订阅时补发 `seq > fromSeq` 的历史事件 | **必须等价实现**（§11.3）：可回放的事件缓冲 + 从任意 `fromSeq` 重放 |
| `mock/run/index.ts:202` | 取消已终止 run：返回当前状态，不报错 | 建议一致（§9），否则 Race 会把无害竞态变成可见错误 |
| `mock/run/index.ts:216-219` | 取消 `queued` run 时 `durationMs: 0` | 需自行定义（`0` 或 `null`）；UI 对两者都处理（`RunDetailView.vue:241-246` 判 `null` 才隐藏） |
| `mock/run/index.ts:75` | 无鉴权、无租户隔离，`runs` 是全局的 | 至少按 `projectId` 隔离；`projectId` 目前由客户端过滤（`stores/runs.ts:83`），服务端不能依赖这一点 |
| `script.ts:50` | `variableKeys` = `Object.keys(variables).sort()`，值被丢弃 | 同样只存/回名字（`types/run.ts:182-189`）。**注意 `secret` 标志在前端已丢失**（`stores/project.ts:73-75`），服务端无法分辨哪个值是密钥 |
| `tests/run/service.spec.ts:362-385` | 同一计划两次创建产生逐字节相同的事件序列 | 真实执行不确定，**这条特性不要移植到后端**——它是 Mock 的可测试性设计，不是契约 |

---

## 13. 与旧 v0.2 API 设计的差异

旧设计（项目早期文档，**不在本仓库**）提出：

```
POST   /api/projects                    GET  /api/projects/{id}
POST   /api/projects/{id}/spec          GET  /api/projects/{id}/spec
POST   /api/projects/{id}/plans         GET  /api/plans/{id}
PATCH  /api/plans/{id}                  POST /api/plans/{id}/approve
POST   /api/plans/{id}/run
GET    /api/runs/{id}                   GET  /api/runs/{id}/evidence
GET    /api/runs/{id}/report
```

逐条裁决：

| 旧接口 | 裁决 | 依据 |
|---|---|---|
| `POST /api/projects` | **后置** | 前端没有任何 project 写操作；项目来自编译期常量（`stores/project.ts:29` ← `mock/projects.ts:11`），没有创建项目的 UI |
| `GET /api/projects/{id}` | **后置** | `projectById` 读同一份常量（`stores/project.ts:78-79`），无网络调用 |
| `POST /api/projects/{id}/spec` | **后置** | 文档今天由浏览器解析并存在 `localStorage`（`stores/agent.ts:59-63`、`utils/agentStorage.ts:203-206`）。它**随每次 create-run 一起下发**（`services/run.ts:56`），所以这一阶段后端不需要独立的上传入口 |
| `GET /api/projects/{id}/spec` | **后置** | 同上；`currentSpecDocument` 是本地读取（`stores/agent.ts:105-109`） |
| `POST /api/projects/{id}/plans` | **放弃（本阶段）** | 计划在浏览器里生成（`services/agent.ts:105`），没有任何调用方 |
| `GET /api/plans/{id}` / `PATCH /api/plans/{id}` | **放弃（本阶段）** | 计划列表与改名都是 store 内部操作（`stores/agent.ts:353-359`），零网络调用 |
| `POST /api/plans/{id}/approve` | **放弃（本阶段）** | 审批是 `stores/agent.ts:318-330` 的本地写。**但注意**：审批若只留在客户端，后端就必须自己重判 `approved`（`services/run.ts:44-47`）——所以"审批上移到服务端"是一个独立且更大的决策，不该顺手塞进 Phase 6.2 |
| `POST /api/plans/{id}/run` | **放弃** | 见下 |
| `GET /api/runs/{id}` | **保留** | 与 `getRunDetail` 一一对应（`stores/runs.ts:317`） |
| `GET /api/runs/{id}/evidence` | **后置** | 见下 |
| `GET /api/runs/{id}/report` | **后置** | 见下 |
| （旧表未列）`GET /api/projects/{projectId}/runs` | **新增** | `stores/runs.ts:81-85` + `RunsView.vue:79`、`:92`；见 §7 |
| （旧表未列）`POST /api/runs/{id}/cancel` | **新增** | `stores/runs.ts:353` |

### 为什么 `POST /api/plans/{id}/run` 不再成立

四条理由，全部来自代码：

1. **后端从未见过那份计划。** 计划由浏览器生成（`services/agent.ts:105`），持久化在 `localStorage` 的 `aiata.console.agentPlans`（`stores/agent.ts:30`、`:65-67`），id 是 `plan_${spec.slug}`（`mock/agent/plan.ts:519`），而 `slug` 由**文档内容**哈希得出（`mock/agent/parse.ts:564-566`）。一个 `planId` 指向的是服务端既没有、也无法按 id 找回的东西。`services/run.ts:31-38` 的注释把这条写死了："An id alone would name something the server cannot look up."

2. **计划 id 不足以表达"跑在哪"。** 一次 run 的目标是**项目环境**：`baseUrl` + 一整套变量（`stores/project.ts:53-76`、`mock/projects.ts:18-51`）。同一个计划在 Development 和 Production 上跑是两件正当且不同的事，环境由 `activeEnvironmentId`（`stores/project.ts:37-41`）在运行时选择，**不在计划里**。所以 run 的创建必须携带 `environmentId` + `variables` + `baseUrl`，这三个字段（`services/run.ts:55-58`）在 `POST /api/plans/{id}/run` 里无处安放。

3. **计划 id 也不足以表达"用哪份文档"。** D1 要求后端自行合成请求，而合成的依据是文档原文（`services/run.ts:36-38`）。文档今天不在服务端。

4. **旧接口隐含"计划归后端所有"，那是一条远比载荷大小更贵的路。** 要让 `POST /api/plans/{id}/run` 成立，得先把整条链搬上服务端：`POST /api/projects/{id}/plans` 生成计划、`PATCH` 编辑、`POST /approve` 审批、`GET` 取回——**四个接口 + 计划生成逻辑 + 审批状态的服务端权威**，而这一切都只是为了省掉请求体里的一个 `plan` 字段。当前载荷确实大（整份计划 + 整份文档），但那是**一次请求的大小**，且它换来的是"前端不需要把计划搬到服务端"这件事（D3 的依赖方向、`stores/agent.ts:121-123` 的本地计划生命周期全部不受影响）。Phase 6.2 选后者。

**结论：`POST /api/projects/{projectId}/runs` 保留 `plan` 与 `specDocument` 在请求体里，`POST /api/plans/{id}/run` 删除。** 如果将来确实要把计划搬到服务端，那是一次独立的重构，不是给旧接口留一个空壳。

### 为什么 Evidence / Report 不该单独开接口

- **Evidence 已经在详情载荷里，而且已经在渲染。** `RunStep.evidence` 是 `RunDetail.scenarios[].steps[].evidence` 的一部分（`types/run.ts:133`），`RunStepRow.vue:94-111` 直接遍历它。开一个 `GET /api/runs/{id}/evidence` 只会返回一份已经被 `GET /api/runs/{id}` 返回过的数据。**建议：不建，而不是建一个空接口占位。**
- **Report 没有任何消费方。** 全仓库没有导出、下载、打印、分享的 UI；`RunSummary` 是前端从 scenarios 现算的（`utils/runState.ts:46-63`），列表页用的也是它（`RunsView.vue:34-35`）。没有代码需要"报告"这个物件。
- 唯一可能给它们翻案的理由是"证据太大，不想塞进详情响应"——**当前没有代码支持这个担忧**，也没有任何体积测量。真出现这个需求时再加，成本是新增一个接口，不是改一个已有接口。

### Project / Spec / Plan 的 CRUD 该去哪

**§15（暂时不做）**，不是 §5。理由统一：**前端没有任何 service 方法或 store action 会调用它们。** 已核实的调用面只有四处——`projectStore` 读常量（`stores/project.ts:29`）、`agentStore` 读 `localStorage`（`stores/agent.ts:59-67`）、计划生成走本地 mock（`services/agent.ts:105`）、文档解析走本地 mock（`services/agent.ts:83`）。在这四处被替换之前，为它们建接口是纯粹的空转。

---

## 14. Phase 6.2 必须确定

- [ ] `POST /api/projects/{projectId}/runs`：`projectId` 同时出现在 path 与 body，后端取哪个、是否忽略 body 中的同名字段。
- [ ] `GET /api/runs` 是否按 `projectId` 过滤，还是返回全部由客户端筛（`stores/runs.ts:83` 已经在客户端筛）。
- [ ] 错误体的线上形状：HTTP status ↔ `RunErrorCode`↔ `messageKey` 的映射表。前端只认 `RunServiceError.detail`（`services/runError.ts:34-42`），**传输格式在代码里完全未定义**。
- [ ] `messageKey` 的取值范围：**只能使用前端字典已有的 key**，还是允许服务端自定义 key（那样用户会看到点号字符串，见 §16）。
- [ ] run id 的格式与 URL 安全性（它进 path：`router/index.ts:120`、`RunDetailView.vue:38`）。
- [ ] 服务端是否存储 `variables` 的**值**（只回 `variableKeys`）。若存，落库时的加密与保留期。
- [ ] `plan.status === 'approved'` 的服务端复核，以及拒绝时的错误码（建议 `not-approved`，参数 `plan`）。
- [ ] `specDocument` 每次创建都传，还是有大小上限/后续改为按 `specId` 引用。
- [ ] 终止态 run 必须能从 REST 快照独立读全（因为前端对已终止 run 不再订阅，`stores/runs.ts:329-331`）。
- [ ] `summary` 由服务端算还是前端算。前端在详情页会覆盖它（`utils/runState.ts:65-69`），但列表页只信服务端（`RunsView.vue:34`）。
- [ ] 事件回放窗口：从任意 `fromSeq` 可重放的保留期（§11.3）。
- [ ] 时间戳格式统一为 ISO-8601 `Z`（列表排序是字符串比较，`stores/runs.ts:84`）。

---

## 15. Phase 6.2 暂时不做

- 真正 HTTP 请求执行
- SSE
- Evidence / Report 独立接口
- PostgreSQL
- Redis
- Celery
- Kafka
- LangGraph
- 真实 LLM
- Project / Spec / Plan 的 CRUD 接口（§13）
- `GET /api/runs/{id}/evidence`、`GET /api/runs/{id}/report`
- 分页
- 鉴权与多租户
- 计划的重新生成 / 版本化
- 把审批状态搬到服务端
- 报告导出、分享、定时执行

---

## 16. 当前风险与待确认问题

### 16.1 风险（代码里看得见的）

| 风险 | 说明 | 证据 |
|---|---|---|
| **列表页刷新后必然为空** | 没有任何 list 调用路径（§7）。这是当前功能最大的正确性缺口 | `stores/runs.ts:47`、`:126-131`；`RunsView.vue:79` |
| **取消的成功反馈完全押在事件流上** | 正常路径没问题：Mock 的取消会同步 drain 出 `run.cancelled`，store 订阅着，`applyEvent` 经 `upsertDetail` 更新详情（`stores/runs.ts:158-173`）。但取消响应本身只对账列表（`:353-358`）。所以后端若返回 200 却没送达 `run.cancelled`，页面会**停在 `running` 且没有任何提示**——而 `stream-failed` 在前端从无构造点（`services/runError.ts:18-19`），连错误都不会出现 | `stores/runs.ts:353-358` vs `:158-173`；`RunDetailView.vue:57-60` |
| **未知 `messageKey` 会原样显示** | `t()` 在字典缺 key 时返回 key 本身 | `stores/locale.ts:70-81`（`:75`、`:79` 的两个 `return key`） |
| **字典里没有"流失败"的文案** | `console.runs.errors` 下只有 8 个 key（title / notFound / notApproved / noPlan / createFailed / loadFailed / cancelFailed / dismiss），没有 stream 相关的 | `src/locales/console/en-US.ts:584-593`；`console-schema.ts:600-610` |
| `stream-failed` / `cancel-failed` 从不产生 | 两个 code 有声明、无构造点 | 声明 `services/runError.ts:18-19`；全 `src/` 无构造 |
| `toRunError` 把一切未知异常标成 `create-failed` | 加载失败、取消失败都会得到 `code: 'create-failed'`，只有 `messageKey` 不同 | `stores/runs.ts:115-118` |
| `getRun` / `activeRun` / `activeDetail` 是死表面 | 前者无生产调用（唯一调用点在测试）；后两者无任何视图读取 | `services/run.ts:107`、`stores/runs.ts:87-93`、`:389-390` |
| `loading` 是全局单标志 | 一次 `loadRun` 会压掉同期的另一次（例如列表→详情快速连点） | `stores/runs.ts:57`、`:311` |
| 前端不校验 `variables` 与 `baseUrl` 的一致性 | `baseUrl` 单独取 `environment.baseUrl`，`variables` 里另有一个同名 key | `stores/runs.ts:277-278`；`mock/projects.ts:25` |
| `secret` 标志已丢失 | 载荷里分不出哪个值是密钥 | `types/project.ts:19` 有定义；`stores/project.ts:73-75` 未透传 |

### 16.2 待确认（代码沉默）

1. **`fromSeq` 的传输格式**：query 参数、header（`Last-Event-ID`）还是别的方式。代码未定义（§11.2）。
2. **后端与 `seq` 的关系**：`seq` 是持久化列还是运行时分配；跨重启是否继续。
3. **事件的保留期**：从任意 `fromSeq` 可回放多久。
4. **`runId` 的格式**：代码只要求 URL 安全，未规定形状。
5. **错误传输格式**：`RunError` 走 HTTP body 还是 header；status code 与 code 的对应表。
6. **鉴权**：run 相关的四个接口是否需要凭证——前端今天不为 run 发任何凭证。
7. **`specDocument` 的大小上限**与是否压缩。
8. **并发**：同一项目/同一 `planId` 是否允许并行多次 run。前端没有任何互斥逻辑（`creating` 只防重复点击，`stores/runs.ts:237`）。
9. **`variables` 的落库策略**：存值 / 只存 key / 只存 hash。
10. **`GET /api/projects/{projectId}/runs` 的默认条数与排序**：前端只假设按 `createdAt` 降序（`stores/runs.ts:84`）。
11. **执行环境**：后端从哪台机器发出真实请求（是否允许 SSRF 面），代码里没有任何输入约束。

---

## 17. Phase 6.2 Backend 开发建议

1. **先把 4 个 REST 做完，再谈 SSE。** 没有流时，创建 → 拉快照 → 取消这条链已经能给出一个可读的 run（只是不会自己更新）。先让这条链端到端跑通，再接流。
2. **列表接口配一个前端 action。** 后端建好 `GET /api/projects/{projectId}/runs` 之后，前端需要新增 `listRuns` 并在 `RunsView` 挂载时调用——这是同一个 PR 里的另一半，别只做一半（§7）。
3. **回放能力优先于推送能力。** 若只能二选一，先做"任意 `fromSeq` 可重放的事件存储"，再考虑实时推送。前端的重连语义建立在回放上（§11.3），没有它 SSE 再快也不正确。
4. **错误码表先落成一张表再写代码。** 前端只认 `{ code, messageKey, params }`，且 `messageKey` 必须在字典里。把 `console.runs.errors.*` 的 8 个 key 抄进后端的错误映射，作为唯一可用集合。
5. **`TestStep.id` / `TestAssertion.id` 当作不可变外键回显。** 任何"服务端重新生成 id"的做法都会让详情页静默失去更新（`utils/runState.ts:84-106`）。
6. **`variableKeys` 而不是 `variables`。** 响应里出现明文密钥是这条链上唯一一个"一旦泄露就回不去"的错误（`types/run.ts:182-189`）。
7. **时间戳统一 `Z`。** 列表排序是字符串比较（`stores/runs.ts:84`），格式不统一会静默乱序。
8. **不要移植 Mock 的确定性。** 同计划两次 run 产生相同事件序列（`tests/run/service.spec.ts:362-385`）是 Mock 的可测试性设计，不是契约。
9. **先写契约测试再写实现。** 把 §6–§9 的 JSON 示例直接当 fixture；这些形状全部有源码行号背书，改形状必须先改前端。

---

## 18. Phase 6.2 Definition of Done

- [ ] `POST /api/projects/{projectId}/runs` 接受 §6 的全部字段，建记录并异步启动执行；`plan.status !== 'approved'` 被拒绝并返回 `not-approved`。
- [ ] 创建响应是 `TestRun`，含 `variableKeys`（**不含值**）、`planName` 冻结副本、`summary`。
- [ ] `GET /api/projects/{projectId}/runs` 返回 `TestRun[]`，按 `createdAt` 降序，时间戳为 ISO-8601 `Z`。
- [ ] `GET /api/runs/{runId}` 返回 `RunDetail`：`run` + `scenarios`（含 steps 与 assertions）+ `lastSeq`。
- [ ] 详情响应中的 `RunStep.id` / `RunScenario.id` / `RunAssertion.id` 与请求里 `plan` 的 id 逐字节相同。
- [ ] 未知 `runId` → 404，前端呈现 not-found 空态而不是错误条。
- [ ] `POST /api/runs/{runId}/cancel` 返回终止态；对已终止 run 幂等返回当前状态（不报错）。
- [ ] 终止态 run 可仅从 REST 快照读全（不依赖流）。
- [ ] 每个 run 的事件序列可持久化、可按 `fromSeq` 重放（为 6.3 铺路）。
- [ ] 错误响应的 `messageKey` 全部落在 `console.runs.errors.*` / `console.runs.failure.*` 已有 key 之内。
- [ ] `variables` 的值不落库到可被 API 读回的地方。
- [ ] 契约测试覆盖 §6–§9 的四个示例载荷。
- [ ] 前端侧（另开 PR）：新增 `listRuns` action 并在 `RunsView` 挂载时调用——否则 §7 的接口无人调用。

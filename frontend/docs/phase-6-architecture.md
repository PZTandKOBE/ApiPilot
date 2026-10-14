



# Phase 6 架构（前端侧）——决策与契约

> 状态：**仅决策与勘察，未开始实现。**
> 本文记录已确认的架构决策、它们与现有代码的相容性核对结果、
> Phase 6.1 的工作边界，以及开始编码前仍需拍板的问题。
>
> 后端（FastAPI / PostgreSQL / 执行引擎）**不在本文范围**。

---

## 1. 已确认的架构决策

| # | 决策 | 要点 |
|---|---|---|
| **D1** | **Step → Request 的合成在后端** | 前端不是 API 执行器。不得为执行给 `TestStep` 增加 headers/body/auth/query 字段。后端接收 `TestPlan + ApiSpec + Variables`，自行构造并发送请求、判定断言、记录证据。前端只负责：创建 Run、查看 Run、订阅 SSE、展示 Step/Assertion/Evidence、Cancel、Reconnect。 |
| **D2** | **Run 不随组件卸载而终止** | Run 生命周期不得依赖 Vue 组件是否 mounted。`EventSource` 由 RunStore / RunService 持有，**不得**放在组件内。 |
| **D3** | **Run 不以 localStorage 为权威** | 服务端是 source of truth，Pinia 仅作运行时缓存。刷新页面用 REST snapshot + SSE 增量恢复。 |
| **D4** | **Timeout 由后端负责** | 前端只展示超时结果。 |
| **D5** | **REST / SSE 分工** | REST：create / get / get detail / cancel。SSE 事件恰为 8 个：`run.started`、`step.started`、`step.completed`、`assertion.completed`、`step.failed`、`run.completed`、`run.failed`、`run.cancelled`。每个事件带 `runId`、`seq`（单调递增）、事件类型。前端丢弃 `seq <= lastSeq`；终止态吸收迟到事件。 |

---

## 2. 决策与现有代码的相容性

### 2.1 D5 与既有声明冲突，但冲突可以零成本消除

`src/types/agent.ts:355-378` 已声明一组占位流式类型，与 D5 **四个维度全部不一致**：

- **名字**：只有 4 个（`run.started` / `step.started` / `step.finished` / `run.finished`），
  用 `step.finished` 同时兜住 D5 的 `step.completed` 与 `step.failed`，
  用 `run.finished` 同时兜住 `run.completed` / `run.failed` / `run.cancelled`，
  而 `assertion.completed` 完全没有对应物。
- **形状**：判别名是 `name` 而非 `type`，且**没有 `seq`** ——
  没有 `seq` 就无法实现 D5 要求的 `seq <= lastSeq` 丢弃规则与 D3 的重连语义。
- **缺字段**：无 `assertionId`（无法 join 到 `TestAssertion.id`）、无结果、无失败原因、无证据、无 run 状态。

**处置：替换，不是扩展。** 依据是两条实证：

1. 该声明**是死代码** —— `grep -rn "AGENT_EVENTS\|AgentEventName\|AgentEvent" src/ tests/`
   在声明点之外**零命中**，没有任何模块导入、没有任何测试断言。
2. 名字本身在 D1 下已经错了：这些是 **run** 事件，而 `AgentEvent` 与
   `AnalysisProgress`（`types/agent.ts:236-239`）同处一文件 —— 那是另一个流概念。
   保留会造成 `step.finished` 与 `step.completed` 两套词汇并存。

新家：`src/types/run.ts`（按本仓库"一域一文件"的惯例：`agent.ts` / `api.ts` / `console.ts` / `project.ts` / `user.ts`）。
原块**删除**，不要留成孤儿。

### 2.2 D1 与 `TestStep` 的现状自洽

`TestStep`（`types/agent.ts:268-281`）本来就没有执行字段，
`src/services/mock/agent/plan.ts:73-92` 的 `requestStep` 产出也正是
`{ id, index, kind, description, endpointId, method, path, produces, consumes }`。
D1 与现状**没有冲突** —— 冲突本来只会发生在"前端要执行"的假设下。

**顺带的一条保护**：`sanitizeStep`（`utils/agentStorage.ts:95-112`）重建的正好是这 10 个字段，
任何未来新增的执行字段都会在下次加载时被静默抹掉。这个机制**在 D1 下从"障碍"变成"护栏"**。

### 2.3 D2 相容

store 挂在 app 级 Pinia 上（`src/main.ts:15-19`），`App.vue` 是裸 `<RouterView />`，
路由表无任何 store teardown，因此 store 状态天然跨路由存活 —— 这正是 D2 需要的。

### 2.4 D3 相容，并且排除了一项既有设施

`usePersistedRef`（`composables/usePersistedRef.ts:53-59`）在每次变更时
`JSON.stringify(value)` 并 `localStorage.setItem`。对 run 来说那是
**每个 SSE 事件触发一次全量同步序列化**，且配额异常被静默吞掉（`:57-59`）。
结论：run 相关状态**一律不得**走 `usePersistedRef`。

**推论：不要创建 `utils/runStorage.ts`。** 没有 sanitizer 才是正确信号。

### 2.5 D4 相容

`timeoutMs` 保留在 `ResolvedApiRequest`（`types/api.ts:109-115`）供 API Client 手动发送使用，
与 run 无关。注意它目前是**死字段** —— `mock/transport.ts:157-186` 从不读取它。

---

## 3. Run 创建契约：前端手上到底有什么

这是决定 D1 能否落地的最关键一节。

### 3.1 可用的（已核实）

| 物料 | 位置 | 是否跨刷新 |
|---|---|---|
| Plan（完整：scenarios/steps/assertions） | `stores/agent.ts:96-108`，持久化于 `aiata.console.agentPlans` | ✅ |
| **OpenAPI 文档原文** | `utils/agentStorage.ts:188-191` `StoredSpec { spec, content }`，持久化于 `aiata.console.agentSpecs` | ✅ |
| 环境变量 `key → value` | `stores/project.ts:69-76` | ✅（源自 `MOCK_PROJECTS` 常量） |
| `baseUrl` | 仅 `stores/apiClient.ts:118-123` 叠加了一份（**`project.ts` 的 variables 不含 baseUrl**） | ✅ |
| 活跃 project / environment id | `stores/project.ts:9`、`:31-35` | ✅ |

`ApiSpec` 本身（`types/agent.ts:63-76`）**不含 schema**，无法据以合成请求；
能合成请求的信息全在派生的 `ApiEndpoint` / `ApiAuthentication` 上，
而它们**故意不持久化**（`utils/agentStorage.ts:8-12`）。

**因此：Run 创建必须传文档原文，不能只传元数据。** 前端已经持有它，无需新增保留逻辑。

### 3.2 缺失的

1. **`environmentId` 不存在于 agent 域的任何地方**（`grep environmentId src/types/agent.ts src/stores/agent.ts` 零命中）。
   没有它，一次 Staging run 在切到 Production 后会被以错误的上下文展示，且**无法察觉**。这是本节最高价值的一项。
2. **`secret` 标志被丢弃**：`types/project.ts:19` 有 `secret: boolean`，
   但 `stores/project.ts:73-75` 的 `Object.fromEntries` 把它抹掉了，全局无任何脱敏。
   `console.environment.secret` 是一个**没有消费者的**标签。
3. **没有任何"某次 run 用了哪些变量"的记录。** 当前变量是编译期常量所以看不见，
   接了真后端之后，这就是"证据可解释"与"不可解释"的分界。
4. **handoff 路径的文档是合成的、有损的**：`services/agent.ts:145-226`
   把请求体样本的每个属性都声明为 required，响应 schema 硬编码为 `{ id: { type: 'string' } }`。
   由它派生的计划，其请求合成会建立在有损文档上。**需要决策**（见 §7）。

### 3.3 最小 create-run 载荷

```
POST /api/projects/{projectId}/runs
{
  planId, plan,            // plan 完整送出（后端从未见过它，plan 只存在于 localStorage）
  specId, specDocument,    // OpenAPI 原文
  environmentId,           // §3.2 第 1 项，当前前端没有
  variables,               // key → value
  baseUrl
}
```

**后端必须自行复核 `plan.status === 'approved'`。** 审批目前是客户端写入 localStorage
（`stores/agent.ts:303-315`），用户可直接编辑。审批对话框是 UI 边界，**不是安全边界**。

---

## 4. 需要新增的表面（Phase 6.1 脚手架）

沿用既有惯例：`as const` 数组导出联合类型、`readonly` 字段、`is*` 守卫；
一个服务接口 + 一个 `create*Service()` 工厂 + `TODO(backend phase)` 注释；
setup store 分「state / derived / actions」段；懒加载子路由 + `props: true` + `meta.titleKey`；
i18n 走 `console.<area>.*` 且 schema 与两个 locale 三处同步。

| 项 | 新文件 | 镜像自 |
|---|---|---|
| 类型 | `src/types/run.ts` | `src/types/agent.ts` |
| 服务边界 | `src/services/run.ts` | `src/services/agent.ts` |
| 错误词汇 | `src/services/runError.ts` | `src/services/agentError.ts` |
| Mock 实现 | `src/services/mock/run/index.ts` | `src/services/mock/agent/index.ts` |
| Store | `src/stores/runs.ts` | `src/stores/agent.ts` |
| 视图 | `src/views/console/RunsView.vue`、`RunDetailView.vue` | `TestPlansView.vue`、`TestPlanDetailView.vue` |
| 组件 | `src/components/console/Run/*` | `src/components/console/Agent/*` |

路由（插在 `src/router/index.ts:101-107` 之后、`pathMatch` 兜底之前）：

| path | name | component |
|---|---|---|
| `runs` | `console-project-runs` | `RunsView.vue` |
| `runs/:runId` | `console-project-run-detail` | `RunDetailView.vue` |

**`console-project-runs` 这个名字不是选择，是既成事实** ——
它已被 `useConsoleNav.ts:85-87`、`useProjectNav.ts:64-66`、`ApprovalPanel.vue:47` 引用。
注册路由会让两处导航项**自动从置灰变为可用**（`useResolvedNav.ts:39` 的 `hasRoute` 门控），**无需改导航代码**。

---

## 5. Phase 6.1 边界

### 5.1 做

1. P0 / P1 / P2 处置（§6）
2. `src/types/run.ts`：`RUN_STATUSES`、`RUN_EVENT_NAMES`（8 个）、`RunEvent`（判别于 `type`，带 `runId`/`seq`/`at` + 每种类型的载荷）、`TestRun`、`RunStep`、`RunAssertion`
3. `src/services/run.ts` + `runError.ts` + `src/services/mock/run/*`（脚本化、确定性、`immediate` 下无定时器）
4. `src/stores/runs.ts`：按项目的 run 缓存、活跃 run、订阅句柄、`Map<runId, lastSeq>`、终止态标记；动作 `createRun` / `loadRun` / `subscribeRun` / `unsubscribe` / `cancelRun` / `applyEvent`
5. 注册两条路由 + 两个视图（列表 / 详情骨架、空态、not-found）
6. i18n `console.runs.*`（schema + 两个 locale）
7. 删除 `types/agent.ts:355-378` 的死块
8. 新增测试：run store（用真实 mock 驱动）、两个视图的 SSR 烟雾测试（**各自注册自己的路由表**）

### 5.2 不做

- 不实现 SSE / `EventSource`
- 不实现执行引擎、FastAPI、真实 LLM
- **不给 `TestStep` 加任何执行字段**（D1 明令）
- 不建 `utils/runStorage.ts`；不用 `usePersistedRef` 存 run
- 不让 `useAgentStore` 反向依赖 run store（依赖方向只允许 runs → agent）
- 不在 run store 里用 `watch(projectId, { immediate: true })` 做网络拉取
  —— 会让 `tests/stores/agent.spec.ts:132-141`、`:303-312` 等所有切换项目的测试产生 I/O
- 不改 Home / Vue Bits，不装依赖

---

## 6. 开始 Phase 6.1 前必须处理的问题

### P0 —— `agentStorage.ts` 静默吞掉未知字段

**问题**：`sanitizeStep`（`:101-111`）、`sanitizeAssertion`（`:117-123`）、
`sanitizeScenario`（`:129-146`）、`sanitizePlans`（`:155-174`）、`sanitizeSpec`（`:200-212`）
都返回**固定字段的对象字面量**。任何新增字段在下次加载时静默消失，
且现象看起来像"生成 bug"而不是"清洗 bug"。

**最小修改**：每个 sanitizer 的返回字面量改为**先展开、后覆盖**：

```ts
return {
  ...value,                          // 本 build 不认识的字段原样保留
  id: asString(value.id, `step_${String(index)}`),   // 已知字段仍然重建
  index: asNumber(value.index, index),
  // …其余已知字段
}
```

展开必须**在已知字段之前**，否则会覆盖掉校验结果。
TS 注意：`value` 是 `Record<string, unknown>`，展开结果可能需要一个显式类型断言
（或一个极小的 `passthrough(value, KNOWN_KEYS, built)` 辅助函数）才能赋值给 `TestPlan`。

**诚实评估**：这是**保险**，不是当前即时的 bug。
它防的是"Phase 6 给已持久化的 plan/step/scenario 加了字段却被静默吃掉"这一类事故。
**触发条件**：若 run 相关 UI 需要在 plan 上记录任何东西（例如 `lastRunId`），陷阱立刻生效。
另外注意 `stores/agent.ts:59-67` 的 deep watch —— 任何对 plan 的写回都会触发
**每个项目每一份 plan** 的 localStorage 重写。**建议：保持 run 状态完全不进 `plans`。**

### P1a —— `parse.ts` endpoint id 碰撞

**问题**：`createEndpointId = ep_${method}_${slugify(path)}`（`parse.ts:229-230`），
`slugify` 把 `[^a-z0-9]+` 压成 `_`，因此 `GET /api/orders/{orderId}` 与
`GET /api/orders/orderId` 得到**同一个 id**。而 `analyze.ts:109` 的
`byId = new Map(...)` 是**后者覆盖前者** —— 两个端点塌缩成一个。

**最小修改**：在解析循环内加去重分配器，**仅在碰撞时**给第 2 个及以后加确定性后缀：

```ts
const seen = new Set<string>()
const uniqueEndpointId = (method: HttpMethod, path: string): string => {
  const base = createEndpointId(method, path)
  let id = base
  let n = 2
  while (seen.has(id)) id = `${base}_${n++}`
  seen.add(id)
  return id
}
```

**性质**：非碰撞文档的 id **逐字节不变** → `parse.spec.ts:137`（`ep_post_api_auth_login`）
与 `:160`（`ep_get_api_orders_orderid`）继续通过，已持久化的旧计划不失效。

**代价（如实说明）**：碰撞时谁拿 `_2` 取决于文档顺序 —— id 从"纯内容派生"
变成"仅在碰撞时顺序相关"。彻底的顺序无关方案要改动所有 id，必然破坏现有测试，不属最小修改。

### P1b —— `analyze.ts` dependency id 重复

**问题**：去重键与 id 用的**不是同一个函数**。
去重键（`analyze.ts:114`）是 `${to.id}::${binding}`（**原始** binding），
而 id（`analyze.ts:515`）是 `dep_${from.id}__${to.id}__${slug(binding)}`（**slug 化**）。
于是 `orderId` 与 `OrderId` 既能通过去重（两条都保留），又生成**完全相同的 id**。
消费点只有一处：`ApiDependencyGraph.vue:138` 的 `:key="branch.edge.id"` —— 重复即重复 key。

**最小修改**：把 `slug(item.binding)` 换成原始 `item.binding`，使 id 与去重键使用同一身份。
已确认 `slug` 在 `analyze.ts:332/369` 另有使用，去掉这一处**不会**触发
`tsconfig.app.json` 的 `noUnusedLocals`。测试中**无任何断言引用 dependency id**，零破坏。

**同类实例（不在原清单，一并报告）**：`analyze.ts:332` 的风险 id
`risk_reference_${dependency.to.id}_${slug(dependency.binding)}` 有**完全相同的碰撞模式**。
不处理的话，同一个 bug 会留在风险列表里。是否纳入由项目所有者决定。

### P2 —— `ApiDependencyGraph` 静默跳过

**问题**：`:68`（源解析不到）、`:74`（目标解析不到）、`:84`（分支数为 0 则不收集）
共同造成"整组无提示消失"，且不报数量差异。
demo 数据下不可达（两侧由同一次 `buildUnderstanding` 供给）。

**最小修改**：不引入新 UI，只**补断言**：渲染后断言**分组数 = 5**、**分支数 = 7**、
每条 rationale 均已渲染。当前测试只断言"页面含某字符串"，而 `token` 在渲染中另有 9 处、
`orderId` 另有 27 处 —— **即使图形一个 chip 都不渲染，现有断言仍会通过**（只有 `user_id` 真能钉住）。

### P2 —— 测试盲区清单

| 盲区 | 现状 | 补什么 |
|---|---|---|
| 多 Plan | 列表测试只放 1 个 plan，无法证伪"每行都渲染 activePlan" | 需要两个 plan 才能覆盖；注意 `agent.ts:185` 的 `applySpec` 会驱逐其他 spec 的 plan，当前**无法经公开 API 构造** |
| Dependency Graph 分组数/分支数 | 无任何断言 | 断言 5 / 7 |
| source endpoint | `analyze.spec.ts` 只断言 target，从未断言 3 条 sub-resource 与 lifecycle 的 **source** | 补 source 断言 |
| `planId → plan` | 无"渲染出的 plan 确为 URL 所指"的断言 | 断言渲染内容与 URL 参数一致 |
| route params | 无 `planId` 缺失/非字符串的用例 | 补边界用例 |

---

## 7. 编码前仍需拍板的问题

1. **Run 状态词汇**：D5 定义的是**事件**不是**状态**。`queued / running / passed / failed / cancelled` 是否合适？
2. **`assertion.completed` 与 `assert` 步骤的关系**：计划里既有 `TestScenario.assertions`
   （独立于 steps），又有 `kind: 'assert'` 的步骤（`mock/agent/plan.ts:113-126`，id 为 `assert__${index}`）。
   同一个事实可能被上报两次。需要明确：SSE 的 assertion 事件对齐哪一侧？
   （另注：`assert__${index}` 是**下标派生**的 id，作为 SSE join 键偏弱。）
3. **run 详情必须从服务端载荷渲染**，不得像 `TestPlanDetailView.vue:34-39` 那样 join 本地数据 ——
   计划会被同 id 原地替换（`stores/agent.ts:280-282`），join 本地计划会渲染到已不存在的步骤。
   → 后端必须在 SSE 与 snapshot 中**回显同一套 `TestStep.id`**。
4. **`environmentId` 是否进 create-run 载荷与 run 记录**（前端目前完全没有它）。
5. **变量/密钥是每次 run 下发，还是后端按 environmentId 自行解析。**
   这直接改变载荷形状，也决定 `secret` 是否需要脱敏。
6. **文档原文是每次 run 下发，还是上传一次后按 `specId` 引用**（D5 未定义上传端点）。
7. **`subscribe` 的形状**：`subscribe(input, { signal })`（与 `services/transport.ts:22-26` 的
   既有取消惯例一致）还是返回 `{ close() }` 句柄。
8. **`PIPELINE_STEPS` 里的 `execute` 何时算完成**：任何终止态，还是仅成功？
   当前 `completedSteps`（`stores/agent.ts:134-145`）从不 push `execute`，
   进度条在审批后**永久停在 Execute**。且 `AgentPipelineSteps` 表达不了"失败"。
9. **6.1 里 Run 按钮保持惰性，还是接受"导航到一个还创建不了 run 的页面"？**
   注册路由会让 `executionRouteReady`（`ApprovalPanel.vue:47`）翻真，
   而现有测试**察觉不到**这个行为变化（SSR 不触发 click）。
10. **测试里如何替身 run service**：本仓库目前**完全没有任何** `vi.mock`/`vi.fn`/`vi.spyOn`
    （测试直接驱动真实 mock）。所以要么引入 `vi.mock`（对仓库是新事物），
    要么给工厂加可替换入口。
11. **handoff 路径的有损文档是否仍是后端合成的依据**（`services/agent.ts:145-226`）。

---

## 8. 已知的测试耦合（改这些会破坏构建）

| 位置 | 耦合 |
|---|---|
| `tests/i18n/keys.spec.ts:120-131` | 两个词典结构性相同 —— `console.runs.*` 必须**三处同步**（schema + 两个 locale） |
| `tests/i18n/keys.spec.ts:90-102` | 只检查**单引号字面量** `t('…')`；双引号或模板字面量的 key 会漏检 |
| `tests/i18n/keys.spec.ts:104-118` | `collectEmittedKeys` 只遍历 `ApiUnderstanding` 与 `TestPlan`；mock run service 若发射 `LocalizedMessage` 标签**不会被收集** |
| `tests/views/ai-test-lab.spec.ts:164-191` | Run 按钮按**渲染文案** `'Run test'` 匹配，`buttonWith` 未命中返回 `''`，而 `isDisabled('') === false`。**改名会让三条 disabled 断言失败** |
| `tests/stores/agent.spec.ts:229-246` | 断言 scenarios 在元数据编辑后 JSON 逐字不变 —— 任何新的 plan 字段必须原样穿过 `updatePlanMeta` |
| `tests/agent/plan.spec.ts`（15 个） | 与 `TestStep` 形状绑定 |

新增 run 视图测试必须**各自注册自己的路由表**，
否则 `RouterLink` 解析不到目标 —— 这正是 Phase 5.3 那次失败的成因。

---

## 9. 附：本次核验引用的证据

本文件所有结论均回源码逐条核实，关键证据：

- 死代码判定：`grep -rn "AGENT_EVENTS\|AgentEventName\|AgentEvent" src/ tests/` → 声明点外零命中
- 工厂调用点：`src/stores/agent.ts:52`、`src/stores/apiClient.ts:67`（均在 store setup 内，非模块作用域）
- 测试替身：`grep -rn "vi\.mock\|vi\.fn\|vi\.spyOn" tests/` → 零命中
- `environmentId`：`grep -rn "environmentId" src/types/agent.ts src/stores/agent.ts` → 零命中
- `secret` 丢弃：`src/types/project.ts:19` 有定义，`src/stores/project.ts:73-75` 未透传

Agent Pipeline Contract（Phase 8.1 Step 1）
状态：契约冻结（Contract Freeze），未实现。 本文只做两件事：把当前真实代码里已经成立的契约写成文字，把本阶段确认的边界固定下来。 本文不实现 LangGraph、LLM、OpenAPI Parser、AI Test Plan Generator，也不改数据库。

架构方向（Prompt Engineering → Agent/LLM → Test Plan → Approve → Deterministic Run Executor → HTTP → Result/Evidence/Event） 已由项目负责人确认。本文不重新设计总体架构，只回答"这条链上各段的输入、输出、权限边界是什么"。

每一处断言都对应仓库里的真实代码，见 §0。

0. 依据：本文引用的真实代码
本文所有结论均来自下列文件（编号为撰写时核对的真实行号，随代码演进可能漂移）。

文件	核对内容	本文引用处
backend/src/backend/db/models/agent.py	AgentTask(:59-100)、TestPlan(:103-182)、TestScenario(:185-221)、TestStep(:224-277)、TestAssertion(:280-325)；模块 docstring:8-18；断言 key 命名要求:287-291	§2 §3 §5 §6
backend/src/backend/db/models/project.py	ApiSpec(:171-236)、ApiEndpoint(:238-279)、Environment(:281-348)、EnvironmentVariable(:350-383)、EnvironmentAuth(:385-429)	§3 §6 §9
backend/src/backend/db/models/result.py	TestRun(:160-245)、RunScenario(:247-319)、RunStep(:321-408)、RunAssertion(:410-490)、RunEvidence(:492-543)、RunEvent(:545-607)	§6 §9
backend/src/backend/schemas/run.py	枚举:91-99、PlanStep:113-127、PlanAssertion:129-137、PlanScenario:139-150、PlanPayload:152-177、RunCreateRequest:179-207；回显规则:5-19；变量值不外传:26-32	§3 §5 §6
backend/src/backend/services/runs.py	计划物化 _get_or_create_plan:602-707、_load_plan_tree:710-758（复用不重写:616-619）、_checkpoint_step_key:766-780、运行快照 _insert_run_tree:783-861、spec 身份 _get_or_create_spec:527-576、审批闸门 _check_approval:375-386	§4 §6 §8 §9
backend/src/backend/services/spec_identity.py	slug 公式:7、derive_spec_identity:243-268、probe_document:190-217（服务端没有 YAML 解析器）	§3 §5
backend/src/backend/services/run_executor.py	执行器真实消费面（Phase 7.3）	§9
backend/src/backend/api/routers/runs.py	全部 6 条路由：:189 :216 :249 :279 :308 :390	§2
backend/src/backend/app.py	路由装配:49-74；docstring "four routes" 已过期（实为 6 条）	§2
backend/dosc/ai-api-testing-agent-database-schema-v1.md	agent_tasks:757-791、test_workflows 延后:882-895、计划/结果关系:1625-1666、Agent 与手动边界:1669-1705、认证/变量边界:1709-1756	§2 §3 §6 §10
frontend/src/services/agent.ts	AgentService 边界:78-97、createAgentService 现状与 TODO:99-105、handoff 文档合成:145-226	§2 §4 §7
frontend/src/types/agent.ts	ApiSpec:63-76、ApiEndpoint:82-104、ApiAuthentication:116-127、ApiDependency:152-161、ApiRisk:166-191、AgentActionSummary:214-221、AnalysisProgress:236-239、ApiUnderstanding:242-251、TestStep:268-281、TestAssertion:286-293、TestScenario:295-304、TestPlan:309-330、PIPELINE_STEPS:343-352	§2 §3 §4 §5
frontend/src/stores/agent.ts	持久化键:28-31、理解不持久化:41-46、审批边界:47-49、generatePlan:283-306、approvePlan/rejectPlan:308-337	§2 §4 §6 §7
frontend/src/services/mock/agent/*	index.ts 服务组装:29-37,:44-88；plan.ts 步骤/断言 id 生成:73-153、场景构造:159-448、计划 id:519	§5 §12
frontend/docs/phase-6-architecture.md	D1（请求合成在后端，前端不得给 TestStep 加执行字段）:19；最小 create-run 载荷:116-130	§2 §7 §9
frontend/docs/phase-6.2-backend-rest-contract.md	REST 总览:100-110、Run/Plan 关系:575-588、Project/Spec/Plan CRUD 裁决:708-746、暂不做清单:767-784	§2 §9 §10
核对结论：现有代码与"Prompt Engineering → Agent → Plan → Approve → Executor"这条目标链在结构上相容，但今天只实现了后两段（Approve 的 UI 侧 + Executor）。前三段（Spec 理解、Test Design、计划持久化）目前整体运行在浏览器里，且完全没有 Prompt Engineering 资产。

1. Purpose
本文冻结 Agent Pipeline Contract，即：

一份 OpenAPI / API Spec 从进入系统到被 Deterministic Executor 执行之前， 谁读什么、谁产出什么、产出必须长什么样、谁不许做什么。

它要解决的问题只有一个：让"AI 生成的测试设计"成为执行器可以直接消费的结构化对象，而不是自然语言。

明确不在本文范围：

不实现 Agent Runtime（LangGraph / LLM 客户端 / 图状态机）
不实现 OpenAPI Parser 的服务端版本（今天解析在前端）
不实现 AI Test Plan Generator 的服务端版本
不改数据库、不改 Run REST / Run Event / SSE / run_executor.py
不新增 Prompt / Skill / Subagent
本文是 Phase 8.2 及以后的输入：后续每一步实现都必须能在这份契约里找到落点。

2. Current Architecture
2.1 今天真实存在的三段
text
复制
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
关键事实（全部可核验）：

后端从未生成过计划。 schemas/run.py:105-107："plan arrives as the whole TestPlan … because the server has no plan of its own to look up -- plans are generated in the browser today."
后端没有 Agent 路由。 app.py 只装配 runs.router，共 6 条路由（创建 / 列表 / 详情 / 取消 / 事件回放 / SSE）。没有任何 /api/agent/*、/api/plans/*、/api/specs/*。
agent_tasks 是一张完全未启用的表。 模型存在（db/models/agent.py:59-100），但它的引用面只有模型包自身：db/models/__init__.py 的导出，以及 db/models/project.py:142/224/336 三条反向关系声明（Project.agent_tasks / ApiSpec.agent_tasks / Environment.agent_tasks）——没有任何服务、路由、schema 或前端代码引用它（frontend/src 全量 grep 零命中）。数据库里 0 行，test_plans.agent_task_id 全为 NULL。
api_endpoints 从未物化。 runs.py:672-676："No api_endpoints are materialised, so there is nothing for this to point at." 数据库 api_endpoints = 0 行。理解结果（endpoints/dependencies/risks）没有任何持久化位置，它是文档的纯函数，每次加载重算（stores/agent.ts:41-46）。
审批是客户端写 localStorage。 stores/agent.ts:318-330。后端只复核 payload 里的 status 字符串（runs.py:375-386），审批的权威在客户端。
TestStep 不携带执行字段。 db/models/agent.py:8-12："test_steps describes a test-plan operation, not an HTTP request. It carries endpoint_id and a config blob; it does not carry headers, a body or an auth scheme." 与前端 D1（frontend/docs/phase-6-architecture.md:19）一致。
执行器只读运行快照。 run_executor.py 的全部输入是 run_scenarios/run_steps/run_assertions + test_runs（base_url、variables）+ 环境变量与认证。唯一一条读计划侧的例外：extract 步骤经 run_steps.source_step_id 读 test_steps.produces（原因见 §6.3）。
快照里的 method/path 来自 payload，不来自 test_steps。 runs.py:816-829 从 PlanStep.method / PlanStep.path 直接抄进 run_steps，而 test_steps 落库时 config={}、endpoint_id=NULL。
2.2 目标架构与现状的差距（Contract Gap）
目标链的一段	今天的实现位置	是否有服务端契约	缺口
OpenAPI / API Spec	浏览器 mock/agent/parse.ts	❌	服务端没有解析器；api_specs.content 只在 create-run 时才写入
AI Understanding	浏览器 mock/agent/analyze.ts（确定性规则，无 LLM）	❌	无表、无接口、无 Prompt
Test Plan Draft	浏览器 mock/agent/plan.ts	❌	无生成入口；计划首次落库只能搭 create-run 的便车
User Approve	浏览器 store + localStorage	⚠️ 仅 payload 复核	无服务端权威、无审批接口、无审计
Deterministic Run Executor	后端 run_executor.py（已完成）	✅	无
一句话：Phase 8.1 冻结的契约，主力是补上前四行里"服务端必须承担什么"，同时保证第 5 行一个字都不用改。

3. Input Contract
3.1 输入真源：agent_tasks 的四个业务列
agent_tasks 是数据库里唯一为"一次 Agent 任务"预留的行，它的列就是输入契约的骨架：

列	类型	可空	语义（dosc/...-v1.md:771-780）	契约含义
project_id	UUID	否	所属项目	租户与隔离边界
spec_id	UUID	否	使用的 API Spec	任务锚定在它实际读过的那份文档（NO ACTION 外键）
environment_id	UUID	是	目标环境	决定 base_url、变量、认证的来源
prompt	TEXT	否	用户给 Agent 的任务要求（例："分析订单系统，重点测试支付失败、重复支付和鉴权异常。"）	唯一的人类意图入口
status	VARCHAR(30)	否	pending / analyzing / completed / failed	任务生命周期，默认 pending
由此得到 AgentTaskInput（本阶段冻结）：

jsonc
复制
{
  "projectId": "prj_orders",            // agent_tasks.project_id
  "specId": "spec_orders_platform_api_pkqkbr",  // agent_tasks.spec_id（= "spec_" + slug，见 §5.3）
  "specDocument": "<OpenAPI/Swagger 原文>",      // 解析的唯一依据；服务端今天只在 create-run 里见过它
  "environmentId": "env_orders_staging",         // agent_tasks.environment_id，可空
  "prompt": "分析订单系统，重点测试支付失败、重复支付和鉴权异常。",  // agent_tasks.prompt
  "variables": { "<name>": "<value>" }           // 可选：环境变量的运行期覆盖，仅传名与值，不落库
}
输入不变量：

I1 文档原文是唯一的结构真源。 ApiSpec（前端类型 types/agent.ts:63-76）不含 schema，派生出的 endpoints 故意不持久化（stores/agent.ts:96-104："the metadata in ApiSpec carries no schemas"）。因此任何"理解"步骤都必须拿到文档原文，不能只给 specId。
I2 specId 是可重算的，不是权威。 spec_identity.py:7：slug = f"{slugify(title or filename)}_{hashString(content)}"；服务端会用文档重算并与 specId 比对（verified 标志，:228-241）。如果 prompt 里指定的 spec 与文档不一致，以文档为准，并把差异报告出来。
I3 environmentId 只影响"跑在哪"，不影响"测什么"。 环境提供 base_url / 变量 / 认证（dosc:1709-1756）。计划本身不得内嵌环境相关的值。
I4 变量值不进入任何持久化对象。 schemas/run.py:26-32：test_runs 只存 variable_keys（名字），值只在请求里出现一次。
I5 prompt 是自然语言，但它的产物必须是结构化对象。 见 §5：prompt 不得成为"直接执行"的指令通道。
3.2 今天实际走的输入：RunCreateRequest
Phase 8.1 之前，Agent 产物进入系统的唯一通道是 create-run：

字段	别名	落点
project_id	projectId	path 与 body 两处，必须一致（_check_identity）
plan_id	planId	test_plans.public_id
plan	plan	整棵计划树（PlanPayload）
spec_id	specId	与文档重算结果比对后解析成 api_specs 行
spec_document	specDocument	api_specs.content
environment_id	environmentId	test_runs.environment_id
variables	variables	运行期变量（值不落库）
base_url	baseUrl	test_runs.base_url
契约立场（与 phase-6.2-backend-rest-contract.md:736 一致）：这是"一次性把计划与文档一起交出去"的通道，本轮保持不变。 Phase 8.x 若把计划生成搬到服务端，plan 可以退化为 planId 引用，但那是一次独立重构，不由本文顺手改。

4. Agent Processing Contract
4.1 处理边界就是既有 AgentService 的四个操作
前端已经把 Agent 的能力边界写成了一个接口（services/agent.ts:78-97），Phase 8.x 的服务端实现必须保持这四个操作的语义：

#	操作	输入	输出	LLM 是否必需	确定性要求
1	parseSpec	SpecInput{projectId, filename, content, source}	ParsedSpec{spec, endpoints, resources, authentication}	否（纯结构解析）	同一文本 → 逐字节相同的输出
2	analyze	ParsedSpec + 进度回调	ApiUnderstanding	是（可先用规则实现）	同一文档 → 同一理解；不得依赖时间/随机
3	generatePlan	ApiUnderstanding + ApiSpec + PlanSource	TestPlan，status 恒为 draft	是	同上；且必须通过与 §5 的字段契约校验
4	（人类）approve / reject	TestPlan.id + （拒绝时）理由	status: approved / rejected	否	不是 Agent 的能力，见 §8
createAgentService() 今天的实现是 createMockAgentService()（services/agent.ts:105），并留有明确 TODO："return a service backed by POST /api/agent/* once FastAPI exposes it. Nothing above this function changes." 本契约与该 TODO 对齐：Phase 8.x 换掉的是这一行背后的实现，不是上层。

4.2 analyze 的输出形状（理解契约）
ApiUnderstanding（types/agent.ts:242-251）的每一部分都必须能追溯到文档：

字段	内容	生成规则（现状，来自 mock/agent/analyze.ts）
endpoints	ApiEndpoint[]	每个 operation 一条：id / method / path / resourceId / summary / requiresAuth / pathParams / requiredBodyProps / constrainedBodyProps / responseStatuses / responseProps
resources	ApiResource[]	按 tag（无 tag 则路径首段）分组，endpointIds 指向 endpoints
authentication	ApiAuthentication	scheme ∈ {none, bearer, apiKey, basic, oauth2}；tokenSourceEndpointId 指登录端点；tokenField 指令牌所在响应字段
dependencies	ApiDependency[]	kind ∈ {token, identity, reference, lifecycle, sub-resource}，binding 是跨边携带的值名
risks	ApiRisk[]	category ∈ {authentication, dependency, validation, negative-coverage, idempotency, authorization}，level ∈ {low, medium, high}
findings	AgentActionSummary[]	只写决策（decisionSummary），不写推理过程；result ∈ {succeeded, failed, skipped}
analyzedAt	ISO 时间戳	无表可落（见 §6.3）
理解是中间产物，不是交付物。 它必须能被重新计算（今天正是如此：不持久化），因此它不得承载任何"只有这一次才有"的信息（例如随机生成的 id、运行期值）。dependencies[].binding 是变量名，不是变量值。

4.3 阶段与 agent_tasks.status 的对应
dosc:778 定义了四个状态，本契约把它固定为唯一合法取值（数据库没有 CHECK 约束，靠服务层保证）：

text
复制
pending   ──► analyzing ──► completed
                   │
                   └──────► failed
状态	含义	何时写
pending	任务已创建，尚未开始	收到 AgentTaskInput 并落 agent_tasks 行时
analyzing	正在理解 / 设计	进入 analyze 之前
completed	已产出计划草稿（test_plans 行已写，agent_task_id 指向本任务）	generatePlan 通过 §5 校验并落库之后
failed	未产出计划	解析失败 / 校验失败 / LLM 失败；必须留下可读原因（今天无列，见 §13 G4）
禁止：completed 不等于 approved。计划状态与任务状态是两个正交的词表（draft/in_review/approved/rejected vs pending/analyzing/completed/failed），不得互相赋值。

5. Output Contract
5.1 输出形状
Agent 的唯一交付物是一棵 TestPlan 树，前后端各有一份同名镜像，二者逐字段对应：

text
复制
TestPlan                 ←→ backend PlanPayload（schemas/run.py:152-177）
├── id, projectId, specId, name, goal, riskLevel, status, source, generatedAt
├── approvedAt, rejectedAt, rejectionReason
└── scenarios[]          ←→ PlanScenario（:139-150）
    ├── id, index, name, description, riskLevel, expected
    ├── steps[]          ←→ PlanStep（:113-127）
    │   └── id, index, kind, description, endpointId, method, path, produces, consumes
    └── assertions[]     ←→ PlanAssertion（:129-137）
        └── id, kind, target, expected, description
5.2 字段级契约
TestPlan

字段	类型	约束	落点
id	string	plan_<spec.slug>（mock/agent/plan.ts:519）；项目内唯一	test_plans.public_id
projectId	string	必须等于输入	校验用，另存 test_plans.project_id
specId	string	必须是 spec_ + 文档 slug	解析为 test_plans.spec_id
name	LocalizedText	应用自撰 → i18n key；用户改名 → 字面量	test_plans.name (JSONB)
goal	LocalizedText	—	test_plans.description（唯一散文列）
riskLevel	low|medium|high	—	test_plans.risk_level
status	draft|in_review|approved|rejected	Agent 只能产出 draft	test_plans.status
source	generated|handoff	—	test_plans.source
generatedAt	ISO 时间戳	无列可落（schemas/run.py:155-159），仅校验格式	丢弃
approvedAt/rejectedAt/rejectionReason	—	由人类审批写入，不由 Agent 写	同名列
TestScenario

字段	约束	落点
id	scenario_key，plan 内唯一	test_scenarios.scenario_key（UNIQUE(plan_id, scenario_key)）
index	场景内执行顺序，plan 内稠密唯一	sort_order
name / description / expected	LocalizedText	三个 JSONB 列
riskLevel	low|medium|high	risk_level
steps / assertions	见下	子表
TestStep

字段	约束	落点
id	step_key，scenario 内唯一	test_steps.step_key（UNIQUE(scenario_id, step_key)）
index	场景内执行顺序，scenario 内稠密唯一	sort_order
kind	request|extract|assert	step_type
description	LocalizedText（test_steps 没有 name，只有 description）	description JSONB
endpointId	前端自己的端点 id（如 ep_post_api_orders），不是 UUID；今天不落库	endpoint_id = NULL
method	GET|POST|PUT|PATCH|DELETE；request 步骤必需，其余为 null	不在 test_steps，只进 run_steps.method
path	文档路径原文，可含 {{var}}	不在 test_steps，只进 run_steps.path
produces	变量名（extract 步骤必需）	test_steps.produces（执行器唯一的计划侧读取）
consumes	变量名数组	test_steps.consumes (JSONB)
TestAssertion

字段	约束	落点
id	assertion_key，scenario 内唯一（UNIQUE(scenario_id, assertion_key)）	assertion_key
kind	status|field|schema|header	assertion_type
target	带点路径：status / body.<path> / header.<Name>（schemas/run.py:134）	target (VARCHAR(255))
expected	字符串（PlanAssertion.expected: str，Pydantic 不会把 int 强转）	expected_value (JSONB，实际存 JSON 字符串)
description	LocalizedText	description JSONB
（无）	计划侧没有 stepId；test_assertions.step_id 恒为 NULL（runs.py:692-696）	断言挂点由 _checkpoint_step_key 在快照时决定
5.3 id 与 key 的生成契约（最重要的一节）
step_key / assertion_key / scenario_key 不是内部主键，而是对外契约本身：

前端按 id 相等匹配行，没有任何位置回退（schemas/run.py:5-19；utils/runState.ts 的匹配逻辑）。
后端回显的是计划里的 key，不是行 UUID（RunStepResponse.id ← run_steps.step_key，RunAssertionResponse.id ← run_assertions.assertion_key）。
事件里的 stepId / assertionId 用的也是同一套 key（run_executor.py 写事件时用 step_key / assertion_key）。
⇒ AI 生成的 key 一旦落库就不可变；任何"服务端重新生成 id"的做法都会让详情页静默失去更新。（phase-6.2-backend-rest-contract.md:827 已把这条写成后端建议第 5 条。）

现状的 key 形状（可复用，不必重新发明）：

对象	现状形状	出处
specId	spec_ + slug，slug = slugify(title) + '_' + hash(content)	spec_identity.py:7
plan.id	plan_${spec.slug}	mock/agent/plan.ts:519
scenario.id	scenario_authentication / scenario_lifecycle_${endpoint.id} / scenario_dependent_${endpoint.id} / scenario_negative_${endpoint.id} / scenario_smoke_${endpoint.id}	plan.ts:176/220/284/389/420
request 步骤	${endpoint.id}__${index}	plan.ts:82
extract 步骤	${endpoint.id}__extract_${variable}	plan.ts:101
assert 步骤	assert__${index}	plan.ts:116
assertion.id	${endpoint.id}__status 等	plan.ts:146
endpoint.id	ep_${method}_${slugify(path)}	mock/agent/parse.ts（createEndpointId）
命名硬约束（来自模型层，db/models/agent.py:287-291）： assertion_key 在整个 scenario 内唯一，而不是每个步骤内唯一。因此生成器必须给 key 加命名空间（推荐 {step_key}.{name}），否则两个步骤都产出 status_200 时第二次插入就是 UniqueViolation。现状的 ${endpoint.id}__status 天然满足这条（因为它带端点前缀），但新增断言种类时必须显式检查。

5.4 LocalizedText 规则
LocalizedText = { key, params? } | { text }（types/agent.ts:31-41），落库为 JSONB，不能用 VARCHAR（dosc:1793-1816）。

来源	形态	理由
应用自撰（生成器的固定文案）	{ key: 'console.aiTest.…', params: {...} }	key 必须已存在于 frontend/src/locales/console/{en-US,zh-CN}.ts，否则用户看到点号字符串
来自文档 / 模型自由文本 / 用户改名	{ text: "…" }	无法翻译的东西不许伪装成 key
约束 P1：Agent 产出的每一个 key 都必须是字典里已存在的 key。今天没有任何服务端字典，所以服务端生成的文案只能走 { text }，或复用已存在的 3 个 evidence key（console.runs.evidence.endpoint/extracted/checked）。这条决定了 Phase 8.x 若要服务端生成计划，必须先解决"文案从哪来"。

6. Test Plan Mapping
6.1 计划侧落库映射（_get_or_create_plan，逐字段）
payload	目标列	备注
plan.id	test_plans.public_id	整个字符串（含 plan_ 前缀），UNIQUE(project_id, public_id)
plan.name	test_plans.name (JSONB)	model_dump()
plan.goal	test_plans.description (JSONB)	goal 没有自己的列
plan.status	test_plans.status	—
plan.riskLevel	test_plans.risk_level	—
plan.source	test_plans.source	—
plan.approvedAt / rejectedAt / rejectionReason	同名列	—
plan.generatedAt	—	无列，丢弃
（无）	test_plans.agent_task_id	不由 create-run 写（恒 NULL）；Agent 路径必须自己写
（无）	test_plans.version	默认 1
scenario.id	test_scenarios.scenario_key	—
scenario.name / description / expected	三个 JSONB 列	—
scenario.riskLevel	test_scenarios.risk_level	—
scenario.index	test_scenarios.sort_order	—
step.id	test_steps.step_key	—
step.description	test_steps.description (JSONB)	—
step.kind	test_steps.step_type	—
step.produces	test_steps.produces	—
step.consumes	test_steps.consumes (JSONB)	—
step.index	test_steps.sort_order	—
step.method / step.path	—	不落 test_steps（见 §6.3 G1）
step.endpointId	test_steps.endpoint_id = NULL	前端的 endpointId 不是 UUID，且 api_endpoints 为空
（无）	test_steps.config = {}	列 NOT NULL，payload 无对应字段
（无）	test_steps.depends_on = JSON null	payload 无 dependsOn；写入的是 Python None，SQLAlchemy 落到 JSONB 上是 JSON 标量 null，不是 SQL NULL（全库 7 行实测 depends_on::text = 'null'）。消费方必须把 JSON null 与 SQL NULL 等价处理
assertion.id	test_assertions.assertion_key	—
assertion.kind	test_assertions.assertion_type	—
assertion.target	test_assertions.target	—
assertion.expected	test_assertions.expected_value	存成 JSON 字符串（\"200\"）
assertion.description	test_assertions.description	—
（无）	test_assertions.step_id = NULL	计划侧没有 stepId ⇒ 所有断言都是 scenario 级
复用语义（runs.py:616-619）： 同一个 (project_id, public_id) 第二次出现时，复用已存的行、不重写，并按稳定 key 反查 id；payload 里有而库里没有的场景拿不到 source_scenario_id（写 NULL，不伪造）。

6.2 运行快照映射（_insert_run_tree，执行器的真实输入）
payload	快照列	备注
scenario.id	run_scenarios.scenario_key	事件的 scenarioId
scenario.name / riskLevel / index	name / risk_level / sort_order	status 初始 pending
step.id	run_steps.step_key	事件的 stepId
step.description / kind / index	description / step_type / sort_order	status 初始 pending
step.method / step.path	run_steps.method / run_steps.path	从 payload 直抄，不 join test_steps（runs.py:823-827 注释："Snapshots, copied rather than joined"）
assertion.id / kind / target / expected / description	assertion_key / assertion_type / target / expected_value / description	status 初始 skipped
（计算）	run_assertions.run_step_id	_checkpoint_step_key：第一个 kind==='assert' 的步骤，否则最后一个步骤，否则 NULL
step.id（经 source_step_id）	run_steps.source_step_id	唯一一条回指计划侧的链路，供 extract 读 test_steps.produces
6.3 三处结构性事实（Phase 8.x 必须先看这一节）
G1 — test_steps 存不下 method/path，但执行器要 method/path。 今天成立的原因很特殊：计划与文档搭同一次 create-run 请求进来，快照直接从 payload 抄 method/path，test_steps 只是个"档案"。一旦 Agent 在服务端生成计划并先落库、之后再单独创建 run，快照就只能从 test_steps 取 method/path —— 而那里没有。后果是每个 request 步骤都会因缺 method/path 而失败。

不需要迁移的最小方案（仅记录，不实施）： test_steps.config 是 JSONB、NOT NULL、默认 '{}'，当前所有行都是 {} 且无任何代码写入或读取它（已核验：全库 test_steps.config 全为 {}，grep 在 src/ 内无消费点）。把 { "method": ..., "path": ... } 放进 config 是零 schema 变更的。
备选方案（代价更大）：给 test_steps 加 method/path 列（需要迁移），或让 api_endpoints 真正物化并让 endpoint_id 指向它（需要服务端 OpenAPI Parser）。
G2 — 断言无法表达"挂在哪个步骤"，靠 checkpointOf 兜底。 test_assertions.step_id 存在但恒为 NULL；快照用"第一个 assert 步骤 / 最后一个步骤"决定挂点。因此AI 无法表达"这条断言属于第 2 个请求"，只能靠 scenario 内步骤顺序隐含。若将来要精确挂点，最小改动是给 PlanAssertion 加可选 stepId（契约变更，前端类型 + 后端 schema 同步改），不需要动数据库。

G3 — depends_on / consumes 只是记录，执行器不读。 执行顺序只由 sort_order 决定（run_executor.py 按 sort_order 推进）。test_steps.depends_on 在 payload 里根本没有来源（_get_or_create_plan 写 None，落库为 JSON null，实测全库 7 行皆如此；没有 SQL NULL）；consumes 落了库但执行器不消费。⇒ AI 想表达"B 必须在 A 之后"，唯一有效手段是把 index 排对，写 dependsOn 没有执行效果（db/models/agent.py:14-18 已说明它是 "document-ordered reference the database cannot police"）。

7. Prompt Engineering Boundary
本 Step 不修改现有 Prompt Engineering，因为当前项目不存在 Agent Pipeline 的 Prompt 资产。

核验结果（本次实际搜索，不是推断）：

检查项	结果
项目内 Prompt / Agent Instruction 文件	不存在。D:\Aiapi_test 下全部 .md 只有 6 个：backend/dosc/ai-api-testing-agent-database-schema-v1.md、frontend/docs/phase-6-architecture.md、frontend/docs/phase-6.2-backend-rest-contract.md、frontend/README.md、frontend/src/components/effects/README.md、.agents/skills/taste-skill/SKILL.md（UI 设计技能，与 Agent Pipeline 无关）
engineering-backend-architect / engineering-frontend-developer	在 D:\Aiapi_test 与 D:\Deepseek\deepseek-harness 中都不存在（对两个目录全量 grep 均零命中）。这两个名字在本仓库没有对应实现
产品侧 Prompt 模板 / 表 / 列	只有 agent_tasks.prompt（TEXT，用户手写的任务要求），0 行数据；没有 prompt_templates 表、没有 prompt 文件、没有 LLM 客户端
Skill / Subagent（本项目新增）	无。.agents/skills/ 下只有 taste-skill（仓库自带）
因此本 Step 的产出是边界定义，而不是 Prompt 内容：

7.1 边界划分
归属	负责什么	存放位置	今天的状态
Prompt Engineering	"让 Agent 产出符合 §5 的输出"：任务陈述（agent_tasks.prompt）、系统提示、输出 schema 的提示、few-shot	未来的 Prompt 资产（本文只定义它必须产出什么）	未建立
Runtime	身份识别、校验、持久化、状态机、审批、调度执行器	后端服务层（agent_tasks / test_plans / Run REST）	部分存在（仅 Run 侧）
7.2 从现在起必须遵守的 Prompt 规则（契约，不实现）
P1 输出契约优先于文风。 Prompt 的第一职责是让输出能被 §5 的字段契约校验通过；任何"更自然的表达"如果破坏字段契约，就是错的。
P2 敏感值绝不入 Prompt。 变量值、token、Cookie、Authorization 头不得出现在 prompt 文本里（与 run_executor.py 的既有安全不变量一致：值不落 run_events/run_steps/run_assertions/run_evidence）。Prompt 里只能出现变量名。
P3 Prompt 不得包含执行指令。 "请调用 /api/orders 并检查状态码"这类指令属于 Agent 的输出（结构化 step/assertion），不属于 Prompt 的指令。LLM 不执行 HTTP（§8）。
P4 人类意图只从 agent_tasks.prompt 进入。 不接受从其他字段（如文档注释）间接注入的任务指令。
P5 未支持的字段不许出现在输出里。 见 §10：Request Body / Query Params / Schema Assertion 在 v1 是 Deferred，Prompt 必须让模型不产出依赖它们的计划，或明确标注。
8. Agent Permission Boundary
8.1 Agent 允许做（Allowed）
#	允许	依据
A1	读取 api_specs.content 与由它派生的 endpoints / resources / authentication	解析是纯函数
A2	生成 ApiUnderstanding（含 dependencies / risks / findings）	现状 analyze
A3	生成 TestPlan 草稿，含 scenarios / steps / assertions	现状 generatePlan
A4	生成稳定 key（plan_* / scenario_* / step_key / assertion_key）	§5.3；必须确定性
A5	生成 LocalizedText，但 key 必须已存在（或退化为 {text}）	§5.4 P1
A6	写 agent_tasks（任务行）与 test_plans（草稿行，agent_task_id 指向任务）	表结构已预留
A7	在 agent_tasks.status 上走 pending → analyzing → completed/failed	§4.3
A8	声明"这条断言/步骤我建议但当前执行器不支持"（表达为不产出或标注），供人类决策	§10
8.2 Agent 禁止做（Forbidden）
#	禁止	理由
F1	发 HTTP 请求 / 决定请求内容	LLM ≠ HTTP Executor。执行器的输入是快照，快照只由计划物化产生
F2	决定数据库状态（test_runs / run_* / run_events）	与 7.3 不变量冲突：只有执行器写运行时状态
F3	把计划置为 approved	types/agent.ts:309-314：只有 approvePlan()（人类动作）能产生 approved
F4	绕过审批创建 run	_check_approval 是服务端闸门（409 not-approved）
F5	写 test_workflows / 新建层级	该表按设计延后（dosc:882-895），当前数据库不存在
F6	修改已冻结的 Run Snapshot / Run Event 契约	Phase 7.2-D/E、7.3 已冻结
F7	产出自然语言形式的"动作"（如"发送一个请求看看效果"）	无法被 run_executor.py 消费，等于没有产出
F8	在输出里携带变量值 / token / cookie	与既有安全不变量冲突（§7.2 P2）
F9	单方面修改 test_plans 的非草稿字段（approved_at / rejected_at / rejection_reason）	审批是人类的
F10	依赖未支持的能力来构造计划（body / query / schema 断言）而不声明	§10；否则计划会在执行期静默失败
审批边界的现状与目标（必须说清楚）： 今天"审批"是客户端写 localStorage，_check_approval 信任 payload —— 前端文档已经指出"审批对话框是 UI 边界，不是安全边界"（phase-6-architecture.md:129-130）。把审批的权威搬到服务端是一个独立且更大的决策（phase-6.2-backend-rest-contract.md:716 已明确不塞进 6.2）。本文不改变它，只把它记录为 Phase 8.x 的头号待决问题。

9. Deterministic Executor Boundary
9.1 执行器真实消费面（Phase 7.3 已冻结）
执行器读取	来源	说明
场景顺序	run_scenarios.sort_order	升序
步骤顺序	run_steps.sort_order	升序
请求	run_steps.method + run_steps.path（{{var}} 解析：运行期变量 > 环境变量）	快照列，见 §6.3 G1
步骤类型	run_steps.step_type ∈ request/extract/assert	assert 步骤不发请求
提取变量名	test_steps.produces（经 run_steps.source_step_id）	唯一的计划侧读取
断言	run_assertions.assertion_type / target / expected_value	status/field/header 执行；schema → skipped
认证	environment_auths（is_default AND is_enabled）	none/bearer/basic/apiKey
base URL	test_runs.base_url	快照
变量	environment_variables + create-run 的 variables	值只在内存
执行器不读：api_specs / api_endpoints（api_endpoints 永远为空）、test_plans、test_scenarios（除 produces 那一条）、任何 LLM 产物。

9.2 AI 输出必须满足的可执行性规则
#	规则	违反的后果
E1	request 步骤必须同时有 method 与 path；method ∈ {GET,POST,PUT,PATCH,DELETE}	快照缺字段 → 步骤失败
E2	extract 步骤必须设置 produces（变量名）	提取值为空 → 后续 {{var}} 解析失败
E3	路径/断言里用到的每个 {{var}}，必须由环境变量或某个更早的 extract 提供	this run has no value for: <key>（既有错误语义）
E4	断言 target 只能是 status / body.<path> / header.<Name>	目标无法解析 → 断言失败
E5	断言 expected 必须是字符串	Pydantic 422（PlanAssertion.expected: str）
E6	同一 scenario 内 step.id 唯一、assertion.id 唯一；同一 plan 内 scenario.id 唯一	UniqueViolation
E7	index 决定执行顺序，必须显式、稠密、与期望顺序一致	顺序错误（dependsOn 无执行效果，见 G3）
E8	断言只能依赖已经被执行过的响应（同场景更早的步骤）	断言拿到空响应 → skipped/失败
E9	不依赖请求体：POST/PUT/PATCH 在 v1 发送空 body	计划里"创建资源"类场景会在执行期失败
E10	不使用 query 参数（执行器尚未支持）	参数丢失 → 断言失败
E11	schema 断言会被判为 skipped，不得当作有效覆盖	覆盖率虚高
E12	计划里不得出现环境/密钥相关的值（只允许变量名）	安全不变量破口
E9/E10/E11 是本契约里"AI 能力"与"执行器能力"之间最紧的三处约束。 它们不是建议：AI 若忽略它们，产出的计划在 7.3 执行器上必然失败或空转。Phase 8.x 要么让生成器避开，要么先扩展执行器（那是 7.x 的后续步骤，不是 8.1）。

10. Unsupported / Deferred Capabilities
Deferred / Unsupported 是契约的一部分，不是待办清单的省略。 以下能力当前不存在，AI 输出不得假设其存在：

#	能力	现状	证据
D1	Request Body 合成与发送	v1 发送空 body	7.3 契约；test_steps 无 body 字段（db/models/agent.py:8-12）
D2	Query Params	执行器不支持	run_steps 无 params 列
D3	Schema 断言	一律 skipped（不引入 jsonschema）	7.3
D4	Cookie 认证	只支持 none/bearer/basic/apiKey	7.3；environment_auths.auth_type
D5	服务端 OpenAPI Parser	解析在前端	api_endpoints 0 行；spec_identity.probe_document 明确不做 YAML 解析
D6	服务端计划存储 / 版本化 / 重新生成	无接口	phase-6.2-...:744-746、:782
D7	服务端审批权威	审批在 localStorage	stores/agent.ts:318-330；_check_approval 只信 payload
D8	agent_tasks 落库与任务生命周期	表在，仅模型包内被导出与反向关系引用，无服务/路由/前端引用，0 行	本次核验
D9	Understanding 持久化 / 流式进度	理解不落库；进度是浏览器定时器	stores/agent.ts:41-46；mock/agent/index.ts:29-37
D10	LangGraph / LLM 客户端 / Prompt 资产	全部不存在	本次核验（§7）
D11	test_workflows（Workflow 层）	表不存在，按设计延后	dosc:882-895；数据库核验
D12	Adaptive Testing、PDF Report、CLI	未实现	phase-6.2-...:767-784
D13	断言精确挂到某个步骤	test_assertions.step_id 恒 NULL	§6.3 G2
D14	幂等性 / 并发执行的模型	无互斥逻辑	phase-6.2-...:814
11. Future LangGraph Position
本文不引入 LangGraph，只固定它将来必须落在哪里，避免后续实现改变既有契约。

text
复制
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
固定的四条：

图的输入输出与 §3/§5 完全一致。 LangGraph 是这四个操作的实现方式，不是新契约；AgentService 的四方法语义不变（services/agent.ts:78-97）。
validate 节点是强制节点。 LLM 的自由输出必须先通过 §5 校验（字段、类型、key 唯一性、E1–E12），校验不过不得落库；失败写 agent_tasks.status = failed。
persist 是唯一的写库节点。 图的其他节点不得写 test_plans / test_scenarios / test_steps / test_assertions；更不得写 test_runs / run_*。
agent_tasks 是任务的锚。 每次任务一行（pending → analyzing → completed/failed），计划经 test_plans.agent_task_id 回指；agent_tasks.spec_id 固定它读过的文档版本。
位置说明（诚实版）： 今天"图"就是浏览器里的一次函数调用链（parseSpec → analyze → generatePlan，mock/agent/index.ts:44-88），它已经满足"确定性 + 可测试"，缺的是服务端权威 + LLM + Prompt。LangGraph 的价值在于把这三段搬到服务端后仍能保持可观测与可重跑，而不是引入新的语义。

12. Example Pipeline
text
复制
① API Spec                     api_specs.content（OpenAPI 3.x / Swagger 2.x 原文）
                               specId = "spec_" + slugify(title) + "_" + hash(content)
        │
        ▼
② Spec Understanding           parseSpec → ApiSpec + ApiEndpoint[] + ApiResource[] + ApiAuthentication
                               analyze   → ApiUnderstanding{endpoints, resources, authentication,
                                                             dependencies, risks, findings}
                               （今天：浏览器规则引擎；未来：服务端 + LLM，形状不变）
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
                               ★ 必须通过 §5 校验后才落库；config/depends_on/endpoint_id/
                                 step_id 今天没有来源（见 §6.1、§6.3）
        │
        ▼
⑤ User Approval                TestPlan.status: draft → in_review → approved
                               approvedAt / rejectedAt / rejectionReason 由人类写
                               ★ Agent 永远不能产生 approved（F3）
        │
        ▼
⑥ Run Creation                 POST /api/projects/{projectId}/runs
                               body = { planId, plan, specId, specDocument,
                                        environmentId, variables, baseUrl }
                               服务端：_check_approval → _check_identity →
                                       _get_or_create_spec → _get_or_create_plan →
                                       _insert_run_tree（快照，method/path 此时才落 run_steps）
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
这条链上"AI 能碰到的东西"止于 ④ 之前的 ③：进入 ⑤ 之后，计划是不可变输入，进入 ⑦ 之后，一切状态由执行器独占写入。

13. 契约缺口与最小修复方向（仅分析，不在本 Step 实施）
#	缺口	影响	最小方案（供 8.2+ 决策）	是否要改数据库
G1	test_steps 无法表达 method/path（§6.3）	计划一旦先在服务端落库，执行器快照就没有请求信息	写入既有 config JSONB（{"method","path"}），零 schema 变更	否
G2	断言无法表达步骤挂点（§6.3）	断言只能 scenario 级，靠 checkpointOf 兜底	PlanAssertion 加可选 stepId（前后端契约同步）	否（test_assertions.step_id 已存在）
G3	dependsOn 无执行语义（§6.3）	写了不生效，顺序只认 index	契约层明确"顺序只由 index 表达"；或后续让执行器读 depends_on	否
G4	agent_tasks 无"结果/失败原因"列	任务失败无处记录	需要新列或复用现有列；建议后续单独评估	可能需要（本 Step 不改）
G5	审批权威在客户端（§8.2）	服务端只复核字符串，不是安全边界	独立决策：审批上移 + POST /api/plans/{id}/approve	否
G6	理解结果无持久化位置	每次重算；无法审计"当时为什么这么设计"	当前不建；将来单独评估	可能需要
G7	服务端无法产出 LocalizedText.key	服务端生成的文案只能 {text}	要么接受 {text}，要么把字典作为服务端资产	否
G8	generatedAt 无列	生成时刻不可恢复（created_at 是落库时刻）	可接受；若必须则需新列	可能需要
结论：Agent Pipeline Contract 在当前数据库结构上"成立但有条件" —— 成立的条件是 §6.3 G1：只要计划仍然通过 create-run 的 payload 与文档一起下发，快照就能拿到 method/path，今日链路完全自洽。一旦计划改为服务端先生成、后创建 run，G1 必须先用零迁移方案（config）补上，否则执行器拿不到请求信息。

14. 一页速查（Cheat Sheet）
问题	答案
Agent 输入什么？	§3.1 AgentTaskInput：projectId / specId / specDocument / environmentId? / prompt / variables?
Agent 输出什么？	§5 一棵 TestPlan 树（status 恒 draft），前端类型 = 后端 PlanPayload
落到哪四张表？	test_plans / test_scenarios / test_steps / test_assertions（逐字段见 §6.1）
执行器读什么？	只读 run_* 快照；唯一计划侧读取是 test_steps.produces（§9.1）
Agent 能做什么？	§8.1 A1–A8（读文档、出理解、出草稿、写任务与草稿、走任务状态机）
Agent 不能做什么？	§8.2 F1–F10（发请求、改运行状态、自行批准、新建层级、携带密钥、输出自然语言动作……）
怎么保证可执行？	§9.2 E1–E12（id 稳定与回显、method/path 齐全、{{var}} 可解析、expected 是字符串、顺序靠 index、不依赖 body/query/schema）
Prompt 与 Runtime 的边界？	§7：Prompt 只负责"产出符合 §5 的对象"，Runtime 负责身份/校验/持久化/审批/执行；值不进 Prompt
本阶段改了什么？	只新增本文档。不改数据库、不改 Prompt、不改 Skill、不改 Run/Executor/Frontend
架构由项目负责人确认，本任务不重新设计总体架构。
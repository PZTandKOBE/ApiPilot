# ApiPilot 项目进度记录（PROJECT_PROGRESS）

> **本文件是 ApiPilot 的统一项目进度记录。**
> 原则：**只追加，不改写旧记录**。每条任务记录一经写入即视为历史证据，后续任务只能在其后追加新记录；
> 若旧记录有误，应在**新记录**中说明更正，而不是直接修改旧条目。
>
> 记录内容以**证据**为准：只写实际执行过的命令与观察到的结果；明确区分「本轮实测」「历史结果」「未运行/未验证」。
> 不得把文件存在当作功能完成，不得把自定义验证脚本的 checks 称为 pytest，不得把历史数字当作本轮重跑结果。

- 项目根目录：`D:\Aiapi_test`
- GitHub：<https://github.com/PZTandKOBE/ApiPilot>
- 本文件路径：`docs/PROJECT_PROGRESS.md`
- 本文件建立于：Task C2（2026-10-14，本机时区 UTC+08）

---

## 0. 当前项目状态摘要

| 项目 | 状态 | 依据 |
|---|---|---|
| Phase 8.5 Step 1–4 | **已完成并验收** | `docs/identity-access-contract.md` 实施进度表 + §10.1/§10.2（Task B19 结项记录） |
| 身份与访问控制契约 | **Phase 8.5 的正式契约** | `docs/identity-access-contract.md` §6（冻结安全契约，行 270–344）、§8（正式验收条件，行 362–404） |
| Agent Pipeline 契约 | 契约文档 | `docs/agent-pipeline-contract.md`（Phase 8.1 Step 1，标题即声明「契约冻结」） |
| 完整 Agent 端到端验收 | **未完成** | 真实 DeepSeek provider 成功路径 + 「上传文档 → 分析 → 计划 → 批准 → Run → 结果」的完整浏览器闭环均未通过验收（`README.md:57`、`:199`、`:206`） |
| Run 启动恢复 | **工作区有第一阶段实现，未提交；首批 10 个 pytest 用例通过（C4 + C5），功能仍未整体验收** | `backend/src/backend/app.py`、`backend/src/backend/services/run_executor.py`（未提交修改）。只覆盖从未启动过的 `queued` Run；`running` Run 的可靠恢复策略未实现（需要 executor lease/heartbeat） |
| 后端测试体系 | **已建立最小 pytest 体系（10 项）**；自定义验证脚本与 pytest 是两种不同体系，不能混称 | `backend/tests/`（C4 建立、C5 扩充）；历史 833 checks 来自 `backend/scripts/verify_*.py` 自定义脚本，**不是 pytest** |
| 前端测试 | 22 个 spec 文件 | `frontend/tests/**/*.spec.ts`（C1 实测计数）。历史结项结果为 22 files / 300 tests / 0 failures，属历史实测 |
| GitHub 远程同步状态 | **尚未确认** | 本机 DNS 被接管 + git TLS 凭证失败，无法联网核对（详见 Task C1 / C2 记录） |

---

## 1. Task B19 — Phase 8.5 文档结项（历史记录）

> 该条为**历史记录**，内容来自 `docs/identity-access-contract.md` §10 与交接资料；本轮未重跑其中任何测试。

- 任务性质：仅修改 `docs/identity-access-contract.md`，把 Step 3 / Step 4 状态更新为已完成，并新增 §10 验收记录与已知局限。
- §6 安全契约与 §8 正式验收条件的原始内容**未因结项而改动**（B19 报告称与备份逐字节一致，备份位于 `D:\_aiata_b19_backup\identity-access-contract.md.orig`，该备份目录在本轮 C2 中被观察到仍然存在）。
- 「后续独立阶段 — User Authentication」的定位未改变：注册/登录不属于 Phase 8.5 验收范围。

**历史测试数字（均非本轮实测，引用时必须标注来源与时间性质）：**

| 数字 | 来源 | 性质 |
|---|---|---|
| 前端 22 个文件 / 300 项测试 / 0 失败；TypeScript `tsc` EXIT=0 | Phase 8.5 结项（B17/B19） | **历史实测**，本轮 C2 未重跑 |
| 后端九个自定义验证套件 833 项检查 / 0 失败 | Task B14 最后一次已知运行 | **历史结果**，且**不是 pytest**，也**不是**本轮结果 |
| 浏览器 E2E 32/32 | Task B11 | 只覆盖**手动 API 代理核心闭环**（真实 Chrome → FastAPI → 受控上游 → 前端显示），**不代表完整 Agent E2E 通过** |
| 后端 pytest 全量 | —— | C4 之前**未运行**（后端当时无 pytest 套件） |

---

## 2. Task C1 — 只读基线审计（2026-10-14 前后，日期待核实）

**结论：PARTIAL**

> **日期异常（如实记录，不擅自统一）：**
> C1 报告自身标注的日期为 `2026-02-14`，而项目交接上下文的日期为 `2026-10-14`；两者不一致。
> **没有任何可靠证据可以判定哪一个正确**，因此：
> - **不修改**任何一方的记录；
> - C1 的实际发生日期在此标注为 **待核实**；
> - 本文件保留两个候选日期及其来源，供负责人后续确认。

- **零产品源码修改、零配置/依赖修改、零数据库访问**。
- **未执行** `git add` / `commit` / `push` / `pull` / `fetch` / `reset` / `clean` / `checkout` / `restore`。
- 本地 Git 与 GitHub 远程的**同步状态未获联网确认**：`web_fetch` 访问 github.com / api.github.com 被拒（解析到非公网地址 `198.18.0.58` / `198.18.0.14`），`git ls-remote origin` 退出码 128（`schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`）。
- 当时 `backend/scripts/` 下 **19 个受 Git 跟踪的文件从工作区消失**（仍完整存在于 `HEAD`）。
- `backend/src/backend/app.py` 与 `backend/src/backend/services/run_executor.py` 存在**未提交的 Run 启动恢复第一阶段实现**（`git diff --stat` = 21 files, +409 / −17764）。
- **未发现被 Git 跟踪的真实密钥**：`backend/.env` 被 `backend/.gitignore:3` 命中且从未进入提交历史；跟踪文件中只出现 `DEEPSEEK_API_KEY` / `POSTGRES_PASSWORD` 等**变量名**，无真实值。
- **未找到任何既有统一项目进度文档**：`docs/` 下只有两个契约；全仓无 `*progress*`/`*status*`/`*roadmap*`/`*changelog*` 文档；正文关键词全仓仅 15 处命中且均属契约语境。因此当时把「进度文档更新」标为 **BLOCKED（等待负责人批准建立/指定统一进度文档）**。
- 记录了若干**过期状态表述**（等待后续专项修订，C1 未修改它们）：`README.md` 关于 Run 启动恢复的说法、`docs/identity-access-contract.md:3` 的「等待架构评审」标签与 `:106-107` 的路由数量快照（8 path / 9 operation，当前为 4 router / 14 operation）、`docs/agent-pipeline-contract.md:95`/`:661`/`:744` 的陈旧陈述。

---

## 3. Task C2 — 恢复验证脚本、保护未提交代码、建立统一进度记录（2026-10-14）

**结论：PASS**

**任务日期**：2026-10-14（本机时区 UTC+08，由 `Get-Date -Format "yyyyMMdd-HHmmss"` 产生，本次备份目录时间戳为 `20261014-163854`）。

### 3.1 目标与授权

授权范围仅三项：恢复 `backend/scripts/` 的历史文件；备份并验证两个未提交源文件未被改动；建立统一项目进度文档。**不开发新功能、不清理数据库、不提交、不推送。**

### 3.2 恢复前检查（阶段 A）

与 C1 记录的预期状态**完全一致**，未触发停止条件：

- `Get-Location` → `D:\Aiapi_test`
- `git branch --show-current` → `main`；`HEAD` → `d7c726a`；`origin` → `https://github.com/PZTandKOBE/ApiPilot.git`
- `Test-Path backend/scripts` → `False`；`git ls-files backend/scripts/` → **19**
- `git status --short --branch --untracked-files=all` → 19 个 ` D` + 2 个 ` M`；**无未跟踪文件**
- `git diff --cached --name-only` → **空**（暂存区为空）；`git diff --check`、`git diff --cached --check` → 均 EXIT=0

### 3.3 未提交代码保护（阶段 A）

**备份位置（项目目录之外）**：`D:\_aiapi_c2_backup_20261014-163854\`

| 文件 | 字节 | SHA-256（备份与源一致） |
|---|---|---|
| `app.py` | 4,852 | `305850D8D42A066EF8B891957F3E07F2827E5D5C4AB2541DB49164ECE757D1EF` |
| `run_executor.py` | 70,097 | `B0E2BC0588326A51063A55AA93472AD034347A14D70A7C162940384814E6C52B` |
| `app.py.diff` | 3,186 | `9113C523C8C25FE512ECCE8D366E02DBFA5AB961263892589E798FEE5CD02A13` |
| `run_executor.py.diff` | 17,352 | `509BCAC34D4021CDFAFFAF7ABE3FFD0E3A0C3396DC265F3EB14236A0F8AE79DD` |

> 备份目录名带时间戳，写入前检查过不存在同名目录，未覆盖任何旧备份；`D:\_aiapi_c2_backup_latest.txt`（备份外）额外记录了同一组哈希，供后续比对。

### 3.4 恢复操作（阶段 B）

执行的唯一写操作：

```powershell
git restore --source=HEAD -- backend/scripts     # EXIT=0，范围仅限 backend/scripts
```

**未执行** `git reset` / `git clean` / `git checkout` / `git restore .` / `git restore --worktree .` / `git stash pop`，也未执行 `git add` / `commit` / `push` / `pull` / `fetch`。

### 3.5 恢复验证（阶段 B）

1. **数量**：`Test-Path backend/scripts` → `True`；磁盘 19 个文件；`git ls-files backend/scripts/` → 19。
2. **内容与 HEAD blob 一致（逐文件）**：19/19 文件 `git hash-object` 计算结果与 `HEAD:<path>` blob 哈希**完全相同**；`git diff HEAD -- backend/scripts/` 输出为**空**；`git ls-files --others --exclude-standard -- backend/scripts/` 为**空**（无新增未跟踪文件）。
3. **磁盘字节数**：19/19 满足 `磁盘字节 = HEAD blob 字节 + 该文件 CR 数量`，**解释失败数 0**。差异来源已确认是 `core.autocrlf=true`（`D:/Git/etc/gitconfig`）在检出时把 blob 的 LF 转成工作区 CRLF；每行恰好 +1 字节，与内容无关。
4. **两个受保护文件**：恢复后 SHA-256 与阶段 A 的**基线完全一致**（`APP_UNCHANGED=True`、`EXEC_UNCHANGED=True`），且两份 diff 文件的 SHA-256 与基线**逐字节相同**（`9113C523…` / `509BCAC3…`）。
5. **暂存区仍为空**：`git diff --cached --name-only` → 空。
6. **产品源码零修改**：`git diff --stat` 最终只剩 2 个文件（`app.py` +42、`run_executor.py` +372/−5），与阶段 A 的未提交改动一致。

**已知的非阻塞状态（如实记录）：** `git status` 会把 7 个脚本（`seed_dev_data.py`、`verify_deepseek_analyze.py`、`verify_deepseek_generate_plan.py`、`verify_deepseek_schema.py`、`verify_guest_session.py`、`verify_llm_client.py`、`verify_proxy.py`）显示为 ` M`，但这是 **Git 索引 stat 缓存的假阳性，不是内容差异**：

- 这 7 个文件的 `index blob = HEAD blob = 工作区 git hash-object` **三者完全相同**；
- `git diff`（会做内容比较）对这 7 个文件输出**长度为 0**，`--ignore-all-space --ignore-blank-lines` 亦为 0；
- `git diff-files` 的 worktree 侧哈希显示为全 `0000000`，即 Git 未完成内容比较；
- 触发原因是 `core.autocrlf=true` 下这 7 个文件的索引缓存 size 与工作区实际 size 不匹配（`blob字节 + CR数`），导致每次 status 都判为「needs update」；`git update-index --refresh` / `--really-refresh` 因此都报 `needs update` 并返回退出码 1，且无法写入修正后的 stat 信息。
- 该状态**不影响提交正确性**（提交会用内容比较），但会污染 `git status` 输出。本轮**未**用 `git add`（含 `git add --refresh`）去消除，因为任务明确禁止 `git add`；建议在后续获准的 Git 提交任务中一并处理并复核。

### 3.6 本轮未运行 / 未触碰的事项

- **未连接数据库**，未创建、修改或删除任何数据库记录。
- **未运行**任何 `verify_*.py` 或 `seed_dev_data.py`（这些脚本可能写入 Guest Session 等夹具数据）。
- **未调用真实 DeepSeek 模型**，无任何 API 计费。
- **未修改**产品源码、依赖、锁文件、Alembic 迁移、`.gitignore` 或两个受保护文件。
- **未提交、未推送、未 fetch**。
- 未运行前端 Vitest（任务明确说明本任务不需要运行完整前后端测试）。

### 3.7 交付报告自检

| 验收项 | 结果 |
|---|---|
| `backend/scripts/` 19 个文件已恢复 | ✅ 19/19，内容与 HEAD 逐字节一致 |
| `app.py` / `run_executor.py` 未提交修改保持原样 | ✅ SHA-256 与 diff 哈希均与基线一致 |
| `docs/PROJECT_PROGRESS.md` 存在且可读 | ✅ 本文件 |
| 未提交或推送 | ✅ 暂存区为空 |
| 未连接数据库、未增删改记录 | ✅ |
| 未调用真实 DeepSeek、无计费 | ✅ |
| 未运行可能写库的脚本 | ✅ |
| 未修改产品源码/依赖/锁文件/迁移 | ✅ |
| 未把历史测试数字写成本轮结果 | ✅ 见 §1 与本节标注 |

### 3.8 下一项建议任务（仅建议，未执行）

**Task C3（建议）：独立审查当前 Run 启动恢复实现及其测试缺口。**

理由：该实现是工作区中唯一「有代码、无测试、无文档、未提交」的成果，且 README 仍声称该功能未实现。建议在**不修改实现**的前提下，先完成只读代码审查（事务边界、并发竞争、`RUN_EXECUTOR_DISABLED` 语义、事件契约一致性、`running` Run 的已知缺口），再决定是否为 `recover_queued_runs` 建立可复现的验证方式（优先独立 scratch 数据库）。

---

## 4. Task C3 — Run 启动恢复实现只读审查（2026-10-14）

**结论：PARTIAL（审查完成；实现本身未验收）**

> **性质声明（必须遵守）：**
> 本节是**静态代码审查**，**不是**动态测试结果。本轮**没有运行任何测试**，**没有连接数据库**，**没有修改任何产品源码**。
> 因此**不得**据此声称 Run 启动恢复功能「已完成」或「PASS」——它的状态仍是**未提交、未测试、未验收**。

审查对象（只读）：`backend/src/backend/app.py`（121 行）、`backend/src/backend/services/run_executor.py`（1,995 行，未提交修改 +372/−5）、`backend/src/backend/services/runs.py`（事件写入）、`frontend/src/utils/runState.ts`（事件消费）、`docs/agent-pipeline-contract.md`（§9、§12/§14）。

审查前核对：两个文件的 SHA-256 与 diff 哈希与 Task C2 基线**完全一致**（`APP_MATCHES_C2=True`、`EXEC_MATCHES_C2=True`；diff `9113C523…` / `509BCAC3…`），暂存区为空、`git diff --stat` 仍只有这 2 个文件。

### 4.1 恢复范围与幂等性（问题 1）

**候选集**：`recover_queued_runs` 选 `TestRun.status IN (queued, running)` 的全部行（`:1979`），按 `created_at` 升序（`:1980`），**无 LIMIT**。

**每个 Run 的分支**（`_recover_one`，`:1881-1939`）：

| 条件 | 返回 | 写入行为 |
|---|---|---|
| 行不存在 | `missing` | 无 |
| 状态非 queued/running | `terminal` | 无 |
| `status == running` | `running` | **一律不动**（`:1897-1902`） |
| `started_at` 非空 或 已有 `run.started` 事件 | `inconsistent` | 无（留给人工） |
| queued 且 age ≤ 阈值 | `rescheduled` | `schedule_run`（另起 asyncio 任务） |
| queued 且 age > 阈值 | `closed` / `lost-race` | 条件 UPDATE + 结算 + 事件，一个事务 |

**为什么只处理“从未启动”的 queued Run**：代码把 `running` 排除在**每一个**分支之外（`:1872-1877` 与 `:1897`），理由是 schema 里没有任何字段能区分“正在本进程执行/正在别的进程执行/已经死了”，`_RUNNING_TASKS` 也只是本进程内存（`:1874-1875`）。因此可靠的 `running` 恢复需要 executor lease 或 heartbeat，而本实现没有。这是有意的最小范围，不是遗漏。

**条件 UPDATE 与后续事务的协调**：判定与写入分离——Python 侧只用来**选分支**（`:1925-1930`），真正决定结果的是单条带完整重检条件的 UPDATE（`_claim_orphaned_queued`，`:1777-1796`），条件包含 `status = 'queued'`、`started_at IS NULL`、`created_at < now() - interval`（**数据库时钟**，`:1784-1785`）、`NOT EXISTS(run.started)`（`:1771-1775、1786`），并以 `.returning(TestRun.id)` 判定是否抢到（`:1794-1798`）。

**并发恢复是否可能重复处理**：条件 UPDATE 是原子的，抢输的一方 `scalar_one_or_none()` 得到 `None` → `rollback` 并返回 `lost-race`（`:1814-1818、1936`），**不写任何东西**。reschedule 分支即使被两个进程同时执行，最终也只有一方真正执行：`_execute` 用 `WHERE status = QUEUED` 的 UPDATE 抢占（`:1465-1477`），抢输方 `rollback` 并记 “not started, it is no longer queued”。**结论：未发现重复处理路径。**

**重复执行恢复是否会重复写事件/重复结算**：不会。首次执行已把 Run 置为 `failed`（`:1789`），第二次运行时 `status` 已不在 active 集合 → `terminal`（`:1894-1895`），直接返回；`_settle_unfinished` 自身的状态过滤也保证幂等（见 4.2）。同进程内 `schedule_run` 另有 `_RUNNING_TASKS` 去重（`:1620-1622`）。

### 4.2 数据库事务边界（问题 2）

`_close_orphaned_queued`（`:1801-1848`）把四件事放进**同一个 session 与同一个事务**：claim UPDATE（`:1814`）、`_settle_unfinished`（`:1820`）、`append_run_event(run.failed)`（`:1824-1836`）、`commit`（`:1837`）。因此异常点分析是干净的：

| 异常发生位置 | 结果 |
|---|---|
| claim UPDATE 之前/之中 | 抛到 `except`（`:1846-1848`），随 session 关闭回滚，**数据库零痕迹**，返回 `False` → `_recover_one` 记为 `error` |
| 结算或事件写入之中 | 同上，整批回滚（Run 仍是 `queued`） |
| `commit()` 自身失败 | 同上，无部分提交 |

**中断/进程被杀**：只有 `commit` 返回后才可能留下痕迹，PostgreSQL 保证要么全部可见要么全部不可见。

**`_settle_unfinished`（`:799-836`）与 `_settle_after_cancel`（`:839-846`）的关系**：后者 = 前者 + `commit`（`:845-846`），语义未变（既有调用点 `:1446、1494、1507` 不受影响）。**未发现重复 commit 风险**：恢复路径只调用不提交的 `_settle_unfinished`，全路径仅一次 `commit`。

**结算的幂等性**：Step 只改 `status IN ('pending','running')`（`:817-818`）、Assertion 只改 `status NOT IN (passed, failed)`（`:825-828`）、Scenario 只改 `status == 'pending'`（`:833-835`）。已判定的断言与已完成的步骤保持原状；重复执行不产生第二次变更。

**一致性边界（低优先级观察）**：`RunScenario` 的结算只匹配 `'pending'`，而执行器确实会写入 `running`（`_start_scenario`，`:712-717`）。因此“Run 终态但 Scenario 仍为 running”在**理论上**可能残留。对本恢复路径**实际不构成影响**（只有从未启动的 queued Run 会被处理，其 scenario 只可能是 pending），但这是与取消路径共有的既有模式，`_skip_pending_steps`（`:759-773`）同样只匹配 `pending`。

### 4.3 Run 事件与状态机契约（问题 3）

- **事件名**：恢复路径只写 `"run.failed"`（`:1827`），属 `docs/agent-pipeline-contract.md:715-717` 冻结的 8 类事件之一；**未引入** `run.created` / `run.finished`。全后端检索亦无集合外事件名。
- **写入器**：通过既有唯一写入器 `append_run_event`（`services/runs.py:2066-2113`），调用方式与执行器（`:1563-1573`）、取消路径（`:2148-2156`）一致；注释明确“no second allocator, no hand-built seq”（`:1822-1823`）。
- **seq 分配**：由 `append_run_event` 内部完成——先对 `test_runs` 行 `SELECT … FOR UPDATE`（`runs.py:2097`），再以 `COALESCE(MAX(seq),0)+1` 子查询 INSERT（`:2099-2111`），`UNIQUE(run_id, seq)`（`result.py:593`）兜底。恢复路径不重新发明 seq，**符合服务端分配规则**。
- **Snapshot / SSE 续传 / 取消状态机**：恢复只**追加**一条 `run.failed` 并写 `test_runs`，不触碰 `_stream_from_seq` 的 `seq >= from_seq` 语义；重复恢复不会重复追加（见 4.1）。前端 `applyRunEvent` 对 `run.failed` 的处理（`frontend/src/utils/runState.ts:233-244`）会把 Run 置 `failed`、`settleRemaining` 结算其余场景，**不要求先有 `run.started`**；`durationMs: 0`（`:1830`）与“从未启动”语义一致，并与既有 `_fail_run` 对 queued Run 的行为同源（`:1531-1536`）。
- **状态一致性**：Run 置 `failed` 同时结算未完成子树（见 4.2），未发现“终态 Run + 未结算行”的组合（唯一例外是上述 Scenario 的 `running` 理论研究缺口）。

### 4.4 应用启动行为（问题 4）

- **触发时机**：FastAPI lifespan 启动阶段，`await recover_queued_runs()` 在 `yield` **之前**（`app.py:82-87`）——即“开始接受请求之前”，且**每个进程一次**。多 worker 部署下每个 worker 都会执行一次（幂等性由条件 UPDATE 保证）。
- **`RUN_EXECUTOR_DISABLED` 置位时**：`recover_queued_runs` 在**打开任何 session 之前**直接返回空计数（`:1964-1969`），即“完全不碰数据库”；判定与 `schedule_run` 的判定逐字一致（`:1616-1618`，`1/true/yes` 大小写不敏感）。
- **数据库不可达或恢复抛异常时**：候选集查询有独立的 `try/except`（`:1973-1986`），失败只记日志并返回；`_recover_one` 内部也吞掉异常并返回 `"error"`（`:1937-1939`）；lifespan 再包一层 `try/except`（`app.py:82-85`）。**三层保护，服务仍会启动。**
- **失败只记日志，不影响启动结果**——这是**有意**的取舍（`app.py:69-73`：“Recovery is a repair, not a prerequisite”）。
- **风险（中）**：**“服务成功启动”不等于“遗留 Run 已全部恢复”**。数据库在启动瞬间不可达时，恢复被静默跳过且**不会重试**，遗留 Run 会一直停在 `queued`/不可见状态，直到有人重启服务或手动处理；日志是唯一线索。README（`:13`、`:205`、`:255`）也仍写着“Run 启动恢复机制尚未实现”，与工作区代码不一致。
- **配置项未文档化**：`RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS`（默认 `300.0`，`:1661-1662`）在 `README.md` 中**零处提及**（`RUN_EXECUTOR_DISABLED` 同样零处提及）。
- **启动延迟（低）**：候选集无 LIMIT，且每个候选要开 1–3 个 session 串行处理（`:1882、1857、1813`）。非终态 Run 很多时，启动会被逐个串行阻塞（N+1 次查询）；这是启动期成本，不是数据正确性问题。

### 4.5 已知缺口与最小测试矩阵（问题 5）

**`running` 为何被排除**：见 4.1。**对后续设计的含义**：在没有 lease/heartbeat 的情况下，“正在运行”与“已死但状态仍是 running”在数据库里**不可区分**，因此任何对 `running` 的自动收敛都有误杀活跃运行的风险。完整恢复需要先引入执行器租约（或心跳列/表 + 过期语义），那是**独立且更大的设计决策**，本阶段不宜在恢复函数里临时猜测。

**本轮未运行的测试**：全部。后端**没有 pytest 套件**，且恢复路径**没有任何验证脚本覆盖**——检索 `backend/scripts/` 对 `recover_queued_runs` / `RUN_RECOVERY` / `recovery_max_age` 的结果为**零命中**；现有 5 个脚本（`verify_cancel_run.py:38`、`verify_get_run.py:38`、`verify_list_runs.py:41`、`verify_run_events.py:38`、`verify_run_events_stream.py:46`）反而都把 `RUN_EXECUTOR_DISABLED=1` 设为夹具保护，因此**它们连恢复代码都不会触发**。

**建议的最小测试矩阵（仅设计，本轮未执行）**：

| # | 场景 | 期望 | 断言要点 |
|---|---|---|---|
| T1 | 无任何非终态 Run | 返回空计数，零写入 | 不产生任何 `run_events` / 状态变更 |
| T2 | queued 且 age > 阈值 | `closed` | Run=`failed`、`error_code='executor-failed'`、`finished_at` 非空、恰好 1 条 `run.failed`（seq=1） |
| T3 | queued 且 age ≤ 阈值 | `rescheduled` | Run 仍 `queued`，随后被执行器正常推进为 running/passed |
| T4 | queued 但已有 `run.started` 事件 | `inconsistent` | **零写入**，仅告警日志 |
| T5 | 两个恢复并发（同一 Run） | 一个 `closed`、一个 `lost-race` | 总事件数 1；无重复结算 |
| T6 | 事务中途异常（如事件写入失败） | `error` | Run 仍 `queued`、无事件、无结算痕迹（全有或全无） |
| T7 | 同一进程内连续调用恢复两次 | 第二次为空/terminal | 不产生第二条 `run.failed` |
| T8 | `RUN_EXECUTOR_DISABLED=1` | 立即返回，**零数据库访问** | 可用“断开数据库仍不报错”或查询计数证明 |
| T9 | 数据库不可达 | 返回空计数、不抛异常 | 进程仍能启动（lifespan 不阻断） |
| T10 | `running` Run | `running`，**零写入** | `started_at`/状态/事件全部不变 |
| T11 | 脏配置（`RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS=abc` / `0` / `-5`） | 回落到 300.0 并告警 | 不出现“无限阈值”分支 |
| T12 | `test_runs` 存在但 scenario/step/assertion 处于各种非终态组合 | 结算后无 `pending`/`running` 残留（Scenario 见 4.2 观察项） | 逐表状态断言 |

**推荐的隔离验证方法（执行前必须完成）**：

1. **独立 scratch 数据库**：全新库 + `alembic upgrade head`，**不得**指向开发库；连接串只经环境变量注入，不写入仓库。
2. **优先建立最小 pytest 骨架**（`httpx.ASGITransport` 已被现有脚本证明可行），而不是再写一个 `verify_*.py`：恢复逻辑需要“构造非终态 Run 再启动应用”的夹具，pytest 的 fixture 生命周期与断言粒度更合适。该骨架**需要独立评估与批准**（新增 dev 依赖属于单独决策）。
3. **夹具与清理**：每个用例自建 guest_session/project/plan/run，用例结束 `TRUNCATE`/删除自己创建的行；不依赖、不清理开发库里的历史数据。
4. **时钟控制**：T2/T3 需要“看起来是 300 秒前创建的行”。**推荐**直接用 SQL 把 `created_at` 回填到过去（确定性、无等待），不要 `sleep` 或用 `RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS` 调小到接近 0 来制造竞态。
5. **禁用真实出网**：T3 会真的调度执行器，必须让目标地址指向**受控本地上游**或让用例在调度后立即取消，避免真实 HTTP 与计费。
6. **不修改产品源码**：若测试需要可注入的 session 工厂，应作为**独立变更提案**提出，而不是在恢复实现里开口子。

### 4.6 本轮未运行的测试与未确认的假设（如实记录）

- **未运行**：上述 T1–T12 全部；前端 Vitest；任何 `verify_*.py`；`pytest`（后端无此套件）。
- **已有但非本轮的证据**：Task C1/C2 的 `compile()` 语法编译通过（`compile OK: app.py, run_executor.py`），属**静态语法验证**，不是行为验证。
- **未确认的假设**：`asyncio.create_task` 在 lifespan 启动阶段创建的任务会在 lifespan 让出控制权后正常执行（依据 asyncio 语义与 FastAPI lifespan 顺序推断，**未实测**）；PostgreSQL 上 `func.make_interval(0,0,0,0,0,0,max_age_seconds)` 的 7 参数形式与 `interval` 运算（**未实测**）；`DateTime(timezone=True)` 列接受 Python 侧 `datetime.now(timezone.utc)` 与实际迁移建表一致性（**未实测**）；多 worker 部署下两个进程同时 reschedule 的实际行为（**未实测**，仅按条件 UPDATE 推断安全）。
- **低优先级观察**：`_claim_orphaned_queued` 的 docstring 写“the claim writes status and started_at together”（`:1759-1760`），但该 UPDATE **并未写 `started_at`**（`:1788-1793`，与 `_fail_run` 的行为一致）——属注释表述不精确，不影响行为；`_orphan_reason` 被调用两次（`:1792` 与 `:1833`），两次文本的时间戳字段可能相差若干毫秒，即 `error_message` 与事件 `failure.detail` 不是同一字符串。

### 4.7 下一项建议任务（仅建议，未执行）

**Task C4（建议）：为 Run 启动恢复建立独立 scratch 数据库上的最小 pytest 验证骨架，并先落地 T1/T2/T3/T4/T8/T10 六个用例。**

理由：本审查已把设计边界与风险说清（结论 PARTIAL），但该实现**至今没有任何可复现的行为证据**；在上述六个用例通过之前，不能把它标记为完成，也不能提交。T5–T7、T9、T11、T12 可作为第二批。

依赖与前置：① 需要批准新增 pytest 作为开发依赖；② 需要确认可用的独立 scratch 数据库；③ 完成后才谈是否提交这两处未提交修改（连同 README/契约的陈旧表述一并修订）。

## 5. Task C4-Preflight — 测试环境准备审计（2026-10-15）

**结论：PARTIAL（环境审计完成；测试环境尚未就绪，实施测试 BLOCKED 于两项批准）**

> 本节是**环境审计**，不是测试执行记录。本轮**未连接数据库、未安装依赖、未运行任何测试、未修改产品源码**。

#### 5.1 依赖与测试能力（实测）

| 问题 | 结论 | 证据 |
|---|---|---|
| pytest 是否在项目依赖声明中 | **否** | `backend/pyproject.toml` 只有 8 个运行时依赖（alembic/asyncpg/fastapi[standard]/greenlet/httpx/python-dotenv/sqlalchemy/uvicorn），**无 `[dependency-groups]`、无 `[project.optional-dependencies]`、无 pytest** |
| 是否在锁文件中 | **否** | `backend/uv.lock`（268,653 B）对 `pytest` / `pytest-asyncio` **0 命中** |
| 本机 venv 中是否安装 | **否** | `backend/.venv/Scripts/python.exe` = Python 3.12.0；`find_spec("pytest") is False`、`find_spec("pytest_asyncio") is False` |
| 系统 Python 是否有 pytest | **否**（`E:\python\python.exe` 同样 False）——**不存在"系统里有就能跑"的假象** | 同上探测 |
| 是否已有测试目录或 pytest 配置 | **否** | `backend/` 下**无** `tests/`、无 `conftest.py`、无 `pytest.ini`/`setup.cfg`/`tox.ini` |
| 已有可用测试工具 | ✅ `anyio`、`httpx`、`sqlalchemy` 均已安装；`backend` 包本身已安装（`find_spec("backend") is True`） | 18 个验证脚本已证明 `httpx.ASGITransport` 驱动 ASGI 应用可行 |

**判定：后端目前没有可复现的 pytest 测试体系。** 现有行为证据全部来自 `backend/scripts/verify_*.py` 自定义脚本；**不得**把"系统 Python 有 pytest"或"某人本地能跑"当作体系可用。

#### 5.2 独立 scratch 数据库方案（设计完成；当时尚未创建，已由 Task C4 创建并迁移）

**已确认的环境事实**：`PostgreSQL-18` 服务 Running/Automatic；`127.0.0.1:5432` 可达；`psql` **不在 PATH**（因此建库不能依赖 psql，需用 SQLAlchemy/asyncpg）；`.env` 键名 = `POSTGRES_HOST|PORT|USER|PASSWORD|DB|DEEPSEEK_API_KEY`（**值未读取、未输出**）。

**关键阻塞点（必须先讲清楚）**：`database_url` 与 `AsyncSessionLocal`、`engine` 都是 `backend/db/database.py` 的**模块级全局对象**（":33-52"），而 `app.py:80` 与 `run_executor.py` 均以**模块内直接引用** `AsyncSessionLocal` 的方式使用。因此**没有依赖注入点**：测试数据库只能通过**进程环境变量在导入之前**生效。这是本方案所有约束的来源。

**方案（七条要求逐条对应）**：

1. **物理隔离**：在同一个 PostgreSQL 18 实例上新建**独立数据库名**（建议 `aiata_c4_test`），与开发库（`POSTGRES_DB` 的值）**不同库**。建库用一次性脚本经 SQLAlchemy `create_async_engine(url, isolation_level="AUTOCOMMIT")` 执行 `CREATE DATABASE`，不依赖 psql。
2. **防止误指开发库（三重保险）**：① `conftest.py` 顶部在**任何 `backend.*` 导入之前**设置 `os.environ["POSTGRES_DB"]="aiata_c4_test"`（`load_dotenv()` 默认不覆盖已存在的环境变量，因此显式设置优先）；② 会话级 fixture **断言** `backend.db.database.database_url.database` 等于预期值，**不相等就直接失败**（用 `raise RuntimeError`，**不要用 `assert`**——`python -O` 会剥离断言）；③ `pytest.ini`/配置里固定 `testpaths`，并要求**从仓库根目录**运行（`load_dotenv()` 以 cwd 为起点，仓库根无 `.env`，可减少误加载开发 `.env` 的机会）。
3. **独立构造夹具**：`GuestSession`（`token_hash` 用 sha256，参照 `seed_dev_data.py:98-127`）→ `Project`（`guest_session_id` 非空、`user_id` 为 NULL，满足 `owner_xor` 约束）→ 测试自己的 `public_id`（**不要复用 `prj_orders`**）→ `ApiSpec` → `TestPlan`（`status="approved"`）→ `TestRun`。每行用**测试自有的唯一 id/前缀**（如 `c4prj_<uuid>`、`c4run_<uuid>`）。
4. **不依赖历史数据**：全部断言只针对本用例创建的 id；不查询、不依赖开发库中已有的 47 个 Guest Session 或 `b9-*` 记录。
5. **只清理自己创建的数据**：fixture 记录本会话创建的 id 列表，teardown 按 `id`/`public_id` 精确删除（`TestRun` 子表随 `ON DELETE CASCADE` 清理——`result.py:279` 的 `run_id` FK 为 CASCADE）；**禁止** `TRUNCATE` 全表、禁止按前缀批量删除以外的任何宽范围删除。
6. **不出网**：除 T3 的受控本地上游外，全部用例不发任何 HTTP。T3 见 4.8.4。
7. **失败也不碰开发库**：由第 2 条的"库名断言"与第 1 条的独立库名共同保证——即使测试失败、崩溃或被中断，其连接只可能指向 scratch 库。

**尚未具备的条件（因此实施测试仍 BLOCKED）**：
- 🔴 scratch 数据库**尚未创建**（本轮禁止建库）；也**尚未确认**该实例上是否已存在同名库。
- 🔴 需要**负责人批准新增 dev 依赖** `pytest`（+ 异步支持：`pytest-asyncio` 或已有 `anyio` 对应的 pytest 插件，二选一需定）。
- 🟠 需要一个**建库 + `alembic upgrade head`** 的受控步骤（`alembic/env.py:27` 复用同一个 `database_url`，因此迁移也会指向 scratch 库——这一点是优势，也必须写进流程）。

#### 5.3 首批六个用例的最小实施计划（仅设计）

共同前置：`conftest.py` 提供 `scratch_db`（会话级：断言库名、建 schema）、`fixture_run`（函数级：造一条符合所测状态的 TestRun，并登记待清理 id）。**直接调用入口是 `await recover_queued_runs()`，不是 HTTP 路由**——恢复入口没有路由，这也是它当初没有任何脚本覆盖的原因。

| 用例 | 前置数据库状态 | 调用 | 预期返回 | Run / 子表 / Event 预期变化 | 副作用证明 | 失败时重点检查 |
|---|---|---|---|---|---|---|
| **T1** | scratch 库中**无**任何 queued/running Run | `recover_queued_runs()` | `{}` | Run 不变；`run_events` 无新增 | 调用前后各表计数相同（对 `test_runs`/`run_events` 做「本用例 id 集合」级断言） | 是否误把 terminal 状态纳入候选 |
| **T2** | 一条 `queued` Run，`started_at IS NULL`，`created_at` **用 SQL 回填到 300 s 之前** | 同上 | `{"closed": 1}` | Run：`failed` + `finished_at` 非空 + `error_code='executor-failed'` + `error_message` 含阈值句；**恰好 1 条** `run.failed`（seq=1）；无 `run.started` | 断言事件**总数为 1**、且不存在第二条事件；断言 `started_at` **仍为 NULL** | 事务是否原子（若事件缺失但 Run 已 failed = 部分提交，属严重缺陷） |
| **T3** | 一条 `queued` Run，`created_at` = 当前（未超阈值） | 同上 | `{"rescheduled": 1}` | **恢复本身不改任何行**；随后执行器把 Run 推进为 `running`→终态，并写 `run.started` | 见 4.8.4 的隔离要求；断言恢复返回后**立即**（未给事件循环机会）Run 仍为 `queued` | 后台任务是否泄漏到用例之外；是否真的发出了 HTTP |
| **T4** | 一条 `queued` Run，`started_at IS NULL`，**但已存在一条 `run.started` 事件**，`created_at` 亦超阈值 | 同上 | `{"inconsistent": 1}` | **零写入**：Run 仍 `queued`、`error_code` 仍 NULL、事件仍 1 条 | 调用前后整行快照逐字段比对（含 `finished_at`/`error_*`） | 是否被误判为孤儿并关闭（这正是该分支要防的数据不一致） |
| **T8** | 库中放一条**超阈值**的 queued Run（即"若恢复运行就一定会写"的诱饵） | 设 `RUN_EXECUTOR_DISABLED=1` 后调用 `recover_queued_runs()` | `{}` | **零写入**（Run 仍 queued、无新事件） | **两层证明**：① 以包装对象替换 `recover_queued_runs` 所用模块属性并计数，断言 `session_factory.call_count == 0`；② 断言 `backend.db.database.engine.pool.checkedout() == 0`（无连接被借出）。诱饵行确保"没写"不是因为没活干 | 是否只是提前 return 但已开 session（`:1964-1969` 的判定必须在任何 session 之前） |
| **T10** | 一条 `running` Run（`started_at` 非空） | 同上 | `{"running": 1}` | **零写入**：状态/`started_at`/`finished_at`/事件全部不变 | 整行快照比对 | 是否被误当作"已死"而收敛（这是本阶段有意不做的事） |

**为什么首批只放这六个**：它们**全部不需要** Run 的子表（scenario/step/assertion）就能验证恢复的核心决策与写入，而完整子树夹具成本高（`ApiSpec`+`TestPlan`+`TestScenario`+`TestStep`+`TestAssertion`，参见 `runs.py:759-810`）。**结论：首批适合放入第一轮。**

**暂缓的用例（C3 的 T5/T6/T7/T9/T11/T12）及原因**：
- **T12（结算完整性）暂缓**：必须先有完整 Run 子树夹具，工作量最大；且它验证的是 `_settle_unfinished`（既有函数）而非恢复本身的新逻辑。
- **T5（并发竞争）暂缓**：需要用两个并发事务精确制造"同时 claim"，容易写出不稳定用例；建议在 T2 稳定后单独设计（仍需**禁止用 `sleep`**，改用显式事务与锁顺序控制）。
- **T6（中途异常）暂缓**：需要注入点（如让 `append_run_event` 抛错），属测试替身设计，建议与 T5 同批。
- **T7（重复执行）** 成本极低，若时间允许可与首批合并（T2 后紧接着再调用一次，断言返回 `{"terminal": 1}` 且事件数仍为 1）。
- **T9（数据库不可达）** 需指向一个**不可达但格式正确**的地址（如保留端口），不需要真实库；可与 T8 同批。
- **T11（脏配置）** 是纯函数级测试（`recovery_max_age_seconds()`），成本极低，建议并入首批或紧随其后。

#### 5.4 T3 的后台执行隔离方案（重点）

**风险事实（静态确认）**：T3 走 `schedule_run`（`run_executor.py:1930-1931`）→ `asyncio.create_task(execute_run(...))`（`:1625`），任务**脱离用例控制**；`_execute` 会先读运行快照，**若该 Run 有场景与 request 步骤，就会真的发 HTTP**（`:1491` 构造 `httpx.AsyncClient`，`:1498` 执行场景）。

**推荐方案（优先级从高到低，均不改产品源码）**：

1. **零场景 Run（首选）**：夹具只建 `TestRun` 行、**不建任何 `run_scenarios`**。则 `_load_tree` 返回空列表（`:601`），`for scenario in scenarios` 一次都不进入（`:1492`），`httpx.AsyncClient` 虽被构造但**不发出任何请求**，`_finish_run` 会把 Run 收为 `passed` 并写 `run.completed`。**这是"能真正走到调度、又不碰网络"的最优点。**
2. **受控本地上游（仅当需要非空场景时）**：把 `base_url` 指向 `127.0.0.1` 上一个**测试自己启动的** ASGI/HTTP 桩（`httpx` 已具备 `ASGITransport`），断言桩被调用一次；用例结束关闭桩。
3. **调度后立即取消（作为兜底）**：用例在断言后取消并等待该任务（`task.cancel()` + `await asyncio.gather(task, return_exceptions=True)`），并**在 teardown 中断言 event loop 无待决任务**，防止任务泄漏到下一个用例。
4. **若以上都不足以隔离**：**不要**为此修改产品源码。应单独提出"为执行器引入可注入的 transport/session 工厂"的变更提案（属产品代码设计决策），批准后再做。

**明确禁止**：不得用真实外部地址；不得用 `sleep` 等待阈值；不得靠"反正本机没有那个域名"来假装隔离。

#### 5.5 C3 日期核实结果（任务第六节）

**结论：C3 记录标注的 `2026-10-14` 有证据支持，无需修正。**

- **本轮实际当前时间**：`2026-10-15 15:46:38 +08:00`（`Get-Date`）。任务正文说"当前记录标注日期为 2026-10-14"并暗示当前是 2026-10-15——**这一点与文件证据一致**。
- **证据链**：
  - `docs/PROJECT_PROGRESS.md` 的 `CreationTime = 2026-10-14 16:42:56`（由 C2 建立），`LastWriteTime` 只在 `2026-10-15 15:44:08`（本轮 C4 的追加）被更新。
  - **全仓库在 2026-10-14 被写入的文件共 20 个**：19 个 `backend/scripts/*`（`16:39:01`，即 C2 的 `git restore`）与 `backend/src/backend/app.py`（`15:11:00`）；`.git/index` 为 `2026-10-14 16:42:14`。
  - **全仓库在 2026-10-15 被写入的文件只有 1 个**：`docs/PROJECT_PROGRESS.md`（本轮）。**没有任何其他文件带 2026-10-15 的时间戳**——若 C3 审查发生在 10-15，则不可能解释为何它之后没有留下任何 10-15 的痕迹，而 10-14 的时间线（16:38 备份 → 16:39 恢复 → 16:42 建文档）恰好完整。
  - `.git/logs/HEAD` 最后一次记录为 2026 年（`d7c726a` 合并），此后再无 Git 写操作。
- **因此**：C3 的记录日期 `2026-10-14` 与 C2 同日（连续会话），属于**正确记录**，本轮**未做任何日期修改**。
- **仍待核实的唯一日期项**：C1 的 `2026-02-14`（见 §2 的"日期异常"说明）——该矛盾**与本轮无关**，保持原样，**本轮不改写**。

#### 5.6 尚需负责人批准的事项

1. 批准新增 **`pytest`** 及异步支持（`pytest-asyncio` 或 anyio 插件）为**开发依赖**（会改动 `pyproject.toml` 与 `uv.lock`）。
2. 批准**创建 scratch 数据库** `aiata_c4_test`（并确认可用库名；需先只读盘点该实例上已有的库名，避免与开发库重名）。
3. 批准**在本机执行 `alembic upgrade head`** 指向 scratch 库。
4. 确认首批范围（T1/T2/T3/T4/T8/T10，T7/T11 可并入）。
5. 是否允许为测试引入**测试替身**（monkeypatch 计数、事件写入失败注入）——不涉及产品源码修改。

#### 5.7 本轮未做的事（如实记录）

**未**安装或升级任何依赖；**未**连接数据库、**未**建库、**未**运行迁移；**未**运行任何 `verify_*.py` 或 `seed_dev_data.py`；**未**运行任何测试（后端无 pytest）；**未**调用真实 DeepSeek 或任何外部目标 API；**未**修改 `pyproject.toml`/`uv.lock`/产品源码/两个未提交文件；**未**执行任何 Git 写操作；**未**处理 C2 遗留的 7 个脚本索引 stat 假阳性（按任务要求）。

#### 5.8 下一项建议任务（仅建议，未执行）

**Task C4（实施）：在获准的 scratch 数据库上落地最小 pytest 骨架，先实现 T1/T2/T4/T8/T10 五个用例。**

理由：这五个用例**完全不触发后台执行器**（T3 是唯一有该风险的），可以在隔离尚未最终确认前安全交付；T3 待 4.8.4 的方案落地并单独评审后再加入。同时把 `docs/PROJECT_PROGRESS.md` 摘要表里"Run 启动恢复 = 未测试"更新为"首批 5 个用例覆盖"。

## 6. Task C4 — Run 启动恢复最小 pytest 验证（2026-10-15）

**结论：PASS（首批五用例通过；Run 启动恢复功能仍未整体验收）**

> **表述边界（必须遵守）：** 本轮只证明"首批五个用例通过"。
> **不得**据此声称完整 Run 启动恢复功能已验收——T3（阈值内重新调度）本轮**有意未纳入**，
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现，T5/T6/T7/T9/T11/T12 仍未覆盖。

### 6.1 新增与修改的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/tests/conftest.py` | **新增**（未跟踪） | 数据库隔离闸门 + 夹具工厂 + 清理 |
| `backend/tests/test_run_recovery.py` | **新增**（未跟踪） | T1/T2/T4/T8/T10 共 9 个测试函数 |
| `backend/pyproject.toml` | **修改** | 新增 `[dependency-groups] dev = ["pytest>=9.1.1"]` |
| `backend/uv.lock` | **修改** | 只新增 pytest 及其传递依赖条目 |
| `docs/PROJECT_PROGRESS.md` | **修改** | 本节（C4 记录） |

**产品源码零修改**：`backend/src/backend/app.py` 与 `services/run_executor.py` 的 SHA-256 与 C2 基线逐字节一致（见 6.6）。未新增/修改 Alembic migration，未修改冻结契约。

### 6.2 依赖变更及原因

- 新增 **`pytest>=9.1.1`** 为开发依赖（`[dependency-groups] dev`），工具链为项目自带的 `uv`（0.12.9），未更换包管理器、未升级任何运行依赖。
- **未新增 `pytest-asyncio`**：项目已安装的 **anyio 4.15.1 自带 pytest 插件**并通过 `pytest11` 入口注册（`anyio → anyio.pytest_plugin`），异步测试直接复用，符合"如插件可用则不再新增依赖"的要求。
- 实际装入 venv 的包仅 4 个：`pytest`、`pluggy`、`iniconfig`、`packaging`（`uv pip install pytest`，未触碰其他包）。

### 6.3 scratch 数据库创建与迁移

- **创建前只读检查**：经 maintenance database `postgres` 查询 `pg_database`，当时可见 4 个库（`ai_api_testing`、`postgres`、`template0`、`template1`），**`aiata_c4_test` 不存在** → 符合创建前提。
- **创建结果**：`CREATE DATABASE "aiata_c4_test"` 成功，库数量 4 → 5；确认 `current_database()` = `aiata_c4_test`，迁移前 public 表数 = 0。
- **迁移**：迁移前以不输出凭证的方式核实 `database_url.database` = **`aiata_c4_test`**（`MATCHES_EXPECTED: True`），随后在 `backend/` 下执行 `python -m alembic upgrade head`，**EXIT=0**，四个 revision 全部应用：`20781896b560 → 96fbc39e6dcc → f3498529f573 → a4c1e8b27d93`。
- **迁移后**：public 表 **24** 张，`alembic_version` = `a4c1e8b27d93`。
- **未删除 scratch 数据库**，未对其他任何数据库执行迁移。

### 6.4 五个用例的实际结果

命令（在 `D:\Aiapi_test\backend` 下）：`python -m pytest tests/`　退出码 **0**

| # | 测试函数 | 覆盖 | 结果 |
|---|---|---|---|
| T1 | `test_t1_no_non_terminal_runs_yields_empty_counts` | 无待恢复任务 | PASS |
| T2 | `test_t2_old_queued_run_is_closed_with_one_failed_event` | 超阈值旧 queued Run | PASS |
| T4 | `test_t4_queued_run_with_a_started_event_is_left_alone` | 已有 `run.started` 的 queued Run | PASS |
| T8 | `test_t8_disabled_executor_skips_before_opening_a_session` | `RUN_EXECUTOR_DISABLED=1` | PASS |
| T10 | `test_t10_running_run_is_never_touched` | running Run 不被触碰 | PASS |
| — | `test_t10b_running_run_survives_an_unusable_window` | 脏阈值不影响 running | PASS |
| — | `test_default_window_is_what_this_file_assumes` | 默认窗口 300.0 | PASS |
| — | `test_unset_window_env_yields_the_default` | 未设变量取默认 | PASS |
| — | `test_disable_flag_did_not_leak_into_the_process` | 禁用标志未泄漏 | PASS |

**收集 9 项，通过 9，失败 0，跳过 0。** 连续运行三次均为 `9 passed`（1.17 s / 1.08 s / 1.08 s，退出码均 0），说明用例可重复且清理幂等。

### 6.5 关键行为证据（T2 断言的实际内容）

- Run：`queued → failed`；`error_code = "executor-failed"`；`finished_at` 已设置；**`started_at` 仍为 NULL**；
- `error_message` 形如 `queued for more than 300s with no executor: treated as orphaned and closed without running. Threshold RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS, decided <ts>Z.`；
- 事件：**恰好一条** `run.failed`，`seq = 1`，`payload.durationMs = 0`，`payload.failure.detail` 非空、`payload.failure.message` 存在；**不存在** `run.started`；
- 时间条件由 SQL 回填 `created_at` 构造（**未使用 sleep**）。

### 6.6 两个受保护源文件的操作前后 SHA-256

| 文件 | 本轮操作前 | 本轮操作后 | 与 C2 备份 |
|---|---|---|---|
| `app.py` | `305850D8D42A066EF8B891957F3E07F2827E5D5C4AB2541DB49164ECE757D1EF` | 同左 | **一致** |
| `run_executor.py` | `B0E2BC0588326A51063A55AA93472AD034347A14D70A7C162940384814E6C52B` | 同左 | **一致** |

diff 哈希亦与基线一致（`9113C523…` / `509BCAC3…`）。**未修改、未重写、未撤销**这两个文件。

### 6.7 隔离与副作用

- **数据库**：只连接 `aiata_c4_test`。开发库未被连接、未被迁移、未被写入（本轮未对其执行任何语句）。
- **残留**：测试结束后 scratch 库业务表行数全为 **0**（`test_runs`/`run_events`/`run_scenarios`/`run_steps`/`run_assertions`/`test_plans`/`api_specs`/`projects`/`guest_sessions`），仅保留 24 张表结构与 `alembic_version`。**未使用 TRUNCATE，未 DROP 任何数据库。**
- **网络**：**零外部 HTTP 请求**，**零 DeepSeek 调用**，无 API 计费。T1/T2/T4/T8/T10 均不会调度执行器（T3 未纳入）。
- **Git**：未执行 `add`/`commit`/`push`/`pull`/`fetch`/`reset`/`clean`。
- **生成物**：`backend/.pytest_cache/` 与 `backend/tests/__pycache__/` 已分别被 `backend/.gitignore:14` 与 `:11` 忽略，不会进入版本控制。

### 6.8 实施过程中对测试代码的两处修正（如实记录）

首轮运行 3 个失败，**原因全部在测试代码本身，不在被测实现**：

1. T2/T4/T10 读取的是测试会话身份映射中的旧对象。被测代码确实提交成功（日志 `run …: closed as an orphan` 即证明），但同一 session 的事务快照看不到。**修正**：夹具改为"写入一个会话、读回另一个新会话"，并用主键值代替 ORM 实例（避免提交/回滚后的过期属性）。
2. 清理逻辑原先依赖测试 session，失败时事务回滚导致夹具行残留（这也是首轮失败后复查 DB 仍为空的原因）。**修正**：清理改用自己独立的 session 并显式提交。
3. 另有一处**断言写错**：T2 原本断言 `error_message` 含回填的 20000 秒，而该句正确表述的是**配置阈值 300s**。已改为断言阈值语义（`300s` 与 `RUN_RECOVERY_QUEUED_MAX_AGE_ENV`）。

> 以上均为**测试代码**修正，**未削弱任何断言**，被测实现一行未改。

### 6.9 Run 恢复目前仍未覆盖的边界

1. **T3（阈值内重新调度）未实施**：会触发后台 `asyncio.create_task` 执行器，需先落实隔离方案（零场景 Run / 受控本地上游 / 调度后取消）。
2. **`running` Run 的可靠恢复未实现**：当前设计有意跳过（缺 executor lease/heartbeat），T10 只断言"不处理"这一行为。
3. **未覆盖**：并发竞争（T5）、事务中途异常（T6）、重复执行（T7）、数据库不可达（T9）、结算完整性 T12（需完整 Run 子树夹具）、脏配置除 `not-a-number` 外的取值（T11）。
4. **未验证**：`asyncio.create_task` 在 lifespan 启动阶段的执行时机、`func.make_interval` 7 参数形式在真实触发路径上的表现（本轮 T2 确实走到了该 SQL，可视为部分验证）、多 worker 并发 reschedule。
5. README 与契约中"Run 启动恢复尚未实现"的陈旧表述仍未修订。

### 6.10 下一项建议任务（仅建议，未执行）

**Task C5（建议）：T3 执行隔离设计与实施——覆盖"阈值内 queued Run 被重新调度"。**

建议采用 C4-Preflight §5.4 的**首选方案**：夹具只建 `TestRun`、不建任何 `run_scenarios`，使 `_load_tree` 返回空、执行器不发出任何 HTTP 却真实走完调度链路；并在用例结束断言 event loop 无待决任务，防止后台任务泄漏。

依赖：① 需确认该"零场景 Run"判定足够（若需非空场景则必须引入受控本地上游）；② 若必须改动产品代码才能注入 transport，应作为独立变更提案，不在测试任务内进行。

## 7. Task C5 — 阈值内 queued Run 重新调度验证（2026-10-15）

**结论：PASS（T3 路径通过；Run 启动恢复功能仍未整体验收）**

> **表述边界：** 本轮只证明"阈值内 `queued` Run 的重新调度路径通过"。
> T5（并发竞争）、T6（事务中途异常）、T7（重复执行）、T9（数据库不可达）、T11（脏配置其余取值）、T12（结算完整性）仍未覆盖，
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现。**不得将整个 Run 恢复功能标记为完成。**

### 7.1 新增与修改的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/tests/test_run_recovery.py` | **追加**（11,192 → 18,143 B；266 → 419 行） | 新增 1 个测试函数 `test_t3_young_queued_run_is_rescheduled_and_finishes_without_http` |
| `docs/PROJECT_PROGRESS.md` | **修改** | 本节 |

**未修改**：`conftest.py`（沿用 C4 夹具，零改动）、`backend/src/**` 全部产品源码、`pyproject.toml`、`uv.lock`、Alembic migration、冻结契约。

### 7.2 对 C4-Preflight 候选方案的重要修正（实测推翻假设）

C4-Preflight §7.3/§7.4 曾假设"零场景 Run 使执行器**不构造** `httpx.AsyncClient`"。**实测证明该假设错误**：

- 首轮实现按该假设把客户端改为"禁止构造"，T3 立即失败，日志显示 `run_executor.py:1491` **确实构造了客户端**。
- **源码事实**：`async with httpx.AsyncClient(...)`（`:1491`）位于 `for scenario in scenarios`（`:1492`）**之前**，即客户端在循环外开启，**空场景集同样会构造它**，只是不会调用发送。
- 正确结论应当是：**零场景避免的是"发出请求"，而不是"构造客户端"**。断言已据此改写为：允许构造、**禁止发送**。

这属于测试代码的修正，**未削弱任何断言**——新断言比原假设更强（它同时证明执行器真的走到了 `:1491`，而不是靠提前返回"蒙混过关"）。

### 7.3 T3 的完整调度链核对（以当前源码为准）

| 环节 | 位置 | 实测结论 |
|---|---|---|
| 候选筛选 | `run_executor.py:1975-1983` | 本 Run（`queued`）进入候选 |
| 年龄判定 | `:1925-1930` | `created_at` 为当前 → 年龄 ≤ 300s → 进入 reschedule 分支 |
| 重新调度 | `:1930-1931` → `schedule_run`（`:1599-1638`） | `asyncio.create_task(execute_run(...), name="run-executor-<id>")`（`:1625`），登记进 `_RUNNING_TASKS`（`:1637`） |
| 抢占 | `:1465-1477` | `UPDATE … WHERE status='queued'` 成功 → `running` + `started_at` |
| 事件 1 | `:1479-1485` | `run.started`，随后 **commit** |
| 空场景 | `_load_tree`（`:601-618`） | 无 `run_scenarios` → **`:617-618` 提前返回 `[]`** |
| 循环体 | `:1491-1512` | `httpx.AsyncClient` **被构造**，但 `for scenario in []` **不进入**，**零发送** |
| 收尾 | `_finish_run`（`:1386-1424`） | `UPDATE … WHERE status='running'` → **`passed`**（`:1393`）+ `run.completed`（`:1419`）+ commit（`:1422`） |

### 7.4 T3 的实际结果与最终状态

命令：`python -m pytest tests/test_run_recovery.py -k t3 -v` → **1 passed / 9 deselected，EXIT=0**

**执行期实测证据（临时加 `-s` 打印，取证后已移除，最终文件不含打印语句）：**

```
C5-EVIDENCE clients_built=1
C5-EVIDENCE events=['run.started', 'run.completed'] seqs=[1, 2] status=passed
```

逐项对应任务要求：

| 要求 | 实测结果 |
|---|---|
| 被正确识别并返回 `rescheduled == 1` | ✅ `counts["rescheduled"] == 1` |
| 返回中无 `closed` 计数 | ✅ 断言 `"closed" not in counts` |
| 正常进入既有后台执行流程 | ✅ 捕获到名为 `run-executor-<run_id>` 的 Task；且客户端构造计数 = **1**，证明执行器真的走到 `:1491` |
| 无 Scenario 时正常结束 | ✅ 最终 `status = passed`，`started_at`/`finished_at` 均非空且 `finished_at >= started_at` |
| 不发 HTTP 请求 | ✅ 客户端被包成 `send()` 直接抛错的子类；全程**零调用**（否则测试失败） |
| 无遗留后台 Task | ✅ `_RUNNING_TASKS` 已释放该 id；`asyncio.all_tasks()` 中无 `run-executor-*` 待决 |
| 不影响 C4 的测试 | ✅ 整套 10 项全过（见 7.5） |

**事件契约核对**：事件类型序列恰为 `["run.started", "run.completed"]`（均属冻结的 8 类）；`seq` 恰为 `[1, 2]`（每 run 从 1 稠密递增）；**无 `run.failed`**；事件总数 2，**无重复**；`run.started` 携带 `startedAt`，`run.completed` 携带 `finishedAt` 与 `durationMs`；Run 行终态 `passed` 与事件流一致。

### 7.5 整套测试的每次运行结果

命令：`D:\Aiapi_test\backend>` `python -m pytest tests/`（以 pytest 自身摘要为准，非仅外层退出码）

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 第 1 次 | `10 passed in 2.22s` | 0 |
| 第 2 次 | `10 passed in 2.19s` | 0 |
| 第 3 次 | `10 passed in 2.25s` | 0 |
| 第 4 次（移除取证打印后，`-v`） | `10 passed in 2.21s` | 0 |
| T3 单独重跑 | `1 passed, 9 deselected in 1.92s` | 0 |

第 4 次逐项：`test_default_window_…` / `test_unset_window_env_…` / `test_t1_…` / `test_t2_…` / `test_t4_…` / `test_t8_…` / `test_t10_…` / `test_t10b_…` / `test_disable_flag_…` / `test_t3_…` **全部 PASSED**。
共 **10 个测试函数**：C4 原有 9 个 + 本轮 T3 1 个。

### 7.6 后台 Task 生命周期与清理

- **捕获方式**：以 spy 包装 `asyncio.create_task`，在 `recover_queued_runs()` 执行期间记录创建出的 Task，并按名字 `run-executor-<run_id>` 精确选中本用例的那一个（不依赖 `asyncio.all_tasks()` 的固定数量、不使用 `sleep`、不轮询）。
- **等待方式**：`await background` —— 等待**该 Task 本身**，无超时、无轮询。
- **结束判定**：`task.done()` 为真；`task.cancelled()` 为假；`task.exception()` 为 `None`。
- **登记释放**：断言 `run_id not in run_executor._RUNNING_TASKS`（done callback `_forget` 已执行）。
- **泄漏检查**：断言 `asyncio.all_tasks()` 中不存在名字以 `run-executor-` 开头的待决任务。
- **清理顺序**：先确认 Task 结束，再由夹具 teardown 删除本用例的行；清理**不使用 TRUNCATE**、不删库、不触碰其他用例的数据。
- **失败兜底**：`finally` 中先 `monkeypatch.undo()`（避免 teardown 期间仍被 spy 影响），再对任何未结束的 Task 执行 `cancel()` 并 `await`，确保**不把未结束的后台 Task 留给后续测试**。**本轮正常路径并未触发该兜底**（断言本身就是"没有未结束的 Task"）。

### 7.7 数据库安全闸门与清理结果

- 闸门未变：`conftest.py:35` `SCRATCH_DB = "aiata_c4_test"`；`:45` 在任何 `backend.*` 导入前 `os.environ["POSTGRES_DB"] = SCRATCH_DB`；导入后再以 `raise RuntimeError`（非 `assert`）核对 `database_url.database`。
- 所有运行结束后重查 scratch 库：`test_runs` / `run_events` / `run_scenarios` / `run_steps` / `run_assertions` / `run_evidence` / `test_plans` / `api_specs` / `projects` / `guest_sessions` **全部为 0 行**；`c4prj_%` 前缀残留 **0**；public 表仍 24 张；`alembic_version = a4c1e8b27d93`。
- **未创建数据库、未重复迁移、未新增或升级依赖。**
- **开发库未被连接、未被迁移、未被写入。**

### 7.8 两个受保护源文件

| 文件 | 本轮前后 | 与 C2 备份 | 与 C4 基线 |
|---|---|---|---|
| `app.py` | `305850D8…57D1EF` 未变 | 一致 | 一致 |
| `run_executor.py` | `B0E2BC05…E6C52B` 未变 | 一致 | 一致 |

### 7.9 仍未测试的恢复场景

1. **T5 并发竞争**：两个恢复过程同时抢同一 Run（`lost-race` 分支）——需显式事务/锁顺序控制，禁止用 `sleep`。
2. **T6 事务中途异常**：`_close_orphaned_queued` 在事件写入或 commit 失败时的全有或全无。
3. **T7 重复执行恢复**：第二次调用是否只报 `terminal`、不产生第二条事件。
4. **T9 数据库不可达**：启动期恢复失败但服务仍启动。
5. **T11 脏配置其余取值**：`0` / `-5` 的回落（目前只覆盖 `not-a-number`）。
6. **T12 结算完整性**：需要完整 Run 子树（scenario/step/assertion）夹具，验证 `_settle_unfinished` 逐表状态。
7. **`running` Run 的可靠恢复**：仍无 lease/heartbeat，T10 只断言"不处理"。
8. **未验证**：多 worker 部署下两个进程同时 reschedule 的真实行为（本轮为单进程）。
9. **未验证**：`run.started` 与步骤事件在真实（非空）Scenario 下的完整序列。

### 7.10 下一项建议任务（仅建议，未执行）

**Task C6（建议）：补齐"重复执行 + 事务原子性"两条低成本用例（C3 的 T7 与 T6 的静态可测部分），并顺带覆盖脏配置 `0` / `-5`（T11）。**

理由：T7 与 T11 成本极低（在同一条 Run 上再调用一次恢复、分别把阈值设为 `0` 与 `-5`），能直接验证"幂等"与"不出现无限阈值"这两个高风险断言；T6 需要注入点，建议在同一轮内以最小 monkeypatch 方案先做"事件写入抛错"的单一场景。

依赖：① 沿用现有夹具，无需新依赖或新库；② 若 T6 需要"可注入 session 工厂/事件写入器"，应先作为独立变更提案评估，不得直接改产品源码。

### 7.11 进度文档被截断与逐字重建（必须记录）

本轮执行过程中，一次失败的 Python `write_text()` 调用把 `docs/PROJECT_PROGRESS.md` 截断为 **0 字节**；该文件当时**未提交**（始终为未跟踪文件，`HEAD` 中不存在），因此没有 Git 历史版本可恢复，本机也**不存在任何影子副本或备份**。文件随后**依据本次对话中逐字保留的原文重建**，内容恢复为重建前的状态；此事件不涉及任何产品源码、依赖或数据库，也未产生其他副作用。

- **受损对象**：仅 `docs/PROJECT_PROGRESS.md`（本地未跟踪文件），大小一度为 0 字节。
- **无可用副本**：未提交、无 Git 历史版本、无影子副本、无备份目录命中该文件。
- **恢复方式**：从本次对话中保留的逐字文本重建，**不是**凭记忆改写或摘要；B19/C1/C2/C3/C4-Preflight/C4 的既有记录未被改写。
- **影响范围**：产品源码、`pyproject.toml`、`uv.lock`、Alembic 迁移与 scratch 数据库**均未受影响**；两个未提交的 Run 恢复源文件 SHA-256 未变。
- **后续要求**：进度文档在提交前应视为**唯一副本**；建议尽快将其纳入版本控制（提交），在那之前任何写入都应先落地一份项目外备份。

## 8. 当前风险与待办

1. **真实 Agent E2E 未完成**：真实 DeepSeek provider 的**成功**调用路径，以及「OpenAPI → 分析 → 测试计划 → 批准 → Run → 结果/事件」的完整浏览器闭环尚未通过端到端验收。
2. **Run 启动恢复仍不完整**：现有实现只处理从未启动过的旧 `queued` Run；`running` Run 的可靠恢复（executor lease / heartbeat）尚未实现。C4/C5 已建立 10 个 pytest 用例，但 T5/T6/T7/T9/T11/T12 仍未覆盖。
3. **后端 pytest 覆盖仍很窄**：`backend/tests/`（10 项）全部针对 Run 启动恢复，其他模块没有 pytest 用例；不要与 `verify_*.py` 自定义脚本混称。
4. **ProjectSwitcher 子路由保留行为仍有验证缺口**：仅人工确认了基础切换与 Overview 路由。
5. **Guest Session 历史测试数据尚未清理**：该表曾由 40 增至 47，另有 B9 的 `b9-*` Project 与 B11 的 3 个无 Project 会话。**未经批准不得删除**。
6. **契约与 README 仍有过期或相互矛盾的状态表述**：`README.md:13`/`:205`/`:255` 关于 Run 启动恢复的说法与当前工作区代码及测试不一致；`docs/identity-access-contract.md:3` 与 `:106-107`、`docs/agent-pipeline-contract.md:95`/`:96`/`:661`/`:744` 亦同。
7. **GitHub 远程同步状态未确认**：DNS 被接管 + git TLS 凭证失败，联网核对前不得断言已同步。
8. **Git 索引 stat 缓存假阳性**：7 个已恢复脚本显示为 ` M`（详见 §3.5）。
9. **仓库卫生**：`.agents/skills/taste-skill/SKILL.md` 被跟踪；`backend/dosc/` 与 `docs/` 存在双份同名契约（权威性未说明）。
10. **恢复可观测性不足**：启动瞬间数据库不可达时恢复被静默跳过且不重试；`RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS` 与 `RUN_EXECUTOR_DISABLED` 在 README 中零处提及。
11. **`running` Run 无租约/心跳**：无法区分「正在运行」与「已死但状态仍是 running」。
12. **多 worker 下并发 reschedule 未实测**（C5 为单进程）。
13. **进度文档曾被我自己的脚本截断（Task C5 事故）**：见 §7.11，文件已重建，但这是一次真实的数据丢失。
## 9. 记录格式约定（后续任务请沿用）

每条任务记录至少包含：

1. 日期、任务编号/标题、目标、最终状态（PASS / PARTIAL / BLOCKED）。
2. 修改文件列表及摘要；零源码修改时明确写「产品源码零修改」。
3. 本轮**真实执行**的命令、测试输出、通过/失败数量与 exit code。
4. 清楚区分「本轮实测」「历史结果」「未运行」。
5. 数据库副作用：是否连接、是否创建/删除记录、是否清理；未触碰也要写。
6. 安全/契约/架构边界是否保持（事件名、授权、Run 状态机、SSE、变量安全）。
7. 未解决问题、风险、证据盲区。
8. 下一项建议任务及依赖。
9. 本次更新涉及的准确路径与小节标题。

**禁止**：把文件存在当成功能完成；把自定义脚本 checks 称为 pytest；把历史测试数说成本轮重跑结果；把手动代理浏览器 E2E 说成完整 Agent E2E；因阶段结项而删除其验证脚本。


---


---

## 10. Task C6 — Run 恢复幂等性与无效窗口配置测试（2026-10-16）

**结论：PASS（T7 与 T11 通过；发现并记录 1 个新的实现缺陷，未修改产品源码）**

> **表述边界：** 本轮只补充"重复执行幂等"与"无效窗口配置"两类用例，并记录一个新发现的实现缺陷。
> T5（并发竞争）、T6（事务中途异常）、T9（数据库不可达）、T12（结算完整性）仍未覆盖；
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现。**不得据此声称整个 Run 恢复功能已验收。**

### 10.1 新增与修改的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/tests/test_run_recovery.py` | **修改** | 删除 `test_t10b`；新增 T7、T11（参数化）、T11 泄漏防护、T11b（xfail）。18,143 → 23,543 B |
| `docs/PROJECT_PROGRESS.md` | **修改** | 追加本节；并修正 §7 子章节顺序 |

**未修改**：`conftest.py`（**零改动**）、`app.py`、`run_executor.py`、其他产品源码、`pyproject.toml`、`uv.lock`、Alembic 迁移、冻结契约。**未新增依赖、未建库、未迁移。**

### 10.2 T7 —— 重复执行恢复的幂等性

`test_t7_recovery_is_idempotent_for_an_already_closed_run`

**做法**：在 `aiata_c4_test` 中创建本用例专属的旧 `queued` Run（`started_at IS NULL`、`created_at` 回填到阈值之前、无 `run.started`），连续调用两次 `recover_queued_runs()`，期间不修改 Run 状态、不删除事件。

| 检查点 | 实测结果 |
|---|---|
| 第一次调用 | `{"closed": 1}`，**不含** `terminal` |
| Run 状态 | `failed`，`error_code = executor-failed` |
| 事件 | **恰好 1 条** `run.failed`，`seq = 1` |
| 第二次调用 | **不含** `closed` / `rescheduled` / `inconsistent`；报告集合为空或仅 `terminal` |
| Run 行（status / started_at / finished_at / error_code / error_message） | 与第一次调用后**逐字段相同** |
| 事件流（名称序列 / seq / 数量） | 与第一次调用后**完全相同**，仍为 1 条 |

**为什么第二次调用是空的**（源码依据）：候选集查询为 `WHERE status IN (queued, running)`（`run_executor.py:1979`），已关闭的 Run 状态为 `failed`，**根本不在候选集中**，因此连 `_recover_one` 都不会进入——这比"进入后返回 terminal"更早地保证了幂等。

> 这是**行为测试**：它验证两次运行之间的数据库状态与事件流，而不是单次调用的返回值。

### 10.3 T11 —— 无效窗口配置

`test_t11_unusable_window_values_fall_back_to_the_default`（参数化）+ `test_t11_env_var_does_not_leak_between_cases`（泄漏防护）

**依据当前源码**（`recovery_max_age_seconds()`，`run_executor.py:1688-1722`）：空串 → 默认；`float()` 失败 → 默认 + 告警；`value <= 0` → 默认 + 告警；否则返回该值。因此"无效值回退 300.0"**由当前代码证实**，不是照抄 C3 的历史结论。

| 参数 | 期望 | 实测 |
|---|---|---|
| `"0"` | 300.0 | ✅ 300.0 |
| `"-5"` | 300.0 | ✅ 300.0 |
| `"not-a-number"` | 300.0 | ✅ 300.0 |
| `" "`（仅空白） | 300.0 | ✅ 300.0 |

每个参数内均断言（测试 ID 明确区分取值）：① 实际返回值等于默认值；② 该测试设置的变量就是被读取的那个；③ 与当前设计一致的回退行为。**参数的隔离由 `monkeypatch` 保证**，并以独立的泄漏防护用例断言测试结束后 `RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS` 不存在且默认值生效——实测无泄漏。

### 10.4 新发现缺陷：无限大窗口不会被拒绝（T11b，xfail）

`test_t11b_infinite_window_is_rejected_not_silently_unlimited`（`@pytest.mark.xfail(strict=False)`）

**缺陷**：`float("1e999")` 在 Python 中返回 `inf` 而非抛错，`inf <= 0` 为假，因此该值被**原样返回**。

- **实际行为**：`recovery_max_age_seconds()` 返回 `inf`。
- **影响**：`age > window` 永远为假 → 旧孤儿 **永远不会被关闭**，恢复静默失去作用（可用性缺陷，不是安全缺陷）。
- **与文档化的设计意图不符**：函数 docstring 明确写 "a typo must not silently turn either branch into an unlimited one"（`:1694-1695`），但上溢值恰好造成 unlimited。
- **本轮处理**：以 `xfail(strict=False)` 固化该缺陷（**实测 XFAIL**），使其可见且不会被遗忘；**未修改产品源码**。若将来实现加上上界校验，该用例会转为 XPASS，提示可以移除标记。
- **建议**：修复合入时应在 `value <= 0` 之外增加"非有限值"判定（例如 `math.isfinite`），并同步补一条正向用例。

### 10.5 测试运行结果（pytest 自身摘要）

命令：`D:\Aiapi_test\backend>` `python -m pytest tests/`

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 新增用例（`-k "t7 or t11"`） | `6 passed, 9 deselected, 1 xfailed in 1.79s` | 0 |
| 全套 第 1 次 | `15 passed, 1 xfailed in 2.60s` | 0 |
| 全套 第 2 次 | `15 passed, 1 xfailed in 2.50s` | 0 |
| 全套 第 3 次 | `15 passed, 1 xfailed in 2.47s` | 0 |

**测试函数数（AST 实测）**：C4 原有 9 个 − 删除的 `test_t10b` 1 个 = 8 个，加本轮新增 4 个（T7、T11 参数化、T11 泄漏防护、T11b）= **13 个测试函数**；参数化展开为 4 项，加上 xfail 记入后 pytest 共收集 **16 项**，实测 **15 passed + 1 xfailed**。

> `test_t10b`（"running Run 在脏窗口下不受影响"）被删除，因为它依赖 `"not-a-number"` 且断言与新的参数化 T11 重复；其覆盖内容已由 `test_t11_unusable_window_values_fall_back_to_the_default[garbage]`（回退语义）与 `test_t10_running_run_is_never_touched`（running 不受影响）**完整保留**，删除不减少覆盖。

### 10.6 数据库使用与清理

- 只连接 `aiata_c4_test`；安全闸门未变（`conftest.py:35` 指定库名，`:45` 在任何 `backend.*` 导入前设置 `POSTGRES_DB`，导入后以 `raise RuntimeError` 复核）。
- 三次全套运行后重查：`test_runs`/`run_events`/`run_scenarios`/`run_steps`/`run_assertions`/`run_evidence`/`test_plans`/`api_specs`/`projects`/`guest_sessions` **全部 0 行**；24 张 public 表；`alembic_version = a4c1e8b27d93`。
- **未使用 TRUNCATE**，不删库，不触碰其他用例数据；**开发库未被连接或修改**。

### 10.7 产品源码未修改的证据

| 文件 | 本轮前后 | 与 C2 备份 |
|---|---|---|
| `app.py` | `305850D8…57D1EF` 未变 | 一致 |
| `run_executor.py` | `B0E2BC05…E6C52B` 未变 | 一致 |

### 10.8 进度文档备份与哈希核验

- **更新前备份**：`D:\_aiapi_progress_backup_20261016-091911\`（含 `PROJECT_PROGRESS.md` 与 `MANIFEST.txt`），与更新前源文件 `IDENTICAL=True`、`SHA_MATCH=True`。
- **更新前 SHA-256**：`D52D3308F217A263FC65D54C657EA333519D24E8AB69383B5AADD5FD38E3C4BF`（65,571 字节）。
- **更新后 SHA-256**：见交付报告（**不写入本文档**，避免"文档记录自身哈希"这一自指矛盾）。
- **写入流程**：先在 `D:\`（同卷）生成临时文件 → 语法/结构检查（章节、围栏、表格、结尾）→ `os.replace` 原子替换 → 重新读取并复算哈希。写入失败时保留原文件与备份，不做就地覆盖。

### 10.9 §7 子章节顺序修正

修正前：`7.9 → 7.11 → 7.10`（7.11 排在 7.10 之前）。修正后：`7.9 → 7.10 → 7.11`。**仅移动小节位置**，未删除、未重写 C5 事故记录，未改动其他历史结论。

### 10.10 尚未覆盖的恢复场景

1. **T5 并发竞争**：两个恢复过程同时抢同一 Run（`lost-race` 分支）——需显式事务/锁顺序控制，禁止 sleep。
2. **T6 事务中途异常**：事件写入或 commit 失败时的"全有或全无"（源码分析已给出结论，缺行为证据）。
3. **T9 数据库不可达**：启动期恢复失败但服务仍启动。
4. **T12 结算完整性**：需完整 Run 子树夹具，逐表验证 `_settle_unfinished`。
5. **`running` Run 的可靠恢复**：仍无 lease/heartbeat。
6. **多 worker 并发 reschedule**：未实测。
7. **无限大窗口缺陷修复后的正向用例**（见 8.4）。

### 10.11 下一项建议任务（仅建议，未执行）

**Task C7（建议）：并发与原子性用例（T5 + T6）。**

理由：这是恢复实现中风险最高、且至今完全没有行为证据的两条路径——条件 UPDATE 的竞争语义与"全有或全无"的事务边界。
依赖：① T5 需要两个真实并发事务与显式锁顺序控制（不得用 sleep 制造竞争）；② T6 需要事件写入失败的注入点，若无法在不改产品源码的前提下实现，应先提交独立变更提案（不得在测试任务内改产品源码）。

### 10.12 进度文档最终状态（更新后核验）

- **更新后 SHA-256**：`92A8D94DE8054D311C01B454A9F8C0C1458C641C4B76B7C06FA23450517EB12F`（本节写入完成时的值）（75063 字节左右；**该值仅表示本节写入完成时的状态**，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`D52D3308F217A263FC65D54C657EA333519D24E8AB69383B5AADD5FD38E3C4BF`（65,571 字节，备份见 8.8）。
- 两个哈希的**权威记录**在项目外备份清单 `D:\_aiapi_progress_backup_20261016-091911\MANIFEST.txt` 与交付报告中；本文档不把自身哈希当作不变量。
- 结构核验：章节编号连续、代码围栏成对、17+ 张 Markdown 表格无列数错误、文件非空且 UTF-8 无 BOM。

---

## 11. Task C7 — 非有限恢复窗口配置缺陷修复与测试（2026-10-16）

**结论：PASS（缺陷已修复；XFAIL 归零；产品源码改动为最小必需）**

> **表述边界：** 本轮只修复 `recovery_max_age_seconds()` 的非有限值处理，并把 C6 固化的 XFAIL 转为正常测试。
> T5（并发竞争）、T6（事务中途异常）、T9（数据库不可达）、T12（结算完整性）仍未覆盖；
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现。**不得据此声称整个 Run 恢复功能已验收。**

### 11.1 实际修改的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/src/backend/services/run_executor.py` | **修改（+13 行，−0 行）** | 新增 `import math`；在 `value <= 0` 之前插入 `math.isfinite` 守卫 |
| `backend/tests/test_run_recovery.py` | **修改** | 删除 T11b 的 `xfail` 并改写为参数化正常测试；新增有限正值用例；补 `import logging` |
| `docs/PROJECT_PROGRESS.md` | **修改** | 追加本节 |

**未修改**：`app.py`、`conftest.py`、其他产品源码、`pyproject.toml`、`uv.lock`、Alembic 迁移、冻结契约。**未新增依赖、未建库、未迁移。**

### 11.2 缺陷与修复

**缺陷（C6 发现）**：`float("1e999")` 返回 `inf`（不抛错），而 `inf <= 0` 为假，因此该值被原样返回。窗口变成无限大 → `age > window` 永远为假 → **旧孤儿永远不会被关闭**，恢复静默失效（fail-open）。这与函数 docstring 的承诺（"a typo must not silently turn either branch into an unlimited one"）直接冲突。

**修复**：在符号检查**之前**插入有限性守卫。顺序很关键——`-inf` 虽然满足 `<= 0`，但语义上属于"非有限"，必须先被明确拒绝；且两者结果相同（都回退并告警），因此不改变任何既有语义。

```python
    if not math.isfinite(value):
        # inf and nan are refused before the sign test: float("1e999") is inf, and a
        # window of inf would make "age > window" false forever, so recovery would
        # silently stop closing orphans -- the opposite of a typo that is too strict.
        logger.warning(
            "%s=%r is not finite; using %s seconds",
            RUN_RECOVERY_MAX_AGE_ENV,
            raw,
            RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS,
        )
        return RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS
```

**未改动**：空串/纯空白的默认行为、`float()` 失败告警、`value <= 0` 语义、有限正数原样返回、函数签名与调用链、告警文案格式。

### 11.3 行为矩阵（实测，修复后）

| 环境变量输入 | 实测返回 | 告警 |
|---|---|---|
| 未设置 | 300.0 | — |
| `""` | 300.0 | — |
| `"   "`（纯空格） | 300.0 | — |
| `"abc"` | 300.0 | `is not a number` |
| `"0"` / `"0.0"` | 300.0 | `is not positive` |
| `"-5"` | 300.0 | `is not positive` |
| **`"1e999"`** | **300.0** | **`is not finite`** |
| **`"-1e999"`** | **300.0** | **`is not finite`** |
| **`"inf"`** | **300.0** | **`is not finite`** |
| **`"-inf"`** | **300.0** | **`is not finite`** |
| **`"Infinity"`** | **300.0** | **`is not finite`** |
| **`"nan"`** | **300.0** | **`is not finite`** |
| **`"NaN"`** | **300.0** | **`is not finite`** |
| `"0.5"` | 0.5 | — |
| `"60"` | 60.0 | — |
| `"300"` | 300.0 | — |

### 11.4 测试变更

- **删除** `test_t11b_infinite_window_is_rejected_not_silently_unlimited`（`xfail(strict=False)`）——缺陷已修复，旧断言不再成立。
- **新增** `test_t11b_non_finite_windows_fall_back_to_the_default`（**参数化 6 项**：`1e999`、`inf`、`Infinity`、`nan`、`NaN`、`-inf`）。每项断言：① 返回值为默认 300.0；② 该测试设置的变量就是被读取的那个；③ **至少产生一条 WARNING 级日志**（用 `caplog` 断言，落实"并告警"要求）。
- **新增** `test_t11b_finite_positive_windows_are_still_honoured`：`60`、`0.5`、`300`、`86400` 均原样返回——防止守卫误伤合法配置。
- **保留** 原有 T11（`0`/`-5`/非数字/空白）与 T11 泄漏防护用例，断言未被削弱。

**测试函数数（AST 实测）**：13 → **14**；pytest 收集项：16 → **22**。

### 11.5 测试运行结果（pytest 自身摘要）

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 配置相关 `-k "t11"` | `12 passed, 10 deselected in 0.68s` | 0 |
| 全套 第 1 次 | `22 passed in 2.32s` | 0 |
| 全套 第 2 次 | `22 passed in 2.34s` | 0 |
| 全套 第 3 次 | `22 passed in 2.23s` | 0 |
| `-rA` 扫描 XFAIL/XPASS | **零命中** | 0 |

**XFAIL 数量 1 → 0**；无 XPASS；无环境变量泄漏（泄漏防护用例通过）；无后台 Task 残留（T3 内断言通过）。T1/T2/T3/T4/T7/T8/T10 全部继续通过。

### 11.6 数据库使用与清理

- 只连接 `aiata_c4_test`；隔离闸门未变（`conftest.py` 未修改）。
- 运行后实测：`test_runs`/`run_events`/`run_scenarios`/`run_steps`/`run_assertions`/`run_evidence`/`test_plans`/`api_specs`/`projects`/`guest_sessions` **全部 0 行**；24 张 public 表；`alembic_version = a4c1e8b27d93`。
- **未使用 TRUNCATE**、未建库、未迁移；**开发库未被连接或修改**；**零外部 HTTP、零真实模型调用**。

### 11.7 备份与哈希

- **改动前备份**：`D:\_aiapi_c7_backup_20261016-092624\`（`run_executor.py`、`test_run_recovery.py`、`PROJECT_PROGRESS.md` + `MANIFEST.txt`），三个文件 `copy_identical=True`。
- **文档更新前备份**：`D:\_aiapi_progress_backup_20261016-092710\`，与源文件 `IDENTICAL=True`、`SHA_MATCH=True`。
- **文档更新前 SHA-256**：`3E652BD65ADF1129CB22E3DD2C112A30DF4D0AEDAA8477D4FD5637B4F7A490A3`（75,098 字节）。
- **文档更新后 SHA-256**：见 11.11 与交付报告；**权威记录**在项目外备份清单中。
- **写入流程**：更新前独立备份 → 同卷临时文件构建完整新版本 → 读回复核 → 结构检查（章节 / 围栏 / 表格 / UTF-8）→ `os.replace` 原子替换 → 重新读取并复算哈希。**未原地截断重写，未从对话重建全文。**

### 11.8 §11 编号与文档结构

本轮记录为新增顶层小节 `## 11.`，其子节为 `### 11.1`–`### 11.11`，均按升序排列。文档顶层编号保持连续：`0–11`。

### 11.9 仍未解决的 Run 恢复风险

1. **T5 并发竞争**：`lost-race` 分支无行为证据（需真实并发事务）。
2. **T6 事务中途异常**："全有或全无"缺行为证据（需事件写入失败的注入点）。
3. **T9 数据库不可达**：启动期恢复失败但服务仍启动，未实测。
4. **T12 结算完整性**：需完整 Run 子树夹具。
5. **`running` Run 无 lease/heartbeat**：无法区分"正在运行"与"已死但状态仍是 running"。
6. **多 worker 并发 reschedule** 未实测。
7. **恢复可观测性不足**：启动期数据库不可达时恢复被静默跳过且不重试；相关环境变量在 README 中零处提及。
8. **进度文档仍未提交**（未跟踪），仍是单一副本风险。

### 11.10 下一项建议任务（仅建议，未执行）

**Task C8（建议）：并发与原子性用例（T5 + T6）。**

理由：修复后剩余的空白集中在"竞争"与"失败原子性"两条路径，二者风险最高且至今完全没有行为证据。
依赖：① T5 需要两个真实并发事务与显式锁顺序控制（**禁止用 sleep**）；② T6 需要事件写入失败的注入点，若无法在不改产品源码的前提下实现，应先提交独立变更提案（不得在测试任务内改产品源码）。

### 11.11 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`5339D2E9468F582671B7B0434624B854282D99DE0E43FC907E82EC9CC14A6529`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`3E652BD65ADF1129CB22E3DD2C112A30DF4D0AEDAA8477D4FD5637B4F7A490A3`（75,098 字节，备份见 11.7）。
- 两个哈希的**权威记录**在项目外备份清单 `D:\_aiapi_progress_backup_20261016-092710\MANIFEST.txt` 与交付报告中。

---

## 12. Task C8 — Run 恢复并发竞争与事务原子性测试（2026-10-16）

**结论：PASS（T5 与 T6 均通过；另记录 1 处语义混淆缺陷，未修改产品源码）**

> **表述边界：** 本轮补上"并发竞争"与"失败原子性"两条行为证据。T9（数据库不可达）与 T12 的其余分支仍未覆盖；
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现。**不得据此声称整个 Run 恢复功能已验收。**

### 12.1 实际修改的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/tests/test_run_recovery.py` | **追加** | 新增 2 个测试 + 3 个测试内私有辅助函数；补 `delete`/`select`/`update` 与子表模型导入 |
| `docs/PROJECT_PROGRESS.md` | **修改** | 追加本节 |

**未修改**：`app.py`、`run_executor.py`、`runs.py`、`conftest.py`、`pyproject.toml`、`uv.lock`、Alembic 迁移、冻结契约。**未新增依赖、未建库、未迁移、未修改 schema。**

### 12.2 T5 —— 真实并发竞争

**测试**：`test_t5_concurrent_recoveries_close_the_orphan_exactly_once`

**同步屏障（关键设计）**：在 `run_executor._claim_orphaned_queued` 的**入口**安装包装函数，内部 `await asyncio.Barrier(2).wait()`。
这一点很重要：`recover_queued_runs()` 先完成候选集查询、再逐个进入 `_recover_one`，因此**两个调用方在到达该屏障时都已完成候选集发现**，随后被同时释放，进入**真实的数据库条件 UPDATE**。

- 未使用 `sleep`；未用 mock 伪造 `lost-race`；未给产品源码加测试钩子；包装函数内部仍调用原函数（真实语句、真实事务）。
- 用 `asyncio.gather(recover_queued_runs(), recover_queued_runs(), return_exceptions=True)` 并发执行两次真实恢复。

**实测证据（临时 `-s` 打印，取证后已移除）**：首次返回计数为 lost-race 一次、closed 一次；抢占入口被访问 **2** 次。

| 断言 | 实测 |
|---|---|
| 两个调用都进入同一条 Run 的抢占路径 | ✅ 抢占入口计数 == 2 |
| 只有一个调用成功关闭 | ✅ closed 恰好 1 次 |
| 另一个落入 lost-race | ✅ lost-race 恰好 1 次 |
| Run 最终状态 | ✅ `failed`，`error_code = executor-failed` |
| 事件流 | ✅ **恰好一条** `run.failed`，`seq = 1`（无重复、无断号） |
| 无重复结算 / 无额外记录 | ✅ 事件总数 1，Run 行与事件一致 |
| 无遗留后台 Task | ✅ `asyncio.all_tasks()` 中无 `run-executor-*` |

**结论**：条件 UPDATE 的竞争语义得到行为证明——抢输方在数据库层阻塞后重估 `WHERE` 并匹配不到行，最终以 lost-race 干净退出且不写任何数据。

### 12.3 T6 —— 事务中途异常与完整回滚

**测试**：`test_t6_event_write_failure_rolls_back_the_whole_repair`

**最小有效子树**：本用例在测试内自行创建 1 个 `RunScenario`（pending）、1 个 `RunStep`（pending）、1 个 `RunAssertion`（pending），全部挂在同一 Run 上——这正是 `_settle_unfinished` 的结算条件。辅助函数 `_seed_child_rows` / `_snapshot_tree` / `_drop_child_rows` 均定义在测试文件内，**`conftest.py` 未改动**。

**故障注入位置（关键）**：`monkeypatch.setattr(run_executor, "append_run_event", failing_append)` —— 替换的是**恢复路径实际调用的那个模块级引用**（`run_executor.py:1837`），而不是数据库 commit、连接配置或整个 Session。

**证明异常发生在预期时点**（而非事务启动前）：同时用 `settle_spy` 包装 `run_executor._settle_unfinished`，它先执行一次真实结算（把 pending 的 Step 改成 skipped）并记录 `rowcount`，然后才交给原函数；故障替身在被调用时断言"结算已经跑过"，否则直接失败。

**实测证据（临时 `-s` 打印，取证后已移除）**：

- 返回计数：lost-race 1 次；结算被调用 **1** 次，其真实 UPDATE 的 `rowcount` == **1**。
- 事务前快照：Run = (queued, NULL, NULL, NULL, NULL)，Scenario / Step / Assertion 均为 pending。
- 事务后快照：与事务前**逐字段完全相同**；事件数 **0**。

| 断言 | 实测 |
|---|---|
| 结算确实执行且真的改了行 | ✅ 调用 1 次，`rowcount == 1`（Step 由 pending → skipped） |
| 异常在结算之后才抛出 | ✅ 故障替身的前置断言通过 |
| Run 状态回滚 | ✅ `queued`，`started_at`/`finished_at`/`error_code`/`error_message` 全为 NULL |
| **子表结算回滚** | ✅ **Step 回到 pending**（已被改过的行被回滚），Scenario 与 Assertion 亦然 |
| 无新事件 | ✅ 该 Run 在 `run_events` 中事件数为 **0** |
| 无部分提交 | ✅ 前后快照完全相等（逐字段比对） |
| 恢复函数返回 | ✅ 被现有逻辑捕获，返回 lost-race 计数（见 12.4） |
| 无后台 Task | ✅ 无 `run-executor-*` 待决 |

**这满足任务要求的"不能仅因 Run 仍是 queued 就断言原子性通过"**：本用例额外证明了**一项真正经过结算逻辑的子表状态被回滚**（Step: pending → skipped → 回滚为 pending，rowcount=1）。

### 12.4 新发现：失败被报告为 lost-race（语义混淆，未修改源码）

**实测**：`_close_orphaned_queued` 内部抛出的异常被其 `except Exception`（`run_executor.py:1858-1862`）捕获并返回 `False`；`_recover_one` 随后把 `False` 一律解释为 **lost-race**（`:1949`）。

- **影响**：真实失败（事件写入错误、约束冲突、连接中断）与"竞争失败"在**返回计数里不可区分**。运维看到 lost-race 会倾向于判断为并发竞争，而实际可能是持续性故障。
- **不改变数据正确性**：回滚完整（见 12.3），只是**分类标签不精确**。
- **本轮处理**：测试**如实断言源码的实际返回值**（lost-race 计数），并在测试内以注释记录该歧义；**未修改产品源码**，也未放宽任何断言。
- **建议**：后续修复时让 `_close_orphaned_queued` 区分"未抢到"与"执行失败"（例如返回三态或抛出可识别异常），并补一条正向用例。

### 12.5 测试运行结果（pytest 自身摘要）

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 新增 `-k "t5 or t6"` | `2 passed, 22 deselected in 1.13s` | 0 |
| 全套 第 1 次 | `24 passed in 2.39s` | 0 |
| 全套 第 2 次 | `24 passed in 2.48s` | 0 |
| 全套 第 3 次 | `24 passed in 2.35s` | 0 |
| `-rA` 扫描 XFAIL/XPASS | **零命中** | 0 |

**收集项**：22 → **24**；**测试函数数**：14 → **16**（新增 T5、T6）；新增 3 个非测试辅助函数。
**回归**：T1/T2/T3/T4/T7/T8/T10/T11/T11b 与两个窗口默认用例全部继续通过。

### 12.6 数据库使用与清理

- 只连接 `aiata_c4_test`；隔离闸门未变（`conftest.py` 未修改）。
- T6 的子表行由测试自身在 `finally` 中按下表顺序删除（Assertion → Step → Scenario），Run 行由既有夹具清理；**不使用 TRUNCATE**、不做全库清理。
- 运行后实测：业务表合计 **0 行**；24 张 public 表；`alembic_version = a4c1e8b27d93`。
- **未建库、未迁移、未改 schema**；**开发库未被连接或修改**；**零外部 HTTP、零真实模型调用**。

### 12.7 产品源码哈希对比

| 文件 | 本轮前（C7 基线） | 本轮后 | 结论 |
|---|---|---|---|
| `app.py` | `305850D8…57D1EF` | 同左 | **未变** |
| `run_executor.py` | `B791D796…8E94E9` | 同左 | **未变** |

### 12.8 备份与文档哈希

- **文档更新前备份**：`D:\_aiapi_progress_backup_20261016-093205\`（含 `MANIFEST.txt`），`IDENTICAL=True`、`SHA_MATCH=True`。
- **测试文件快照**：`D:\_aiapi_c8_backup_20261016-093205\test_run_recovery.py`（`identical=True`）。
- **更新前 SHA-256**：`6D1DC06591D15ACC4DDC29CEE7F4AB41A800B656FE8FC95BE86803D91B44DDF9`（83,247 字节）。
- **更新后 SHA-256**：见 12.11；权威记录在项目外备份清单与交付报告中。
- **写入流程**：更新前备份 → 校验哈希 → 同卷临时文件构建完整新版本 → 读回复核 → 结构检查（UTF-8 / 顶层编号 / 围栏 / 表格）→ `os.replace` 原子替换 → 重新读取并复算哈希。**未原地截断重写，未从对话重建全文。**

### 12.9 测试实现过程中的两处自我修正（如实记录）

1. 首轮 T5 误用 `asyncio.Barrier(2, timeout=30)`：Python 3.12 的 `Barrier` **不接受**构造参数 `timeout`，`wait()` 也不接受。已改为 `Barrier(2)` 加无参 `wait()`。
2. 首轮 T6 断言计数为 error，实测为 lost-race——**断言写错，不是产品缺陷**（源码确实把失败归入 lost-race）。已改为如实断言源码行为，并把该歧义记录为 12.4 的发现（**未削弱断言**，反而新增了"结算真的改了行"的更强证明）。

### 12.10 仍未覆盖的场景

1. **T9 数据库不可达**：启动期恢复失败但服务仍启动，未实测（需指向不可达但格式正确的地址）。
2. **T12 其余分支**：`RunAssertion` 在"已判定"（passed/failed）时**不应**被改写的分支尚未单独覆盖（本轮已覆盖 pending 断言被结算并回滚的路径）。
3. **`running` Run 的可靠恢复**：仍无 lease/heartbeat，T10 只断言"不处理"。
4. **多 worker 并发 reschedule**：T5 验证的是同一进程内的并发；跨进程未实测。
5. **lost-race / 失败标签歧义**（12.4）修复后的正向用例。

### 12.11 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`58535CF379BB8C664558B2FEF443D95CA95148186A4620B468F4A119E549BCFC`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`6D1DC06591D15ACC4DDC29CEE7F4AB41A800B656FE8FC95BE86803D91B44DDF9`（83,247 字节，备份见 12.8）。
- 两个哈希的**权威记录**在 `D:\_aiapi_progress_backup_20261016-093205\MANIFEST.txt` 与交付报告中。

### 12.12 下一项建议任务（仅建议，未执行）

**Task C9（建议）：修正 lost-race / 失败标签歧义，并补 T9（数据库不可达）用例。**

理由：12.4 的歧义是本轮唯一的实现层面发现，修复成本低（区分"未抢到"与"执行失败"两种返回），但**必须修改产品源码**，因此需要单独授权；T9 不需要改源码，可与之并行。
依赖：① 修改 `run_executor.py` 需明确授权；② T9 需要指向一个"格式正确但不可达"的地址，且不得指向开发库。

---

## 13. Task C9 — 区分 Run 恢复竞争失败与真实事务异常（2026-10-16）

**结论：PASS（语义缺陷已修复；T5/T6 通过并新增双向回归断言；产品改动 +20/−4 行）**

> **表述边界：** 本轮只修正"恢复结果分类"这一处语义缺陷。T9（数据库不可达）与 T12 的其余分支仍未覆盖；
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现。**不得据此声称整个 Run 恢复功能已验收。**

### 13.1 缺陷原因

`_close_orphaned_queued` 原有**二态**返回：抢占成功返回 `True`；抢占失败与**任何事务异常**都返回 `False`。调用方 `_recover_one` 把 `False` 一律解释为 `lost-race`。

结果：**真实事务失败与正常竞争失败在恢复计数里不可区分**。C8 的 T6 实测输出即为 lost-race 计数，而实际发生的是注入的事件写入异常。危害在于误导：运维看到 lost-race 会判断为并发竞争，从而错过持续性故障。

**调用者范围已核实**：`_close_orphaned_queued` 在整个后端（产品源码 + scripts + tests）**只有一个调用者**（`_recover_one`），因此修改其返回约定不涉及对外 API 契约。

### 13.2 最小修复（三态返回）

保留原有结果名称体系（`closed` / `lost-race` / `error` 三个词都是源码里既有的），只让第三个状态**能够被表达出来**：

| 情形 | 修改前 | 修改后 |
|---|---|---|
| 条件 UPDATE 抢占成功、事务提交 | `True` → `closed` | 不变 |
| 条件 UPDATE 未匹配到行（他人已抢先） | `False` → `lost-race` | **不变** |
| 事务中抛异常（结算 / 事件写入 / 提交） | `False` → **lost-race（错误）** | **`None` → `error`** |

**产品代码最小 diff（+20 / −4 行，全部位于这两个函数内）**：

- 签名：`-> bool` 改为 `-> bool | None`；docstring 明确写出三态契约。
- 抢占失败分支：新增一条 `logger.info`（not closed here, another writer claimed it first），使两条路径在日志层面也可区分；返回 `False` 不变。
- 异常分支：`return False` 改为 `return None`，并加注释说明"回滚由 session 上下文管理器负责"。
- `_recover_one`：在 `closed` 之后插入 `if closed is None: return "error"`，其余不变。

**明确没有做的事**：没有把所有 `False` 改成 `error`（那会把竞争失败误报为故障）；没有新增状态名；没有重构事务结构；没有改动冻结的事件名、seq 分配、状态机或异常隔离原则；没有重复提交事务。

### 13.3 T5 回归（真实竞争仍是竞争）

保留原有真实并发测试（`asyncio.Barrier` 安装在 `_claim_orphaned_queued` 入口，两个调用方都完成候选发现后同时释放进入真实条件 UPDATE）。

**实测证据（临时 `-s`，取证后已移除）**：返回计数为 lost-race 一次、closed 一次；抢占入口被访问 **2** 次。

新增**反向回归断言**：`any(r.get("error") for r in results)` 必须为假——确保 C9 的修复**没有把竞争失败重新标记为 error**。

| 断言 | 实测 |
|---|---|
| 两个调用都进入抢占路径 | ✅ 入口计数 == 2 |
| 一个 closed、一个 lost-race | ✅ 各恰好 1 次 |
| 竞争失败未被误标为 error | ✅ 新增断言通过 |
| Run 最终 `failed`、恰好一条 `run.failed`、seq=1 | ✅ |
| 无后台任务泄漏 | ✅ |

### 13.4 T6 更新（真实异常归类为 error）

故障注入机制保持不变：先执行**真实的** `_settle_unfinished` 并证明它**确实改了行**（`rowcount == 1`），再在恢复路径实际调用的 `append_run_event` 模块级引用处抛异常。

**实测证据（临时 `-s`，取证后已移除）**：

- 返回计数：**error 一次**（修改前为 lost-race 一次）。
- 结算被调用 1 次，其真实 UPDATE 的 `rowcount == 1`。
- 事件数 **0**；Run/Scenario/Step/Assertion 与事务前**逐字段完全相同**（含已被改成 skipped 的 Step 回滚为 pending）。

| 断言 | 实测 |
|---|---|
| 分类为真实错误而非竞争失败 | ✅ counts 等于 error 1 |
| **且明确不是 lost-race** | ✅ 新增 lost-race 为假断言通过 |
| Run 回滚到事务前状态 | ✅ `queued`，时间与 error 字段全为 NULL |
| 子表回滚 | ✅ Step 由 skipped 回到 pending；Scenario 与 Assertion 亦然 |
| 无部分写入事件 | ✅ 事件数 0 |
| 无部分提交 | ✅ 前后快照完全相等 |
| 回滚语义未被本轮修复改变 | ✅ 与原 C8 证据一致 |

### 13.5 完整测试套件连续三次结果

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 针对性 `-k "t5 or t6"` | `2 passed, 22 deselected in 1.12s` | 0 |
| 全套 第 1 次 | `24 passed in 2.56s` | 0 |
| 全套 第 2 次 | `24 passed in 2.37s` | 0 |
| 全套 第 3 次 | `24 passed in 2.35s` | 0 |
| `-rA` 扫描 XFAIL/XPASS | **零命中** | 0 |

原有 22 项**无回归**；收集项 24、测试函数 16 保持不变（本轮只改断言，未新增测试函数）。

### 13.6 产品源码哈希

| 文件 | 本轮前（C7 基线） | 本轮后 | 说明 |
|---|---|---|---|
| `app.py` | `305850D8…57D1EF` | 同左 | **未修改** |
| `run_executor.py` | `B791D796…8E94E9` | `17E1ED00…6567B4CA` | **按本轮授权修改**（+20/−4 行） |

### 13.7 数据库、网络与副作用

- 只连接 `aiata_c4_test`；隔离闸门未变（`conftest.py` 未修改）。
- 运行后实测：业务表合计 **0 行**；24 张 public 表；`alembic_version = a4c1e8b27d93`。
- **未建库、未迁移、未改 schema、无 TRUNCATE**；**开发库未被连接或修改**；**零外部 HTTP、零真实模型调用**；**未新增依赖**。
- Git：未执行 add/commit/push/pull/fetch/reset/clean/restore；暂存区为空；C2 遗留的 7 个索引假阳性未处理。

### 13.8 备份与文档哈希

- **改动前备份**：`D:\_aiapi_c9_backup_20261016-093456\`（`run_executor.py`、`test_run_recovery.py`、`PROJECT_PROGRESS.md` + `MANIFEST.txt`，三者 `copy_identical=True`）。
- **文档更新前备份**：`D:\_aiapi_progress_backup_20261016-093532\`（`IDENTICAL=True`、`SHA_MATCH=True`）。
- **文档更新前 SHA-256**：`331D3ECF02AB8790F99867F4628D471F3610B8F9AB78568E9A30AEAA662D3D5B`（93,786 字节）。
- **文档更新后 SHA-256**：见 13.11；权威记录在项目外备份清单与交付报告中。
- **写入流程**：更新前备份 → 校验哈希 → 同卷临时文件构建完整新版本 → 读回复核 → 结构检查（UTF-8 / 顶层编号 / 围栏 / 表格）→ `os.replace` 原子替换 → 重新读取并复算哈希。**未原地截断重写，未从对话重建全文。**

### 13.9 回归保护的对称性

本轮刻意让两条路径**互相约束**：

1. T6 断言"真实异常 → error"**且**"不得为 lost-race"；
2. T5 断言"真实竞争 → lost-race"**且**"不得为 error"。

因此**任何把两者重新合并的改动都会同时打破两条测试**，不会出现"改错方向但测试仍绿"的情况。

### 13.10 仍未解决的恢复风险

1. **T9 数据库不可达**：启动期恢复失败但服务仍启动，未实测。
2. **T12 其余分支**：`RunAssertion` 处于已判定（passed/failed）时**不应**被改写的分支未单独覆盖。
3. **`running` Run 无 lease/heartbeat**：无法区分"正在运行"与"已死但状态仍是 running"。
4. **跨进程并发**（多 worker reschedule）未实测。
5. **恢复可观测性不足**：启动期库不可达时静默跳过且不重试；环境变量在 README 中零处提及。
6. **进度文档仍未提交**（未跟踪），仍是单一副本风险。

### 13.11 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`EA503FA115D61825CF186472C5708246102C433625EA2A6DB1F004D98A9C70C1`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`331D3ECF02AB8790F99867F4628D471F3610B8F9AB78568E9A30AEAA662D3D5B`（93,786 字节，备份见 13.8）。
- 两个哈希的**权威记录**在 `D:\_aiapi_progress_backup_20261016-093532\MANIFEST.txt` 与交付报告中。

### 13.12 下一项建议任务（仅建议，未执行）

**Task C10（建议）：补 T9（数据库不可达）用例，并覆盖 `RunAssertion` 已判定分支（T12 剩余部分）。**

理由：这两项都**不需要修改产品源码**，可直接在现有夹具与隔离闸门下完成，正好补上恢复矩阵中最后两块无行为证据的区域。
依赖：T9 需要指向一个"格式正确但不可达"的地址（例如保留端口），且**不得指向开发库**；T12 剩余分支需要把断言的 passed/failed 状态纳入快照比对。

---

## 14. Task C10 — 数据库不可达启动行为与已判定 Assertion 状态保护（2026-10-16）

**结论：PASS（T9 与 T12 均通过；产品源码零修改；新增 1 个独立启动测试文件）**

> **表述边界：** 本轮只补上"数据库不可达时启动不中断"与"已判定断言不被改写"两条行为证据。
> `running` Run 的可靠恢复（lease/heartbeat）仍未实现；跨进程并发 reschedule 仍未实测。**不得据此声称整个 Run 恢复功能已验收。**

### 14.1 实际修改与新增的文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/tests/test_run_recovery_startup.py` | **新增** | T9：在独立子进程中验证数据库不可达时的启动行为 |
| `backend/tests/_c10_unreachable_child.py` | **新增** | 子进程脚本：先设环境、再导入后端、驱动真实 lifespan、输出一行 JSON 结论 |
| `backend/tests/test_run_recovery.py` | **修改** | 新增 T12（参数化 passed/failed）；`_drop_child_rows` 泛化为可接收多个 id 集合 |
| `docs/PROJECT_PROGRESS.md` | **修改** | 追加本节 |

**未修改**：`app.py`、`run_executor.py`、`runs.py`、`conftest.py`、`pyproject.toml`、`uv.lock`、Alembic 迁移、冻结契约。**未新增依赖、未建库、未迁移。**

### 14.2 T9 —— 数据库不可达时的启动行为

**为什么必须用子进程**：`database_url`、`engine`、`AsyncSessionLocal` 都是 `backend/db/database.py` 的**模块级对象**，在已导入后端的 pytest 进程里改环境变量不会改变它们。子进程在**导入任何 `backend.*` 之前**完成环境设置，才真正让 engine 指向不可达地址。

**不可达地址的取得与证明**（不使用 sleep）：

1. `socket.bind(("127.0.0.1", 0))` 让操作系统分配一个空闲端口，随即释放；
2. 立刻用 `connect_ex` 探测该端口 → **必须连不上**，否则测试直接失败（不会退回到开发库或外部地址）；
3. 显式断言取得的端口 **不是 5432**（PostgreSQL 服务端口）。

实测：分配端口 `58698`（非 5432），探测 `reachable = False`。

**子进程环境隔离**：把 `cwd` 指向一个临时目录并在其中放置**空 `.env`**，使 `load_dotenv()` 找不到任何可覆盖子进程环境的键；随后显式给出 `POSTGRES_HOST=127.0.0.1`、`POSTGRES_PORT=<不可达端口>`、`POSTGRES_DB=aiata_c4_test`、`POSTGRES_USER/POSTGRES_PASSWORD` 用明显的测试占位值，并**显式剔除 `RUN_EXECUTOR_DISABLED`**（否则"跳过恢复"会让测试变得毫无意义）。

**已核对**：全后端只使用 `POSTGRES_USER/PASSWORD/HOST/PORT/DB` 这 5 个数据库相关环境变量，**不存在** `DATABASE_URL` 之类的旁路，因此不存在"另一个变量覆盖目标"的可能。

**子进程实测结论（JSON）**：

| 字段 | 值 | 含义 |
|---|---|---|
| `resolved_database` | `aiata_c4_test` | 目标库正确 |
| `resolved_host` / `resolved_port` | `127.0.0.1` / `58698` | 确实指向不可达的本机端口 |
| `executor_disabled` | `False` | **不是因为禁用执行器而跳过** |
| `recovery_logged_failure` | `True` | 恢复**确实尝试访问数据库并失败**（捕获到候选集列举失败的日志） |
| `recovery_returned_empty` | `True` | 失败被现有错误处理吞掉并返回空计数 |
| `app_constructed` | `True` | `create_app()` 正常返回应用 |
| `reached_running_phase` | `True` | **lifespan 正常进入运行阶段**（恢复失败没有阻止启动） |
| 子进程退出码 | `0` | |

> 这两个条件必须**同时**成立才有意义：只断言"应用启动成功"无法证明恢复代码执行过；只断言"记录了失败"无法证明启动未被中断。测试对二者都做了断言。

**关于日志证据的凭证安全**：子进程用一个自定义 `logging.Handler` 只判断"是否出现 run recovery / could not be listed 这条消息"，**只把布尔值写进 JSON**；traceback 与连接串不会离开子进程。

**未触碰任何数据库**：本测试指向的是**不可达端口**，不建立 PostgreSQL 会话、不建库、不迁移、不写数据、不发 HTTP、不调用模型。

### 14.3 T12 —— 已判定 Assertion 保持原状态

**测试**：`test_t12_resolved_assertions_keep_their_verdict`，参数化 `passed` 与 `failed`。

**夹具结构**：同一 Run 下两个场景 —— 一个全部 `pending`（应被结算），一个已判定（`scenario=passed`、`step=passed`、`assertion=<passed|failed>`，**不应被改写**）。测试**完整走真实恢复路径**（抢占 → `_settle_unfinished` → 事件 → 提交），**没有 mock 结算、没有伪造最终状态**。

**实测前后快照（临时 `-s`，取证后已移除）**：

参数 `passed`：

- pending 组：`scenario/step/assertion` 由 `pending` **全部变为 `skipped`**；
- judged 组：`passed/passed/passed` **前后完全一致**（`expected=200`、`actual=200`、`type=status`、`target=status`、`step_id` 均未变）。

参数 `failed`：

- pending 组：`scenario/step/assertion` 由 `pending` **全部变为 `skipped`**；
- judged 组：`scenario=passed`、`step=passed`、`assertion=failed`，**前后完全一致**（含 `expected/actual/type/target/step_id`）。

| 断言 | 实测 |
|---|---|
| Run 结束为 `failed`、`error_code = executor-failed` | ✅ |
| pending 场景/步骤/断言被结算 | ✅ 三者均为 `skipped` |
| 已判定 `passed` 断言仍为 `passed` | ✅ |
| 已判定 `failed` 断言仍为 `failed` | ✅ |
| 已判定断言的其他业务字段未被重写 | ✅ `expected_value`/`actual_value`/`assertion_type`/`target`/`run_step_id` 前后一致 |
| 已判定场景与步骤未被结算 | ✅ 保持 `passed` |
| 事件流符合冻结契约 | ✅ 恰好一条 `run.failed`，`seq = 1` |
| 无重复事件、无部分提交 | ✅ |
| 只清理本测试数据 | ✅ `finally` 中按 Assertion → Step → Scenario 顺序删除两个场景的行 |

> 目标达成的是"恢复会结算未完成项目，但**不会改写已判定结果**"；本轮**没有**重复覆盖 C8 已证明的事务回滚路径。

### 14.4 完整测试套件连续三次结果

| 运行 | 摘要 | 退出码 |
|---|---|---|
| 启动测试单独 `test_run_recovery_startup.py` | `1 passed in 7.69s` | 0 |
| T12 单独 `-k "t12"` | `2 passed, 24 deselected in 1.36s` | 0 |
| 全套 第 1 次 | `27 passed in 10.68s` | 0 |
| 全套 第 2 次 | `27 passed in 10.55s` | 0 |
| 全套 第 3 次 | `27 passed in 10.74s` | 0 |
| `-rA` 扫描 XFAIL/XPASS/SKIPPED | **零命中** | 0 |

**收集项**：24 → **27**（T9 一项、T12 参数化两项）；**测试函数数**：16 → **17**（`test_run_recovery.py`）+ 1（`test_run_recovery_startup.py`）。
原有 24 项**无回归**；无 skip、无 xfail、无 xpass。全套耗时由约 2.4s 增至约 10.7s，增量来自 T9 的子进程启动（每次约 7–8s），属预期。

### 14.5 产品源码哈希（本轮应完全不变）

| 文件 | 本轮前（C9 基线） | 本轮后 | 结论 |
|---|---|---|---|
| `app.py` | `305850D8…57D1EF` | 同左 | **未变** |
| `run_executor.py` | `17E1ED00…6567B4CA` | 同左 | **未变** |

### 14.6 数据库、网络与副作用

- T12 只连接 `aiata_c4_test`；隔离闸门未变（`conftest.py` 未修改）。
- T9 **不连接任何数据库**：目标为不可达的本机端口（已证明无法建立 TCP 连接）。
- 运行后实测：业务表合计 **0 行**；24 张 public 表；`alembic_version = a4c1e8b27d93`。
- **未建库、未迁移、未改 schema、无 TRUNCATE**；**开发库未被连接或修改**；**零外部 HTTP、零真实模型调用**；**未新增依赖**。
- Git：未执行 add/commit/push/pull/fetch/reset/clean/restore；暂存区为空；C2 遗留的 7 个索引假阳性未处理。

### 14.7 备份与文档哈希

- **文档更新前备份**：`D:\_aiapi_progress_backup_20261016-094006\`（含 `MANIFEST.txt`），与源文件 `IDENTICAL=True`、`SHA_MATCH=True`。
- **测试文件快照**：`D:\_aiapi_c10_backup_20261016-094006\`（3 个文件，均 `identical=True`）。
- **更新前 SHA-256**：`5DF1578DAA28F2D87FBA57B4723CEA39D2F0B5F9890EB30BB96F37CC2C839BF2`（102,540 字节）。
- **更新后 SHA-256**：见 14.10；权威记录在项目外备份清单与交付报告中。
- **写入流程**：更新前备份 → 校验哈希 → 同卷临时文件构建完整新版本 → 读回复核 → 结构检查（UTF-8 / 顶层编号 / 围栏 / 表格）→ `os.replace` 原子替换 → 重新读取并复算哈希。**未原地截断重写，未从对话重建全文。**

### 14.8 关于测试文件与 `conftest.py` 边界

- 新增的启动测试**刻意不使用任何共享夹具**：它不需要数据库，也不需要隔离闸门，因此与 `conftest.py` 完全解耦（该文件本轮**未改动**）。
- `test_run_recovery.py` 中的 `_drop_child_rows` 由"单个 id 集合"泛化为"可变个 id 集合"，**保持单参数调用兼容**（T6 的既有调用未改），属本次新增 T12 所必需的最小调整。
- 测试内新增 2 个辅助函数（`_seed_mixed_tree`、`_read_states`），均定义在测试文件内，不进入产品代码。

### 14.9 仍未覆盖的风险

1. **`running` Run 的可靠恢复**：仍无 lease/heartbeat，T10 只断言"不处理"。
2. **跨进程并发 reschedule**：T5 验证的是同进程内并发；多 worker 场景未实测。
3. **恢复可观测性不足**：启动期数据库不可达时恢复被静默跳过且**不重试**；相关环境变量在 README 中零处提及。
4. **T9 只覆盖"启动期不可达"**：不覆盖"启动后中途失联"，也不覆盖子进程之外的多 worker 启动竞态。
5. **进度文档仍未提交**（未跟踪），仍是单一副本风险。

### 14.10 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`5964E684D138B2D0D431BE6F9C648EEF979A53B43B90274EB184D60354F5EB9F`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`5DF1578DAA28F2D87FBA57B4723CEA39D2F0B5F9890EB30BB96F37CC2C839BF2`（102,540 字节，备份见 14.7）。
- 两个哈希的**权威记录**在 `D:\_aiapi_progress_backup_20261016-094006\MANIFEST.txt` 与交付报告中。

### 14.11 下一项建议任务（仅建议，未执行）

**Task C11（建议）：恢复矩阵收口审计 —— 汇总"已覆盖 / 未覆盖"并评估是否具备提交条件。**

理由：T1–T12 中除 `running` 恢复（需要产品级 lease/heartbeat 设计）与跨进程并发外均已具备行为证据，且产品源码已累积 C7 与 C9 两处已授权修复。下一步的价值不在继续加测试，而在**决定这些未提交改动是否以及如何进入版本控制**（需先解决本机 git TLS/网络问题并复核 `.gitignore`）。
依赖：① 提交需负责人明确授权；② README 与契约中"Run 启动恢复尚未实现"等陈旧表述应与提交同批修订；③ 进度文档目前仍是未跟踪的单一副本。

---

## 15. Task C11 — Run 恢复测试矩阵收口与版本归档准备审计（2026-10-16）

**结论：PASS（只读审计完成）；版本归档结论：NOT READY**

> **本轮性质：只读审计。** 未修改产品源码、未修改测试代码、未修改 README 或契约、未运行任何测试、未连接数据库、未新增依赖、未执行任何 Git 写操作。
> 归档结论为 **NOT READY**，原因是文档陈旧与版本管理状态，而非测试证据不足。

### 15.1 工作区与文件清单（三类严格区分）

- 分支 `main`；HEAD `d7c726a`（`origin/main`）；共 4 个提交；remote 仍为 `https://github.com/PZTandKOBE/ApiPilot.git`。
- `git diff --check` / `--cached --check` 均为 0；**暂存区为空**。

**第 1 类：已跟踪且存在真实内容修改（4 个）**

| 文件 | 字节 | 相对 HEAD 的差异 |
|---|---|---|
| `backend/src/backend/services/run_executor.py` | 71,438 | +401/−5（含 C3 恢复实现本体 + C7 + C9） |
| `backend/src/backend/app.py` | 4,852 | +42（lifespan） |
| `backend/pyproject.toml` | 641 | +5（`[dependency-groups] dev = ["pytest>=9.1.1"]`） |
| `backend/uv.lock` | 271,829 | +53（pytest 及其传递依赖） |

`git diff --stat` 合计 **4 files changed, 496 insertions(+), 5 deletions(-)**。

**第 2 类：未跟踪的新文件（5 个）**

| 文件 | 字节 | SHA-256（前 16 位） |
|---|---|---|
| `backend/tests/conftest.py` | 11,227 | `B70261A2207DF5C1` |
| `backend/tests/test_run_recovery.py` | 43,135 | `E279ED23A6D06571` |
| `backend/tests/test_run_recovery_startup.py` | 4,659 | `BB8DA934E611F5D7` |
| `backend/tests/_c10_unreachable_child.py` | 2,820 | `DB8A7A31CA9A7E34` |
| `docs/PROJECT_PROGRESS.md` | 113,636 | `73AC528A00AD3E75` |

**第 3 类：`git status` 显示 ` M` 但内容与 HEAD 逐字节一致（7 个历史脚本）**

逐一用 `git hash-object` 与 `git rev-parse HEAD:<path>` 比对，**7/7 三个哈希完全相同**：

| 脚本 | 工作区 blob | HEAD blob | 相同 |
|---|---|---|---|
| `seed_dev_data.py` | `e67b7cd06d` | `e67b7cd06d` | ✅ |
| `verify_deepseek_analyze.py` | `9becd5d0bf` | `9becd5d0bf` | ✅ |
| `verify_deepseek_generate_plan.py` | `100a1cec32` | `100a1cec32` | ✅ |
| `verify_deepseek_schema.py` | `9586046eb9` | `9586046eb9` | ✅ |
| `verify_guest_session.py` | `acb899fcb3` | `acb899fcb3` | ✅ |
| `verify_llm_client.py` | `85222a7870` | `85222a7870` | ✅ |
| `verify_proxy.py` | `1626e48dcf` | `1626e48dcf` | ✅ |

**这是索引 stat 缓存假阳性，不是产品代码修改**：`git diff --stat` 只列出上面 4 个文件，`git diff` 对这 7 个脚本输出为空。按任务要求**本轮未做任何索引写操作**。

**基线核对**：`run_executor.py` = `17E1ED00C1A0C3D75737EA797066FD7EDB40B88D2BA5878DE4A1F7A26567B4CA`（= C9 基线，未使用 C2 旧哈希）；`app.py` = `305850D8D42A066EF8B891957F3E07F2827E5D5C4AB2541DB49164ECE757D1EF`（= C7/C9 基线）。**未发现任何未授权变化。**

### 15.2 恢复测试矩阵（16 + 1 个测试函数 → 27 个收集项）

| 场景 | 测试函数（文件） | 行为测试 | 访问真实 DB | 特殊机制 | 最近证据来源 | 未覆盖边界 |
|---|---|---|---|---|---|---|
| T1 无待恢复任务 | `test_t1_no_non_terminal_runs_yields_empty_counts` | ✅ | ✅ | — | C4 首轮 → C10 27 passed | 仅覆盖"完全为空"，不覆盖"仅有终态行" |
| T2 过期 queued 被关闭 | `test_t2_old_queued_run_is_closed_with_one_failed_event` | ✅ | ✅ | SQL 回填 `created_at` | C4 → C10 | 无 scenario 子树的结算由 T12 覆盖 |
| T3 阈值内重新调度 | `test_t3_young_queued_run_is_rescheduled_and_finishes_without_http` | ✅ | ✅ | **monkeypatch**（拦 `create_task`、包 `httpx.AsyncClient`） | C5 → C10 | 非空场景树的真实 HTTP 路径未覆盖 |
| T4 已有 run.started | `test_t4_queued_run_with_a_started_event_is_left_alone` | ✅ | ✅ | — | C4 → C10 | — |
| T5 并发竞争 | `test_t5_concurrent_recoveries_close_the_orphan_exactly_once` | ✅ | ✅ | **`asyncio.Barrier(2)`** 装在抢占入口 | C8 → C9 增强 → C10 | 跨进程并发未测 |
| T6 事务中途异常 | `test_t6_event_write_failure_rolls_back_the_whole_repair` | ✅ | ✅ | **故障注入**（替换 `run_executor.append_run_event`）+ 真实结算 rowcount 证明 | C8 → C9 更新分类 | 提交阶段自身失败未单独注入 |
| T7 重复恢复幂等 | `test_t7_recovery_is_idempotent_for_an_already_closed_run` | ✅ | ✅ | — | C6 → C10 | — |
| T8 执行器禁用 | `test_t8_disabled_executor_skips_before_opening_a_session` | ✅ | ✅ | **monkeypatch**（计数工厂证明 0 次 session） | C4 → C10 | — |
| T9 数据库不可达 | `test_t9_unreachable_database_does_not_stop_startup`（`test_run_recovery_startup.py`） | ✅ | ❌（指向已证明不可达端口） | **子进程** + 真实 lifespan | C10 → 本轮复算哈希一致 | 启动后中途失联未覆盖 |
| T10 running 保持不变 | `test_t10_running_run_is_never_touched` | ✅ | ✅ | — | C4 → C10 | **产品缺口**：无 lease/heartbeat |
| T11 无效窗口回退 | `test_t11_unusable_window_values_fall_back_to_the_default`（参数化 4） | ✅ | ❌（纯配置解析） | monkeypatch env | C6 → C7 → C10 | — |
| T11b 非有限窗口 | `test_t11b_non_finite_windows_fall_back_to_the_default`（参数化 6）+ `test_t11b_finite_positive_windows_are_still_honoured` | ✅ | ❌ | monkeypatch env + `caplog` | C6 发现 → **C7 修复** → C10 | — |
| T12 pending 结算 + 已判定保护 | `test_t12_resolved_assertions_keep_their_verdict`（参数化 passed/failed） | ✅ | ✅ | — | **C10** | 已判定 Scenario/Step 的其余状态组合未穷举 |
| 支撑：默认窗口常量 | `test_default_window_is_what_this_file_assumes` | ✅ | ❌ | — | C4 → C10 | — |
| 支撑：未设变量取默认 | `test_unset_window_env_yields_the_default` | ✅ | ❌ | — | C4 → C10 | — |
| 支撑：禁用标志未泄漏 | `test_disable_flag_did_not_leak_into_the_process` | ✅ | ❌ | — | C4 → C10 | — |
| 支撑：窗口变量未泄漏 | `test_t11_env_var_does_not_leak_between_cases` | ✅ | ❌ | — | C6 → C10 | — |

**收集项统计**：`test_run_recovery.py` 16 个函数（参数化展开为 2+4+6+3 = 15 项额外），`test_run_recovery_startup.py` 1 个函数 → **合计 27 项**，与 C10 报告的 `27 passed` 一致。

**精确性更正（本轮实测）**：T12 曾被 C10 记录的 marker 扫描标为"含 monkeypatch"，经 AST 复核其参数为 `fixtures, stack, read_session, resolved_status`，**并不调用 `monkeypatch`**；该标记是扫描文本的假阳性，已在本表更正。

### 15.3 关键实现与契约核对（全部实测）

| 项目 | 结果 |
|---|---|
| `app.py` lifespan 启动路径 | ✅ 存在（`+42` 行，`_lifespan` + `lifespan=_lifespan`），T9 以真实 lifespan 驱动验证 |
| C7 `math.isfinite()` | ✅ `import math` 与 `if not math.isfinite(value):` 均在位 |
| C9 `bool \| None` 分类 | ✅ 签名 `-> bool \| None`、异常分支 `return None`、调用方 `if closed is None: return "error"` 均在位 |
| 冻结事件名 | ✅ 执行器内仅出现 `run.started` / `run.failed`（外加取消路径的 `RUN_CANCELLED_EVENT`），全部属于冻结的 8 类 |
| seq 语义 | ✅ 由 `append_run_event` 统一分配（`FOR UPDATE` + `COALESCE(MAX(seq),0)+1`），T2/T4/T5/T7/T12 均断言 `seq` 稠密无重复 |
| T3 后台 Task 生命周期与无 HTTP | ✅ 以 `create_task` 拦截 + 具名任务精确等待 + `httpx.AsyncClient` 子类化（`send` 抛错）证明"构造 1 次、发送 0 次" |

### 15.4 剩余风险分类

**A. 已知未解决的产品能力（不是测试遗漏）**

1. **`running` Run 无 executor lease / heartbeat**：无法区分"仍在执行"与"执行进程已死亡"。当前设计**有意跳过** `running`，T10 只断言这一行为。属独立产品设计决策。
2. **多 worker 跨进程并发 reschedule**：T5 验证的是**同进程内**并发；多进程启动竞态未实测。

**B. 尚未充分验证的运行时行为**

3. **数据库在服务启动后中途失联**：T9 只覆盖"启动期不可达"；运行期失联的行为无行为证据。
4. **多进程同时启动**：见 A-2，无行为证据。
5. **T6 仅注入事件写入失败**：提交阶段自身失败、结算阶段失败未单独注入（事务边界已由 T6 证明，但注入点单一）。
6. **T3 仅覆盖空场景树**：非空场景下的真实 HTTP 路径与步骤/断言事件序列未覆盖。

**C. 文档与版本管理问题**

| 项目 | 现状 | 准确位置 | 性质 |
|---|---|---|---|
| README 称 Run 启动恢复未实现 | `- **Run 启动恢复：** …恢复机制尚未实现。` | `README.md:205` | **陈旧**，与工作区代码 + 27 项测试矛盾 |
| README 称"完整后端 pytest 套件尚未运行" | `…完整后端 pytest 套件尚未运行。` | `README.md:199` | **陈旧**，现已有 27 项 pytest |
| README 状态段落未提恢复已实现 | `> **项目状态：Early Development / Alpha。** …Run 启动恢复机制尚未实现，PDF 导出尚未实现。` | `README.md:13` | **陈旧** |
| README 未记载两个恢复环境变量 | `RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS`、`RUN_EXECUTOR_DISABLED` **零处提及** | 全文 | **缺失**（运维所需） |
| Agent 契约称"后端有 9 条路由" | `2. **后端有 9 条路由：run 6 条 + agent 3 条。**` | `docs/agent-pipeline-contract.md:95` | 陈旧（当前 4 router / 14 operation） |
| 身份契约的旧快照 | `8 个 path / 9 个 operation`、多处"9 条路由" | `docs/identity-access-contract.md:107,143,145,372` | 部分已就地标注为历史快照；`:107` 仍缺标注 |
| 进度文档未跟踪 / 未提交 | `?? docs/PROJECT_PROGRESS.md` | 仓库根 | **版本管理风险：单一副本** |
| GitHub 远程同步未确认 | `git ls-remote` C1 时因 TLS 失败；DNS 返回非公网地址 | — | **未处理**（本轮未尝试修复网络） |

### 15.5 版本归档准备评估：**NOT READY**

**变更清单（相对 HEAD 的真实变化）**

- Run 恢复产品源码：`run_executor.py`（+401/−5，含 C3 本体 + C7 + C9）、`app.py`（+42 lifespan）。
- pytest 测试体系：`conftest.py`、`test_run_recovery.py`、`test_run_recovery_startup.py`、`_c10_unreachable_child.py`（均未跟踪）。
- 开发依赖：`pyproject.toml`（+5）、`uv.lock`（+53）。
- 进度记录：`docs/PROJECT_PROGRESS.md`（未跟踪，113,636 字节）。
- 7 个脚本的索引 stat 假阳性（**内容与 HEAD 一致**）。

**六个问题的回答**

| # | 问题 | 结论 |
|---|---|---|
| 1 | 27 项测试能否在文档指定的隔离库中重复执行？ | **能**。`conftest.py` 在导入前把 `POSTGRES_DB` 固定为 `aiata_c4_test` 并以 `raise RuntimeError` 复核；T9 不需要数据库；C10 已记录同一命令连续三次 `27 passed`。**本轮按任务要求未重跑。** |
| 2 | 必须同时纳入归档的文件？ | 上表 7 个真实变化文件 **加上** `docs/PROJECT_PROGRESS.md`；测试目录需整体纳入（含 `_c10_unreachable_child.py`，它是 T9 的被调用脚本而非 pytest 测试）。 |
| 3 | 是否有调试打印/临时文件/凭证/无关内容？ | **否**。候选文件中 `C4/C5/C8/C9/C10-EVIDENCE` 标记 **0 处**；`test_run_recovery.py`、`conftest.py`、两个产品文件**裸 print 行 0**；`_c10_unreachable_child.py` 的 1 处 `print` 是它的**输出协议**（`C10-VERDICT <json>`）。无 `sk-` 密钥、无内联 DSN；`conftest.py` 仅在其 docstring 中**提到变量名** `DEEPSEEK_API_KEY`（不读取、不输出）。测试用 `base_url` 为 `http://127.0.0.1:9/...`（回环、不可路由）。 |
| 4 | 7 个假阳性如何影响后续 staging？ | 建议：按目录显式 `git add`（或 `git add -A`）不会改变它们的内容，但会让**索引 stat 刷新**、状态转为干净；提交后 `git status` 才不再撒谎。**风险**：若用 `git add -p` 或按 `git status` 人工挑选，可能误把它们当"待提交修改"而浪费时间，或误以为存在未保存改动。**本轮不执行任何索引操作。** |
| 5 | 哪些属同一逻辑提交，哪些单独处理？ | **建议拆分**：(a) 恢复实现 + lifespan + 测试 + dev 依赖 + 锁文件 = 一个功能提交（互相依赖，缺一不可运行）；(b) `docs/PROJECT_PROGRESS.md` 作为**独立的文档提交**（与 (a) 无代码依赖，且体量大、易冲突）；(c) 索引假阳性不单独提交（`git add -A` 后自然消解）。 |
| 6 | README/契约修订应先于代码归档吗？ | **应先完成或同批完成**。`README.md:13/199/205` 直接与新代码矛盾；若先归档代码而 README 仍称"尚未实现"，则该提交自带错误陈述。契约文件（`docs/agent-pipeline-contract.md:95`、`docs/identity-access-contract.md:107`）的陈旧描述建议同批或紧随其后。 |

**结论：NOT READY**，阻断项有且仅有三类（均非测试证据问题）：

1. 🔴 **README 陈旧且自相矛盾**（`:13`、`:199`、`:205`）——提交后即刻产生错误文档。
2. 🔴 **Git 网络/TLS 未解决**（`git ls-remote` 曾失败；DNS 被接管）——**无法推送**，因此"归档"目前只能停在本地提交。
3. 🟠 **进度文档仍是未跟踪的单一副本**（113 KB，曾于 C5 被截断）——提交前应尽快纳入版本控制，且此前任何写入都须先做项目外备份。

**不构成阻断**：7 个索引假阳性（内容一致）、两处已授权产品修复（C7/C9 均有测试保护）、T9 需子进程（耗时属预期）。

### 15.6 本轮未做与未运行（如实记录）

**未**修改任何产品源码、测试代码、README 或契约；**未**运行 pytest（按任务要求）；**未**连接数据库、未执行 Alembic、未运行 `verify_*.py` 或 `seed_dev_data.py`；**未**新增依赖；**未**执行任何 Git 写操作（`add`/`commit`/`push`/`pull`/`fetch`/`reset`/`clean`/`checkout`/`restore`）；**未**处理 7 个脚本的索引假阳性；**未**修改网络、TLS、代理或凭证设置；**未**调用真实模型或外部 HTTP。

### 15.7 下一步（仅建议，未执行）

**Task C12（建议）：README 与契约的陈旧表述修订（纯文档，需授权）。**

最小范围：`README.md:13`、`:199`、`:205` 三处改为与工作区代码及 27 项测试一致的表述，并在"测试与验证"一节补上 `RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS`（默认 300）与 `RUN_EXECUTOR_DISABLED` 的说明；契约两处陈旧路由数量描述同批修正（`docs/agent-pipeline-contract.md:95`、`docs/identity-access-contract.md:107`）。
依赖：① README 与契约的修订需明确授权（本轮禁止修改）；② 修订完成后再评估归档；③ GitHub 推送仍需先解决本机 TLS/DNS 问题（属独立事项，不得在本任务中擅自改动网络配置）。

### 15.8 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`B0439E0892B046AE591271F4A226A5CBD32C22294569FEAC03EE59415C290956`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`73AC528A00AD3E75B681E606B804A0405CBCFCF7196486F3C752A321D5D2D2AE`（113,636 字节）。
- **更新前备份**：`D:\_aiapi_progress_backup_20261016-100538\`（含 `MANIFEST.txt`），`IDENTICAL=True`、`SHA_MATCH=True`。
- 两个哈希的**权威记录**在该备份清单与交付报告中。

---

## 16. Task C12 — README 与契约文档状态对齐（2026-10-16）

**结论：PASS（三份文档已对齐当前代码与测试证据；冻结区逐字节保持不变）**

> **本轮只改文档。** 未修改产品源码、测试代码、依赖与锁文件；未运行任何测试；未连接数据库；未修改 Alembic 迁移与冻结契约的设计内容；未执行任何 Git 写操作。

### 16.1 实际修改的文档

| 文件 | 前 → 后字节 | 前 → 后 SHA-256（前 12 位） | 修改摘要 |
|---|---|---|---|
| `README.md` | 13,160 → 16,128 | `24D0886FB76F` → `9BF3E5068DF1` | 状态段、技术栈表、测试与验证、已知限制、英文摘要共 6 处；新增「可选环境变量：Run 启动恢复」小节 |
| `docs/agent-pipeline-contract.md` | 75,037 → 75,775 | `FA2FE0FD2B75` → `101386DE0002` | §2「关键事实」第 2 条（路由计数）与第 3 条（前端引用状态） |
| `docs/identity-access-contract.md` | 35,724 → 36,846 | `CA434CD6F9DE` → `5CF62B99D469` | 文件头状态块、§2.1 历史快照标注、§2.3 历史快照标注与其收尾段 |
| `docs/PROJECT_PROGRESS.md` | 129,222 → 见 16.11 | — | 追加本节 |

**未修改**：`backend/src/**`、`backend/tests/**`、`backend/pyproject.toml`、`backend/uv.lock`、Alembic 迁移、`backend/dosc/agent-pipeline-contract.md`（旧副本，见 16.7）。逐个哈希复核见 16.6。

### 16.2 README 状态修订前后对比

| 位置 | 修改前 | 修改后 | 依据 |
|---|---|---|---|
| 状态段（原 `:13`） | `…Run 启动恢复机制尚未实现，PDF 导出尚未实现。` | `…Run 启动恢复仍不完整（见「已知限制与路线图」），PDF 导出尚未实现。` | `app.py` 已含 `_lifespan` + `recover_queued_runs`；10 项恢复测试有行为证据 |
| 技术栈表 | `测试 \| Vitest、…、后端自定义验证脚本、受控浏览器 E2E harness` | 增列 `后端 pytest（backend/tests/）` | `backend/tests/` 4 个文件、14+1 个测试函数 |
| 测试与验证 | `…完整后端 pytest 套件尚未运行。` | 新增一段：pytest 体系位于 `backend/tests/`，**目前只覆盖 Run 启动恢复专项**；最近一次已记录为 **27 passed**（Task C10 实测，连续三次；本次未重跑）；给出 `$env:POSTGRES_DB = "<独立测试库>"` + `python -m pytest tests/` 的运行方式；并显式声明**该数字不代表后端全量 pytest 覆盖** | C10 记录与 C11 复核 |
| 已知限制 | `**Run 启动恢复：** …恢复机制尚未实现。` | 改为一句话准确描述**第一阶段已实现**（超窗口未启动的 queued 收敛为 failed + 结算 + 一条 `run.failed`；窗口内重新调度），并明确**仍缺** executor lease / heartbeat 与跨进程并发实测，结尾声明**不得理解为完整恢复已交付** | `run_executor.recover_queued_runs` / `_recover_one` 分支 + T1–T12 矩阵 |
| 英文摘要 | `Startup recovery for in-flight runs is not implemented;` | 改为描述"只实现了第一阶段，`running` Run 因无 lease/heartbeat 被有意跳过" | 同上 |
| 本地运行（新增小节） | （无） | 新增「可选环境变量：Run 启动恢复」表（见 16.3） | 源码实测解析逻辑 |

**验证**：全文检索 `恢复机制尚未实现`、`完整后端 pytest 套件尚未运行`、`recovery … is not implemented` 均**零命中**。

### 16.3 两个环境变量的语义及源码依据

**`RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS`**（声明 `run_executor.py:1662`；读取 `:1698`；默认 `:1663` = `300.0`）

- 作用：启动恢复用它判断仍在 `queued` 的 Run 是否已超过恢复窗口——**未超过**则 `schedule_run` 重新调度；**超过**且从未启动则收敛为 `failed`。
- 无效值处理（`:1698-1733`）：空串/纯空白 → 默认；无法 `float()` 转换 → 默认 + warning；**非有限值（`math.isfinite` 为假，如 `1e999`、`inf`、`nan`）→ 默认 + warning**；`<= 0` → 默认 + warning；有限正数原样使用。
- **没有热更新**：函数注释明确"read per call rather than at import"，即每次调用重新读环境变量，但**改了环境变量仍需重启进程**（环境变量属进程级），README 已按此表述。

**`RUN_EXECUTOR_DISABLED`**（声明 `run_executor.py:139`；判定 `:1617`（调度）与 `:1993`（恢复））

- 判定规则是 `os.getenv(..., "").strip().lower() in ("1", "true", "yes")`。因此 `1` / `true` / `TRUE` / `yes`（含前后空白）算置位；**`0` / `false` / `no` 以及任何其他字符串都不算置位**——README 已按此写全，未只凭测试用了 `"1"` 就推断其余字符串。
- 置位时：不启动后台执行器（`:1617`），并**跳过启动恢复**（`:1993`），且该跳过发生在**创建任何 Session 之前**（T8 用计数工厂证明 `session_factory.call_count == 0`）。
- README 同时说明 `backend/scripts/verify_*.py` 中部分脚本依赖该变量保护夹具。

### 16.4 Agent Pipeline 过期状态修订及计数依据

**计数依据（对 `create_app()` 生成的 OpenAPI 实测，而非猜测）**：**router 模块 4 个**（`agent` / `runs` / `guest_sessions` / `projects`）、**API 路径 12 条**、**OpenAPI operation 14 个**（runs 6 + agent 3 + guest_sessions 2 + projects 3）。三个概念在文档中已分别写明，未混用。

| 位置 | 修改前 | 修改后 |
|---|---|---|
| §2 关键事实 第 2 条 | `**后端有 9 条路由：run 6 条 + agent 3 条。** app.py 装配 runs.router 与 agent.router。` | 改为 4 router / 12 path / 14 operation 的当前实测值，并**保留原句为历史说明**（"本节写于 Phase 8.2，当时的数字是…"），说明新增的 5 个 operation 不属于本契约的 Agent 管线范围 |
| §2 关键事实 第 3 条 | `**前端仍然零引用**（frontend/src 全量 grep 零命中）。` | 改为"曾经零引用，Phase 8.2 Step 3 起已接入"，并注明现仅剩一处文案注释命中（`frontend/src/i18n/console-schema.ts:378`） |

**复核后未改动的三处疑点（原报告以为过期，实测已正确）**：

- 前端是否已切换服务端：文档 `:184` 已写"**Phase 8.2 Step 3 起前端已连上服务端**"，与代码一致，无需修改。
- "没有数据库变更"：`grep` 在正文中**未找到**该表述；`:438` 的"没有 LLM 客户端"指的是**产品侧 Prompt 模板**，属专项说明，未误改。
- 冻结边界：审批闸门（`:81`）、客户端审批权威（`:98`）、8 类事件名（`:715-717`）、职责边界与 schema 约定**均未改动**，本轮只修改了两条**实施状态**描述。

### 16.5 身份访问契约 §6、§8 逐字节校验结果

| 冻结区 | 修改前 SHA-256 | 修改后 SHA-256 | 字节数 | 结果 |
|---|---|---|---|---|
| `## 6. 安全契约（冻结）`（到 `## 7.` 之前） | `97B79D770A2A255E…` | **`97B79D770A2A255E…`** | 4,585 → 4,585 | ✅ **逐字节一致** |
| `## 8.` 原始正式验收条件整段（到 `## 9.` 之前） | `752E2C93ED3D932A…` | **`752E2C93ED3D932A…`** | 2,416 → 2,416 | ✅ **逐字节一致** |

> **必须如实记录的一次自我纠正**：首次修订时我把"9 条 operation"的说明直接写进了 §8 的验收条款（Step 2 依赖行与 Step 3 验收行），字节校验立即发现 §8 从 `752E2C93…` 变为 `E1F6A323…`（2,416 → 2,597 字节）。**这两处修改已被完整还原**，§8 恢复为与备份逐字节一致；`9 条 operation` 的说明改由 **§2.1 / §2.3 的历史快照标注**与 **§10.1 的结项记录**承担。

**身份契约的其余修订（均在冻结区之外）**：

- 文件头状态块：原文 `状态：契约冻结草案 —— 等待架构评审。…不含任何实现。` 与同段 `:11-13` 的"四个 Step 均已交付并验收完成"自相矛盾；改为"**已冻结的安全契约；Phase 8.5 Step 1–4 均已交付并验收完成**"，并说明"等待架构评审/不含实现"指的是 Step 1 时的初始状态。
- `§2.1`：在 `8 个 path / 9 个 operation` 之前新增**历史快照标注**，指明当前实测为 **12 path / 14 operation**（见 §10.1），原句保留以维持审计背景。
- `§2.3`：新增历史快照标注，说明表中三处"9 条"是 Step 1 时的计数、当前为 14 个 operation，分类与授权结论未变；收尾段补充"该缺陷已修复（Step 3 接上授权）"。

### 16.6 保护状态复核（本轮结束时实测）

| 文件 | SHA-256 是否与审计前一致 |
|---|---|
| `backend/src/backend/app.py` | ✅ 未变（`305850D8…`） |
| `backend/src/backend/services/run_executor.py` | ✅ 未变（`17E1ED00…`） |
| `backend/tests/conftest.py` | ✅ 未变（`B70261A2…`） |
| `backend/tests/test_run_recovery.py` | ✅ 未变（`E279ED23…`） |
| `backend/tests/test_run_recovery_startup.py` | ✅ 未变（`BB8DA934…`） |
| `backend/tests/_c10_unreachable_child.py` | ✅ 未变（`DB8A7A31…`） |
| `backend/pyproject.toml` | ✅ 未变（`5AA0D72E…`） |
| `backend/uv.lock` | ✅ 未变（`027B1562…`） |
| `backend/dosc/agent-pipeline-contract.md`（旧副本） | ✅ **未同步、未覆盖**（`715DACD8…`） |

### 16.7 关于 `backend/dosc/` 旧副本的权威性差异（只报告）

`docs/agent-pipeline-contract.md`（75,775 B，619 行）与 `backend/dosc/agent-pipeline-contract.md`（46,530 B，508 行）**同名但内容不同**：前者更完整、更新（含 Phase 8.2–8.4 的实施记录），后者体量约为其 61%。**本仓库没有任何文档声明两者谁是权威**。按任务要求，**本轮未修改、未同步、未覆盖**该旧副本；建议后续明确其定位（历史副本应标注，或删除需单独授权）。

### 16.8 未运行、未触碰（如实记录）

**未**运行 pytest 或任何 `verify_*.py` / `seed_dev_data.py`（因此 **27 passed 是引用 C10 的历史实测，不是本轮结果**）；**未**连接数据库、未执行 Alembic；**未**调用真实模型或外部 HTTP；**未**新增/升级依赖；**未**执行任何 Git 写操作（`add`/`commit`/`push`/`pull`/`fetch`/`reset`/`clean`/`checkout`/`restore`）；**未**修复 DNS/TLS/代理/凭证；**未**处理 7 个脚本的索引 stat 假阳性。

### 16.9 仍未解决的问题

1. **Git 网络/TLS 未解决**：`git ls-remote` 曾因 `schannel` 失败、DNS 返回非公网地址，因此仍**无法推送**；归档只能停在本地提交。
2. **`docs/PROJECT_PROGRESS.md` 仍未跟踪**（未提交），仍是单一副本风险（曾在 C5 被截断为 0 字节）。
3. **`running` Run 无 executor lease / heartbeat**：产品能力缺口，非测试遗漏。
4. **跨进程并发 reschedule 未实测**（T5 为同进程内并发）。
5. **恢复可观测性不足**：启动期数据库不可达时恢复被静默跳过且不重试。README 现已说明两个变量，但"失败不重试"这一行为仍未文档化。
6. **两处契约仍含其它历史表述**：本轮只处理了 C11 明确列出的位置；`docs/agent-pipeline-contract.md` 的 §12/§14 中"9 条路由"等历史图注未逐一重写（同一文档已在上文给出当前计数说明）。
7. **`backend/dosc/` 旧副本权威性未定**（见 16.7）。
8. **7 个历史脚本的索引 stat 假阳性**仍未消除（内容与 HEAD 一致）。

### 16.10 下一项建议任务（仅建议，未执行）

**Task C13（建议）：归档前的一致性复核与提交准备（只读复核 + 提交提案，不执行提交）。**

建议内容：① 复核本轮 README/契约修订与代码是否仍有残留矛盾（含 `docs/agent-pipeline-contract.md` 的图注计数）；② 给出建议的提交拆分（功能提交 vs 文档提交）与提交信息草稿；③ 明确推送前必须先解决本机 TLS/DNS，且该事项需单独授权。
依赖：① 提交与推送需负责人明确授权；② 进度文档应在本轮之后尽快纳入版本控制；③ 不得在本任务中擅自改动网络配置。

### 16.11 备份与哈希

- **改动前备份**：`D:\_aiapi_c12_backup_20261016-120537\`，含四个文件的副本、`MANIFEST.txt`（记录源路径、备份路径、字节数、mtime、SHA-256、逐字节一致标志）以及**冻结区快照** `frozen_sec6.md` / `frozen_sec8.md`；备份与源文件 `identical=True`。
- **文档更新前 SHA-256**：`docs/PROJECT_PROGRESS.md` = `B4CDDA116486FCE568E9BDAF1721E9FD9E22A0A2C25FF40D3005E3B09964BC70`（129,222 字节）。
- **本轮结束后三份文档**：`README.md` = `9BF3E5068DF1DBD89B58134E0925462880CDE8829563D8E5D7AA1A50785D585F`（16,128 B）；`docs/agent-pipeline-contract.md` = `101386DE0002EEACE180CCAF7BFF6BA0D4AD9FBD01E94166574F2944A8DACFCA`（75,775 B）；`docs/identity-access-contract.md` = `5CF62B99D469F9D1015AC1319397A9D9DD1089F5125C6523E9193E8DC4214935`（36,846 B）。
- **进度文档最终状态**：见 16.12；权威记录在备份清单与本任务交付报告中。

### 16.12 进度文档最终状态（本节写入后核验）

- **本节写入完成时的 SHA-256**：`2972E6C0C1A2A57F5A6E2E0709D95DD62D15C86DA06E49B33DDD7B7788455653`（该值仅表示写入完成时的状态，后续任何改写都会使其失效）。
- **更新前 SHA-256**：`B4CDDA116486FCE568E9BDAF1721E9FD9E22A0A2C25FF40D3005E3B09964BC70`（129,222 字节，备份见 16.11）。

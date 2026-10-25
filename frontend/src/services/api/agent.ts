/**
 * The agent service, over HTTP.
 *
 * The backend fixes three reads/writes: `POST /api/projects/{id}/agent/tasks`
 * creates and runs a task, `GET /api/agent/tasks/{id}` reads one back, and
 * `GET /api/projects/{id}/agent/tasks` lists recent task summaries for the
 * dashboard. The adapter's whole job is the shape the rest of the console
 * already understands: a task result carrying the plan tree and, on the
 * response that produced it, the understanding; the list carries only the
 * persisted activity fields.
 *
 * Three decisions are worth knowing about.
 *
 * **The plan is checked, not cast.**  `AgentPlanSummary` was a count of rows;
 * the endpoint now answers with the rows themselves, and the console draws them.
 * Rather than assert the shape at the type level and hope, `planIsRenderable`
 * walks what arrived and refuses a response the page could not render — a
 * mismatch surfaces as an error the user can read instead of a blank panel.
 *
 * **Errors keep the server's sentence.**  The envelope carries
 * `messageKey` already; it is used when it is one this console can render, and
 * the caller's fallback sentence when it is not (`stores/locale.ts` returns the
 * key itself on a miss, which is how a user ends up reading a dotted path).
 *
 * **The document decoder is local.**  `parseSpec` turns pasted text into the
 * metadata the page draws before any task exists: title, format, endpoint count,
 * the spec id.  The backend exposes no decode endpoint, so the alternative is a
 * second decoder — and a second decoder is a second source of truth for the slug
 * every id in this feature is derived from.  It is the *agent* that no longer
 * runs in the browser: `analyze` and `generatePlan` are the server's, and
 * nothing here falls back to the local rules.
 */

import {
  AGENT_ERROR_CODES,
  AgentServiceError,
  type AgentError,
  type AgentErrorCode,
} from '@/services/agentError'
import type {
  AgentService,
  AgentTaskInput,
  AgentTaskOptions,
  AgentTaskResult,
  LoadedSpec,
  SpecInput,
} from '@/services/agent'
import { ApiError, request } from '@/services/http'
import { DEMO_OPENAPI_DOCUMENT, DEMO_SPEC_FILENAME } from '@/services/spec/demo'
import { parseSpecContent } from '@/services/spec/parse'
import {
  AGENT_TASK_STATUSES,
  type AgentTaskStatus,
  type AgentTaskSummary,
  type TestPlan,
} from '@/types/agent'

const ANALYZE_FAILED = 'console.aiTest.errors.analyzeFailed'
const GENERATE_FAILED = 'console.aiTest.errors.generateFailed'
const LOAD_FAILED = 'console.aiTest.errors.loadFailed'

/**
 * The message keys this console can actually render.
 *
 * Everything else falls back to the sentence the caller knows is true for the
 * operation it attempted.  These are the keys `src/locales/console/en-US.ts`
 * defines under `console.aiTest.errors`.
 */
const RENDERABLE_ERROR_KEYS: ReadonlySet<string> = new Set([
  'console.aiTest.errors.title',
  'console.aiTest.errors.parseFailed',
  'console.aiTest.errors.unsupportedFormat',
  'console.aiTest.errors.noEndpoints',
  'console.aiTest.errors.analyzeFailed',
  'console.aiTest.errors.generateFailed',
  'console.aiTest.errors.planExists',
  'console.aiTest.errors.taskNotFound',
  'console.aiTest.errors.loadFailed',
  'console.aiTest.errors.projectNotReady',
  'console.aiTest.errors.dismiss',
])

/**
 * Whether the console could render the sentence a refusal names.
 *
 * The same membership test `toAgentError` applies to an envelope's
 * `messageKey`: a key outside this set is replaced by the caller's fallback, so
 * a refusal the backend names `console.aiTest.errors.projectNotReady` only
 * reaches the screen because the key is in here.  Exported for that assertion.
 */
export const isRenderableAgentErrorKey = (key: string): boolean =>
  RENDERABLE_ERROR_KEYS.has(key)

/**
 * One task, as the endpoint returns it.
 *
 * Declared here rather than in `types/agent.ts` for the same reason the run
 * adapter declares its replay record: it is the wire shape of these endpoints,
 * not part of the model the UI draws.  The plan and the understanding inside it
 * *are* domain types -- the backend models mirror them field for field.
 */
/** The audit record's fields that this console uses. */
interface AgentTaskAuditWireResponse {
  readonly taskId: string
  readonly status: string
  readonly understanding: AgentUnderstandingWire | null
}

interface AgentTaskWireResponse {
  readonly id: string
  readonly projectId: string
  readonly specId: string
  readonly environmentId: string | null
  readonly prompt: string
  readonly status: string
  readonly createdAt: string
  readonly updatedAt: string
  readonly plan: TestPlan | null
  readonly understanding: AgentUnderstandingWire | null
}

/** The understanding as it arrives; the domain type is what the store holds. */
type AgentUnderstandingWire = NonNullable<AgentTaskResult['understanding']>

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isAgentErrorCode = (value: string): value is AgentErrorCode =>
  (AGENT_ERROR_CODES as readonly string[]).includes(value)

const asTaskStatus = (value: unknown): AgentTaskStatus | null =>
  typeof value === 'string' && (AGENT_TASK_STATUSES as readonly string[]).includes(value)
    ? (value as AgentTaskStatus)
    : null

/**
 * Whether the console could actually draw this plan.
 *
 * Not a schema validator: it checks the fields the review screen reads — the id
 * it keys rows by, the scenarios it iterates, the step kinds it branches on —
 * and nothing else.  A response that fails here is a contract break, and saying
 * so is better than rendering an empty panel.
 */
const planIsRenderable = (plan: unknown): plan is TestPlan => {
  if (!isRecord(plan)) return false
  if (typeof plan.id !== 'string' || typeof plan.status !== 'string') return false
  if (typeof plan.riskLevel !== 'string' || !Array.isArray(plan.scenarios)) return false

  return plan.scenarios.every(
    (scenario) =>
      isRecord(scenario) &&
      typeof scenario.id === 'string' &&
      Array.isArray(scenario.steps) &&
      Array.isArray(scenario.assertions) &&
      scenario.steps.every(
        (step) => isRecord(step) && typeof step.id === 'string' && typeof step.kind === 'string',
      ),
  )
}

/** The fields the dashboard reads from one task-summary row. */
const taskSummaryIsRenderable = (value: unknown): value is AgentTaskSummary => {
  if (!isRecord(value)) return false

  return (
    typeof value.id === 'string' &&
    typeof value.projectId === 'string' &&
    typeof value.prompt === 'string' &&
    asTaskStatus(value.status) !== null &&
    typeof value.createdAt === 'string' &&
    typeof value.updatedAt === 'string'
  )
}

const toAgentError = (thrown: unknown, fallbackCode: AgentErrorCode, fallbackKey: string): AgentError => {
  if (thrown instanceof ApiError) {
    const error: AgentError = {
      code: isAgentErrorCode(thrown.code) ? thrown.code : fallbackCode,
      messageKey: RENDERABLE_ERROR_KEYS.has(thrown.messageKey) ? thrown.messageKey : fallbackKey,
    }

    return thrown.params === undefined ? error : { ...error, params: thrown.params }
  }

  // Not an answer from this service: a network failure, an aborted request, a
  // malformed body. The caller's sentence is the only true one available.
  return { code: fallbackCode, messageKey: fallbackKey }
}

const guarded = async <T>(
  work: () => Promise<T>,
  fallbackCode: AgentErrorCode,
  fallbackKey: string,
): Promise<T> => {
  try {
    return await work()
  } catch (thrown) {
    if (thrown instanceof AgentServiceError) throw thrown

    throw new AgentServiceError(toAgentError(thrown, fallbackCode, fallbackKey))
  }
}

const projectTasksPath = (projectId: string): string =>
  '/api/projects/' + encodeURIComponent(projectId) + '/agent/tasks'

const taskPath = (taskId: string): string => '/api/agent/tasks/' + encodeURIComponent(taskId)

const taskAuditPath = (taskId: string): string =>
  taskPath(taskId) + '/audit'

const projectPlansPath = (projectId: string): string =>
  '/api/projects/' + encodeURIComponent(projectId) + '/plans'

const toTaskResult = (body: AgentTaskWireResponse): AgentTaskResult => {
  const status = asTaskStatus(body?.status)

  if (typeof body?.id !== 'string' || status === null) {
    throw new AgentServiceError({ code: 'analyze-failed', messageKey: ANALYZE_FAILED })
  }

  const plan = body.plan ?? null

  if (plan !== null && !planIsRenderable(plan)) {
    throw new AgentServiceError({ code: 'generate-failed', messageKey: GENERATE_FAILED })
  }

  return {
    taskId: body.id,
    status,
    understanding: body.understanding ?? null,
    plan,
  }
}

export const createHttpAgentService = (): AgentService => ({
  async loadDemoSpec(projectId: string): Promise<LoadedSpec> {
    // Serialised and re-parsed rather than handed over as an object, so the
    // demo travels the same decode path as an uploaded file.
    const content = JSON.stringify(DEMO_OPENAPI_DOCUMENT, null, 2)

    const parsed = await parseSpecContent({
      projectId,
      filename: DEMO_SPEC_FILENAME,
      content,
      source: 'demo',
    })

    return { parsed, content }
  },

  async parseSpec(input: SpecInput) {
    return parseSpecContent(input)
  },

  async runTask(input: AgentTaskInput, _options: AgentTaskOptions = {}) {
    return guarded(async () => {
      const body = await request<AgentTaskWireResponse>(projectTasksPath(input.projectId), {
        method: 'POST',
        body: input,
      })

      return toTaskResult(body)
    }, 'analyze-failed', ANALYZE_FAILED)
  },

  async getTask(taskId: string) {
    return guarded(async () => {
      const body = await request<AgentTaskWireResponse>(taskPath(taskId))

      return toTaskResult(body)
    }, 'task-not-found', LOAD_FAILED)
  },

  async getTaskAudit(taskId: string) {
    return guarded(async () => {
      const body = await request<AgentTaskAuditWireResponse>(taskAuditPath(taskId))

      // The audit's understanding is the same validated wire shape as the task
      // response; null means the task stopped before analysis.
      return body.understanding ?? null
    }, 'task-not-found', LOAD_FAILED)
  },

  async listTasks(projectId: string, limit = 3) {
    return guarded(async () => {
      const query = '?limit=' + encodeURIComponent(String(limit))
      const body = await request<readonly unknown[]>(projectTasksPath(projectId) + query)

      if (!Array.isArray(body) || !body.every((task) => taskSummaryIsRenderable(task))) {
        throw new AgentServiceError({
          code: 'analyze-failed',
          messageKey: LOAD_FAILED,
        })
      }

      return body as readonly AgentTaskSummary[]
    }, 'analyze-failed', LOAD_FAILED)
  },

  async listPlans(projectId: string) {
    return guarded(async () => {
      const body = await request<readonly unknown[]>(projectPlansPath(projectId))

      if (!Array.isArray(body) || !body.every((plan) => planIsRenderable(plan))) {
        throw new AgentServiceError({
          code: 'generate-failed',
          messageKey: GENERATE_FAILED,
        })
      }

      return body as readonly TestPlan[]
    }, 'generate-failed', GENERATE_FAILED)
  },

  async deletePlan(projectId: string, planId: string) {
    await guarded(async () => {
      await request<void>(
        projectPlansPath(projectId) + '/' + encodeURIComponent(planId),
        { method: 'DELETE' },
      )
    }, 'generate-failed', GENERATE_FAILED)
  },
})

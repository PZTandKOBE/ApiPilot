/**
 * Mock agent service.
 *
 * Wires the rule engine together and gives it the timing an agent would have.
 * There is no randomness anywhere: the same document produces the same
 * understanding, and the same understanding produces the same plan.
 *
 * Since Phase 8.2 Step 3 this is the *alternative* implementation: production
 * talks to the server, and this one is kept for tests, for development without a
 * backend, and as the fallback `createAgentService` names. It implements the
 * same task-shaped interface, so nothing above the boundary can tell them apart
 * -- including the rules the server enforces, which are mirrored here:
 *
 * * a second task for a document whose plan this instance already holds is
 *   refused with `plan-exists`, exactly as the endpoint refuses it;
 * * an unknown task id is `task-not-found`.
 *
 * A double that accepted what the real service refuses would let a spec pass
 * here and fail in the browser.
 *
 * Only the analysis and the planning carry artificial latency, because only they
 * represent work a real agent would spend time on. Decoding and parsing a
 * document is instant in both worlds, which matters beyond cosmetics: the store
 * re-parses a persisted document on every load, and that path must stay
 * invisible.
 */

import { AgentServiceError } from '@/services/agentError'
import type {
  AgentService,
  AgentTaskInput,
  AgentTaskOptions,
  AgentTaskResult,
  AnalyzeOptions,
  ParsedSpec,
  SpecInput,
} from '@/services/agent'
import type { AnalysisStage, ApiSpec, ApiUnderstanding, PlanSource, TestPlan } from '@/types/agent'
import { ANALYSIS_STAGES } from '@/types/agent'
import { buildUnderstanding } from './analyze'
import { buildPlan } from './plan'
import { DEMO_OPENAPI_DOCUMENT, DEMO_SPEC_FILENAME } from '@/services/spec/demo'
import { parseSpecContent } from '@/services/spec/parse'

/**
 * Per-stage delay in milliseconds.
 *
 * Fixed rather than jittered so a slow-looking stage always looks the same
 * amount of slow — a UI problem seen once can be reproduced.
 */
const STAGE_DELAY_MS: Readonly<Record<AnalysisStage, number>> = {
  parsing: 110,
  endpoints: 200,
  authentication: 150,
  dependencies: 300,
  risks: 200,
}

const PLAN_DELAY_MS = 420

const wait = (millis: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, millis)
  })

/**
 * The mock, which is the service *and* the rule engine.
 *
 * `analyze` and `generatePlan` are not on `AgentService`: the server has
 * one door, so the production boundary has one too. They stay here because the
 * specs that test the rules themselves drive them directly, and because a task
 * is the two of them in sequence.
 */
export interface MockAgentService extends AgentService {
  analyze(parsed: ParsedSpec, options?: AnalyzeOptions): Promise<ApiUnderstanding>
  generatePlan(
    understanding: ApiUnderstanding,
    spec: ApiSpec,
    source: PlanSource,
  ): Promise<TestPlan>
}

export const createMockAgentService = (): MockAgentService => {
  /**
   * The tasks this instance has run, keyed the way the server keys them.
   *
   * Enough of a registry to enforce the two rules the endpoint enforces -- one
   * plan per document, and an id that names a real task -- and nothing more: a
   * task the server would keep for the next reload is not something a tab-local
   * double can honestly promise.
   */
  const tasks = new Map<string, AgentTaskResult>()

  /**
   * Plans by project/document series, so regeneration can allocate the next
   * version and `listPlans` can answer from the same registry the tasks use.
   */
  const series = new Map<string, TestPlan[]>()

  const seriesKey = (projectId: string, specId: string): string =>
    projectId + ':' + specId

  const analyze = async (
    parsed: ParsedSpec,
    options: AnalyzeOptions = {},
  ): Promise<ApiUnderstanding> => {
    const { onProgress, immediate = false } = options

    if (immediate) return buildUnderstanding(parsed)

    const completed: AnalysisStage[] = []

    for (const stage of ANALYSIS_STAGES) {
      onProgress?.({ stage, completed: [...completed] })
      await wait(STAGE_DELAY_MS[stage])
      completed.push(stage)
    }

    // Final frame: every row ticked. Without it the checklist would end with
    // the last stage still shown as running.
    const last = ANALYSIS_STAGES[ANALYSIS_STAGES.length - 1] ?? 'risks'
    onProgress?.({ stage: last, completed: [...completed] })

    return buildUnderstanding(parsed)
  }

  const plan = async (
    understanding: ApiUnderstanding,
    spec: ApiSpec,
    source: PlanSource,
  ): Promise<TestPlan> => {
    await wait(PLAN_DELAY_MS)
    return buildPlan(understanding, spec, source)
  }

  return {
    async loadDemoSpec(projectId: string) {
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

    async parseSpec(input: SpecInput): Promise<ParsedSpec> {
      return parseSpecContent(input)
    },

    analyze,
    generatePlan: plan,

    async runTask(input: AgentTaskInput, options: AgentTaskOptions = {}) {
      // The document is re-decoded here exactly as the server re-decodes the one
      // it stored: the task input carries text, not a parsed document.
      const parsed = await parseSpecContent({
        projectId: input.projectId,
        filename: 'spec.json',
        content: input.specDocument,
        source: 'upload',
      })

      const understanding = await analyze(parsed, options)
      const generated = await plan(understanding, parsed.spec, 'generated')
      const key = seriesKey(input.projectId, parsed.spec.id)
      const versions = series.get(key) ?? []

      if (!input.regenerate && versions.length > 0) {
        throw new AgentServiceError({
          code: 'plan-exists',
          messageKey: 'console.aiTest.errors.planExists',
        })
      }

      const version = versions.reduce((highest, item) => Math.max(highest, item.version ?? 1), 0) + 1
      const planId = version === 1 ? generated.id : generated.id + '_v' + version
      const taskId = 'task_' + planId

      if (tasks.has(taskId)) {
        throw new AgentServiceError({
          code: 'plan-exists',
          messageKey: 'console.aiTest.errors.planExists',
        })
      }

      const nextPlan: TestPlan = {
        ...generated,
        id: planId,
        version,
        isCurrent: true,
        runCount: 0,
      }

      // The old versions remain, but only the newest one is current.  Updating
      // the stored task results too keeps `loadTask(oldTaskId)` honest.
      series.set(key, [
        ...versions.map((item) => ({ ...item, isCurrent: false })),
        nextPlan,
      ])
      for (const [id, stored] of tasks) {
        if (
          stored.plan !== null &&
          stored.plan.projectId === input.projectId &&
          stored.plan.specId === parsed.spec.id
        ) {
          tasks.set(id, {
            ...stored,
            plan: { ...stored.plan, isCurrent: false },
          })
        }
      }

      const result: AgentTaskResult = {
        taskId,
        status: 'completed',
        understanding,
        plan: nextPlan,
      }

      tasks.set(taskId, result)

      return result
    },

    async getTask(taskId: string) {
      const found = tasks.get(taskId)

      if (found === undefined) {
        throw new AgentServiceError({
          code: 'task-not-found',
          messageKey: 'console.aiTest.errors.taskNotFound',
        })
      }

      return found
    },

    async listPlans(projectId: string) {
      return [...series.values()]
        .flat()
        .filter((item) => item.projectId === projectId)
        .map((item) => ({ ...item }))
    },
  }
}

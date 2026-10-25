import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { isRenderableAgentErrorKey } from '@/services/api/agent'
import { enUS } from '@/locales/en-US'
import { zhCN } from '@/locales/zh-CN'
import { useAgentStore } from '@/stores/agent'
import { useApiClientStore } from '@/stores/apiClient'
import { ProjectNotReadyError, useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

/**
 * The agent store's project-readiness gate, under the *default* test
 * configuration.
 *
 * The real project initialisation branches — a backend list, an empty list after
 * deletion, a failed load — are covered through the real store in
 * projectPersistence.spec.ts, which switches the project-service mode for itself.
 * What is left for this file is everything that does not depend on that switch:
 *
 * * the gate is on the path and uses the id it resolved (driven through the seam
 *   the store actually calls, so what is asserted is this store's behaviour);
 * * the refusal produces the code and the sentence the console renders;
 * * the error model accepts that sentence, in both languages;
 * * Mock mode still behaves exactly as it did before the gate existed.
 */

let storage: Map<string, string>

const installStorage = (): void => {
  const cells = new Map<string, string>()
  storage = cells

  ;(globalThis as unknown as Record<string, unknown>).window = {
    localStorage: {
      getItem: (key: string): string | null => cells.get(key) ?? null,
      setItem: (key: string, value: string): void => {
        cells.set(key, String(value))
      },
      removeItem: (key: string): void => {
        cells.delete(key)
      },
      clear: (): void => cells.clear(),
      key: (index: number): string | null => [...cells.keys()][index] ?? null,
      get length(): number {
        return cells.size
      },
    },
  }
}

let requests: string[] = []

const recordFetch = (): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(String(url))
      throw new Error('no request was expected: ' + String(url))
    }),
  )
}

const setup = () => {
  const agent = useAgentStore()
  const project = useProjectStore()
  const api = useApiClientStore()
  // The store no longer seeds itself, and the analysis is scoped to a project the
  // guest really has — so these tests state the project they are working in.
  installProjectFixtures(project)
  return { agent, project, api }
}

const refuseProject = (
  project: ReturnType<typeof useProjectStore>,
  reason: 'failed' | 'missing' = 'failed',
) => vi.spyOn(project, 'requireReadyProjectId').mockRejectedValue(new ProjectNotReadyError(reason))

const expectRefusal = (error: { code: string; messageKey: string } | null): void => {
  expect(error?.code).toBe('project-not-ready')
  expect(error?.messageKey).toBe('console.aiTest.errors.projectNotReady')
}

const storedPlans = (): readonly { readonly projectId: string }[] =>
  JSON.parse(storage.get('aiata.console.agentPlans') ?? '[]') as readonly {
    readonly projectId: string
  }[]

beforeEach(() => {
  installStorage()
  setActivePinia(createPinia())
  requests = []
  recordFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* ------------------------------------------------------------------ *
 * The gate is on the path
 * ------------------------------------------------------------------ */

describe('the task is scoped to the project readiness resolved', () => {
  it('uses the resolved id, not the one the store was reading', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    const seeded = project.activeProjectId
    expect(seeded).not.toBe('')

    // Readiness vouches for a different project than the store is holding.
    vi.spyOn(project, 'requireReadyProjectId').mockResolvedValue('prj_other')

    await agent.analyzeSpec()

    // The request carried what was resolved: the plan the task wrote is filed
    // under that id, and under no other.
    expect(storedPlans().map((plan) => plan.projectId)).toEqual(['prj_other'])
    expect(agent.analysisError).toBeNull()
    expect(agent.taskStatus).toBe('completed')
    expect(agent.analyzing).toBe(false)
  })

  it('asks the project store for a project rather than trusting its own id', async () => {
    const { agent, project } = setup()
    const gate = vi.spyOn(project, 'requireReadyProjectId')

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    expect(gate).toHaveBeenCalled()
  })
})

/* ------------------------------------------------------------------ *
 * The refusal
 * ------------------------------------------------------------------ */

describe('a refusal reaches the screen as an error, not an exception', () => {
  it('shows the project-not-ready sentence and sends nothing', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    refuseProject(project)

    await agent.analyzeSpec()

    expectRefusal(agent.analysisError)
    expect(agent.planError).toBeNull()
    expect(agent.understanding).toBeNull()
    expect(agent.taskStatus).toBe('failed')
    expect(agent.taskId).toBeNull()
    expect(agent.analyzing).toBe(false)
    expect(agent.progress).toBeNull()
    expect(agent.projectPlans).toEqual([])
    expect(requests).toEqual([])
  })

  it('refuses the same way for a missing project as for a failed one', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    refuseProject(project, 'missing')

    await agent.analyzeSpec()

    expectRefusal(agent.analysisError)
    expect(agent.analyzing).toBe(false)
  })

  it('leaves the handoff on screen when it cannot be adopted', async () => {
    const { agent, api, project } = setup()

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001"}' })
    expect(api.requestAgentHandoff()).toBe(true)

    refuseProject(project)
    await agent.adoptHandoff()

    expect(api.handoff).not.toBeNull()
    expect(agent.pendingHandoff).not.toBeNull()
    expectRefusal(agent.analysisError)
    expect(storage.get('aiata.console.agentSpecs')).toBeUndefined()
    expect(requests).toEqual([])
  })
})

/* ------------------------------------------------------------------ *
 * The gate is not applied where it does not belong
 * ------------------------------------------------------------------ */

describe('actions that do not need a project are left alone', () => {
  it('reads a task back by its own id', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const taskId = agent.taskId ?? ''

    agent.resetSpec()
    refuseProject(project)

    await agent.loadTask(taskId)

    // Addressed by task id, and the server checks that task's own project.
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.taskStatus).toBe('completed')
    expect(agent.analysisError).toBeNull()
  })

  it('keeps the approval actions local', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const planId = agent.activePlan?.id ?? ''

    refuseProject(project)

    agent.startReview(planId)
    expect(agent.activePlan?.status).toBe('in_review')

    expect(agent.rejectPlan(planId, '   ')).toBe(false)
    expect(agent.rejectPlan(planId, '  Missing the refund path.  ')).toBe(true)
    expect(agent.activePlan?.rejectionReason).toBe('Missing the refund path.')

    agent.approvePlan(planId)
    expect(agent.activePlan?.status).toBe('approved')

    agent.updatePlanMeta(planId, { name: 'Renamed', goal: 'Regoaled' })
    expect(agent.activePlan?.name).toEqual({ text: 'Renamed' })
    expect(agent.activePlan?.status).toBe('approved')
  })
})

/* ------------------------------------------------------------------ *
 * Mock mode is unchanged
 * ------------------------------------------------------------------ */

describe('mock mode still runs the pipeline it always did', () => {
  it('produces the understanding, the plan and the status in one action', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    expect(agent.understanding?.endpoints).toHaveLength(18)
    expect(agent.taskStatus).toBe('completed')
    expect(agent.taskId).toMatch(/^task_plan_/)
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.activePlan?.status).toBe('draft')
    expect(agent.analysisError).toBeNull()
    expect(agent.planError).toBeNull()
    expect(agent.analyzing).toBe(false)
    // The gate resolved through the mock project store without a single request.
    expect(requests).toEqual([])
  })

  it('still refuses a second plan for the same document', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.generatePlan()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.generating).toBe(false)
  })
})

/* ------------------------------------------------------------------ *
 * The sentence behind the refusal
 * ------------------------------------------------------------------ */

describe('the refusal sentence is complete and renderable', () => {
  const lookup = (dictionary: unknown): unknown => {
    let node: unknown = dictionary

    for (const segment of ['console', 'aiTest', 'errors', 'projectNotReady']) {
      if (typeof node !== 'object' || node === null) return undefined
      node = (node as Record<string, unknown>)[segment]
    }

    return node
  }

  it('exists in both dictionaries and is not empty', () => {
    const en = lookup(enUS)
    const zh = lookup(zhCN)

    expect(typeof en).toBe('string')
    expect(typeof zh).toBe('string')
    expect((en as string).trim()).not.toBe('')
    expect((zh as string).trim()).not.toBe('')
  })

  it('is a key the agent error mapper is willing to pass through', () => {
    // The same membership test an envelope's messageKey goes through: outside
    // this set, a refusal naming this key would be replaced by a generic
    // sentence and the user would never read the real reason.
    expect(isRenderableAgentErrorKey('console.aiTest.errors.projectNotReady')).toBe(true)
    expect(isRenderableAgentErrorKey('console.aiTest.errors.invented')).toBe(false)
  })
})

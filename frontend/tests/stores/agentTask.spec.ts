import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * The agent task, as the store drives it.
 *
 * The store talks to whichever `AgentService` the boundary hands it; under
 * vitest that is the mock, which mirrors the server's two rules -- one plan per
 * document, and an id that names a real task. What is asserted here is what the
 * *screen* gets: the status, the plan, where a failure is shown, and the promise
 * that a variable's value reaches no storage.
 */

const setup = () => {
  const project = useProjectStore()
  // The store starts empty; this spec switches between projects by id.
  // Installed before the agent store, which follows the active project.
  installProjectFixtures(project)
  const agent = useAgentStore()
  return { agent, project }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('running a task', () => {
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
  })

  it('advances the pipeline past the plan, because the plan exists', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    expect(agent.completedSteps).toEqual(['spec'])

    await agent.analyzeSpec()

    expect(agent.completedSteps).toEqual(['spec', 'analyze', 'understanding', 'plan'])
    expect(agent.step).toBe('approve')
  })

  it('shows a refused plan as a planning failure, not an analysis one', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.analyzeSpec()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.planError?.messageKey).toBe('console.aiTest.errors.planExists')
    expect(agent.analysisError).toBeNull()
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.taskStatus).toBe('failed')
  })

  it('leaves an approved plan alone when a second task is refused', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    agent.approvePlan(agent.activePlan?.id ?? '')

    // Captured after the approval: approving replaces the plan object, so a
    // snapshot taken before it would report the draft's nulls.
    const approved = agent.activePlan
    expect(approved?.status).toBe('approved')

    await agent.generatePlan()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.activePlan?.id).toBe(approved?.id)
    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.activePlan?.approvedAt).toBe(approved?.approvedAt)
    expect(JSON.stringify(agent.activePlan?.scenarios)).toBe(JSON.stringify(approved?.scenarios))
  })
})

describe('recovering a server plan the browser did not have', () => {
  it('loads the version list before deciding what the action means', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const planId = agent.activePlan?.id
    expect(planId).toBeDefined()

    agent.resetSpec()
    expect(agent.projectPlans).toHaveLength(0)

    await agent.loadDemoSpec()
    await agent.loadPlans()

    expect(agent.activePlan?.id).toBe(planId)
    expect(agent.planError).toBeNull()
  })

  it('turns an ordinary plan-exists refusal into a refreshed plan list', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const planId = agent.activePlan?.id

    agent.resetSpec()
    await agent.loadDemoSpec()

    await agent.generatePlan()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.activePlan?.id).toBe(planId)
  })
})

describe('regenerating a plan', () => {
  it('creates an independent next version and leaves the approved old plan alone', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    const first = agent.activePlan
    expect(first).not.toBeNull()
    if (first === null) return

    agent.approvePlan(first.id)
    const approved = agent.projectPlans.find((plan) => plan.id === first.id)
    expect(approved?.status).toBe('approved')
    const approvedScenarios = JSON.stringify(approved?.scenarios)

    await agent.regeneratePlan()

    expect(agent.planError).toBeNull()
    expect(agent.projectPlans).toHaveLength(2)
    expect(agent.activePlan?.id).toBe(first.id + '_v2')
    expect(agent.activePlan?.version).toBe(2)
    expect(agent.activePlan?.isCurrent).toBe(true)
    expect(agent.activePlan?.status).toBe('draft')

    const old = agent.projectPlans.find((plan) => plan.id === first.id)
    expect(old?.status).toBe('approved')
    expect(old?.approvedAt).toBe(approved?.approvedAt)
    expect(JSON.stringify(old?.scenarios)).toBe(approvedScenarios)
    expect(old?.isCurrent).toBe(false)
  })

  it('merges server versions without losing the local approval', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const first = agent.activePlan
    expect(first).not.toBeNull()
    if (first === null) return

    agent.approvePlan(first.id)
    await agent.regeneratePlan()
    await agent.loadPlans()

    expect(agent.plansError).toBeNull()
    expect(agent.projectPlans).toHaveLength(2)
    expect(agent.projectPlans.find((plan) => plan.id === first.id)?.status).toBe('approved')
    expect(agent.activePlan?.status).toBe('draft')
    expect(agent.activePlan?.version).toBe(2)
  })
})

describe('reading a task back', () => {
  it('adopts the plan the server stored', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
        await agent.analyzeSpec()
    const taskId = agent.taskId ?? ''

    agent.resetSpec()
    expect(agent.projectPlans).toHaveLength(0)

    await agent.loadTask(taskId)

    expect(agent.taskStatus).toBe('completed')
    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.analysisError).toBeNull()
  })

  it('reports an unknown id without inventing a plan', async () => {
    const { agent } = setup()

    await agent.loadTask('task_nothing')

    expect(agent.analysisError?.code).toBe('task-not-found')
    expect(agent.analysisError?.messageKey).toBe('console.aiTest.errors.taskNotFound')
    expect(agent.projectPlans).toHaveLength(0)
    expect(agent.loading).toBe(false)
  })
})

describe('rehydration', () => {
  it('does not run a second task when the project changes', async () => {
    const { agent, project } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const planId = agent.activePlan?.id

    project.selectProject('prj_payments')
    project.selectProject('prj_orders')
    // Rehydration decodes the stored document; it does not replay the analysis.
    // The server holds this document's plan already, and a second task would be
    // refused -- so the plan on screen is the one that was stored.
    await new Promise((resolve) => setTimeout(resolve, 50))

    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.activePlan?.id).toBe(planId)
    expect(agent.planError).toBeNull()
    expect(agent.analysisError).toBeNull()
  })
})

describe('what storage is allowed to keep', () => {
  afterEach(() => {
    removeStorage()
  })

  it('keeps the spec metadata and the plan, and no variable value', async () => {
    installStorage({})

    const { agent, project } = setup()
    const values = Object.values(project.variables)

    // The fixture has values to leak; a test with none would prove nothing.
    expect(values.length).toBeGreaterThan(0)

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    const stored = ['aiata.console.agentSpecs', 'aiata.console.agentPlans']
      .map((key) => globalThis.window?.localStorage.getItem(key) ?? '')
      .join('\n')

    expect(stored).toContain('Orders Platform API')

    for (const value of values) {
      expect(stored).not.toContain(value)
    }
  })
})

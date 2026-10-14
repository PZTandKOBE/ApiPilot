import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAgentStore } from '@/stores/agent'
import { useApiClientStore } from '@/stores/apiClient'
import { useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

/**
 * The agent store: orchestration, and the approval boundary.
 *
 * These run against the real stores with a real Pinia instance, so what is
 * asserted is the behaviour the components actually get — not a description of
 * it.
 */
beforeEach(() => {
  setActivePinia(createPinia())
})

const setup = () => {
  const project = useProjectStore()
  // The store starts empty now, and these tests switch between projects by id —
  // so the projects they switch between are stated here instead of implied.
  // Installed before the stores that watch the active project are built.
  installProjectFixtures(project)
  const agent = useAgentStore()
  const api = useApiClientStore()
  return { agent, api, project }
}

describe('pipeline position is derived, never stored', () => {
  it('starts at the specification step with nothing loaded', () => {
    const { agent } = setup()

    expect(agent.currentSpec).toBeNull()
    expect(agent.understanding).toBeNull()
    expect(agent.activePlan).toBeNull()
    expect(agent.step).toBe('spec')
    expect(agent.completedSteps).toEqual([])
  })

  it('advances only as the artifact each step produces exists', async () => {
    const { agent } = setup()

    await agent.loadDemoSpec()
    expect(agent.step).toBe('analyze')
    expect(agent.completedSteps).toEqual(['spec'])

    // One task, not two: the server parses, analyses, plans and stores in a
    // single request, so a plan exists the moment the analysis returns.
    await agent.analyzeSpec()
    expect(agent.step).toBe('approve')
    expect(agent.completedSteps).toEqual(['spec', 'analyze', 'understanding', 'plan'])
    expect(agent.activePlan?.status).toBe('draft')

    agent.approvePlan(agent.activePlan?.id ?? '')
    expect(agent.step).toBe('execute')
  })
})

describe('specification loading', () => {
  it('parses the demo document through the real service', async () => {
    const { agent } = setup()
    await agent.loadDemoSpec()

    expect(agent.currentSpec?.title).toBe('Orders Platform API')
    expect(agent.currentSpec?.endpointCount).toBe(18)
    expect(agent.analysisError).toBeNull()
  })

  it('surfaces a parse failure as a localized error rather than throwing', async () => {
    const { agent } = setup()
    await agent.loadSpec({ filename: 'x.json', content: '{ not json', source: 'paste' })

    expect(agent.analysisError?.code).toBe('parse-failed')
    expect(agent.analysisError?.messageKey).toBe('console.aiTest.errors.parseFailed')
    expect(agent.currentSpec).toBeNull()
  })

  it('drops plans that belonged to the previous document', async () => {
    const { agent } = setup()
    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    expect(agent.projectPlans).toHaveLength(1)

    await agent.loadSpec({
      filename: 'tiny.json',
      content: JSON.stringify({
        openapi: '3.0.3',
        info: { title: 'Tiny', version: '1' },
        paths: { '/ping': { get: { responses: { 200: { description: 'ok' } } } } },
      }),
      source: 'upload',
    })

    expect(agent.projectPlans).toHaveLength(0)
    expect(agent.understanding).toBeNull()
  })
})

describe('analysis', () => {
  it('produces an understanding and clears its running state', async () => {
    const { agent } = setup()
    await agent.loadDemoSpec()

    await agent.analyzeSpec()

    expect(agent.understanding?.endpoints).toHaveLength(18)
    expect(agent.understanding?.dependencies).toHaveLength(7)
    expect(agent.analyzing).toBe(false)
    // Progress is a running indicator; leaving it set would strand the
    // checklist on screen after the run finished.
    expect(agent.progress).toBeNull()
    expect(agent.analysisError).toBeNull()
  })
})

describe('plans', () => {
  const withPlan = async () => {
    const context = setup()
    await context.agent.loadDemoSpec()
    // The task writes the plan; there is no second call to make.
    await context.agent.analyzeSpec()
    return context
  }

  it('never accumulates a second plan for the same document', async () => {
    const { agent } = await withPlan()
    expect(agent.projectPlans).toHaveLength(1)

    // A second task for the same document is refused by the server rather than
    // overwriting what a reviewer may already have approved.
    await agent.generatePlan()

    expect(agent.projectPlans).toHaveLength(1)
    expect(agent.planError?.code).toBe('plan-exists')
  })

  it('scopes plans to the active project', async () => {
    const { agent, project } = await withPlan()
    expect(agent.projectPlans).toHaveLength(1)

    project.selectProject('prj_payments')
    expect(agent.projectPlans).toHaveLength(0)

    project.selectProject('prj_orders')
    expect(agent.projectPlans).toHaveLength(1)
  })
})

describe('the approval boundary', () => {
  const withPlan = async () => {
    const context = setup()
    await context.agent.loadDemoSpec()
    await context.agent.analyzeSpec()
    return { ...context, planId: context.agent.activePlan?.id ?? '' }
  }

  it('cannot run a draft', async () => {
    const { agent } = await withPlan()
    expect(agent.activePlan?.status).toBe('draft')
  })

  it('moves draft to in review when the plan is put in front of a reviewer', async () => {
    const { agent, planId } = await withPlan()
    agent.startReview(planId)

    expect(agent.activePlan?.status).toBe('in_review')
  })

  it('refuses a rejection with no reason', async () => {
    const { agent, planId } = await withPlan()
    agent.startReview(planId)

    expect(agent.rejectPlan(planId, '   ')).toBe(false)
    expect(agent.activePlan?.status).toBe('in_review')
    expect(agent.activePlan?.rejectionReason).toBeNull()
  })

  it('records a rejection reason verbatim, trimmed', async () => {
    const { agent, planId } = await withPlan()
    agent.startReview(planId)

    expect(agent.rejectPlan(planId, '  Missing the refund path.  ')).toBe(true)
    expect(agent.activePlan?.status).toBe('rejected')
    expect(agent.activePlan?.rejectionReason).toBe('Missing the refund path.')
    expect(agent.activePlan?.rejectedAt).not.toBeNull()
  })

  it('approves, and is the only path to an approved plan', async () => {
    const { agent, planId } = await withPlan()
    agent.startReview(planId)
    agent.approvePlan(planId)

    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.activePlan?.approvedAt).not.toBeNull()
    expect(agent.activePlan?.rejectionReason).toBeNull()
  })

  it('leaves the approved plan approved when regeneration is refused', async () => {
    const { agent, planId } = await withPlan()
    agent.approvePlan(planId)
    expect(agent.activePlan?.status).toBe('approved')

    await agent.generatePlan()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.activePlan?.id).toBe(planId)
    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.activePlan?.approvedAt).not.toBeNull()
  })
})

describe('metadata editing', () => {
  const approvedPlan = async () => {
    const context = setup()
    await context.agent.loadDemoSpec()
    await context.agent.analyzeSpec()

    const planId = context.agent.activePlan?.id ?? ''
    context.agent.approvePlan(planId)
    return { ...context, planId }
  }

  it('replaces name and goal with the reviewer’s own words', async () => {
    const { agent, planId } = await approvedPlan()

    agent.updatePlanMeta(planId, {
      name: 'Checkout regression',
      goal: 'Cover the paid path end to end.',
    })

    expect(agent.activePlan?.name).toEqual({ text: 'Checkout regression' })
    expect(agent.activePlan?.goal).toEqual({ text: 'Cover the paid path end to end.' })
  })

  it('leaves approval state, timestamps and scenarios untouched', async () => {
    const { agent, planId } = await approvedPlan()
    const before = agent.activePlan
    const scenariosBefore = JSON.stringify(before?.scenarios)

    agent.updatePlanMeta(planId, { name: 'Renamed', goal: 'Regoaled' })
    const after = agent.activePlan

    expect(after?.status).toBe('approved')
    expect(after?.approvedAt).toBe(before?.approvedAt)
    expect(after?.rejectedAt).toBe(before?.rejectedAt)
    expect(after?.generatedAt).toBe(before?.generatedAt)
    expect(after?.riskLevel).toBe(before?.riskLevel)
    expect(after?.source).toBe(before?.source)
    expect(after?.specId).toBe(before?.specId)
    // The plan a human approved is still the plan the agent wrote.
    expect(JSON.stringify(after?.scenarios)).toBe(scenariosBefore)
  })

  it('does not invent a new status transition', async () => {
    const { agent, planId } = await approvedPlan()
    agent.updatePlanMeta(planId, { name: 'x', goal: 'y' })

    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.step).toBe('execute')
  })
})

describe('API Client handoff', () => {
  it('is derived from the API Client store, with no copy to go stale', () => {
    const { agent, api } = setup()

    expect(agent.pendingHandoff).toBeNull()

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001","quantity":2}' })
    expect(api.requestAgentHandoff()).toBe(true)

    // No watcher, no tick: the value is there the moment it is produced.
    expect(agent.pendingHandoff).not.toBeNull()
    expect(agent.pendingHandoff?.resolved.url).toBe(
      'https://api.dev.example.com/api/orders',
    )
  })

  it('parses and analyses the handed-over request in one action', async () => {
    const { agent, api } = setup()

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setHeaders([
      {
        id: 'h1',
        enabled: true,
        key: 'Content-Type',
        value: 'application/json',
        description: '',
      },
    ])
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001"}' })
    api.requestAgentHandoff()

    await agent.adoptHandoff()

    expect(agent.currentSpec?.source).toBe('handoff')
    expect(agent.currentSpec?.endpointCount).toBe(1)
    expect(agent.understanding?.endpoints).toHaveLength(1)
    // The handoff runs the same task, so the plan is written with it.
    expect(agent.step).toBe('approve')
    expect(agent.activePlan?.status).toBe('draft')
    // Consumed exactly once.
    expect(api.handoff).toBeNull()
    expect(agent.pendingHandoff).toBeNull()
  })

  it('does not capture a handoff belonging to another project', async () => {
    const { agent, api, project } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.requestAgentHandoff()

    project.selectProject('prj_payments')
    expect(agent.pendingHandoff).toBeNull()
  })

  it('dismissing clears the API Client’s handoff too', () => {
    const { agent, api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.requestAgentHandoff()

    agent.dismissHandoff()
    expect(api.handoff).toBeNull()
    expect(agent.pendingHandoff).toBeNull()
  })
})

describe('reset', () => {
  it('clears the project’s spec, understanding and plans', async () => {
    const { agent } = setup()
    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    agent.resetSpec()

    expect(agent.currentSpec).toBeNull()
    expect(agent.understanding).toBeNull()
    expect(agent.projectPlans).toHaveLength(0)
    expect(agent.step).toBe('spec')
  })
})

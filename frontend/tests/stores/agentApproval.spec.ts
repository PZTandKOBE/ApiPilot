import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentServiceError } from '@/services/agentError'
import { createMockAgentService } from '@/services/mock/agent'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import type { TestPlan } from '@/types/agent'

import { installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * Server-side approval, driven through the store.
 *
 * Approval stopped being a local flag: the run gate reads the receipt the
 * server wrote when `/approve` was called, so a store that only edited its own
 * copy would leave the user with a plan that looks approved and a run that is
 * refused with 409.  These tests pin the new contract -- the service is called,
 * its answer replaces the local plan, and a refusal changes nothing.
 *
 * The service is the product's own mock (the test-mode implementation), shared
 * between stores here so a fresh store can be built against the same server
 * state -- which is what makes the `loadPlans` staleness test a real
 * client/server disagreement rather than a hand-made object.
 */
const holder = vi.hoisted(() => ({
  service: null as unknown as ReturnType<typeof createMockAgentService>,
}))

vi.mock('@/services/agent', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/agent')>()

  return { ...actual, createAgentService: () => holder.service }
})

const PROPOSED_AT = '2026-06-01T10:00:00.000Z'

beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  holder.service = createMockAgentService()
})

afterEach(() => {
  vi.restoreAllMocks()
  removeStorage()
})

const setup = () => {
  const agent = useAgentStore()
  return { agent }
}

const withDraftPlan = async () => {
  const { agent } = setup()

  await agent.loadDemoSpec()
  await agent.analyzeSpec()

  const plan = agent.activePlan
  if (plan === null) throw new Error('expected the task to write a plan')

  return { agent, planId: plan.id }
}

const storedPlans = (): TestPlan[] =>
  JSON.parse(window.localStorage.getItem('aiata.console.agentPlans') ?? '[]') as TestPlan[]

describe('approval is a server round trip', () => {
  it('calls approve and adopts the plan the server returned', async () => {
    const { agent, planId } = await withDraftPlan()
    const approve = vi.spyOn(holder.service, 'approvePlan').mockResolvedValueOnce({
      ...(agent.activePlan as TestPlan),
      status: 'approved',
      approvedAt: PROPOSED_AT,
      rejectedAt: null,
      rejectionReason: null,
      approvedBy: 'account',
    })

    expect(await agent.approvePlan(planId)).toBe(true)

    expect(approve).toHaveBeenCalledWith('prj_orders', planId)
    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.activePlan?.approvedAt).toBe(PROPOSED_AT)
    expect(agent.activePlan?.approvedBy).toBe('account')
    expect(agent.approvalError).toBeNull()
  })

  it('keeps the local plan untouched when the server refuses', async () => {
    const { agent, planId } = await withDraftPlan()
    const before = agent.activePlan

    vi.spyOn(holder.service, 'approvePlan').mockRejectedValueOnce(
      new AgentServiceError({
        code: 'invalid-plan-state',
        messageKey: 'console.plans.errors.invalidState',
      }),
    )

    expect(await agent.approvePlan(planId)).toBe(false)

    // Same object, not merely equal: nothing was written on the way out.
    expect(agent.activePlan).toBe(before)
    expect(agent.activePlan?.status).toBe('draft')
    expect(agent.activePlan?.approvedBy ?? null).toBeNull()
    expect(agent.approvalError).toEqual({
      code: 'invalid-plan-state',
      messageKey: 'console.plans.errors.invalidState',
    })
  })

  it('reports a plan that is no longer in the local list without calling the server', async () => {
    const { agent } = await withDraftPlan()
    const approve = vi.spyOn(holder.service, 'approvePlan')

    expect(await agent.approvePlan('plan_does_not_exist')).toBe(false)

    expect(approve).not.toHaveBeenCalled()
    expect(agent.approvalError?.code).toBe('plan-not-found')
    expect(agent.approvalError?.messageKey).toBe('console.plans.notFound')
  })
})

describe('rejection requires a reason and goes to the server', () => {
  it('refuses a blank reason before it asks the service', async () => {
    const { agent, planId } = await withDraftPlan()
    const reject = vi.spyOn(holder.service, 'rejectPlan')

    expect(await agent.rejectPlan(planId, '   ')).toBe(false)

    expect(reject).not.toHaveBeenCalled()
    expect(agent.activePlan?.status).toBe('draft')
    expect(agent.approvalError?.messageKey).toBe('console.aiTest.approval.reasonRequired')
  })

  it('sends the trimmed sentence and adopts the rejected plan', async () => {
    const { agent, planId } = await withDraftPlan()
    const reject = vi.spyOn(holder.service, 'rejectPlan')

    expect(await agent.rejectPlan(planId, '  Missing the refund path.  ')).toBe(true)

    expect(reject).toHaveBeenCalledWith('prj_orders', planId, 'Missing the refund path.')
    expect(agent.activePlan?.status).toBe('rejected')
    expect(agent.activePlan?.rejectionReason).toBe('Missing the refund path.')
    expect(agent.activePlan?.rejectedAt).not.toBeNull()
    expect(agent.activePlan?.approvedAt).toBeNull()
    expect(agent.activePlan?.approvedBy ?? null).toBeNull()
  })

  it('keeps the local plan untouched when the server refuses', async () => {
    const { agent, planId } = await withDraftPlan()
    const before = agent.activePlan

    vi.spyOn(holder.service, 'rejectPlan').mockRejectedValueOnce(
      new AgentServiceError({
        code: 'invalid-plan-state',
        messageKey: 'console.plans.errors.invalidState',
      }),
    )

    expect(await agent.rejectPlan(planId, 'Too vague.')).toBe(false)

    expect(agent.activePlan).toBe(before)
    expect(agent.activePlan?.status).toBe('draft')
    expect(agent.approvalError?.code).toBe('invalid-plan-state')
  })
})

describe('loadPlans treats the server as authoritative', () => {
  it('does not let a locally approved cache outrank a server draft', async () => {
    const { planId } = await withDraftPlan()

    // What an old build (or a hand-edited localStorage cell) left behind:
    // approved locally, still draft on the server.
    const stale = storedPlans().map((plan) =>
      plan.id === planId
        ? {
            ...plan,
            status: 'approved' as const,
            approvedAt: PROPOSED_AT,
            approvedBy: 'account' as const,
          }
        : plan,
    )
    window.localStorage.setItem('aiata.console.agentPlans', JSON.stringify(stale))

    // A fresh browser restores that cache before it asks the server.
    setActivePinia(createPinia())
    installProjectFixtures(useProjectStore())
    const restored = useAgentStore()
    expect(restored.activePlan?.status).toBe('approved')

    await restored.loadPlans()

    expect(restored.activePlan?.status).toBe('draft')
    expect(restored.activePlan?.approvedAt).toBeNull()
    expect(restored.activePlan?.approvedBy ?? null).toBeNull()
  })
})

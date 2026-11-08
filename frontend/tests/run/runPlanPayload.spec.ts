import { describe, expect, it } from 'vitest'

import { toRunPlanPayload } from '@/services/run'
import type { TestPlan } from '@/types/agent'

/**
 * The Run request Plan DTO must not carry response-only approval metadata.
 *
 * approvedBy belongs to AgentPlanResponse/TestPlan and to the review UI; the
 * backend Run PlanPayload rejects it.  The projection must strip it without
 * mutating the plan the review screen still holds.
 */
const approvedPlan = (approvedBy: 'account' | 'guest'): TestPlan => ({
  id: 'plan_orders_1a2b',
  projectId: 'prj_orders',
  specId: 'spec_orders_api_1a2b',
  name: { text: 'Orders' },
  goal: { text: 'Check out' },
  riskLevel: 'medium',
  status: 'approved',
  scenarios: [
    {
      id: 'scenario_orders',
      index: 0,
      name: { text: 'Orders' },
      description: { text: 'Read an order' },
      riskLevel: 'low',
      steps: [
        {
          id: 'step_read',
          index: 0,
          kind: 'request',
          description: { text: 'Read' },
          endpointId: 'ep_get_orders',
          method: 'GET',
          path: '/orders',
          produces: null,
          consumes: [],
        },
      ],
      expected: { text: 'Orders answer' },
      assertions: [],
    },
  ],
  source: 'generated',
  generatedAt: '2026-11-08T00:00:00.000Z',
  approvedAt: '2026-11-08T01:00:00.000Z',
  rejectedAt: null,
  rejectionReason: null,
  approvedBy,
  version: 2,
  isCurrent: true,
  runCount: 4,
})

describe('the Run request Plan DTO', () => {
  it('strips approvedBy for an account approval and keeps the payload fields', () => {
    const plan = approvedPlan('account')
    const payload = toRunPlanPayload(plan)

    expect(payload).not.toHaveProperty('approvedBy')
    expect(payload.id).toBe(plan.id)
    expect(payload.projectId).toBe(plan.projectId)
    expect(payload.specId).toBe(plan.specId)
    expect(payload.name).toEqual(plan.name)
    expect(payload.goal).toEqual(plan.goal)
    expect(payload.riskLevel).toBe(plan.riskLevel)
    expect(payload.status).toBe(plan.status)
    expect(payload.scenarios).toBe(plan.scenarios)
    expect(payload.source).toBe(plan.source)
    expect(payload.generatedAt).toBe(plan.generatedAt)
    expect(payload.approvedAt).toBe(plan.approvedAt)
    expect(payload.rejectedAt).toBe(plan.rejectedAt)
    expect(payload.rejectionReason).toBe(plan.rejectionReason)
    expect(payload.version).toBe(plan.version)
    expect(payload.isCurrent).toBe(plan.isCurrent)
    expect(payload.runCount).toBe(plan.runCount)
  })

  it('strips approvedBy for a guest approval', () => {
    const payload = toRunPlanPayload(approvedPlan('guest'))

    expect(payload).not.toHaveProperty('approvedBy')
  })

  it('does not mutate the original Plan held by the review UI', () => {
    const plan = approvedPlan('account')

    toRunPlanPayload(plan)

    expect(plan.approvedBy).toBe('account')
    expect(plan.approvedAt).toBe('2026-11-08T01:00:00.000Z')
    expect(plan.status).toBe('approved')
  })
})

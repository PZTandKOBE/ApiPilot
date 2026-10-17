import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { AgentServiceError } from '@/services/agentError'
import { createMockAgentService } from '@/services/mock/agent'
import { installProjectFixtures } from '../support/projects'

/**
 * A regeneration failure is a failure of the new task, not of the old plan.
 *
 * The module mock replaces only `createAgentService`; every other export stays
 * the real one, and the mock implementation is the product's own in-browser
 * pipeline.  The failure is injected on its `runTask` so the store's error and
 * "leave the old plan alone" paths are exercised without a backend.
 */
const holder = vi.hoisted(() => ({ service: null as unknown }))

vi.mock('@/services/agent', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/agent')>()
  return {
    ...actual,
    createAgentService: () => holder.service,
  }
})

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  holder.service = createMockAgentService()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('regeneration request', () => {
  it('asks the service for a new version, not an ordinary generation', async () => {
    const agent = useAgentStore()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    expect(agent.activePlan).not.toBeNull()

    const service = holder.service as ReturnType<typeof createMockAgentService>
    const runTask = vi.spyOn(service, 'runTask')

    await agent.regeneratePlan()

    expect(runTask).toHaveBeenCalledTimes(1)
    expect(runTask.mock.calls[0]?.[0]).toMatchObject({ regenerate: true })
    expect(agent.activePlan?.version).toBe(2)
  })
})

describe('regeneration failure', () => {
  it('keeps the old plan visible and reports the planning error', async () => {
    const agent = useAgentStore()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    const before = agent.activePlan
    expect(before).not.toBeNull()
    if (before === null) return

    agent.approvePlan(before.id)
    const approved = agent.projectPlans.find((plan) => plan.id === before.id)
    const snapshot = JSON.stringify(agent.projectPlans)

    const service = holder.service as ReturnType<typeof createMockAgentService>
    vi.spyOn(service, 'runTask').mockRejectedValueOnce(
      new AgentServiceError({
        code: 'generate-failed',
        messageKey: 'console.aiTest.errors.generateFailed',
      }),
    )

    await agent.regeneratePlan()

    expect(agent.planError?.code).toBe('generate-failed')
    expect(agent.planError?.messageKey).toBe('console.aiTest.errors.generateFailed')
    expect(agent.generating).toBe(false)
    expect(JSON.stringify(agent.projectPlans)).toBe(snapshot)
    expect(agent.activePlan?.id).toBe(before.id)
    expect(agent.activePlan?.status).toBe('approved')
    expect(agent.activePlan?.approvedAt).toBe(approved?.approvedAt)
  })
})

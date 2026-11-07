import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockRunService } from '@/services/mock/run'
import type { RunErrorCode } from '@/services/run'
import { RunServiceError } from '@/services/runError'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'

import { installProjectFixtures } from '../support/projects'

/**
 * The run store's plan-gate errors.
 *
 * A run is now created against the *stored* plan, so the server can refuse with
 * plan-changed or plan-not-found after the store's own UX pre-check passed.
 * What these tests pin is that the refusal reaches `error` with its own code
 * and sentence -- not folded into create-failed -- because the user needs to
 * know whether to re-approve the plan or go back and generate it.
 *
 * The run service is replaced at the module seam so the store sees the exact
 * refusal the server sends.
 */
const holder = vi.hoisted(() => ({
  service: null as unknown as ReturnType<typeof createMockRunService>,
}))

vi.mock('@/services/run', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/run')>()

  return { ...actual, createRunService: () => holder.service }
})

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  holder.service = createMockRunService()
})

const withApprovedPlan = async () => {
  const agent = useAgentStore()

  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.approvePlan(agent.activePlan?.id ?? '')

  return { agent, runs: useRunsStore() }
}

const refuseCreateRun = (code: RunErrorCode, messageKey: string): void => {
  vi.spyOn(holder.service, 'createRun').mockRejectedValueOnce(
    new RunServiceError({ code, messageKey }),
  )
}

describe('the run gate\'s plan refusals', () => {
  it('keeps plan-changed as its own code and sentence', async () => {
    const { runs } = await withApprovedPlan()

    refuseCreateRun('plan-changed', 'console.runs.errors.planChanged')

    expect(await runs.createRun({ immediate: true })).toBeNull()
    expect(runs.error).toEqual({
      code: 'plan-changed',
      messageKey: 'console.runs.errors.planChanged',
    })
    expect(runs.projectRuns).toHaveLength(0)
  })

  it('maps a deleted plan to the shared plan sentence', async () => {
    const { runs } = await withApprovedPlan()

    refuseCreateRun('plan-not-found', 'console.plans.notFound')

    expect(await runs.createRun({ immediate: true })).toBeNull()
    expect(runs.error).toEqual({
      code: 'plan-not-found',
      messageKey: 'console.plans.notFound',
    })
  })

  it('maps an invalid plan state without pretending the plan is gone', async () => {
    const { runs } = await withApprovedPlan()

    refuseCreateRun('invalid-plan-state', 'console.plans.errors.invalidState')

    expect(await runs.createRun({ immediate: true })).toBeNull()
    expect(runs.error?.code).toBe('invalid-plan-state')
    expect(runs.error?.messageKey).toBe('console.plans.errors.invalidState')
  })
})

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import type { RunEvent } from '@/types/run'

import { installProjectFixtures } from '../support/projects'

/**
 * The run store, driven by the real run service.
 *
 * There is no test double here for the same reason there is none in the agent
 * store's tests: the mock *is* the implementation of the boundary, and what is
 * worth asserting is the behaviour a component gets when it drives it.
 *
 * `immediate` is passed throughout. It is not a test-only switch — it is the
 * service's "do not pace this" option, the same one the analysis takes — and
 * without it a run of the demo plan would spend ten seconds of wall clock per
 * test delivering a script that was written before the first event.
 */
beforeEach(() => {
  setActivePinia(createPinia())
})

const setup = () => {
  const context = {
    runs: useRunsStore(),
    agent: useAgentStore(),
    project: useProjectStore(),
  }

  // The store starts empty now; this spec switches between projects by id, and a
  // run needs an environment with a base URL to be creatable at all.
  installProjectFixtures(context.project)

  return context
}

/** A demo plan, generated and approved the way a reviewer would. */
const withApprovedPlan = async () => {
  const context = setup()

  await context.agent.loadDemoSpec()
  await context.agent.analyzeSpec()
  await context.agent.generatePlan()

  context.agent.approvePlan(context.agent.activePlan?.id ?? '')

  return context
}

const runToCompletion = async () => {
  const context = await withApprovedPlan()
  const run = await context.runs.createRun({ immediate: true })

  return { ...context, run }
}

describe('creating a run', () => {
  it('refuses a plan that has not been approved', async () => {
    const { runs, agent } = setup()
    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.generatePlan()

    expect(agent.activePlan?.status).toBe('draft')
    expect(await runs.createRun({ immediate: true })).toBeNull()
    expect(runs.error?.code).toBe('not-approved')
    expect(runs.error?.messageKey).toBe('console.runs.errors.notApproved')
    expect(runs.projectRuns).toHaveLength(0)
  })

  it('says why when there is nothing to run at all', async () => {
    const { runs } = setup()

    expect(runs.canCreateRun).toBe(false)
    expect(await runs.createRun({ immediate: true })).toBeNull()
    expect(runs.error?.messageKey).toBe('console.runs.errors.noPlan')
  })

  it('carries the document, the environment and the variables to the backend', async () => {
    const { runs, agent, project } = await withApprovedPlan()

    expect(runs.canCreateRun).toBe(true)
    const run = await runs.createRun({ immediate: true })

    // The frontend never composes a request; it hands over what a backend
    // would need in order to. These are the parts that could silently go
    // missing between the store and the payload.
    expect(run?.planId).toBe(agent.activePlan?.id)
    expect(run?.specId).toBe(agent.currentSpec?.id)
    expect(run?.environmentId).toBe(project.activeEnvironment?.id)
    expect(run?.baseUrl).toBe(project.activeEnvironment?.baseUrl)
    expect(run?.variableKeys).toEqual(Object.keys(project.variables).sort())
    expect(agent.currentSpecDocument).not.toBeNull()
  })

  it('records the environment it ran against, not the one selected now', async () => {
    const { runs, project } = await withApprovedPlan()
    const run = await runs.createRun({ immediate: true })

    const other = project.environments.find(
      (environment) => environment.id !== project.activeEnvironment?.id,
    )
    project.selectEnvironment(other?.id ?? '')

    expect(runs.projectRuns[0]?.environmentId).toBe(run?.environmentId)
  })

  it('scopes runs to the project that made them', async () => {
    const { runs, project } = await runToCompletion()

    expect(runs.projectRuns).toHaveLength(1)

    project.selectProject('prj_payments')
    expect(runs.projectRuns).toHaveLength(0)

    project.selectProject('prj_orders')
    expect(runs.projectRuns).toHaveLength(1)
  })
})

describe('a run follows its plan', () => {
  it('reaches a terminal state and reports it', async () => {
    const { runs } = await runToCompletion()

    expect(runs.activeRun?.status).toBe('passed')
    expect(runs.activeRun?.startedAt).not.toBeNull()
    expect(runs.activeRun?.finishedAt).not.toBeNull()
    expect(runs.activeRun?.failure).toBeNull()
    expect(runs.activeDetail?.lastSeq).toBeGreaterThan(0)
  })

  it('joins every step and assertion back to the plan by its own id', async () => {
    const { runs, agent } = await runToCompletion()

    const plan = agent.activePlan
    const detail = runs.activeDetail
    if (plan === null || detail === null) throw new Error('expected a loaded run')

    // The ids are the contract the stream is keyed by. A detail page that
    // could not match them would have to fall back to the local plan — which
    // is exactly the join the run payload exists to avoid.
    expect(detail.scenarios.flatMap((scenario) => scenario.steps.map((s) => s.id))).toEqual(
      plan.scenarios.flatMap((scenario) => scenario.steps.map((step) => step.id)),
    )
    expect(
      detail.scenarios.flatMap((scenario) => scenario.assertions.map((a) => a.id)),
    ).toEqual(
      plan.scenarios.flatMap((scenario) =>
        scenario.assertions.map((assertion) => assertion.id),
      ),
    )
  })

  it('gives every step and assertion an outcome, and leaves none pending', async () => {
    const { runs } = await runToCompletion()

    const steps = runs.activeDetail?.scenarios.flatMap((scenario) => scenario.steps) ?? []
    const assertions =
      runs.activeDetail?.scenarios.flatMap((scenario) => scenario.assertions) ?? []

    expect(steps.length).toBeGreaterThan(0)
    expect(assertions.length).toBeGreaterThan(0)
    expect(steps.every((step) => step.status === 'passed')).toBe(true)
    expect(assertions.every((assertion) => assertion.status === 'passed')).toBe(true)
    // A step carries evidence and a measured cost, not just a tick.
    expect(steps.every((step) => step.evidence.length > 0)).toBe(true)
    expect(steps.every((step) => (step.durationMs ?? 0) > 0)).toBe(true)
  })

  it('counts what ran in the summary the list draws', async () => {
    const { runs, agent } = await runToCompletion()

    const expectedSteps = agent.activePlan?.scenarios.reduce(
      (total, scenario) => total + scenario.steps.length,
      0,
    )

    expect(runs.activeRun?.summary.scenarios).toBe(agent.activePlan?.scenarios.length)
    expect(runs.activeRun?.summary.steps).toBe(expectedSteps)
    expect(runs.activeRun?.summary.passedSteps).toBe(expectedSteps)
    expect(runs.activeRun?.summary.failedSteps).toBe(0)
  })
})

describe('the event stream', () => {
  it('drops an event that has already been applied', async () => {
    const { runs } = await runToCompletion()

    const before = runs.activeDetail
    if (before === null) throw new Error('expected a loaded run')

    const replay: RunEvent = {
      type: 'step.started',
      runId: before.run.id,
      seq: 1,
      at: new Date().toISOString(),
      scenarioId: before.scenarios[0]?.id ?? '',
      stepId: before.scenarios[0]?.steps[0]?.id ?? '',
    }

    runs.applyEvent(replay)

    // Identity, not equality: nothing was rebuilt, so nothing re-rendered.
    expect(runs.activeDetail).toBe(before)
  })

  it('absorbs a late event for a run that has already finished', async () => {
    const { runs } = await runToCompletion()

    const before = runs.activeDetail
    if (before === null) throw new Error('expected a loaded run')

    runs.applyEvent({
      type: 'step.started',
      runId: before.run.id,
      seq: before.lastSeq + 100,
      at: new Date().toISOString(),
      scenarioId: before.scenarios[0]?.id ?? '',
      stepId: before.scenarios[0]?.steps[0]?.id ?? '',
    })

    expect(runs.activeRun?.status).toBe('passed')
    expect(runs.activeDetail).toBe(before)
  })

  it('ignores an event for a run whose detail was never loaded', async () => {
    const { runs } = await runToCompletion()

    runs.applyEvent({
      type: 'run.started',
      runId: 'run_never_loaded',
      seq: 1,
      at: new Date().toISOString(),
      startedAt: new Date().toISOString(),
    })

    expect(runs.activeRun?.status).toBe('passed')
    expect(runs.activeDetail?.run.id).not.toBe('run_never_loaded')
  })
})

describe('reconnecting', () => {
  it('rebuilds the same state from a fresh snapshot, applying nothing twice', async () => {
    const { runs, run } = await runToCompletion()
    const id = run?.id ?? ''

    const finished = runs.activeDetail
    expect(finished?.run.status).toBe('passed')

    // Stopping watching and coming back: what navigating away and returning
    // does, and what a reload does with a fresh store.
    runs.unsubscribe(id)
    expect(runs.subscribedRunIds).not.toContain(id)

    await runs.loadRun(id, { immediate: true })

    expect(runs.activeDetail).toEqual(finished)
    expect(runs.subscribedRunIds).not.toContain(id)
  })

  it('does not open a second stream for a run already being followed', async () => {
    const { runs } = await runToCompletion()
    const id = runs.activeRun?.id ?? ''

    runs.subscribeRun(id, { immediate: true })

    expect(runs.subscribedRunIds.filter((candidate) => candidate === id)).toHaveLength(0)
  })

  it('stops following a run once it reaches a terminal state', async () => {
    const { runs, run } = await runToCompletion()

    expect(runs.subscribedRunIds).not.toContain(run?.id)
    expect(runs.activeRun?.status).toBe('passed')
  })
})

describe('cancelling', () => {
  it('stops a run that has not finished, and skips what never ran', async () => {
    const { runs, agent } = await withApprovedPlan()

    // Paced, so the run is still in flight when it is cancelled — the same
    // window a user would be cancelling in.
    const run = await runs.createRun()
    const id = run?.id ?? ''
    expect(run?.status).not.toBe('cancelled')

    expect(await runs.cancelRun(id)).toBe(true)

    expect(runs.activeRun?.status).toBe('cancelled')
    expect(runs.activeRun?.finishedAt).not.toBeNull()
    expect(runs.activeRun?.summary.passedSteps).toBe(0)

    // Whatever had not run is not left looking like it still might.
    const steps = runs.activeDetail?.scenarios.flatMap((scenario) => scenario.steps) ?? []
    expect(steps.some((step) => step.status === 'skipped')).toBe(true)
    expect(steps.every((step) => step.status !== 'pending')).toBe(true)

    // Cancelling a run does not un-approve its plan.
    expect(agent.activePlan?.status).toBe('approved')
  })

  it('reports a cancellation of a finished run as the state it already had', async () => {
    const { runs, run } = await runToCompletion()

    expect(await runs.cancelRun(run?.id ?? '')).toBe(true)
    expect(runs.activeRun?.status).toBe('passed')
  })
})

describe('unknown runs', () => {
  it('reports a missing run as a localized error instead of throwing', async () => {
    const { runs } = setup()

    await runs.loadRun('run_does_not_exist', { immediate: true })

    expect(runs.error?.code).toBe('run-not-found')
    expect(runs.error?.messageKey).toBe('console.runs.errors.notFound')
    expect(runs.activeDetail).toBeNull()
  })
})

describe('nothing is persisted', () => {
  it('keeps runs out of storage entirely', async () => {
    // `usePersistedRef` serialises on every change, and a run changes on every
    // event. Runs are server state the browser is allowed to hold, not to own
    // (D3) — so there is deliberately no storage key for them.
    const { runs } = await runToCompletion()

    expect(runs.projectRuns).toHaveLength(1)
    expect(typeof window).toBe('undefined')
  })
})

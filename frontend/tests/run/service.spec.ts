import { beforeAll, describe, expect, it } from 'vitest'

import { createMockAgentService } from '@/services/mock/agent'
import { createRunService, isRunServiceError } from '@/services/run'
import type { CreateRunInput } from '@/services/run'
import type { TestPlan } from '@/types/agent'
import type { RunEvent, RunStatus } from '@/types/run'
import { RUN_EVENT_NAMES } from '@/types/run'

/**
 * The run service contract.
 *
 * These are properties of the boundary rather than of the mock that currently
 * implements it — a real backend has to satisfy every one of them, and the
 * store is written against them. The two that carry the most weight:
 *
 * - **`seq` is monotonic and dense.** A gap would be invisible to a client
 *   that only drops events at or below its high-water mark, and would show up
 *   as a step that never finished.
 * - **The snapshot equals a full replay.** Reconnecting is only correct if
 *   "load, then follow" lands in the same place as "follow from the start".
 */
const agent = createMockAgentService()
const PROJECT = 'prj_orders'

let plan: TestPlan

beforeAll(async () => {
  const { parsed } = await agent.loadDemoSpec(PROJECT)
  const understanding = await agent.analyze(parsed, { immediate: true })
  plan = await agent.generatePlan(understanding, parsed.spec, 'generated')
  approved = { ...plan, status: 'approved' }
})

/** A creation payload around whichever plan the test needs. */
const payloadFor = (candidate: TestPlan): CreateRunInput => ({
  projectId: PROJECT,
  planId: candidate.id,
  plan: candidate,
  specId: 'spec_demo',
  specDocument: '{"openapi":"3.0.3"}',
  environmentId: 'env_prj_orders_dev',
  variables: { baseUrl: 'https://api.dev.example.com', apiKey: 'secret' },
  baseUrl: 'https://api.dev.example.com',
})

let approved: TestPlan

/**
 * Collects the full stream for a run, without pacing.
 *
 * Takes the service that owns the run: a run lives in the service that created
 * it, so a fresh instance would report nothing and every assertion built on
 * this would pass vacuously.
 */
const streamOf = (
  runs: ReturnType<typeof createRunService>,
  runId: string,
): readonly RunEvent[] => {
  const events: RunEvent[] = []

  runs.subscribe({
    runId,
    immediate: true,
    onEvent: (event) => events.push(event),
  })

  // `subscribe` delivers synchronously when it is not paced, so by the time
  // it returns, the stream is complete.
  return events
}

describe('creation is gated on approval', () => {
  it('refuses a draft, and says which rule refused it', async () => {
    const runs = createRunService()

    let caught: unknown
    try {
      await runs.createRun(payloadFor(plan))
    } catch (thrown) {
      caught = thrown
    }

    expect(isRunServiceError(caught)).toBe(true)
    expect((caught as { detail: { code: string } }).detail.code).toBe('not-approved')
  })

  it('creates a run that starts out queued, with the plan drawn and nothing run', async () => {
    const runs = createRunService()
    // Paced, so it is still queued when it is read back — the moment between
    // "created" and "started" that a detail page can be opened in.
    const run = await runs.createRun(payloadFor(approved))

    expect(run.status).toBe('queued')
    expect(run.startedAt).toBeNull()
    expect(run.finishedAt).toBeNull()

    const detail = await runs.getRunDetail(run.id)
    const steps = detail.scenarios.flatMap((scenario) => scenario.steps)

    expect(detail.scenarios).toHaveLength(approved.scenarios.length)
    expect(steps).toHaveLength(
      approved.scenarios.reduce((total, scenario) => total + scenario.steps.length, 0),
    )
    expect(steps.every((step) => step.status === 'pending')).toBe(true)

    await runs.cancelRun(run.id)
  })

  it('records the environment, the base url and the variable names, but not their values', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })

    expect(run.environmentId).toBe('env_prj_orders_dev')
    expect(run.baseUrl).toBe('https://api.dev.example.com')
    expect(run.variableKeys).toEqual(['apiKey', 'baseUrl'])
    // A run history is not the place to accumulate copies of a secret.
    expect(JSON.stringify(run)).not.toContain('secret')
  })
})

describe('the event stream', () => {
  it('carries exactly the eight declared names', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const events = streamOf(runs, run.id)

    expect(events.length).toBeGreaterThan(0)
    for (const event of events) {
      expect(RUN_EVENT_NAMES).toContain(event.type)
      expect(event.runId).toBe(run.id)
    }

    expect(events[0]?.type).toBe('run.started')
    expect(events.at(-1)?.type).toBe('run.completed')
  })

  it('numbers events densely from one, so nothing can go missing unnoticed', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const events = streamOf(runs, run.id)

    expect(events.map((event) => event.seq)).toEqual(
      events.map((_event, index) => index + 1),
    )
  })

  it('opens and closes every step it reports', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const events = streamOf(runs, run.id)

    const started = events
      .filter((event) => event.type === 'step.started')
      .map((event) => event.stepId)

    const finished = events
      .filter((event) => event.type === 'step.completed' || event.type === 'step.failed')
      .map((event) => event.stepId)

    expect(started.length).toBeGreaterThan(0)
    expect(finished).toEqual(started)
  })

  it('reports an assertion against the plan’s own assertion id', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const detail = await runs.getRunDetail(run.id)
    const planAssertions = new Set(
      approved.scenarios.flatMap((scenario) =>
        scenario.assertions.map((assertion) => assertion.id),
      ),
    )

    const reported = detail.scenarios.flatMap((scenario) =>
      scenario.assertions.filter((assertion) => assertion.actual !== null),
    )

    expect(reported.length).toBeGreaterThan(0)
    for (const assertion of reported) {
      expect(planAssertions.has(assertion.id)).toBe(true)
    }
  })

  it('honours fromSeq, so a reconnect is not a re-delivery', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const detail = await runs.getRunDetail(run.id)

    const tail = await new Promise<readonly RunEvent[]>((resolve) => {
      const events: RunEvent[] = []
      runs.subscribe({
        runId: run.id,
        immediate: true,
        fromSeq: detail.lastSeq,
        onEvent: (event) => events.push(event),
      })
      resolve(events)
    })

    expect(tail).toEqual([])
  })

  it('delivers no timers when it is asked not to pace', async () => {
    const runs = createRunService()
    const started = Date.now()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    streamOf(runs, run.id)

    // The whole script, with no waiting. A paced run of this plan takes
    // seconds; anything close to that here means a timer crept back in.
    expect(Date.now() - started).toBeLessThan(500)
  })
})

describe('the snapshot and the stream agree', () => {
  it('lands on the same state whether a client watched or rejoined', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })

    streamOf(runs, run.id)

    const after = await runs.getRunDetail(run.id)

    // Folding the script has to produce the same state the stream described,
    // or "reload and resume" would show something a live client never saw.
    expect(after.run.status).toBe('passed')
    expect(after.lastSeq).toBeGreaterThan(0)
    expect(after.scenarios.flatMap((scenario) => scenario.steps).every(
      (step) => step.status === 'passed',
    )).toBe(true)
  })

  it('folds to the same lastSeq as the final event it emitted', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const events = streamOf(runs, run.id)
    const detail = await runs.getRunDetail(run.id)

    expect(detail.lastSeq).toBe(events.at(-1)?.seq)
  })
})

describe('a plan that cannot run', () => {
  /**
   * A request step naming no endpoint.
   *
   * The one thing the mock refuses to pretend about: there is no call it could
   * have made, so reporting a pass would be a lie about a plan rather than a
   * lie about a network. It is also the failure path a real backend reports
   * and the UI has to draw.
   */
  const brokenPlan = (): TestPlan => ({
    ...approved,
    scenarios: approved.scenarios.map((scenario, index) =>
      index !== 0
        ? scenario
        : {
            ...scenario,
            steps: scenario.steps.map((step, position) =>
              position !== 0
                ? step
                : {
                    ...step,
                    kind: 'request' as const,
                    endpointId: null,
                    method: null,
                    path: null,
                  },
            ),
          },
    ),
  })

  it('fails the run, names the step and leaves the rest skipped', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(brokenPlan()), { immediate: true })
    streamOf(runs, run.id)

    const detail = await runs.getRunDetail(run.id)
    const steps = detail.scenarios.flatMap((scenario) => scenario.steps)

    expect(detail.run.status).toBe('failed')
    expect(detail.run.failure?.message).toMatchObject({
      key: 'console.runs.failure.notExecutable',
    })
    expect(detail.run.failure?.detail).toBeTruthy()

    const failed = steps.filter((step) => step.status === 'failed')
    expect(failed).toHaveLength(1)
    expect(failed[0]?.failure?.message).toMatchObject({
      key: 'console.runs.failure.notExecutable',
    })

    // Never "still might": a finished run says so about every step it has.
    expect(steps.every((step) => step.status !== 'pending')).toBe(true)
    expect(steps.every((step) => step.status !== 'running')).toBe(true)
  })
})

describe('cancellation', () => {
  it('ends the run where it was, and reports nothing it never did', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved))

    const cancelled = await runs.cancelRun(run.id)

    expect(cancelled.status).toBe('cancelled')
    expect(cancelled.finishedAt).not.toBeNull()

    const detail = await runs.getRunDetail(run.id)
    const steps = detail.scenarios.flatMap((scenario) => scenario.steps)

    expect(steps.every((step) => step.status !== 'pending')).toBe(true)
    expect(steps.every((step) => step.status !== 'running')).toBe(true)
    // Nothing was reported as done, because nothing was done.
    expect(detail.run.summary.passedSteps).toBe(0)
  })

  it('does not restate a finished run', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    streamOf(runs, run.id)

    const again = await runs.cancelRun(run.id)

    expect(again.status).toBe('passed')
  })
})

describe('unknown runs', () => {
  it('reports a run it does not have', async () => {
    const runs = createRunService()

    let caught: unknown
    try {
      await runs.getRunDetail('run_nope')
    } catch (thrown) {
      caught = thrown
    }

    expect(isRunServiceError(caught)).toBe(true)
    expect((caught as { detail: { code: string } }).detail.code).toBe('run-not-found')
  })

  it('reports it to a subscriber rather than throwing at it', async () => {
    const runs = createRunService()

    const failure = await new Promise<{ code: string } | null>((resolve) => {
      runs.subscribe({
        runId: 'run_nope',
        onEvent: () => undefined,
        onError: (error) => resolve(error),
      })
      resolve(null)
    })

    expect(failure?.code).toBe('run-not-found')
  })
})

describe('determinism', () => {
  it('writes the same script for the same plan', async () => {
    const runs = createRunService()
    const first = await runs.createRun(payloadFor(approved), { immediate: true })
    const second = await runs.createRun(payloadFor(approved), { immediate: true })

    const firstEvents = streamOf(runs, first.id)
    const secondEvents = streamOf(runs, second.id)

    // Every timestamp is nulled: two runs are the same script, not the same
    // instant, and a test that demanded identical clock readings would be
    // asserting something the service never promised.
    const shape = (events: readonly RunEvent[]): string =>
      JSON.stringify(
        events.map((event) => {
          const copy: Record<string, unknown> = { ...event, runId: null, at: null }
          if ('startedAt' in copy) copy.startedAt = null
          if ('finishedAt' in copy) copy.finishedAt = null
          return copy
        }),
      )

    expect(shape(secondEvents)).toBe(shape(firstEvents))
  })

  it('reports the status the events say it should', async () => {
    const runs = createRunService()
    const run = await runs.createRun(payloadFor(approved), { immediate: true })
    const events = streamOf(runs, run.id)

    const terminal: Readonly<Record<string, RunStatus>> = {
      'run.completed': 'passed',
      'run.failed': 'failed',
      'run.cancelled': 'cancelled',
    }

    const last = events.at(-1)
    expect(last).toBeDefined()
    expect((await runs.getRun(last?.runId ?? '')).status).toBe(
      terminal[last?.type ?? ''] ?? 'running',
    )
  })
})

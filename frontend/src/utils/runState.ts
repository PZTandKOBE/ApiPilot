/**
 * The projection from a run's event stream onto its state.
 *
 * One reducer, used by both sides. The service uses it to answer "what does
 * this run look like right now"; the store uses it to answer "what does this
 * run look like given the snapshot I loaded and the events I have since
 * applied". Those two answers have to agree — the whole refresh story is
 * *snapshot, then tail* — and the only way to guarantee that is for there to be
 * one implementation rather than two that are supposed to match.
 *
 * Two rules make the fold safe to run against a stream that can misbehave:
 *
 * - **`seq` is the only ordering.** An event at or below the high-water mark
 *   is already in the state and is dropped. A re-delivered event and a
 *   duplicated one are the same case, and neither needs diffing.
 * - **A finished run stays finished.** Once the status is terminal the stream
 *   has been told everything it will ever be told, so anything arriving after
 *   it is ignored. Without this, a late `step.started` from a slow reconnect
 *   would reopen a run the user has already read the result of.
 *
 * Nothing here is stored. A run is server state that the browser is allowed to
 * hold while it is on screen — not something it owns (D3).
 */

import type {
  RunAssertion,
  RunDetail,
  RunEvent,
  RunScenario,
  RunStep,
  RunStepStatus,
  RunSummary,
} from '@/types/run'
import { isTerminalRunStatus } from '@/types/run'

/* ------------------------------------------------------------------ *
 * Summary
 * ------------------------------------------------------------------ */

/**
 * Counts, recomputed from the scenarios rather than tracked alongside them.
 *
 * A running total would be one more thing an out-of-order or missed event
 * could put out of step with the list it describes.
 */
export const summariseScenarios = (
  scenarios: readonly RunScenario[],
): RunSummary => {
  const steps = scenarios.flatMap((scenario) => scenario.steps)
  const assertions = scenarios.flatMap((scenario) => scenario.assertions)

  return {
    scenarios: scenarios.length,
    steps: steps.length,
    assertions: assertions.length,
    passedSteps: steps.filter((step) => step.status === 'passed').length,
    failedSteps: steps.filter((step) => step.status === 'failed').length,
    passedAssertions: assertions.filter((assertion) => assertion.status === 'passed')
      .length,
    failedAssertions: assertions.filter((assertion) => assertion.status === 'failed')
      .length,
  }
}

const withSummary = (detail: RunDetail): RunDetail => ({
  ...detail,
  run: { ...detail.run, summary: summariseScenarios(detail.scenarios) },
  lastSeq: detail.lastSeq,
})

/* ------------------------------------------------------------------ *
 * Targeted updates
 * ------------------------------------------------------------------ */

const updateScenario = (
  scenarios: readonly RunScenario[],
  scenarioId: string,
  update: (scenario: RunScenario) => RunScenario,
): readonly RunScenario[] =>
  scenarios.map((scenario) =>
    scenario.id === scenarioId ? update(scenario) : scenario,
  )

const updateStep = (
  scenarios: readonly RunScenario[],
  scenarioId: string,
  stepId: string,
  update: (step: RunStep) => RunStep,
): readonly RunScenario[] =>
  updateScenario(scenarios, scenarioId, (scenario) => ({
    ...scenario,
    steps: scenario.steps.map((step) => (step.id === stepId ? update(step) : step)),
  }))

const updateAssertion = (
  scenarios: readonly RunScenario[],
  scenarioId: string,
  assertionId: string,
  update: (assertion: RunAssertion) => RunAssertion,
): readonly RunScenario[] =>
  updateScenario(scenarios, scenarioId, (scenario) => ({
    ...scenario,
    assertions: scenario.assertions.map((assertion) =>
      assertion.id === assertionId ? update(assertion) : assertion,
    ),
  }))

/**
 * Marks everything still pending or running as skipped.
 *
 * A run that ends — for any reason — ends for the steps that never got their
 * turn. Leaving them `pending` would render the same as a run still in
 * progress, and the difference between "not yet" and "never" is the whole
 * point of looking at a finished run.
 */
const settleRemaining = (scenarios: readonly RunScenario[]): readonly RunScenario[] =>
  scenarios.map((scenario) => {
    const steps: readonly RunStep[] = scenario.steps.map((step) =>
      step.status === 'pending' || step.status === 'running'
        ? { ...step, status: 'skipped' as const }
        : step,
    )

    const assertions: readonly RunAssertion[] = scenario.assertions.map((assertion) =>
      assertion.status === 'passed' || assertion.status === 'failed'
        ? assertion
        : { ...assertion, status: 'skipped' as const },
    )

    const started = steps.some(
      (step) => step.status !== 'skipped' && step.status !== 'pending',
    )
    const status: RunStepStatus = started ? scenario.status : 'skipped'

    return { ...scenario, steps, assertions, status }
  })

/* ------------------------------------------------------------------ *
 * The fold
 * ------------------------------------------------------------------ */

/**
 * Applies one event. Returns the same object when the event changes nothing,
 * so a caller can skip a re-render by identity.
 */
export const applyRunEvent = (detail: RunDetail, event: RunEvent): RunDetail => {
  if (event.runId !== detail.run.id) return detail
  if (isTerminalRunStatus(detail.run.status)) return detail
  if (event.seq <= detail.lastSeq) return detail

  const next: RunDetail = { ...detail, lastSeq: event.seq }

  switch (event.type) {
    case 'run.started':
      return withSummary({
        ...next,
        run: { ...next.run, status: 'running', startedAt: event.startedAt },
      })

    case 'step.started':
      return withSummary({
        ...next,
        scenarios: updateScenario(
          updateStep(next.scenarios, event.scenarioId, event.stepId, (step) => ({
            ...step,
            status: 'running',
          })),
          event.scenarioId,
          (scenario) => ({ ...scenario, status: 'running' }),
        ),
      })

    case 'step.completed':
      return withSummary({
        ...next,
        scenarios: updateStep(
          next.scenarios,
          event.scenarioId,
          event.stepId,
          (step) => ({
            ...step,
            status: 'passed',
            durationMs: event.durationMs,
            evidence: event.evidence,
          }),
        ),
      })

    case 'step.failed':
      return withSummary({
        ...next,
        scenarios: updateStep(
          next.scenarios,
          event.scenarioId,
          event.stepId,
          (step) => ({
            ...step,
            status: 'failed',
            durationMs: event.durationMs,
            failure: event.failure,
          }),
        ),
      })

    case 'assertion.completed':
      return withSummary({
        ...next,
        scenarios: updateAssertion(
          next.scenarios,
          event.scenarioId,
          event.assertionId,
          (assertion) => ({
            ...assertion,
            status: event.status,
            expected: event.expected,
            actual: event.actual,
          }),
        ),
      })

    case 'run.completed':
      return withSummary({
        ...next,
        run: {
          ...next.run,
          status: 'passed',
          finishedAt: event.finishedAt,
          durationMs: event.durationMs,
        },
        scenarios: settleRemaining(next.scenarios),
      })

    case 'run.failed':
      return withSummary({
        ...next,
        run: {
          ...next.run,
          status: 'failed',
          finishedAt: event.finishedAt,
          durationMs: event.durationMs,
          failure: event.failure,
        },
        scenarios: settleRemaining(next.scenarios),
      })

    case 'run.cancelled':
      return withSummary({
        ...next,
        run: {
          ...next.run,
          status: 'cancelled',
          finishedAt: event.finishedAt,
          durationMs: event.durationMs,
        },
        scenarios: settleRemaining(next.scenarios),
      })

    default:
      // An event this build has never heard of. The server is allowed to grow
      // new ones -- the run event store writes whatever the execution engine
      // sends, and only the eight below have a meaning here -- so the safe
      // answer is the state that was already there. Returning nothing (which is
      // what a switch with no default does at runtime) would take the caller
      // down with it, and the caller is the page the user is looking at.
      return detail
  }
}

/** Folds a whole stream onto a state, for replay and for the service's own snapshots. */
export const applyRunEvents = (
  detail: RunDetail,
  events: readonly RunEvent[],
): RunDetail => events.reduce(applyRunEvent, detail)

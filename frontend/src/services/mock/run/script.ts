/**
 * Turning a plan into the run it would produce.
 *
 * This is the whole "execution engine" today, and it deliberately does not
 * execute anything: it reads the plan and writes down what a backend would
 * report having done with it. That is enough to build the entire interface —
 * the shapes, the ordering, the failure paths — without the frontend ever
 * holding a request it could send, which is the line D1 draws.
 *
 * There is no randomness and no clock-dependent branching. The same plan
 * produces the same events in the same order with the same durations, so a
 * result seen once can be reproduced, and a test can assert it.
 */

import type { CreateRunInput } from '@/services/run'
import type { TestAssertion, TestPlan, TestScenario, TestStep } from '@/types/agent'
import type {
  RunAssertion,
  RunDetail,
  RunEvent,
  RunFailure,
  RunScenario,
  RunStep,
  TestRun,
} from '@/types/run'

/**
 * How long the script claims a step took.
 *
 * Derived from the step's position rather than measured, because nothing was
 * measured. A number that looked random would invite reading meaning into it.
 */
const stepDurationMs = (index: number): number => 120 + index * 40

const at = (): string => new Date().toISOString()

/** The run as it exists before anything has happened to it. */
export const buildRun = (input: CreateRunInput, id: string): TestRun => ({
  id,
  projectId: input.projectId,
  planId: input.planId,
  // Copied, not referenced: regenerating a plan must not rewrite the name of a
  // run that already happened under the old one.
  planName: input.plan.name,
  specId: input.specId,
  environmentId: input.environmentId,
  baseUrl: input.baseUrl,
  // Names only. The values are the backend's business, and a run history is
  // the wrong place to accumulate copies of anything a secret might be in.
  variableKeys: Object.keys(input.variables).sort(),
  status: 'queued',
  createdAt: at(),
  startedAt: null,
  finishedAt: null,
  durationMs: null,
  failure: null,
  summary: {
    scenarios: input.plan.scenarios.length,
    steps: 0,
    assertions: 0,
    passedSteps: 0,
    failedSteps: 0,
    passedAssertions: 0,
    failedAssertions: 0,
  },
})

const runStepOf = (step: TestStep, scenario: TestScenario): RunStep => ({
  // The plan's own id, echoed back. This is the join the detail page relies
  // on, and the reason a run can be rendered without reading the local plan.
  id: step.id,
  scenarioId: scenario.id,
  index: step.index,
  kind: step.kind,
  description: step.description,
  endpointId: step.endpointId,
  method: step.method,
  path: step.path,
  status: 'pending',
  durationMs: null,
  failure: null,
  evidence: [],
})

const runAssertionOf = (
  assertion: TestAssertion,
  scenario: TestScenario,
  stepId: string | null,
): RunAssertion => ({
  id: assertion.id,
  scenarioId: scenario.id,
  stepId,
  kind: assertion.kind,
  target: assertion.target,
  expected: assertion.expected,
  actual: null,
  status: 'skipped',
  description: assertion.description,
})

/**
 * The checkpoint an assertion is reported against.
 *
 * A scenario's assertions concern the responses its steps produced, and the
 * `assert` step is where a plan puts that checkpoint — so it is the honest
 * attachment when one exists. It is only an attachment: the assertion's own id
 * is what the stream is keyed by, because a step id derived from a position
 * (`assert__3`) would change the moment the plan did.
 */
const checkpointOf = (scenario: TestScenario): string | null =>
  scenario.steps.find((step) => step.kind === 'assert')?.id ??
  scenario.steps[scenario.steps.length - 1]?.id ??
  null

/** The starting state: the whole plan, drawn, with nothing yet run. */
export const buildRunDetail = (input: CreateRunInput, id: string): RunDetail => ({
  run: buildRun(input, id),
  scenarios: input.plan.scenarios.map<RunScenario>((scenario) => ({
    id: scenario.id,
    index: scenario.index,
    name: scenario.name,
    riskLevel: scenario.riskLevel,
    status: 'pending',
    steps: scenario.steps.map((step) => runStepOf(step, scenario)),
    assertions: scenario.assertions.map((assertion) =>
      runAssertionOf(assertion, scenario, checkpointOf(scenario)),
    ),
  })),
  lastSeq: 0,
})

/* ------------------------------------------------------------------ *
 * The script
 * ------------------------------------------------------------------ */

/**
 * A request step with no endpoint is a plan defect, not a failure to connect.
 *
 * It is the one thing this mock refuses to pretend about: there is no call it
 * could have made, so reporting success would be a lie about a plan that
 * cannot run. Every other step is reported as passing, which is what a
 * correctly generated plan against a working API looks like.
 */
const NOT_EXECUTABLE: RunFailure = {
  message: { key: 'console.runs.failure.notExecutable' },
  detail: 'the step names no endpoint',
}

/**
 * `Omit` over a union collapses it to the keys every member shares, which
 * would erase every payload this script exists to write. This keeps each
 * member intact so `emit` can only be called with a complete event.
 */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never
type EventDraft = DistributiveOmit<RunEvent, 'runId' | 'seq' | 'at'>

interface ScriptContext {
  readonly events: RunEvent[]
  next: number
}

const emit = (context: ScriptContext, runId: string, draft: EventDraft): void => {
  context.next += 1
  context.events.push({ ...draft, runId, seq: context.next, at: at() })
}

/** What the step left behind: the call it made, or the value it pulled out. */
const evidenceOf = (step: TestStep, scenario: TestScenario): RunStep['evidence'] => {
  if (step.method !== null && step.path !== null) {
    return [
      {
        label: { key: 'console.runs.evidence.endpoint' },
        value: `${step.method} ${step.path}`,
      },
    ]
  }

  if (step.produces !== null) {
    return [
      { label: { key: 'console.runs.evidence.extracted' }, value: step.produces },
    ]
  }

  return [
    {
      label: { key: 'console.runs.evidence.checked' },
      value: String(scenario.assertions.length),
    },
  ]
}

/** A plausible observed value for an assertion that is being reported as met. */
const observedOf = (assertion: TestAssertion): string => {
  switch (assertion.kind) {
    case 'status':
      return assertion.expected
    case 'header':
      return 'present'
    case 'field':
      return 'present'
    default:
      return 'matches'
  }
}

/**
 * Writes the whole run down, in advance.
 *
 * A script rather than a simulation: the events exist before the first one is
 * delivered, so replaying them from any point gives the same state as having
 * watched from the beginning. That is the property the client's reconnect
 * logic depends on, and producing it any other way would make the mock an
 * easier thing to be wrong about than the backend it stands in for.
 */
export const buildRunEvents = (input: CreateRunInput, runId: string): readonly RunEvent[] => {
  const context: ScriptContext = { events: [], next: 0 }

  emit(context, runId, { type: 'run.started', startedAt: at() })

  let failure: { readonly scenarioId: string; readonly stepId: string; readonly failure: typeof NOT_EXECUTABLE } | null = null

  for (const scenario of input.plan.scenarios) {
    if (failure !== null) break

    for (const step of scenario.steps) {
      emit(context, runId, {
        type: 'step.started',
        scenarioId: scenario.id,
        stepId: step.id,
      })

      const durationMs = stepDurationMs(step.index)

      if (step.kind === 'request' && step.endpointId === null) {
        emit(context, runId, {
          type: 'step.failed',
          scenarioId: scenario.id,
          stepId: step.id,
          durationMs,
          failure: { message: NOT_EXECUTABLE.message, detail: NOT_EXECUTABLE.detail },
        })

        failure = { scenarioId: scenario.id, stepId: step.id, failure: NOT_EXECUTABLE }
        break
      }

      emit(context, runId, {
        type: 'step.completed',
        scenarioId: scenario.id,
        stepId: step.id,
        durationMs,
        evidence: evidenceOf(step, scenario),
      })
    }

    if (failure !== null) break

    const checkpoint = checkpointOf(scenario)

    for (const assertion of scenario.assertions) {
      emit(context, runId, {
        type: 'assertion.completed',
        scenarioId: scenario.id,
        stepId: checkpoint ?? assertion.id,
        assertionStepId: checkpoint,
        assertionId: assertion.id,
        status: 'passed',
        expected: assertion.expected,
        actual: observedOf(assertion),
      })
    }
  }

  const total = input.plan.scenarios
    .flatMap((scenario) => scenario.steps)
    .reduce((sum, step) => sum + stepDurationMs(step.index), 0)

  if (failure !== null) {
    emit(context, runId, {
      type: 'run.failed',
      finishedAt: at(),
      durationMs: total,
      failedStepId: failure.stepId,
      failure: { message: failure.failure.message, detail: failure.failure.detail },
    })
  } else {
    emit(context, runId, { type: 'run.completed', finishedAt: at(), durationMs: total })
  }

  return context.events
}

/** The plan a run was created from, for the id the mock derives. */
export const runIdFrom = (plan: TestPlan, ordinal: number): string =>
  `run_${plan.id.replace(/^plan_/, '')}__${String(ordinal)}`

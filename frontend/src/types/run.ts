/**
 * Run domain model.
 *
 * A run is what happened when a plan met a real API. Three rules shape this
 * file, and all three exist to keep the frontend out of the execution path:
 *
 * 1. **The frontend is not an executor.** There is no field here for headers,
 *    a body, an auth scheme or a timeout, and no function that composes a
 *    request. The backend receives the plan, the document and the variables,
 *    builds the calls itself, judges the assertions and reports what it saw.
 *    `TestStep` is untouched by this file — a `RunStep` is the *record* of a
 *    step having run, not a step with execution fields bolted on.
 *
 * 2. **The server is the source of truth.** A run's state is whatever the
 *    server last said it was. Nothing here is reconstructed from local data:
 *    a plan can be regenerated under the same id while a run is in flight, so
 *    a detail page that joined against the local plan would render steps that
 *    no longer exist. `RunDetail` carries everything a page needs to draw a
 *    run, including the steps and assertions themselves.
 *
 * 3. **Events are ordered, and the order is the server's.** Every event
 *    carries a monotonic `seq`. A subscriber drops anything at or below the
 *    last `seq` it applied, which is what makes reconnecting safe: the
 *    snapshot plus the tail of the stream reconstructs the same state as
 *    having been connected throughout.
 */

import type { HttpMethod } from './api'
import type {
  AgentEvidence,
  AssertionKind,
  LocalizedText,
  RiskLevel,
  TestStepKind,
} from './agent'

/* ------------------------------------------------------------------ *
 * Status
 * ------------------------------------------------------------------ */

/**
 * Where a run is, as a whole.
 *
 * `queued` and `running` are the only non-final states; the other three are
 * terminal, and a terminal run never changes again. That is a promise the
 * store relies on: a late event arriving for a finished run is dropped rather
 * than applied, so a reconnecting client cannot resurrect one.
 */
export const RUN_STATUSES = [
  'queued',
  'running',
  'passed',
  'failed',
  'cancelled',
] as const
export type RunStatus = (typeof RUN_STATUSES)[number]

const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['passed', 'failed', 'cancelled']

export const isTerminalRunStatus = (status: RunStatus): boolean =>
  TERMINAL_RUN_STATUSES.includes(status)

export const isRunStatus = (value: unknown): value is RunStatus =>
  typeof value === 'string' && (RUN_STATUSES as readonly string[]).includes(value)

/** A step's own state within a run. `skipped` is what a failure leaves behind. */
export const RUN_STEP_STATUSES = [
  'pending',
  'running',
  'passed',
  'failed',
  'skipped',
] as const
export type RunStepStatus = (typeof RUN_STEP_STATUSES)[number]

export const RUN_ASSERTION_STATUSES = ['passed', 'failed', 'skipped'] as const
export type RunAssertionStatus = (typeof RUN_ASSERTION_STATUSES)[number]

/* ------------------------------------------------------------------ *
 * Records
 * ------------------------------------------------------------------ */

/**
 * Why something failed, in both languages.
 *
 * `detail` is the machine's own words — an exception message, a status line —
 * and is shown verbatim. `message` is the authored sentence that goes with it,
 * so a failure raised by the backend reads correctly in either locale without
 * the frontend having to interpret it.
 */
export interface RunFailure {
  readonly message: LocalizedText
  readonly detail: string | null
}

/** One assertion as it came out, not as it was written. */
export interface RunAssertion {
  /** The plan's `TestAssertion.id` — the join key, echoed back by the server. */
  readonly id: string
  readonly scenarioId: string
  /** The step this assertion was checked on, when it belongs to one. */
  readonly stepId: string | null
  readonly kind: AssertionKind
  /** Dotted path within the response, e.g. `body.token`. */
  readonly target: string
  readonly expected: string
  /** What the response actually carried, when there was something to compare. */
  readonly actual: string | null
  readonly status: RunAssertionStatus
  readonly description: LocalizedText
}

/** One step as it came out. */
export interface RunStep {
  /** The plan's `TestStep.id` — the join key, echoed back by the server. */
  readonly id: string
  readonly scenarioId: string
  readonly index: number
  readonly kind: TestStepKind
  readonly description: LocalizedText
  readonly endpointId: string | null
  readonly method: HttpMethod | null
  readonly path: string | null
  readonly status: RunStepStatus
  readonly durationMs: number | null
  readonly failure: RunFailure | null
  /**
   * What the step left behind: a status code, a header, an extracted value.
   *
   * The same shape the analysis uses for its own findings, because it is the
   * same idea — a concrete artifact, not a restatement of the outcome.
   */
  readonly evidence: readonly AgentEvidence[]
}

/** A scenario as it came out, with its steps and assertions in run order. */
export interface RunScenario {
  /** The plan's `TestScenario.id`. */
  readonly id: string
  readonly index: number
  readonly name: LocalizedText
  readonly riskLevel: RiskLevel
  readonly status: RunStepStatus
  readonly steps: readonly RunStep[]
  readonly assertions: readonly RunAssertion[]
}

/** How much of the plan actually ran, and how much of it held. */
export interface RunSummary {
  readonly scenarios: number
  readonly steps: number
  readonly assertions: number
  readonly passedSteps: number
  readonly failedSteps: number
  readonly passedAssertions: number
  readonly failedAssertions: number
}

/**
 * A run's identity and outcome, without its steps.
 *
 * This is what the list needs and what a snapshot returns; the detail adds the
 * scenarios. Keeping them apart means the list never pays for a payload it
 * would not draw.
 */
export interface TestRun {
  readonly id: string
  readonly projectId: string
  readonly planId: string
  /** Copied at creation, so a renamed or regenerated plan does not rewrite history. */
  readonly planName: LocalizedText
  readonly specId: string
  /**
   * The environment the run was created against.
   *
   * Recorded rather than derived: reading it back from whatever environment is
   * selected now would relabel a Staging run as Production the moment the user
   * switches, with nothing on screen to say it changed.
   */
  readonly environmentId: string
  readonly baseUrl: string
  /**
   * Which variables the run was given, by name only.
   *
   * The values travel in the creation payload and are not echoed back here:
   * an environment can carry secrets, and a run history is not the place to
   * accumulate copies of them.
   */
  readonly variableKeys: readonly string[]
  readonly status: RunStatus
  readonly createdAt: string
  readonly startedAt: string | null
  readonly finishedAt: string | null
  readonly durationMs: number | null
  readonly failure: RunFailure | null
  readonly summary: RunSummary
}

/**
 * A run together with everything needed to draw it.
 *
 * `lastSeq` is the reconnect contract and the reason this type exists rather
 * than a bare pair. A snapshot is only useful alongside the point in the
 * stream it was taken at: the client sets its high-water mark from it and
 * subscribes from there, so the events it already has are not applied twice
 * and the ones it missed are not skipped.
 *
 * The scenarios are part of the payload for the same reason. Deriving them
 * from the local plan would be cheaper and wrong — a plan regenerated under
 * the same id would repaint a finished run with steps that never ran.
 */
export interface RunDetail {
  readonly run: TestRun
  readonly scenarios: readonly RunScenario[]
  readonly lastSeq: number
}

/* ------------------------------------------------------------------ *
 * Events
 * ------------------------------------------------------------------ */

/**
 * The eight events a run stream carries. Exactly these, no more.
 *
 * A closed set rather than an open one because each name is a decision the
 * frontend has to make about state — a `step.finished` that covered both
 * outcomes would leave the reader of this type unable to tell whether the run
 * is going well, and `assertion.completed` would have nowhere to live.
 *
 * `assertion.completed` is about the plan's *assertions* — the entries in
 * `TestScenario.assertions`, keyed by `TestAssertion.id`. A `kind: 'assert'`
 * step is a step, and it completes through `step.completed` like any other.
 * Reporting both would describe one fact twice, and the step id (`assert__3`)
 * is derived from a position — a weak thing to join a stream on.
 */
export const RUN_EVENT_NAMES = [
  'run.started',
  'step.started',
  'step.completed',
  'assertion.completed',
  'step.failed',
  'run.completed',
  'run.failed',
  'run.cancelled',
] as const
export type RunEventName = (typeof RUN_EVENT_NAMES)[number]

/**
 * Fields every event carries.
 *
 * `seq` is assigned by the producer and strictly increases across a run, so a
 * consumer can drop a re-delivered event with one comparison instead of
 * diffing payloads. `at` is when the *server* observed the event, not when the
 * browser received it: a run that took four seconds is not a run that took
 * four seconds plus a reconnect.
 */
export interface RunEventBase {
  readonly runId: string
  readonly seq: number
  readonly at: string
}

/** An event scoped to one step of one scenario. */
export interface RunStepEventBase extends RunEventBase {
  readonly scenarioId: string
  readonly stepId: string
}

export interface RunStartedEvent extends RunEventBase {
  readonly type: 'run.started'
  readonly startedAt: string
}

export interface StepStartedEvent extends RunStepEventBase {
  readonly type: 'step.started'
}

export interface StepCompletedEvent extends RunStepEventBase {
  readonly type: 'step.completed'
  readonly durationMs: number
  readonly evidence: readonly AgentEvidence[]
}

export interface AssertionCompletedEvent extends RunStepEventBase {
  readonly type: 'assertion.completed'
  /** The plan's `TestAssertion.id`. */
  readonly assertionId: string
  readonly status: RunAssertionStatus
  readonly expected: string
  readonly actual: string | null
  /** Set when the assertion belongs to no particular step. */
  readonly assertionStepId: string | null
}

/**
 * A step that failed. The run does not stop here — later steps are reported as
 * skipped — but this is the event that carries the reason.
 */
export interface StepFailedEvent extends RunStepEventBase {
  readonly type: 'step.failed'
  readonly durationMs: number
  readonly failure: RunFailure
}

export interface RunCompletedEvent extends RunEventBase {
  readonly type: 'run.completed'
  readonly finishedAt: string
  readonly durationMs: number
}

export interface RunFailedEvent extends RunEventBase {
  readonly type: 'run.failed'
  readonly finishedAt: string
  readonly durationMs: number
  readonly failure: RunFailure
  /** The step the run died on, when it died on one. */
  readonly failedStepId: string | null
}

export interface RunCancelledEvent extends RunEventBase {
  readonly type: 'run.cancelled'
  readonly finishedAt: string
  readonly durationMs: number
}

/**
 * One event off the stream, discriminated on `type`.
 *
 * Discriminated rather than a name plus an optional bag, so a consumer cannot
 * read `failure` off a `run.completed` — the compiler refuses. The previous
 * placeholder in `types/agent.ts` had this wrong in four separate ways at
 * once and was never imported by anything.
 */
export type RunEvent =
  | RunStartedEvent
  | StepStartedEvent
  | StepCompletedEvent
  | AssertionCompletedEvent
  | StepFailedEvent
  | RunCompletedEvent
  | RunFailedEvent
  | RunCancelledEvent

const EVENT_NAMES: readonly string[] = RUN_EVENT_NAMES

export const isRunEvent = (value: unknown): value is RunEvent => {
  if (typeof value !== 'object' || value === null) return false

  const candidate = value as { type?: unknown; runId?: unknown; seq?: unknown }
  return (
    typeof candidate.type === 'string' &&
    EVENT_NAMES.includes(candidate.type) &&
    typeof candidate.runId === 'string' &&
    typeof candidate.seq === 'number'
  )
}

/** The event that ends a run, if this is one. */
export const isTerminalRunEvent = (event: RunEvent): boolean =>
  event.type === 'run.completed' ||
  event.type === 'run.failed' ||
  event.type === 'run.cancelled'

/** Where a terminal event leaves the run. */
export const runStatusOfTerminalEvent = (
  event: RunEvent,
): RunStatus | null => {
  switch (event.type) {
    case 'run.completed':
      return 'passed'
    case 'run.failed':
      return 'failed'
    case 'run.cancelled':
      return 'cancelled'
    default:
      return null
  }
}

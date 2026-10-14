/**
 * Run service boundary.
 *
 * The single place that decides whether runs are executed by a local script or
 * by a real backend. Nothing above this line — store or component — knows
 * which, which is what lets the FastAPI execution engine drop in later without
 * touching the UI.
 *
 *   now:   Browser → MockRunService  (scripted, deterministic)
 *   later: Browser → FastAPI → execution engine → the API under test
 *
 * The split it encodes is the one D5 settled on: REST for anything that has a
 * current answer (create, read, snapshot, cancel) and a stream for anything
 * that only exists as it happens. The stream is not an `EventSource` yet —
 * that is the next phase — but its shape is final, because the store is
 * written against it rather than against a promise that resolves an array.
 */

import type { TestPlan } from '@/types/agent'
import type { RunDetail, RunEvent, TestRun } from '@/types/run'
import { createHttpRunService } from './api/run'
import { createMockRunService } from './mock/run'
import type { RunError } from './runError'

export type { RunError, RunErrorCode } from './runError'
export { RunServiceError, isRunServiceError } from './runError'

/**
 * Everything the backend needs to execute a plan.
 *
 * The two fields that look redundant are the two that matter most:
 *
 * - **`plan` travels whole.** The backend has never seen it: a plan is
 *   generated in the browser and lives in `localStorage`. An id alone would
 *   name something the server cannot look up.
 * - **`specDocument` travels as text.** `ApiSpec` holds metadata only — no
 *   schemas, no request bodies — and the derived endpoints that do carry them
 *   are deliberately not persisted. Request synthesis needs the document, not
 *   a summary of it.
 *
 * `environmentId` is recorded alongside `variables` rather than replacing it.
 * The values are what makes a run reproducible; the id is what makes it
 * *explainable* afterwards, when the environment they came from has moved on.
 *
 * **The backend must re-check `plan.status === 'approved'`.** Approval is
 * written to `localStorage` by the browser and is editable there. The approval
 * dialog is a UI boundary, not a security one, and "the client said it was
 * approved" is not a fact a server can act on.
 */
export interface CreateRunInput {
  readonly projectId: string
  readonly planId: string
  readonly plan: TestPlan
  readonly specId: string
  /** The OpenAPI document's original text, as stored. */
  readonly specDocument: string
  readonly environmentId: string
  readonly variables: Readonly<Record<string, string>>
  readonly baseUrl: string
}

export interface RunRequestOptions {
  /**
   * Skip simulated latency.
   *
   * Set by tests and by anything reconstructing state the user has already
   * watched happen — mirroring `AnalyzeOptions.immediate` in the agent
   * service, so the two seams are driven the same way.
   */
  readonly immediate?: boolean
}

/**
 * A subscription to a run's event stream.
 *
 * Cancellation is an `AbortSignal` rather than a returned handle, matching
 * `TransportSendInput`. It matters more here than there: a run outlives the
 * component that is looking at it, so whoever holds the signal holds the
 * subscription — and when that is the store rather than a component, closing
 * it on unmount stops being possible by accident.
 */
export interface SubscribeRunInput {
  readonly runId: string
  readonly onEvent: (event: RunEvent) => void
  readonly onError?: (error: RunError) => void
  /**
   * Resume point. Events at or below this `seq` are not re-delivered.
   *
   * Taken from the snapshot's `lastSeq`, which is what makes "load, then
   * subscribe" gap-free without the client having to buffer.
   *
   * **Advisory for the real service, which ignores it on purpose.** A browser's
   * `EventSource` reconnects by itself and reports where it got to as
   * `Last-Event-ID`; a `fromSeq` pinned into the URL would outrank that header
   * on every reconnect and replay the same prefix forever. The stream therefore
   * starts from the beginning the first time and resumes from the header after
   * that, and the store's `seq` rule drops the prefix it has already applied.
   * The mock keeps honouring it, because a script has no connection to resume.
   */
  readonly fromSeq?: number
  readonly immediate?: boolean
  readonly signal?: AbortSignal
}

export interface RunService {
  /**
   * Creates a run. It does not start one.
   *
   * Creation is a REST call with an answer; the execution it kicks off is a
   * stream. Keeping them apart is what lets a created run survive a reload
   * that happens before the first event arrives.
   */
  createRun(input: CreateRunInput, options?: RunRequestOptions): Promise<TestRun>

  /** Current state, for the list. */
  getRun(runId: string): Promise<TestRun>

  /**
   * Every run this project has, newest first.
   *
   * The list page is the one screen that cannot be served from anything the
   * browser already holds: after a reload there is nothing to draw until the
   * server is asked. The server orders it (`createdAt` descending, with the id
   * as a tiebreaker), so the client renders what it is given.
   */
  listRuns(projectId: string): Promise<readonly TestRun[]>

  /**
   * A run's persisted events, from `fromSeq` onwards, already adapted to
   * `RunEvent`.
   *
   * Not part of the detail page's flow: the stream replays the same events, and
   * a page that read both would apply each one twice. See the note on
   * `createHttpRunService`.
   */
  getRunEvents(runId: string, fromSeq?: number): Promise<readonly RunEvent[]>

  /**
   * Current state plus the scenarios, and the `seq` it was taken at.
   *
   * This is the refresh path: reload the page and the run is rebuilt from
   * here, not from anything the browser kept.
   */
  getRunDetail(runId: string): Promise<RunDetail>

  /**
   * Requests cancellation. Returns the run as it stands.
   *
   * No `immediate` here: cancelling is a user waiting on an answer, so it is
   * never the right call to pace it.
   */
  cancelRun(runId: string): Promise<TestRun>

  /**
   * Streams a run's events. Returns immediately; events arrive via callbacks
   * until the run reaches a terminal state or `signal` aborts.
   */
  subscribe(input: SubscribeRunInput): void
}

/** Which implementation the console gets. */
const RUN_SERVICE_HTTP = 'http'
const RUN_SERVICE_MOCK = 'mock'

/**
 * The run service the console talks to.
 *
 * The real one, unless something says otherwise. `VITE_RUN_SERVICE=mock` picks
 * the scripted service explicitly; the test suite gets it by default, because
 * those specs are written against the mock on purpose -- they drive a run
 * through a known script and assert what a component sees -- and a spec that
 * wants the real transport asks for it by name.
 *
 * There is no provider registry here and there is not meant to be one: two
 * implementations, one switch, and the switch is the same three lines the agent
 * service will need when its turn comes.
 */
const runServiceMode = (): string => {
  const configured: unknown = import.meta.env.VITE_RUN_SERVICE

  if (configured === RUN_SERVICE_MOCK || configured === RUN_SERVICE_HTTP) {
    return configured
  }

  return import.meta.env.MODE === 'test' ? RUN_SERVICE_MOCK : RUN_SERVICE_HTTP
}

/**
 * The run service the console talks to today: the real backend.
 *
 * `POST /api/projects/{id}/runs`, `GET /api/projects/{id}/runs`,
 * `GET /api/runs/{id}`, `POST /api/runs/{id}/cancel`, `GET /api/runs/{id}/events`
 * and the Server-Sent Events stream at `GET /api/runs/{id}/events/stream`.
 * Nothing above this function changed to make that true, which is what the
 * boundary was for.
 */
export const createRunService = (): RunService =>
  runServiceMode() === RUN_SERVICE_MOCK ? createMockRunService() : createHttpRunService()

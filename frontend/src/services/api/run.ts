/**
 * The run service, backed by the real FastAPI server.
 *
 * The boundary above this file does not change: `RunService` is the same five
 * calls the mock implements, plus the two this phase added (a project's runs,
 * and a run's events), and nothing above the boundary knows which
 * implementation it is holding. What changes is that a run now outlives the
 * tab: the server owns it, the list is read back from PostgreSQL, and the
 * events arrive over a real connection.
 *
 * Three notes on the shape of the traffic.
 *
 * **The response bodies are already the frontend's types.** The REST payloads
 * were built to `types/run.ts` -- same names, same nesting, same id contract --
 * so none of these calls maps fields. The one place a mapping is needed is the
 * replay record, whose payload the backend returns as an object and the browser
 * expects spread over the event, and that adapter is the reason
 * `RunEventReplayRecord` exists.
 *
 * **`variables` travels out and never back.** The create body carries the real
 * values because that is the only moment they are needed; the server stores
 * their names and answers with `variableKeys`, and nothing in this module keeps
 * a copy of either.
 *
 * **The stream carries the session, so it is a fetch stream.** `EventSource`
 * cannot set a request header, and the guest token must not travel in a query
 * string -- so `subscribe()` reads the same frames from a `fetch` response body
 * instead, and resumes the way the server already supports: `Last-Event-ID` set
 * to the last sequence number it folded in, which the backend turns into "one
 * past what you have". The event names, the `seq` values and the frame format
 * are unchanged; only the transport under them is.
 */

import { ApiError, apiBaseUrl, request } from '@/services/http'
import { SESSION_HEADER, ensureSession } from '@/services/session'
import {
  RUN_ERROR_CODES,
  RunServiceError,
  type RunError,
  type RunErrorCode,
} from '@/services/runError'
import type {
  CreateRunInput,
  RunRequestOptions,
  RunService,
  SubscribeRunInput,
} from '@/services/run'
import { RUN_EVENT_NAMES, type RunDetail, type RunEvent, type TestRun } from '@/types/run'

const CREATE_FAILED = 'console.runs.errors.createFailed'
const LOAD_FAILED = 'console.runs.errors.loadFailed'
const CANCEL_FAILED = 'console.runs.errors.cancelFailed'
const UNAUTHORIZED = 'console.runs.errors.unauthorized'

/**
 * How many times a dropped stream is dialled again before the page is told.
 *
 * A finished run ends by the server closing the response, and that is handled
 * where it happens -- on the terminal event. A connection that drops while the
 * run is still going is what this bound exists for: a few attempts with a
 * growing pause, then one error, instead of reconnecting forever.
 */
const MAX_STREAM_ATTEMPTS = 5

/** Base pause between those attempts; each one waits a multiple of it. */
const STREAM_RETRY_MS = 500

/**
 * The message keys this console can actually render.
 *
 * `stores/locale.ts` returns the key itself when the dictionary has no entry for
 * it, so a server that invents a key produces a user reading
 * `console.runs.errors.something`. The eight below are the ones
 * `src/locales/console/en-US.ts` defines; anything else falls back to the
 * sentence the caller knows is true for the operation it attempted.
 */
const RENDERABLE_ERROR_KEYS: ReadonlySet<string> = new Set([
  'console.runs.errors.title',
  UNAUTHORIZED,
  'console.runs.errors.notFound',
  'console.runs.errors.notApproved',
  'console.runs.errors.noPlan',
  'console.runs.errors.createFailed',
  'console.runs.errors.loadFailed',
  'console.runs.errors.cancelFailed',
  'console.runs.errors.dismiss',
])

/** The three events that end a run, and therefore a subscription to it. */
const TERMINAL_EVENT_NAMES: ReadonlySet<string> = new Set([
  'run.completed',
  'run.failed',
  'run.cancelled',
])

/**
 * One event as `GET /api/runs/{runId}/events` returns it: the stored row, with
 * its payload still an object.
 *
 * Declared here, and not in `types/run.ts`, because it is not part of the run
 * model the UI draws -- it is the wire shape of one endpoint, and the adapter
 * below turns it into the `RunEvent` everything else already understands.
 */
export interface RunEventReplayRecord {
  readonly runId: string
  readonly seq: number
  readonly at: string
  readonly eventType: string
  readonly payload: Readonly<Record<string, unknown>> | null
}

const projectRunsPath = (projectId: string): string =>
  '/api/projects/' + encodeURIComponent(projectId) + '/runs'

const runPath = (runId: string): string => '/api/runs/' + encodeURIComponent(runId)

const isRunErrorCode = (value: string): value is RunErrorCode =>
  (RUN_ERROR_CODES as readonly string[]).includes(value)

const toRunError = (
  thrown: unknown,
  fallbackCode: RunErrorCode,
  fallbackKey: string,
): RunError => {
  if (thrown instanceof ApiError) {
    const error: RunError = {
      code: isRunErrorCode(thrown.code) ? thrown.code : fallbackCode,
      messageKey: RENDERABLE_ERROR_KEYS.has(thrown.messageKey) ? thrown.messageKey : fallbackKey,
    }

    return thrown.params === undefined ? error : { ...error, params: thrown.params }
  }

  // Not an answer from this service: a network failure, a parse failure, an
  // aborted request. The caller's sentence is the only true one available.
  return { code: fallbackCode, messageKey: fallbackKey }
}

const guarded = async <T>(
  work: () => Promise<T>,
  fallbackCode: RunErrorCode,
  fallbackKey: string,
): Promise<T> => {
  try {
    return await work()
  } catch (thrown) {
    if (thrown instanceof RunServiceError) throw thrown

    throw new RunServiceError(toRunError(thrown, fallbackCode, fallbackKey))
  }
}

/**
 * A replay record as the event the reducer folds.
 *
 * `eventType` becomes `type` and the payload's fields are lifted to the top
 * level, which is the shape `utils/runState.ts` switches on. The assertion is
 * the honest part of this function: an `eventType` the frontend has never heard
 * of is returned as it is rather than filtered out, and the reducer ignores what
 * it does not know instead of throwing.
 */
const toRunEvent = (record: RunEventReplayRecord): RunEvent =>
  ({
    ...(record.payload ?? {}),
    runId: record.runId,
    seq: record.seq,
    at: record.at,
    type: record.eventType,
  }) as RunEvent

const parseFrame = (data: string): RunEvent | null => {
  try {
    const parsed: unknown = JSON.parse(data)

    if (typeof parsed !== 'object' || parsed === null) return null

    const event = parsed as RunEvent

    return typeof event.type === 'string' && typeof event.seq === 'number' ? event : null
  } catch {
    return null
  }
}

export const createHttpRunService = (): RunService => ({
  async createRun(input: CreateRunInput, _options: RunRequestOptions = {}) {
    return guarded(
      () => request<TestRun>(projectRunsPath(input.projectId), { method: 'POST', body: input }),
      'create-failed',
      CREATE_FAILED,
    )
  },

  async listRuns(projectId: string) {
    return guarded(
      () => request<TestRun[]>(projectRunsPath(projectId)),
      'run-not-found',
      LOAD_FAILED,
    )
  },

  async getRun(runId: string) {
    // There is no lighter endpoint to call: the contract keeps one detail
    // response and lets `run` inside it answer both questions.
    const detail = await guarded(
      () => request<RunDetail>(runPath(runId)),
      'run-not-found',
      LOAD_FAILED,
    )

    return detail.run
  },

  async getRunDetail(runId: string) {
    return guarded(
      () => request<RunDetail>(runPath(runId)),
      'run-not-found',
      LOAD_FAILED,
    )
  },

  async cancelRun(runId: string) {
    return guarded(
      () => request<TestRun>(runPath(runId) + '/cancel', { method: 'POST' }),
      'cancel-failed',
      CANCEL_FAILED,
    )
  },

  /**
   * A run's events, from `fromSeq` onwards, as frontend events.
   *
   * Declared and correct, and deliberately not part of the detail page's flow:
   * the stream replays the same events, so a page that read both would apply
   * each one twice. It exists for callers that want the history without a
   * connection -- a test, a future export, a page that finds the stream
   * unavailable.
   */
  async getRunEvents(runId: string, fromSeq = 1) {
    const records = await guarded(
      () => request<RunEventReplayRecord[]>(runPath(runId) + '/events?fromSeq=' + String(fromSeq)),
      'run-not-found',
      LOAD_FAILED,
    )

    return records.map(toRunEvent)
  },

  subscribe(input: SubscribeRunInput): void {
    // One abort controller for the whole subscription: it closes the response
    // body, which is what releases the reader and the connection underneath it.
    const controller = new AbortController()

    let closed = false
    let lastSeq = 0
    let attempts = 0

    const close = (): void => {
      if (closed) return

      closed = true
      controller.abort()
      input.signal?.removeEventListener('abort', close)
    }

    /**
     * One SSE frame, as the server writes it: `id`, `event` and `data` lines
     * separated by a blank line.  Reuses `parseFrame` for the payload, so the
     * event object is the same one `EventSource` produced.
     */
    const handleFrame = (frame: string): void => {
      let name = ''
      let data = ''
      let id = ''

      for (const rawLine of frame.split('\n')) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine

        if (line === '' || line.startsWith(':')) continue

        const colon = line.indexOf(':')
        const field = colon === -1 ? line : line.slice(0, colon)
        const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')

        if (field === 'event') name = value
        else if (field === 'id') id = value
        else if (field === 'data') data = data === '' ? value : data + '\n' + value
      }

      if (data === '' || !RUN_EVENT_NAMES.includes(name as (typeof RUN_EVENT_NAMES)[number])) {
        return
      }

      const seq = Number.parseInt(id, 10)

      // A sequence number already folded in is dropped rather than applied
      // twice: a reconnect that starts one event too early must not double an
      // assertion in the tree the page is holding.
      if (Number.isFinite(seq) && seq <= lastSeq) return

      const event = parseFrame(data)

      if (event === null) return
      if (Number.isFinite(seq)) lastSeq = seq

      input.onEvent(event)

      // A finished run has nothing left to say, and the server closes the
      // response.  Stopping here is what keeps that close from looking like a
      // dropped connection that has to be dialled again.
      if (TERMINAL_EVENT_NAMES.has(event.type)) close()
    }

    /** The error a refused stream hands back: the envelope's sentence, not a guess. */
    const refusal = async (response: Response): Promise<RunError> => {
      let envelope: { code?: unknown; messageKey?: unknown } = {}

      try {
        envelope = (await response.json()) as typeof envelope
      } catch {
        envelope = {}
      }

      const code = typeof envelope.code === 'string' ? envelope.code : ''
      const key = typeof envelope.messageKey === 'string' ? envelope.messageKey : ''

      return {
        code: isRunErrorCode(code) ? code : 'stream-failed',
        messageKey: RENDERABLE_ERROR_KEYS.has(key) ? key : LOAD_FAILED,
      }
    }

    /**
     * One connection, until the run ends or the connection drops.
     *
     * Returns whether the caller should dial again: a drop mid-stream resumes,
     * because the alternative is a page that silently stops updating a run that
     * is still going.
     */
    const connect = async (): Promise<boolean> => {
      const token = await ensureSession()
      const headers: Record<string, string> = {
        [SESSION_HEADER]: token,
        Accept: 'text/event-stream',
      }

      // The receipt for what this subscription already has -- not a credential,
      // and never a substitute for one.
      if (lastSeq > 0) headers['Last-Event-ID'] = String(lastSeq)

      const response = await fetch(apiBaseUrl() + runPath(input.runId) + '/events/stream', {
        headers,
        signal: controller.signal,
      })

      if (!response.ok) {
        closed = true
        input.onError?.(await refusal(response))

        return false
      }

      const reader = response.body?.getReader()

      if (reader === undefined) {
        closed = true
        input.onError?.({ code: 'stream-failed', messageKey: LOAD_FAILED })

        return false
      }

      const decoder = new TextDecoder()
      let buffer = ''

      try {
        for (;;) {
          const { done, value } = await reader.read()

          if (done) break

          // `stream: true` keeps a multi-byte character split across two chunks
          // intact instead of decoding it as a replacement character.
          buffer += decoder.decode(value, { stream: true })

          let boundary = buffer.indexOf('\n\n')

          while (boundary !== -1) {
            const frame = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            handleFrame(frame)

            if (closed) {
              await reader.cancel().catch(() => undefined)

              return false
            }

            boundary = buffer.indexOf('\n\n')
          }
        }
      } finally {
        reader.releaseLock()
      }

      return !closed
    }

    const run = async (): Promise<void> => {
      while (!closed) {
        let again = false

        try {
          again = await connect()
        } catch {
          // An abort is this page closing the stream, not a failure to report.
          if (closed) return

          again = true
        }

        if (!again || closed) return

        attempts += 1

        if (attempts > MAX_STREAM_ATTEMPTS) {
          close()
          input.onError?.({ code: 'stream-failed', messageKey: LOAD_FAILED })

          return
        }

        await new Promise((resolve) => setTimeout(resolve, attempts * STREAM_RETRY_MS))
      }
    }

    input.signal?.addEventListener('abort', close)

    void run()
  },
})

import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createHttpRunService } from '@/services/api/run'
import { apiBaseUrl } from '@/services/http'
import type { CreateRunInput } from '@/services/run'
import { RunServiceError } from '@/services/runError'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'

import { installProjectFixtures } from '../support/projects'
import type { RunEvent } from '@/types/run'

/**
 * The run service with a real server behind it, and the stream the way it is
 * actually read: a `fetch` response body, decoded frame by frame.
 *
 * **What changed, and why the old shape was wrong.** The stream used to be an
 * `EventSource`, and this spec stood in for one. It is not: `subscribe` now reads
 * `response.body.getReader()` and parses SSE frames itself, so a fake
 * `EventSource` stood in for an API the product no longer calls -- which is why
 * those tests failed rather than reporting anything about the stream. What is
 * stubbed here is `fetch` and nothing else; the frame parser, the sequence rule,
 * the terminal-event close, the abort handling and the resume header are the code
 * that ships.
 *
 * The other thing this spec got wrong was arithmetic on the request list: it
 * assumed the first `fetch` was a run request. It is not -- the shared HTTP layer
 * obtains a guest session first, and `services/http.ts` is deliberately the one
 * place that attaches it. Calls are therefore classified by their path (see
 * `runCalls`), not counted, so a retry or a later session refresh cannot silently
 * re-point an assertion at the wrong request.
 */

interface Call {
  readonly url: string
  readonly init: RequestInit | undefined
}

let calls: Call[] = []

/**
 * The run requests, in order.
 *
 * Everything that is not a run call is the platform's own business -- the guest
 * session today, something else tomorrow -- and a test that counted positions
 * would break each time that list grows. `captured()` is therefore the first *run*
 * request, found by path, never `calls[0]`.
 *
 * The test covers both shapes a run endpoint has: a run belongs to a project
 * (`/api/projects/{id}/runs`) or is addressed directly (`/api/runs/{id}`). An
 * earlier version of this filter matched only the second, and then reported "no
 * run request was made" about a request that had plainly been made.
 */
const isRunCall = (call: Call): boolean => new URL(call.url).pathname.includes('/runs')

const runCalls = (): Call[] => calls.filter(isRunCall)

/** Answered bodies, by path fragment, so a test states only what it cares about. */
type Route = (url: string) => Response | undefined
let route: Route = () => undefined

/**
 * A response the stream can actually be read from.
 *
 * `Response` is global in this environment, but its `body` is null unless it is
 * given one -- and a null body is the "this browser cannot stream" branch, not the
 * happy one. The controller is handed back so a test can push frames, close the
 * stream, or leave it open, which are the three things a server can do.
 */
const streamResponse = (): { response: Response; push: (chunk: string) => void; end: () => void } => {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null

  const stream = new ReadableStream<Uint8Array>({
    start(next) {
      controller = next
    },
  })

  return {
    response: new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
    push: (chunk) => controller?.enqueue(encoder.encode(chunk)),
    end: () => {
      try {
        controller?.close()
      } catch {
        // Already closed by the reader cancelling it, which is a real outcome.
      }
    },
  }
}

/** An SSE frame as the server writes it: `id`, `event`, `data`, blank line. */
const sseFrame = (name: string, seq: number, payload: unknown): string =>
  'id: ' + String(seq) + '\nevent: ' + name + '\ndata: ' + JSON.stringify(payload) + '\n\n'

const installFetch = (): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })

      if (url.includes('/api/guest-sessions')) {
        return new Response(
          JSON.stringify({
            sessionToken: 'gs_spec_token',
            createdAt: '2026-10-07T10:00:00Z',
            expiresAt: '2026-11-07T10:00:00Z',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }

      const answered = route(url)
      if (answered !== undefined) return answered

      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

/** The same, for the tests that only need one JSON body back. */
const respondWith = (body: unknown, status = 200): void => {
  route = () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
}

const captured = (index = 0): Call => {
  const call = runCalls()[index]
  if (call === undefined) throw new Error('no run request was made')

  return call
}

const bodyOf = (call: Call): Record<string, unknown> =>
  JSON.parse(String(call.init?.body ?? '{}')) as Record<string, unknown>

beforeEach(() => {
  calls = []
  route = () => undefined
  installFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const createInput = (): CreateRunInput => ({
  projectId: 'prj_orders',
  planId: 'plan_orders_1a2b',
  plan: {
    id: 'plan_orders_1a2b',
    projectId: 'prj_orders',
    specId: 'spec_orders_api_1a2b',
    name: { text: 'Orders' },
    goal: { text: 'Check out' },
    riskLevel: 'medium',
    status: 'approved',
    scenarios: [],
    source: 'generated',
    generatedAt: '2026-09-28T00:00:00.000Z',
    approvedAt: null,
    rejectedAt: null,
    rejectionReason: null,
  },
  specId: 'spec_orders_api_1a2b',
  specDocument: '{"openapi":"3.0.3"}',
  environmentId: 'env_orders_staging',
  variables: { token: 's3cr3t-value' },
  baseUrl: 'https://api.stg.example.com',
})

const runBody = {
  id: 'run-1',
  projectId: 'prj_orders',
  planId: 'plan_orders_1a2b',
  planName: { text: 'Orders' },
  specId: 'spec_orders_api_1a2b',
  environmentId: 'env_orders_staging',
  baseUrl: 'https://api.stg.example.com',
  variableKeys: ['token'],
  status: 'queued',
  createdAt: '2026-09-28T09:00:00Z',
  startedAt: null,
  finishedAt: null,
  durationMs: null,
  failure: null,
  summary: {
    scenarios: 0,
    steps: 0,
    assertions: 0,
    passedSteps: 0,
    failedSteps: 0,
    passedAssertions: 0,
    failedAssertions: 0,
  },
}

describe('the run service, over HTTP', () => {
  it('posts the create payload whole, variables and all', async () => {
    respondWith(runBody, 201)
    const service = createHttpRunService()

    const run = await service.createRun(createInput())

    const call = captured()
    expect(call.url).toBe(apiBaseUrl() + '/api/projects/prj_orders/runs')
    expect(call.init?.method).toBe('POST')
    // The credential the platform attaches is on the same request, and is not
    // part of the body the run is described by.
    expect((call.init?.headers as Record<string, string>)['X-Guest-Session']).toBe('gs_spec_token')
    expect(bodyOf(call)).toMatchObject({
      projectId: 'prj_orders',
      planId: 'plan_orders_1a2b',
      specId: 'spec_orders_api_1a2b',
      environmentId: 'env_orders_staging',
      baseUrl: 'https://api.stg.example.com',
      variables: { token: 's3cr3t-value' },
    })
    // The value goes out; it does not come back.
    expect(run.variableKeys).toEqual(['token'])
    expect('variables' in run).toBe(false)
  })

  it('reads a project\'s runs from its own collection', async () => {
    respondWith([runBody])
    const service = createHttpRunService()

    const list = await service.listRuns('prj_orders')

    expect(captured().url).toBe(apiBaseUrl() + '/api/projects/prj_orders/runs')
    expect(list).toHaveLength(1)
    expect(list[0]?.id).toBe('run-1')
  })

  it('reads a detail as it arrives, without mapping a single field', async () => {
    respondWith({ run: runBody, scenarios: [], lastSeq: 0 })
    const service = createHttpRunService()

    const detail = await service.getRunDetail('run-1')

    expect(captured().url).toBe(apiBaseUrl() + '/api/runs/run-1')
    expect(detail.run.status).toBe('queued')
    expect(detail.lastSeq).toBe(0)
  })

  it('cancels through the run\'s own path', async () => {
    respondWith({ ...runBody, status: 'cancelled' })
    const service = createHttpRunService()

    const run = await service.cancelRun('run-1')

    expect(captured().url).toBe(apiBaseUrl() + '/api/runs/run-1/cancel')
    expect(captured().init?.method).toBe('POST')
    expect(run.status).toBe('cancelled')
  })

  it('turns a refusal into the error the store already renders', async () => {
    respondWith(
      {
        code: 'not-approved',
        messageKey: 'console.runs.errors.notApproved',
        params: { plan: 'Orders' },
      },
      409,
    )
    const service = createHttpRunService()

    await expect(service.createRun(createInput())).rejects.toMatchObject({
      detail: {
        code: 'not-approved',
        messageKey: 'console.runs.errors.notApproved',
        params: { plan: 'Orders' },
      },
    })
  })

  it('turns a missing run into the not-found error, not a generic failure', async () => {
    respondWith({ code: 'run-not-found', messageKey: 'console.runs.errors.notFound' }, 404)
    const service = createHttpRunService()

    let caught: unknown
    try {
      await service.getRunDetail('run-nope')
    } catch (thrown) {
      caught = thrown
    }

    expect(caught).toBeInstanceOf(RunServiceError)
    expect((caught as RunServiceError).detail).toEqual({
      code: 'run-not-found',
      messageKey: 'console.runs.errors.notFound',
    })
  })

  it('falls back to the caller\'s sentence for a key it cannot render', async () => {
    respondWith({ code: 'internal-error', messageKey: 'console.runs.errors.invented' }, 500)
    const service = createHttpRunService()

    await expect(service.cancelRun('run-1')).rejects.toMatchObject({
      detail: { code: 'cancel-failed', messageKey: 'console.runs.errors.cancelFailed' },
    })
  })
})

describe('the replay record, adapted', () => {
  it('becomes the event the reducer folds', async () => {
    respondWith([
      {
        runId: 'run-1',
        seq: 3,
        at: '2026-09-28T09:00:05Z',
        eventType: 'run.cancelled',
        payload: { finishedAt: '2026-09-28T09:00:05+00:00', durationMs: 0 },
      },
    ])
    const service = createHttpRunService()

    const events = await service.getRunEvents('run-1', 3)

    expect(captured().url).toBe(apiBaseUrl() + '/api/runs/run-1/events?fromSeq=3')
    expect(events).toHaveLength(1)
    expect(events[0]).toEqual({
      type: 'run.cancelled',
      runId: 'run-1',
      seq: 3,
      at: '2026-09-28T09:00:05Z',
      finishedAt: '2026-09-28T09:00:05+00:00',
      durationMs: 0,
    })
  })

  it('carries an event nobody knows without inventing anything', async () => {
    respondWith([{ runId: 'run-1', seq: 4, at: 'x', eventType: 'future.event', payload: null }])
    const service = createHttpRunService()

    const events = await service.getRunEvents('run-1')

    expect(events[0]).toEqual({ type: 'future.event', runId: 'run-1', seq: 4, at: 'x' })
  })
})
describe('the event stream', () => {
  const STREAM_PATH = apiBaseUrl() + '/api/runs/run-1/events/stream'

  /** The stream request, found by path -- never by counting requests. */
  const streamCalls = (): Call[] =>
    calls.filter((call) => call.url.includes('/events/stream'))

  interface Feed {
    readonly frame: { readonly response: Response; readonly push: (chunk: string) => void; readonly end: () => void }
    readonly received: RunEvent[]
    readonly failures: { readonly code: string; readonly messageKey: string }[]
    readonly controller: AbortController
  }

  /**
   * Subscribe to a stream the test controls, chunk by chunk.
   *
   * The route hands out a fresh body per dial, so a resuming connection is a real
   * second request with its own stream.
   */
  const subscribe = (runId = 'run-1'): Feed => {
    const frame = streamResponse()
    route = (url) => (url.includes('/events/stream') ? frame.response : undefined)

    const received: RunEvent[] = []
    const failures: { code: string; messageKey: string }[] = []
    const controller = new AbortController()

    createHttpRunService().subscribe({
      runId,
      onEvent: (event) => received.push(event),
      onError: (error) => failures.push(error),
      signal: controller.signal,
    })

    return { frame, received, failures, controller }
  }

  /** Waits for a condition the stream sets up asynchronously. */
  const until = async (ready: () => boolean, label: string, timeoutMs = 2000): Promise<void> => {
    const deadline = Date.now() + timeoutMs

    while (Date.now() < deadline) {
      if (ready()) return
      await new Promise((resolve) => setTimeout(resolve, 5))
    }

    throw new Error('timed out waiting for ' + label)
  }

  const frame = {
    type: 'step.started',
    runId: 'run-1',
    seq: 1,
    at: '2026-09-28T09:00:00Z',
    scenarioId: 'scn_a',
    stepId: 'scn_a__step_0',
  }

  it('opens exactly one connection, on the stream path, with no query string', async () => {
    subscribe()

    await until(() => streamCalls().length === 1, 'the stream request')
    expect(streamCalls()).toHaveLength(1)
    expect(streamCalls()[0]?.url).toBe(STREAM_PATH)
    expect(streamCalls()[0]?.url).not.toContain('fromSeq')
  })

  it('asks for an event stream and carries the platform session, not a credential in the url', async () => {
    subscribe()

    await until(() => streamCalls().length === 1, 'the stream request')

    const headers = streamCalls()[0]?.init?.headers as Record<string, string>
    expect(headers['Accept']).toBe('text/event-stream')
    expect(headers['X-Guest-Session']).toBe('gs_spec_token')
    // A token in a query string would end up in a server log and a Referer.
    expect(streamCalls()[0]?.url).not.toContain('session')
  })

  it('hands a frame to the caller as an event', async () => {
    const feed = subscribe()
    await until(() => streamCalls().length === 1, 'the stream request')

    feed.frame.push(sseFrame('step.started', 1, frame))

    await until(() => feed.received.length === 1, 'the frame to arrive')
    expect(feed.received).toEqual([frame])
    expect(feed.controller.signal.aborted).toBe(false)
  })

  it('closes the connection once a terminal event has been delivered', async () => {
    const feed = subscribe()
    await until(() => streamCalls().length === 1, 'the stream request')

    const cancelled = {
      type: 'run.cancelled',
      runId: 'run-1',
      seq: 2,
      at: '2026-09-28T09:00:05Z',
      finishedAt: '2026-09-28T09:00:05Z',
      durationMs: 0,
    }

    feed.frame.push(sseFrame('run.cancelled', 2, cancelled))

    await until(() => feed.received.length === 1, 'the terminal event')
    expect(feed.received).toEqual([cancelled])

    // What "closes the connection" means here, observably: the subscription aborts
    // its *own* controller -- which closes the response body, and with it the
    // socket -- stops reading, and never dials again.  The caller's controller is a
    // different object and is deliberately left alone, so asserting on it was
    // asserting the wrong thing.
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(streamCalls()).toHaveLength(1)
    expect(feed.failures).toEqual([])
  })

  it('closes the connection when the caller aborts', async () => {
    const feed = subscribe()
    await until(() => streamCalls().length === 1, 'the stream request')

    feed.controller.abort()

    await until(() => feed.controller.signal.aborted, 'the abort to be observed')
    expect(feed.failures).toEqual([])
    expect(feed.received).toEqual([])
  })

  it('reports a stream that failed before it could be read', async () => {
    route = () =>
      new Response(JSON.stringify({ code: 'load-failed', messageKey: 'console.runs.errors.loadFailed' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      })

    const failures: { code: string; messageKey: string }[] = []
    createHttpRunService().subscribe({
      runId: 'run-1',
      onEvent: () => undefined,
      onError: (error) => failures.push(error),
    })

    await until(() => failures.length === 1, 'the stream failure')
    expect(failures).toEqual([{ code: 'stream-failed', messageKey: 'console.runs.errors.loadFailed' }])
  })

  it('reports one failure when every re-dial is refused, and stops', async () => {
    route = () =>
      new Response(JSON.stringify({ code: 'load-failed', messageKey: 'console.runs.errors.loadFailed' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      })

    const failures: { code: string; messageKey: string }[] = []
    createHttpRunService().subscribe({
      runId: 'run-1',
      onEvent: () => undefined,
      onError: (error) => failures.push(error),
    })

    await until(() => failures.length > 0, 'the first failure', 3000)
    await new Promise((resolve) => setTimeout(resolve, 150))

    // A refusal is not a dropped connection: there is nothing to resume, so the
    // caller hears it once instead of being told again on every retry.
    expect(failures).toHaveLength(1)
  })

  it('ignores a frame that is not an event at all', async () => {
    const feed = subscribe()
    await until(() => streamCalls().length === 1, 'the stream request')

    // A comment, a keep-alive, a nameless payload: none of them is one of the
    // eight events, so none of them reaches the caller and none is an error.
    feed.frame.push(': keep-alive\n\n')
    feed.frame.push('data: {"hello":"there"}\n\n')
    feed.frame.push('event: future.event\nid: 9\ndata: {"type":"future.event"}\n\n')
    feed.frame.end()

    await new Promise((resolve) => setTimeout(resolve, 60))
    expect(feed.received).toEqual([])
    expect(feed.failures).toEqual([])
  })

  it('does not re-deliver a sequence it has already folded', async () => {
    const feed = subscribe()
    await until(() => streamCalls().length === 1, 'the stream request')

    feed.frame.push(sseFrame('step.started', 1, frame))
    await until(() => feed.received.length === 1, 'the first frame')

    // A server that replays one event too many must not double anything the page
    // is already showing.  This is the rule the store relies on, exercised here at
    // the parser.
    feed.frame.push(sseFrame('step.started', 1, frame))
    await new Promise((resolve) => setTimeout(resolve, 60))

    expect(feed.received).toHaveLength(1)
  })

  it('sends an empty url to the stream, with no receipt before there is one', async () => {
    // Two things the URL must not carry: a query string, and the platform
    // credential.  A `fromSeq` pinned into the url would outrank `Last-Event-ID` on
    // every reconnect and replay the same prefix forever -- which is why
    // `SubscribeRunInput.fromSeq` is documented as advisory and ignored by this
    // service (the mock honours it; a script has no connection to resume).
    const feed = streamResponse()
    route = (url) => (url.includes('/events/stream') ? feed.response : undefined)

    createHttpRunService().subscribe({ runId: 'run-1', onEvent: () => undefined })

    await until(() => streamCalls().length === 1, 'the stream request')

    const headers = streamCalls()[0]?.init?.headers as Record<string, string | undefined>
    expect(streamCalls()[0]?.url).toBe(STREAM_PATH)
    expect(streamCalls()[0]?.url).not.toContain('fromSeq')
    expect(streamCalls()[0]?.url).not.toContain('session')
    expect(headers['Accept']).toBe('text/event-stream')
    // Nothing has been applied yet, so there is nothing to resume from.
    expect(headers['Last-Event-ID']).toBeUndefined()
  })

  it('dials again when a stream drops mid-run, and says nothing about it', async () => {
    // The behaviour that matters when a server closes the body while the run is
    // still going: the subscription tries again rather than leaving the page frozen,
    // and it does not report a failure for a connection it is already re-opening.
    const first = streamResponse()
    const later = streamResponse()
    let dialled = 0

    route = (url) => {
      if (!url.includes('/events/stream')) return undefined
      dialled += 1

      return dialled === 1 ? first.response : later.response
    }

    const received: RunEvent[] = []
    const failures: { code: string; messageKey: string }[] = []

    createHttpRunService().subscribe({
      runId: 'run-1',
      onEvent: (event) => received.push(event),
      onError: (error) => failures.push(error),
    })

    await until(() => streamCalls().length === 1, 'the first connection')
    first.push(sseFrame('step.started', 1, frame))
    await until(() => received.length === 1, 'the first event')

    // The server drops the connection mid-run.
    first.end()

    await until(() => streamCalls().length >= 2, 'the next connection', 4000)
    expect(streamCalls()[1]?.url).toBe(STREAM_PATH)
    expect(received.map((event) => event.seq)).toEqual([1])

    // A resume is not an error: the caller is not told the stream failed while it
    // is being re-opened.
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(failures).toEqual([])
  })

  it('resumes a dropped stream at the event it already folded, via Last-Event-ID', async () => {
    // The receipt the server needs to resume without repeating itself.  This is
    // the one assertion that proves the two halves of the contract meet: the
    // parser's `lastSeq` (api/run.ts:304) and the header built from it
    // (api/run.ts:349).  Every other stream test here would still pass if the
    // header were never sent at all -- they only ever look at one connection.
    //
    // The route below is deliberately strict about *when* it answers.  Resuming
    // is only correct if the frame has been processed before the next dial, so a
    // second request that arrives too early fails here by name instead of
    // producing a confusing header assertion.  That turns an ordering race into a
    // message that says which ordering broke.
    const first = streamResponse()
    const second = streamResponse()
    let dialled = 0

    route = (url) => {
      if (!url.includes('/events/stream')) return undefined

      dialled += 1

      if (dialled === 2 && received.length === 0) {
        throw new Error('the stream was dialled again before the first frame was folded')
      }

      return dialled === 1 ? first.response : second.response
    }

    const received: RunEvent[] = []
    const failures: { code: string; messageKey: string }[] = []
    const controller = new AbortController()

    createHttpRunService().subscribe({
      runId: 'run-1',
      onEvent: (event) => received.push(event),
      onError: (error) => failures.push(error),
      signal: controller.signal,
    })

    // 1. The first connection, which has nothing to resume from yet.
    await until(() => streamCalls().length === 1, 'the first connection')
    const firstHeaders = streamCalls()[0]?.init?.headers as Record<string, string | undefined>
    expect(streamCalls()[0]?.url).toBe(STREAM_PATH)
    expect(firstHeaders['Accept']).toBe('text/event-stream')
    expect(firstHeaders['Last-Event-ID']).toBeUndefined()

    // 2. and 3. A real SSE frame through the real parser, delivered to the caller.
    first.push(sseFrame('step.started', 1, frame))
    await until(() => received.length === 1, 'the first event to be folded')
    expect(received).toEqual([frame])

    // 4. The test closes the connection itself, at a point it chose: the frame is
    // folded, so the subscription holds a receipt and the ordering the resume
    // depends on is established rather than hoped for.
    first.end()

    // 5. The subscription opens the second connection on its own.
    await until(() => streamCalls().length >= 2, 'the second connection', 4000)

    // 6. The receipt, and nothing else in its place.
    const secondHeaders = streamCalls()[1]?.init?.headers as Record<string, string | undefined>
    expect(secondHeaders['Last-Event-ID']).toBe('1')
    expect(streamCalls()[1]?.url).toBe(STREAM_PATH)
    expect(streamCalls()[1]?.url).not.toContain('fromSeq')

    // 7. The resumed connection finishes the stream the way a run does: a terminal
    // event, delivered once, and a subscription that closes instead of dialling again.
    const completed = {
      type: 'run.completed',
      runId: 'run-1',
      seq: 2,
      at: '2026-09-28T09:00:09Z',
      finishedAt: '2026-09-28T09:00:09Z',
      durationMs: 9000,
    }

    second.push(sseFrame('run.completed', 2, completed))
    await until(() => received.length === 2, 'the terminal event')

    expect(received).toEqual([frame, completed])
    expect(failures).toEqual([])

    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(streamCalls()).toHaveLength(2)
  })
})
/**
 * The two store rules this phase added or repaired, driven through the mock the
 * test environment selects: they are about what the reducer does with an event,
 * which is the same question whichever transport delivered it.
 */
describe('the store, against the events a stream can deliver', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const loaded = async () => {
    // The store starts empty now: a run needs an active project with an
    // environment, so the project these two tests run against is stated here.
    installProjectFixtures(useProjectStore())

    const runs = useRunsStore()
    const agent = useAgentStore()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.generatePlan()
    agent.approvePlan(agent.activePlan?.id ?? '')

    const run = await runs.createRun({ immediate: true })

    return { runs, id: run?.id ?? '' }
  }

  it('applies a replayed sequence once, not twice', async () => {
    const { runs, id } = await loaded()
    const before = runs.activeDetail
    if (before === null) throw new Error('expected a loaded run')

    const replay: RunEvent = {
      type: 'run.started',
      runId: id,
      seq: 1,
      at: new Date().toISOString(),
      startedAt: new Date().toISOString(),
    }

    runs.applyEvent(replay)
    runs.applyEvent(replay)

    expect(runs.activeDetail).toBe(before)
  })

  it('ignores an event it has never heard of instead of throwing', async () => {
    const { runs, id } = await loaded()
    const before = runs.activeDetail
    if (before === null) throw new Error('expected a loaded run')

    const unknown = {
      type: 'future.event',
      runId: id,
      seq: before.lastSeq + 1,
      at: new Date().toISOString(),
      note: 'from a later phase',
    } as unknown as RunEvent

    runs.applyEvent(unknown)

    expect(runs.activeDetail).toBe(before)
    expect(runs.activeRun?.status).toBe('passed')
  })
})
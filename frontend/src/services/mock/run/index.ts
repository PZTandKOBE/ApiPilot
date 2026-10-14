/**
 * Mock run service.
 *
 * A server in miniature: it owns the runs, answers REST reads from its own
 * state, and pushes the events it has decided are happening down a stream.
 * What it does *not* do is execute anything — the script is written when the
 * run is created (see `script.ts`), and everything afterwards is delivery.
 *
 * Three properties are load-bearing, and together they are why this is a
 * script rather than a chain of promises:
 *
 * - **Delivery is not the run.** The clock advances the run whether or not
 *   anyone is listening. Unsubscribing — which is what a component unmounting
 *   does — must not stop a run, because a run's lifetime is not a component's
 *   lifetime (D2).
 * - **Replay is exact.** A subscriber is owed every event after the `seq` its
 *   snapshot was taken at, whether it was there when the event happened or
 *   not. That is what makes "load, then subscribe" gap-free.
 * - **The snapshot is the truth.** `getRunDetail` folds the events that have
 *   happened using the same reducer the client uses, so a reloaded page and a
 *   live one cannot disagree about what a run looks like.
 */

import { RunServiceError } from '@/services/runError'
import type {
  CreateRunInput,
  RunRequestOptions,
  RunService,
  SubscribeRunInput,
} from '@/services/run'
import type { RunDetail, RunEvent, TestRun } from '@/types/run'
import { isTerminalRunStatus } from '@/types/run'
import { applyRunEvent } from '@/utils/runState'
import { buildRunDetail, buildRunEvents, runIdFrom } from './script'

/**
 * Pacing, in milliseconds.
 *
 * Fixed rather than jittered: a run that felt slow once should feel the same
 * amount of slow when it is looked at again.
 */
const START_DELAY_MS = 180
const EVENT_DELAY_MS = 220

interface Subscriber {
  readonly onEvent: (event: RunEvent) => void
  readonly signal?: AbortSignal
}

interface ScriptedRun {
  readonly id: string
  readonly projectId: string
  /** The state before any event — the whole plan, drawn, nothing run. */
  readonly base: RunDetail
  /** The full script. Truncated when the run is cancelled. */
  events: RunEvent[]
  /** How many events have happened. The server's clock, not a client's. */
  emitted: number
  /** Set when this run is being delivered without timers. */
  unpaced: boolean
  timer: ReturnType<typeof setTimeout> | null
  readonly subscribers: Set<Subscriber>
}

const notFound = (runId: string): RunServiceError =>
  new RunServiceError({
    code: 'run-not-found',
    messageKey: 'console.runs.errors.notFound',
    params: { runId },
  })

const now = (): string => new Date().toISOString()

export const createMockRunService = (): RunService => {
  const runs = new Map<string, ScriptedRun>()
  let ordinal = 0

  /* --- State ------------------------------------------------------- */

  /** The run as it stands, by folding the events that have happened. */
  const stateOf = (script: ScriptedRun): RunDetail => {
    let detail = script.base

    for (let index = 0; index < script.emitted; index += 1) {
      const event = script.events[index]
      if (event !== undefined) detail = applyRunEvent(detail, event)
    }

    return detail
  }

  const require = (runId: string): ScriptedRun => {
    const script = runs.get(runId)
    if (script === undefined) throw notFound(runId)
    return script
  }

  /* --- Delivery ---------------------------------------------------- */

  /** Advances the run by one event and hands it to everyone listening. */
  const deliver = (script: ScriptedRun, event: RunEvent): void => {
    script.emitted += 1

    for (const subscriber of [...script.subscribers]) {
      if (subscriber.signal?.aborted === true) {
        script.subscribers.delete(subscriber)
        continue
      }

      subscriber.onEvent(event)
    }
  }

  const stopClock = (script: ScriptedRun): void => {
    if (script.timer === null) return
    clearTimeout(script.timer)
    script.timer = null
  }

  const schedule = (script: ScriptedRun): void => {
    if (script.timer !== null || script.unpaced) return
    if (script.emitted >= script.events.length) return

    const delay = script.emitted === 0 ? START_DELAY_MS : EVENT_DELAY_MS
    script.timer = setTimeout(() => {
      script.timer = null

      const event = script.events[script.emitted]
      if (event === undefined) return

      deliver(script, event)
      schedule(script)
    }, delay)
  }

  /** Runs the script to its end with no timers at all. */
  const drain = (script: ScriptedRun): void => {
    stopClock(script)

    while (script.emitted < script.events.length) {
      const event = script.events[script.emitted]
      if (event === undefined) break
      deliver(script, event)
    }
  }

  /* --- Service ----------------------------------------------------- */

  return {
    async createRun(input: CreateRunInput, options: RunRequestOptions = {}) {
      // The approval gate, re-checked here rather than trusted. The browser
      // writes `status` to localStorage and its user can edit it, so taking
      // the client's word for it would make the dialog the security boundary.
      if (input.plan.status !== 'approved') {
        throw new RunServiceError({
          code: 'not-approved',
          messageKey: 'console.runs.errors.notApproved',
          params: { plan: input.plan.id },
        })
      }

      ordinal += 1
      const id = runIdFrom(input.plan, ordinal)

      const script: ScriptedRun = {
        id,
        projectId: input.projectId,
        base: buildRunDetail(input, id),
        events: [...buildRunEvents(input, id)],
        emitted: 0,
        unpaced: options.immediate === true,
        timer: null,
        subscribers: new Set(),
      }

      runs.set(id, script)

      // Creating a run starts it. Waiting for a subscriber would make a run's
      // progress depend on someone watching it, which is the opposite of what
      // a run is — and would quietly break the case the store cares about,
      // where a page is closed and reopened mid-run.
      if (script.unpaced) drain(script)
      else schedule(script)

      return stateOf(script).run
    },

    async getRun(runId: string): Promise<TestRun> {
      return stateOf(require(runId)).run
    },

    async getRunDetail(runId: string): Promise<RunDetail> {
      return stateOf(require(runId))
    },

    /**
     * A project's runs, newest first.
     *
     * Sorted the way the server sorts rather than the way the map happens to
     * iterate: the list is defined as `createdAt` descending with the id as a
     * tiebreaker, and a mock that answered in insertion order would let a
     * caller depend on something the real endpoint does not promise.
     */
    async listRuns(projectId: string): Promise<readonly TestRun[]> {
      return [...runs.values()]
        .filter((script) => script.projectId === projectId)
        .map((script) => stateOf(script).run)
        .sort((left, right) =>
          right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id),
        )
    },

    /**
     * The events that have happened so far, from `fromSeq` onwards.
     *
     * `emitted` rather than the whole script: the events a run will produce are
     * written when it is created, and handing back the ones that have not
     * happened yet would be a different answer from the server's.
     */
    async getRunEvents(runId: string, fromSeq = 1): Promise<readonly RunEvent[]> {
      return require(runId)
        .events.slice(0, require(runId).emitted)
        .filter((event) => event.seq >= fromSeq)
    },

    async cancelRun(runId: string): Promise<TestRun> {
      const script = require(runId)
      const current = stateOf(script)

      // Cancelling something already over is neither an error nor a second
      // transition: the run has an answer, and this is it.
      if (isTerminalRunStatus(current.run.status)) return current.run

      stopClock(script)

      // Everything the run had left to say is dropped and the cancellation
      // takes its place, so a client replaying the script afterwards sees a
      // run that stopped — not one that finished and was relabelled.
      script.events = script.events.slice(0, script.emitted)
      script.events.push({
        type: 'run.cancelled',
        runId: script.id,
        seq: script.emitted + 1,
        at: now(),
        finishedAt: now(),
        durationMs:
          current.run.startedAt === null
            ? 0
            : Date.now() - Date.parse(current.run.startedAt),
      })

      // Someone is waiting on this, so it lands now rather than on a tick.
      drain(script)

      return stateOf(script).run
    },

    subscribe(input: SubscribeRunInput): void {
      const script = runs.get(input.runId)

      if (script === undefined) {
        input.onError?.(notFound(input.runId).detail)
        return
      }

      if (input.signal?.aborted === true) return

      const subscriber: Subscriber = { onEvent: input.onEvent, signal: input.signal }
      script.subscribers.add(subscriber)

      input.signal?.addEventListener('abort', () => {
        script.subscribers.delete(subscriber)
      })

      const fromSeq = input.fromSeq ?? 0

      // What the subscriber is owed: everything the run has already said,
      // after the point their snapshot was taken at.
      for (let index = 0; index < script.emitted; index += 1) {
        const event = script.events[index]
        if (event !== undefined && event.seq > fromSeq) subscriber.onEvent(event)
      }

      if (input.immediate === true) script.unpaced = true

      if (script.unpaced || script.emitted >= script.events.length) {
        drain(script)
        script.subscribers.delete(subscriber)
        return
      }

      schedule(script)
    },
  }
}

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import {
  createRunService,
  isRunServiceError,
  type CreateRunInput,
  type RunError,
  type RunRequestOptions,
} from '@/services/run'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import type { RunDetail, RunEvent, TestRun } from '@/types/run'
import { isTerminalRunStatus } from '@/types/run'
import { applyRunEvent } from '@/utils/runState'

/**
 * Runs, and the one connection that keeps them current.
 *
 * Nothing here is persisted, and that is a decision rather than an omission
 * (D3). A run is server state: the browser is allowed to hold it while it is
 * on screen, not to be its source of truth. Refreshing rebuilds a run from a
 * REST snapshot plus the tail of its stream, so there is nothing a stale
 * `localStorage` copy could contribute except a way to be wrong — and, for
 * something that updates on every event, a full re-serialisation per tick.
 *
 * The subscription lives *here* rather than in a component (D2). A run is not
 * a view's property: navigating away from a detail page must not stop it, and
 * coming back must not restart it. That is why the store keeps the
 * `AbortController` and the high-water mark rather than a component holding
 * them in a `ref` that unmount discards.
 *
 * Dependency direction is one-way: `runs → agent`. The agent store knows
 * nothing about runs, so approving a plan cannot accidentally start one, and
 * the lab keeps working with no run store in the application at all.
 */
export const useRunsStore = defineStore('runs', () => {
  const service = createRunService()
  const agentStore = useAgentStore()
  const projectStore = useProjectStore()
  const { localize } = useLocalizedText()

  /* --- State -------------------------------------------------------- */

  /** Every run this session has heard about, across projects. */
  const runs = ref<readonly TestRun[]>([])

  /**
   * Loaded details, by run id.
   *
   * Only for runs that have been opened. A list of twenty runs should not
   * carry twenty sets of scenarios it is not going to draw.
   */
  const details = ref<readonly RunDetail[]>([])

  const loading = ref(false)
  /**
   * The list's own flag, deliberately not `loading`.
   *
   * `loading` already guards `loadRun` with an early return, so a list request
   * that reused it would silently cancel a detail load that happened to be in
   * flight -- and the run page would sit empty with nothing to explain it.
   */
  const listing = ref(false)
  const creating = ref(false)
  const cancelling = ref(false)
  const error = ref<RunError | null>(null)

  /** The run the detail page is following. */
  const activeRunId = ref<string | null>(null)

  /**
   * High-water marks, and the subscriptions they belong to.
   *
   * Both are deliberately outside the reactive state: a `seq` is bookkeeping
   * for one connection and an `AbortController` is not a value to render.
   * Making them reactive would also make every event touch two more
   * dependencies than it needs to.
   */
  const lastSeq = new Map<string, number>()
  const controllers = new Map<string, AbortController>()

  /* --- Derived ------------------------------------------------------ */

  const projectId = computed(() => projectStore.activeProjectId)

  /** Newest first: the run just started is the one being looked for. */
  const projectRuns = computed<readonly TestRun[]>(() =>
    runs.value
      .filter((run) => run.projectId === projectId.value)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
  )

  const activeRun = computed<TestRun | null>(
    () => runs.value.find((run) => run.id === activeRunId.value) ?? null,
  )

  const activeDetail = computed<RunDetail | null>(
    () => details.value.find((detail) => detail.run.id === activeRunId.value) ?? null,
  )

  /**
   * Which runs are being followed right now.
   *
   * The controllers themselves stay out of the reactive state — a connection
   * is not a value to render — but "is this run live?" is, because the detail
   * page says so.
   */
  const subscribedRunIds = ref<readonly string[]>([])

  const markSubscribed = (runId: string, subscribed: boolean): void => {
    subscribedRunIds.value = subscribed
      ? [...new Set([...subscribedRunIds.value, runId])]
      : subscribedRunIds.value.filter((id) => id !== runId)
  }

  const detailOf = (runId: string): RunDetail | null =>
    details.value.find((detail) => detail.run.id === runId) ?? null

  /* --- Errors ------------------------------------------------------- */

  const toRunError = (thrown: unknown, fallbackKey: string): RunError =>
    isRunServiceError(thrown)
      ? thrown.detail
      : { code: 'create-failed', messageKey: fallbackKey }

  const clearError = (): void => {
    error.value = null
  }

  /* --- Writing ------------------------------------------------------ */

  const upsertRun = (run: TestRun): void => {
    const known = runs.value.some((candidate) => candidate.id === run.id)
    runs.value = known
      ? runs.value.map((candidate) => (candidate.id === run.id ? run : candidate))
      : [...runs.value, run]
  }

  const upsertDetail = (detail: RunDetail): void => {
    const known = details.value.some((candidate) => candidate.run.id === detail.run.id)
    details.value = known
      ? details.value.map((candidate) =>
          candidate.run.id === detail.run.id ? detail : candidate,
        )
      : [...details.value, detail]
  }

  /* --- Events ------------------------------------------------------- */

  /**
   * Folds one event into the run it belongs to.
   *
   * Three ways an event is dropped, and each of them is a real thing that
   * happens rather than a defensive branch:
   *
   * - **No detail loaded.** Nothing to fold into. The next snapshot will
   *   carry everything up to a later `seq` anyway, so the event is not lost —
   *   it is simply not this store's to reconstruct.
   * - **The run already finished.** A late event would otherwise reopen a run
   *   whose result the user has already read.
   * - **The `seq` is not new.** Re-delivery after a reconnect is the normal
   *   case, not an exceptional one.
   */
  const applyEvent = (event: RunEvent): void => {
    const detail = detailOf(event.runId)
    if (detail === null) return

    const mark = lastSeq.get(event.runId) ?? detail.lastSeq
    if (isTerminalRunStatus(detail.run.status)) return
    if (event.seq <= mark) return

    const next = applyRunEvent(detail, event)

    lastSeq.set(event.runId, next.lastSeq)
    upsertDetail(next)
    upsertRun(next.run)

    if (isTerminalRunStatus(next.run.status)) unsubscribe(event.runId)
  }

  /* --- Subscriptions ------------------------------------------------ */

  /**
   * Opens the stream for a run, resuming from the last event applied.
   *
   * Safe to call twice: a run already being followed is not followed twice.
   */
  const subscribeRun = (
    runId: string,
    options: RunRequestOptions = {},
  ): void => {
    if (controllers.has(runId)) return

    const detail = detailOf(runId)
    if (detail !== null && isTerminalRunStatus(detail.run.status)) return

    const controller = new AbortController()
    controllers.set(runId, controller)
    markSubscribed(runId, true)

    service.subscribe({
      runId,
      signal: controller.signal,
      immediate: options.immediate,
      fromSeq: lastSeq.get(runId) ?? 0,
      onEvent: applyEvent,
      onError: (failure) => {
        error.value = failure
        controllers.delete(runId)
        markSubscribed(runId, false)
      },
    })
  }

  /**
   * Closes the stream for a run.
   *
   * Deliberately does not touch the run: stopping watching and stopping
   * running are different actions, and conflating them would make navigating
   * away cancel a test.
   */
  const unsubscribe = (runId: string): void => {
    const controller = controllers.get(runId)
    if (controller === undefined) return

    controller.abort()
    controllers.delete(runId)
    markSubscribed(runId, false)
  }

  /* --- Actions ------------------------------------------------------ */

  /**
   * Creates a run from the project's approved plan.
   *
   * Returns `null` rather than throwing when there is nothing to run — a
   * caller that has to catch a "you have no plan yet" is a caller that will
   * forget to. The reason is left in `error` for the view to show.
   */
  const createRun = async (
    options: RunRequestOptions = {},
  ): Promise<TestRun | null> => {
    if (creating.value) return null

    const plan = agentStore.activePlan
    const spec = agentStore.currentSpec
    const document = agentStore.currentSpecDocument
    const environment = projectStore.activeEnvironment

    if (plan === null || spec === null || document === null || environment === null) {
      error.value = { code: 'create-failed', messageKey: 'console.runs.errors.noPlan' }
      return null
    }

    // The backend re-checks this; so does the store. Not because the store's
    // answer is authoritative — it is not — but because sending a request
    // that is going to be refused is a worse way to find out.
    if (plan.status !== 'approved') {
      error.value = {
        code: 'not-approved',
        messageKey: 'console.runs.errors.notApproved',
        // Rendered here rather than passed as a message, because the sentence
        // around it has to survive a language switch. The plan's own name is
        // frozen at the moment it was refused, which is the moment the user
        // was looking at it.
        params: { plan: localize(plan.name) },
      }
      return null
    }

    creating.value = true
    clearError()

    const input: CreateRunInput = {
      projectId: projectId.value,
      planId: plan.id,
      // Whole, not by reference: the backend has never seen this plan.
      plan,
      specId: spec.id,
      // The document itself. Metadata alone could not be turned into requests.
      specDocument: document,
      environmentId: environment.id,
      variables: projectStore.variables,
      baseUrl: environment.baseUrl,
    }

    try {
      const run = await service.createRun(input, options)

      upsertRun(run)
      activeRunId.value = run.id

      // Snapshot, then tail: the run exists before the first event does, so a
      // reload between the two loses nothing.
      await loadRun(run.id, options)

      return run
    } catch (thrown) {
      error.value = toRunError(thrown, 'console.runs.errors.createFailed')
      return null
    } finally {
      creating.value = false
    }
  }

  /**
   * Loads the project's runs, replacing whatever this session held for it.
   *
   * The list is the one thing a reload cannot reconstruct: the store starts
   * empty and nothing in the browser knows what has run here before. Replacing
   * per project rather than merging keeps the server authoritative -- a run
   * changed or removed there does not linger here as a ghost row -- while other
   * projects' runs are left alone, because switching project back must not have
   * to ask again for what it already had.
   */
  const loadRuns = async (): Promise<void> => {
    if (listing.value) return

    const id = projectId.value

    listing.value = true
    clearError()

    try {
      const list = await service.listRuns(id)

      runs.value = [...runs.value.filter((run) => run.projectId !== id), ...list]
    } catch (thrown) {
      error.value = toRunError(thrown, 'console.runs.errors.loadFailed')
    } finally {
      listing.value = false
    }
  }

  /**
   * Loads a run's current state from the server, then follows it.
   *
   * The order matters and is the whole refresh story: the snapshot fixes a
   * point in the stream, the subscription resumes from it, and the two
   * together are indistinguishable from having been connected all along.
   */
  const loadRun = async (
    runId: string,
    options: RunRequestOptions = {},
  ): Promise<void> => {
    if (loading.value) return

    loading.value = true
    clearError()

    try {
      const detail = await service.getRunDetail(runId)
      const known = detailOf(runId)

      // A snapshot older than the events already applied must not rewind the
      // run. The stream can be ahead of a response that was in flight when it
      // arrived -- a cancel answered late, a slow reload -- and letting the
      // older answer win would repaint "cancelled" as "running" until the next
      // event happened to correct it. Equal marks are fine: that is the
      // reconnect case, where the snapshot and the state are the same run.
      if (known === null || detail.lastSeq >= known.lastSeq) {
        upsertRun(detail.run)
        upsertDetail(detail)
      }

      // Only ever forwards: a snapshot older than what has been applied must
      // not rewind the mark and re-apply events that are already in state.
      lastSeq.set(runId, Math.max(lastSeq.get(runId) ?? 0, detail.lastSeq))
    } catch (thrown) {
      error.value = toRunError(thrown, 'console.runs.errors.loadFailed')
    } finally {
      // Nothing to follow if the run is over — but the snapshot stands.
      const detail = detailOf(runId)
      if (detail !== null && !isTerminalRunStatus(detail.run.status)) {
        subscribeRun(runId, options)
      }

      loading.value = false
    }
  }

  /** Opens a run: makes it the active one and brings it up to date. */
  const openRun = async (
    runId: string,
    options: RunRequestOptions = {},
  ): Promise<void> => {
    activeRunId.value = runId
    await loadRun(runId, options)
  }

  const cancelRun = async (runId: string): Promise<boolean> => {
    if (cancelling.value) return false

    cancelling.value = true
    clearError()

    try {
      const run = await service.cancelRun(runId)

      // The terminal event arrives down the stream, so this is a reconciliation
      // rather than a second source of truth -- and when there is no stream to
      // carry that event, the snapshot is what tells the page. `loadRun` will
      // not let an answer older than a delivered event overwrite it.
      upsertRun(run)

      if (!controllers.has(runId)) {
        await loadRun(runId)
      }

      return true
    } catch (thrown) {
      error.value = toRunError(thrown, 'console.runs.errors.cancelFailed')
      return false
    } finally {
      cancelling.value = false
    }
  }

  /** Whether the project has anything runnable — what the empty state asks. */
  const canCreateRun = computed<boolean>(
    () =>
      agentStore.activePlan?.status === 'approved' &&
      agentStore.currentSpec !== null &&
      agentStore.currentSpecDocument !== null &&
      projectStore.activeEnvironment !== null,
  )

  return {
    // state
    runs,
    details,
    loading,
    listing,
    creating,
    cancelling,
    error,
    activeRunId,
    subscribedRunIds,

    // derived
    projectRuns,
    activeRun,
    activeDetail,
    canCreateRun,

    // actions
    createRun,
    loadRuns,
    loadRun,
    openRun,
    subscribeRun,
    unsubscribe,
    cancelRun,
    applyEvent,
    clearError,
  }
})

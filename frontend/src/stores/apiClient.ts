import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
import { ProxyTransportError } from '@/services/api/transport'
import { createTransport } from '@/services/transport'
import { ProjectNotReadyError, useProjectStore } from '@/stores/project'
import type {
  AgentHandoff,
  ApiAuth,
  ApiBody,
  ApiClientError,
  ApiCollection,
  ApiHistoryItem,
  ApiKeyValue,
  ApiRequestDraft,
  ApiResponse,
  ApiSavedRequest,
  HttpMethod,
} from '@/types/api'
import { sanitizeCollections, sanitizeHistory } from '@/utils/apiCollections'
import {
  createEmptyDraft,
  sanitizeDraft,
  withTrailingBlank,
} from '@/utils/apiDraft'
import { resolveDraft, type ResolutionFailureReason } from '@/utils/apiRequest'
import { createId } from '@/utils/id'

/**
 * Total sends retained, newest first.
 *
 * A single global cap rather than one per project: it bounds what localStorage
 * has to hold, and the panel only ever renders one project's slice anyway.
 */
const HISTORY_LIMIT = 50

const STORAGE = {
  draft: 'aiata.console.apiDraft',
  collections: 'aiata.console.collections',
  history: 'aiata.console.apiHistory',
} as const

const isAbortError = (thrown: unknown): boolean =>
  thrown instanceof DOMException && thrown.name === 'AbortError'

export interface SaveRequestInput {
  readonly name: string
  /**
   * Target collection name. Ignored when a saved request is already open —
   * saving an open request updates it where it lives rather than silently
   * moving it.
   */
  readonly collection?: string
}

/**
 * The API Client's single source of truth.
 *
 * Owns the draft, the response, and the saved/history lists; delegates the
 * network to a transport and all substitution to `resolveDraft`. Components
 * call actions and read computed state — none of them build a request by hand.
 */
export const useApiClientStore = defineStore('apiClient', () => {
  const projectStore = useProjectStore()
  const transport = createTransport()

  /* --- Persisted ---------------------------------------------------- */

  const draft = usePersistedRef<ApiRequestDraft>(
    STORAGE.draft,
    createEmptyDraft(),
    { parse: sanitizeDraft },
  )

  // Both start empty, and that is the product's answer for a browser that has
  // never saved anything: a console that opened with somebody else's sample
  // collections -- saved against a project the guest does not own -- would be
  // showing data as if it were theirs.  What `usePersistedRef` does is offer
  // these as the *fallback*: storage wins whenever the key holds anything it can
  // parse, so an existing user's lists are restored, not replaced.
  const collections = usePersistedRef<readonly ApiCollection[]>(
    STORAGE.collections,
    [],
    { parse: sanitizeCollections },
  )

  const history = usePersistedRef<readonly ApiHistoryItem[]>(
    STORAGE.history,
    [],
    { parse: sanitizeHistory },
  )

  /* --- Session ------------------------------------------------------ */

  const response = ref<ApiResponse | null>(null)
  const error = ref<ApiClientError | null>(null)
  const sending = ref(false)
  const lastSentAt = ref<string | null>(null)

  /**
   * The request handed to the agent, held until the AI Test Lab exists.
   * Deliberately inert in this phase: the seam is real, the consumer is not.
   */
  const handoff = ref<AgentHandoff | null>(null)

  const openRequestId = ref<string | null>(null)
  const openRequestName = ref('')

  let controller: AbortController | null = null

  /* --- Derived ------------------------------------------------------ */

  const projectId = computed(() => projectStore.activeProjectId)

  /**
   * Substitutions for the active environment.
   *
   * `baseUrl` is always present because a relative request path is meaningless
   * without one, and a user typing `{{baseUrl}}/orders` should not have to
   * define it by hand. Anything the user *did* define wins.
   */
  const variables = computed<Readonly<Record<string, string>>>(() => {
    const environment = projectStore.activeEnvironment
    if (environment === null) return {}

    return { baseUrl: environment.baseUrl, ...projectStore.variables }
  })

  const resolution = computed(() =>
    resolveDraft(
      draft.value,
      variables.value,
      projectStore.activeEnvironment?.baseUrl ?? '',
    ),
  )

  /** The request as it would go on the wire, or `null` if it cannot be built. */
  const resolvedRequest = computed(() =>
    resolution.value.ok ? resolution.value.request : null,
  )

  const unresolvedVariables = computed<readonly string[]>(() => {
    const outcome = resolution.value
    if (outcome.ok) return []
    return outcome.reason === 'unresolved-variables' ? outcome.names : []
  })

  const blockedReason = computed<ResolutionFailureReason | null>(() => {
    const outcome = resolution.value
    return outcome.ok ? null : outcome.reason
  })

  const projectCollections = computed(() =>
    collections.value.filter((collection) => collection.projectId === projectId.value),
  )

  const projectHistory = computed(() =>
    history.value.filter((item) => item.projectId === projectId.value),
  )

  const collectionNames = computed(() =>
    projectCollections.value.map((collection) => collection.name),
  )

  const hasOpenRequest = computed(() => openRequestId.value !== null)

  /* --- Draft editing ------------------------------------------------ */

  const setMethod = (method: HttpMethod): void => {
    draft.value = { ...draft.value, method }
  }

  const setUrl = (url: string): void => {
    draft.value = { ...draft.value, url }
  }

  // Every list edit is normalised to end in a blank row, so the editor can
  // rely on always having somewhere to put the caret.
  const setParams = (rows: readonly ApiKeyValue[]): void => {
    draft.value = { ...draft.value, params: withTrailingBlank(rows) }
  }

  const setHeaders = (rows: readonly ApiKeyValue[]): void => {
    draft.value = { ...draft.value, headers: withTrailingBlank(rows) }
  }

  const setAuth = (auth: ApiAuth): void => {
    draft.value = { ...draft.value, auth }
  }

  const patchAuth = (patch: Partial<ApiAuth>): void => {
    draft.value = { ...draft.value, auth: { ...draft.value.auth, ...patch } }
  }

  const setBody = (body: ApiBody): void => {
    draft.value = { ...draft.value, body }
  }

  const loadDraft = (source: ApiRequestDraft): void => {
    draft.value = {
      ...source,
      params: withTrailingBlank(source.params),
      headers: withTrailingBlank(source.headers),
    }
    response.value = null
    error.value = null
  }

  const newRequest = (): void => {
    draft.value = createEmptyDraft()
    response.value = null
    error.value = null
    lastSentAt.value = null
    openRequestId.value = null
    openRequestName.value = ''
  }

  /* --- Sending ------------------------------------------------------ */

  const toClientError = (reason: ResolutionFailureReason): ApiClientError =>
    reason === 'unresolved-variables'
      ? {
          kind: 'unresolved-variables',
          messageKey: 'console.apiClient.error.unresolvedVariables',
          params: { names: unresolvedVariables.value.join(', ') },
          variables: unresolvedVariables.value,
        }
      : {
          kind: 'missing-base-url',
          messageKey: 'console.apiClient.error.missingBaseUrl',
        }

  /**
   * The project this request will be addressed to, or a refusal to display.
   *
   * `requireReadyProjectId` is reused rather than re-implemented, and it is
   * awaited *before* the transport is handed anything: the proxy route is
   * project-scoped, and the id in that path has to be one the backend actually
   * listed for this guest.  An empty id, a leftover mock id, or an id belonging to
   * a replaced session fails the check — which is the point, because sending it
   * would produce a 404 the user would misread as "my project disappeared".
   *
   * This is not a security boundary.  The backend authorizes the caller against
   * the project again on every call; this only avoids making a request that is
   * known in advance to be refused.
   */
  const requireSendableProjectId = async (): Promise<string | null> => {
    try {
      return await projectStore.requireReadyProjectId()
    } catch (thrown) {
      error.value =
        thrown instanceof ProjectNotReadyError
          ? {
              kind: 'transport',
              messageKey: 'console.apiClient.error.projectNotReady',
            }
          : {
              kind: 'network',
              messageKey: 'console.apiClient.error.network',
            }

      return null
    }
  }

  const send = async (): Promise<void> => {
    if (sending.value) return

    const outcome = resolution.value
    if (!outcome.ok) {
      // Refuse rather than send a request with a literal `{{token}}` in it:
      // the far end would answer 401 and point the user at the wrong problem.
      error.value = toClientError(outcome.reason)
      return
    }

    // Resolved before `sending` is raised: asking the project store can itself
    // hit the backend, and a request that is never going to be sent should not
    // put the form into its in-flight state.  A refusal is reported and this
    // returns -- nothing is addressed to an unvalidated project.
    const readyProjectId = await requireSendableProjectId()
    if (readyProjectId === null) return

    sending.value = true
    error.value = null
    controller = new AbortController()

    // Snapshot: the user is free to keep editing while the request is in
    // flight, and history should record what was actually sent.
    const snapshot = draft.value

    try {
      const result = await transport.send({
        request: outcome.request,
        projectId: readyProjectId,
        signal: controller.signal,
      })

      response.value = result
      lastSentAt.value = result.receivedAt

      // No project, no attribution: the response still reaches the page, but a
      // history row filed under an empty id is a row nobody can find again.
      if (projectId.value === '') return

      history.value = [
        {
          id: createId('his'),
          projectId: projectId.value,
          method: snapshot.method,
          url: snapshot.url,
          status: result.status,
          timeMs: result.timeMs,
          sizeBytes: result.sizeBytes,
          at: result.receivedAt,
          draft: snapshot,
        },
        ...history.value,
      ].slice(0, HISTORY_LIMIT)
    } catch (thrown) {
      if (isAbortError(thrown)) {
        // Cancelled on purpose: leave the previous response on screen rather
        // than replacing it with an error the user caused deliberately.
      } else {
        // A real transport says *why* it failed -- a timeout, a refused address,
        // an unreachable target -- and those sentences are the whole point of the
        // error panel.  Anything else is an unknown failure and gets the generic
        // one; nothing thrown is ever rendered, so no internal detail escapes.
        error.value =
          thrown instanceof ProxyTransportError
            ? thrown.clientError
            : {
                kind: 'network',
                messageKey: 'console.apiClient.error.network',
              }
      }
    } finally {
      sending.value = false
      controller = null
    }
  }

  const cancel = (): void => {
    controller?.abort()
  }

  /* --- Collections -------------------------------------------------- */

  const findSavedRequest = (
    id: string,
  ): { readonly request: ApiSavedRequest; readonly folderId: string | null } | null => {
    for (const collection of collections.value) {
      const direct = collection.requests.find((item) => item.id === id)
      if (direct !== undefined) return { request: direct, folderId: null }

      for (const folder of collection.folders) {
        const nested = folder.requests.find((item) => item.id === id)
        if (nested !== undefined) return { request: nested, folderId: folder.id }
      }
    }

    return null
  }

  const openSavedRequest = (id: string): void => {
    const found = findSavedRequest(id)
    if (found === null) return

    loadDraft(found.request.draft)
    openRequestId.value = found.request.id
    openRequestName.value = found.request.name
  }

  const deleteSavedRequest = (id: string): void => {
    collections.value = collections.value.map((collection) => ({
      ...collection,
      folders: collection.folders.map((folder) => ({
        ...folder,
        requests: folder.requests.filter((item) => item.id !== id),
      })),
      requests: collection.requests.filter((item) => item.id !== id),
    }))

    if (openRequestId.value === id) {
      openRequestId.value = null
      openRequestName.value = ''
    }
  }

  /**
   * Saving is scoped to the active project, so it needs one.
   *
   * The lists are a single stored pool filtered by project id, which means an
   * empty id is not "unscoped" — it is a scope of its own, and a row written
   * under it belongs to no project the guest can ever open.  The console does not
   * show this page without a project, so this is the guard for the moment
   * initialisation has failed or is still running: the save is refused rather
   * than misfiled.
   */
  const saveRequest = (input: SaveRequestInput): void => {
    if (projectId.value === '') return

    const name =
      input.name.trim() !== ''
        ? input.name.trim()
        : `${draft.value.method} ${draft.value.url || '/'}`
    const savedAt = new Date().toISOString()

    if (openRequestId.value !== null) {
      const id = openRequestId.value

      collections.value = collections.value.map((collection) => ({
        ...collection,
        folders: collection.folders.map((folder) => ({
          ...folder,
          requests: folder.requests.map((item) =>
            item.id === id ? { ...item, name, draft: draft.value, savedAt } : item,
          ),
        })),
        requests: collection.requests.map((item) =>
          item.id === id ? { ...item, name, draft: draft.value, savedAt } : item,
        ),
      }))

      openRequestName.value = name
      return
    }

    const targetName = (input.collection ?? '').trim()
    const created: ApiSavedRequest = {
      id: createId('req'),
      name,
      draft: draft.value,
      savedAt,
    }

    const existing = collections.value.find(
      (collection) =>
        collection.projectId === projectId.value &&
        collection.name.toLowerCase() === targetName.toLowerCase(),
    )

    if (existing !== undefined) {
      collections.value = collections.value.map((collection) =>
        collection.id === existing.id
          ? { ...collection, requests: [...collection.requests, created] }
          : collection,
      )
    } else {
      const created2: ApiCollection = {
        id: createId('col'),
        projectId: projectId.value,
        // An unnamed target becomes a collection named after the request:
        // better than an unlabelled bucket the user cannot find again.
        name: targetName === '' ? name : targetName,
        folders: [],
        requests: [created],
      }
      collections.value = [...collections.value, created2]
    }

    openRequestId.value = created.id
    openRequestName.value = name
  }

  /* --- History ------------------------------------------------------ */

  const restoreFromHistory = (id: string): void => {
    const item = history.value.find((entry) => entry.id === id)
    if (item === undefined) return

    loadDraft(item.draft)
    // Restoring is not "opening": the draft is now unsaved, and Save should
    // create a new entry rather than overwrite whatever it came from.
    openRequestId.value = null
    openRequestName.value = ''
  }

  const clearHistory = (): void => {
    // The filter below would delete every row whose project id is empty, so an
    // unscoped clear is not a no-op — it is the one call that could remove rows
    // this console cannot attribute.  Refused instead.
    if (projectId.value === '') return

    history.value = history.value.filter(
      (item) => item.projectId !== projectId.value,
    )
  }

  /* --- Agent seam --------------------------------------------------- */

  const requestAgentHandoff = (): boolean => {
    const outcome = resolution.value
    if (!outcome.ok) {
      error.value = toClientError(outcome.reason)
      return false
    }

    handoff.value = {
      projectId: projectId.value,
      draft: draft.value,
      resolved: outcome.request,
      requestedAt: new Date().toISOString(),
    }

    return true
  }

  const clearHandoff = (): void => {
    handoff.value = null
  }

  const dismissError = (): void => {
    error.value = null
  }

  /**
   * Switching project clears everything that belonged to the previous one —
   * but not the draft, which is work in progress the user did not ask to lose.
   */
  watch(projectId, () => {
    response.value = null
    error.value = null
    lastSentAt.value = null
    openRequestId.value = null
    openRequestName.value = ''
  })

  return {
    draft,
    response,
    error,
    sending,
    lastSentAt,
    handoff,
    openRequestId,
    openRequestName,

    variables,
    resolution,
    resolvedRequest,
    unresolvedVariables,
    blockedReason,
    projectCollections,
    projectHistory,
    collectionNames,
    hasOpenRequest,

    setMethod,
    setUrl,
    setParams,
    setHeaders,
    setAuth,
    patchAuth,
    setBody,
    loadDraft,
    newRequest,

    send,
    cancel,
    dismissError,

    saveRequest,
    openSavedRequest,
    deleteSavedRequest,
    restoreFromHistory,
    clearHistory,

    requestAgentHandoff,
    clearHandoff,
  }
})

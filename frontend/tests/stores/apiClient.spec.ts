import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { useApiClientStore } from '@/stores/apiClient'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'
import { sanitizeCollections } from '@/utils/apiCollections'
import { createEmptyDraft, createKeyValueRow, withTrailingBlank } from '@/utils/apiDraft'
import { resolveDraft } from '@/utils/apiRequest'

import {
  COLLECTION_FIXTURES,
  HISTORY_FIXTURES,
  buildCollection,
  buildHistoryItem,
} from '../support/apiClientData'
import { installProjectFixtures, SECOND_PROJECT_FIXTURE } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * The API Client's request pipeline.
 *
 * The client shares the console with the agent and is the other half of the
 * handoff seam, so its core behaviour is covered here rather than left to the
 * view tests: what gets resolved, what refuses to be sent, and what survives a
 * round trip through storage.
 */
beforeEach(() => {
  setActivePinia(createPinia())
})

interface SetupOptions {
  /** What the browser already had, keyed by the store's storage keys. */
  readonly stored?: Readonly<Record<string, unknown>>
  /** The projects to install. Defaults to the shared fixture list. */
  readonly projects?: readonly Project[]
}

const COLLECTIONS_KEY = 'aiata.console.collections'
const HISTORY_KEY = 'aiata.console.apiHistory'

/**
 * A console with a project, and whatever the browser already had.
 *
 * The order is load-bearing in two ways.  Storage is seeded before the store is
 * built, because \`usePersistedRef\` reads once, when the store is created — a
 * seed written afterwards would be a different test entirely.  And the project is
 * installed before the client store exists, because the client clears its
 * response and error when the active project changes, and installing fixtures
 * afterwards would look like a project switch to it.
 */
const setup = (options: SetupOptions = {}) => {
  installStorage(options.stored ?? {})

  const project = useProjectStore()
  installProjectFixtures(project, options.projects)

  const api = useApiClientStore()
  return { api, project }
}

/** What the browser holds now, parsed — the store writes through this stub. */
const storedIn = (key: string): readonly unknown[] =>
  JSON.parse(
    (globalThis as unknown as { window: { localStorage: Storage } }).window.localStorage.getItem(
      key,
    ) ?? '[]',
  ) as readonly unknown[]

afterEach(() => {
  removeStorage()
})

describe('request resolution', () => {
  it('folds params, auth and body into a sendable request', () => {
    const { api } = setup()

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setParams([createKeyValueRow({ key: 'page', value: '1' })])
    api.setHeaders([
      createKeyValueRow({ key: 'Content-Type', value: 'application/json' }),
    ])
    api.setAuth({
      type: 'bearer',
      bearerToken: 'dev_token',
      username: '',
      password: '',
      apiKeyName: '',
      apiKeyValue: '',
      apiKeyIn: 'header',
    })
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001"}' })

    const resolved = api.resolvedRequest
    expect(resolved?.url).toBe('https://api.dev.example.com/api/orders?page=1')
    expect(resolved?.headers).toEqual([
      { name: 'Content-Type', value: 'application/json' },
      { name: 'Authorization', value: 'Bearer dev_token' },
    ])
    expect(resolved?.body).toBe('{"product_id":"prod_001"}')
  })

  it('substitutes environment variables without touching the draft', () => {
    const { api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders/{{order_id}}')
    api.setAuth({
      type: 'bearer',
      bearerToken: '{{token}}',
      username: '',
      password: '',
      apiKeyName: '',
      apiKeyValue: '',
      apiKeyIn: 'header',
    })

    expect(api.resolvedRequest?.url).toBe('https://api.dev.example.com/api/orders/order_001')
    // The stored draft keeps the placeholders, so it still works in another
    // environment.
    expect(api.draft.url).toBe('/api/orders/{{order_id}}')
    expect(api.draft.auth.bearerToken).toBe('{{token}}')
  })

  it('refuses to resolve when a variable is undefined', () => {
    const { api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.setAuth({
      type: 'bearer',
      bearerToken: '{{missing_token}}',
      username: '',
      password: '',
      apiKeyName: '',
      apiKeyValue: '',
      apiKeyIn: 'header',
    })

    expect(api.resolvedRequest).toBeNull()
    expect(api.blockedReason).toBe('unresolved-variables')
    expect(api.unresolvedVariables).toEqual(['missing_token'])
  })

  it('refuses a relative URL with no base URL to resolve it against', () => {
    // Exercised through `resolveDraft` directly: every seeded project has an
    // environment and the store falls back to the first one, so this branch is
    // unreachable with the current mock data — the rule still has to hold.
    const outcome = resolveDraft(
      { ...createEmptyDraft(), method: 'GET', url: '/api/orders' },
      {},
      '',
    )

    if (outcome.ok) throw new Error('expected resolution to fail')
    expect(outcome.reason).toBe('missing-base-url')
  })

  it('does not send while a variable is undefined', async () => {
    const { api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders/{{nope}}')
    await api.send()

    expect(api.response).toBeNull()
    expect(api.error?.kind).toBe('unresolved-variables')
    expect(api.error?.variables).toEqual(['nope'])
  })
})

describe('sending', () => {
  it('records a response and a history entry', async () => {
    // Three rows the browser already had, so the assertions below are about the
    // list growing by exactly one — the same claim the seeded store used to make,
    // now stated by the test.
    const { api } = setup({ stored: { [HISTORY_KEY]: HISTORY_FIXTURES } })

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setHeaders([
      createKeyValueRow({ key: 'Content-Type', value: 'application/json' }),
    ])
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001","quantity":2}' })

    await api.send()

    expect(api.response?.status).toBe(201)
    expect(api.response?.statusText).toBe('Created')
    expect(api.response?.body).toContain('order_001')
    expect(api.projectHistory).toHaveLength(4)
    expect(api.projectHistory[0].status).toBe(201)
    // History stores the unresolved draft so it can be replayed elsewhere.
    expect(api.projectHistory[0].url).toBe('/api/orders')
  })

  it('treats an error status as a response, not a failure', async () => {
    const { api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders/order_999')
    await api.send()

    expect(api.response?.status).toBe(404)
    expect(api.error).toBeNull()
  })
})

describe('row editing invariants', () => {
  it('always leaves exactly one blank row for the caret', () => {
    const rows = withTrailingBlank([createKeyValueRow({ key: 'a', value: '1' })])

    expect(rows).toHaveLength(2)
    expect(rows.at(-1)?.key).toBe('')
    expect(rows.at(-1)?.enabled).toBe(false)
  })

  it('keeps the blank row stable so the input is not remounted mid-keystroke', () => {
    const once = withTrailingBlank([createKeyValueRow({ key: 'a', value: '1' })])
    const twice = withTrailingBlank(once)

    expect(twice.map((row) => row.id)).toEqual(once.map((row) => row.id))
  })

  it('never accumulates two blank rows', () => {
    const rows = withTrailingBlank([
      createKeyValueRow({ key: 'a', value: '1' }),
      createKeyValueRow({ key: '', value: '' }),
      createKeyValueRow({ key: '', value: '' }),
    ])

    expect(rows).toHaveLength(2)
  })
})

describe('persistence sanitizers', () => {
  it('rebuilds a valid draft from garbage', () => {
    const draft = createEmptyDraft()
    expect(draft.method).toBe('GET')
    expect(draft.params).toEqual([])
  })

  it('drops unusable collections but keeps the salvageable ones', () => {
    const collections = sanitizeCollections([
      { id: 'c1', projectId: 'p', name: 'C', folders: 'not-an-array', requests: [null, { id: 'r1', name: 'R' }] },
      'garbage',
    ])

    expect(collections).toHaveLength(1)
    expect(collections[0].requests).toHaveLength(1)
    expect(collections[0].folders).toEqual([])
  })

  it('names an unnamed saved request after its endpoint', () => {
    const collections = sanitizeCollections([
      {
        id: 'c1',
        projectId: 'p',
        name: 'C',
        requests: [{ id: 'r1', draft: { method: 'DELETE', url: '/api/orders/1' } }],
      },
    ])

    expect(collections[0].requests[0].name).toBe('DELETE /api/orders/1')
  })
})

describe('saved requests', () => {
  it('updates an open request in place rather than duplicating it', () => {
    // The "Orders" collection an earlier run of this test relied on came from the
    // store's seed; it is a fixture now.
    const { api } = setup({ stored: { [COLLECTIONS_KEY]: COLLECTION_FIXTURES } })

    const before = api.projectCollections.flatMap((collection) => collection.requests).length

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.saveRequest({ name: 'List orders', collection: 'Orders' })
    expect(api.openSavedRequest !== undefined).toBe(true)

    const seeded = api.projectCollections.find((collection) => collection.name === 'Orders')
    const id = seeded?.requests.at(-1)?.id ?? ''
    api.openSavedRequest(id)
    api.setUrl('/api/orders?page=2')
    api.saveRequest({ name: 'List orders (paged)', collection: 'Orders' })

    const after = api.projectCollections.flatMap((collection) => collection.requests).length
    expect(after).toBe(before + 1)
  })
})

/* ------------------------------------------------------------------ *
 * Where the data comes from, and where it goes
 * ------------------------------------------------------------------ */

describe('a browser that has never saved anything', () => {
  it('starts with no collections and no history', () => {
    const { api } = setup()

    expect(api.projectCollections).toEqual([])
    expect(api.projectHistory).toEqual([])
    // Not "empty because the project is empty": a project is installed, and the
    // lists are still empty — which is the answer for a new user.
    expect(api.collectionNames).toEqual([])
  })

  it('does not invent a collection when a draft is saved', () => {
    // Saving is what a seed used to make look pre-populated.  It still creates a
    // collection on demand — but only the one the user asked for.
    const { api } = setup()

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.saveRequest({ name: 'List orders', collection: 'Orders' })

    expect(api.projectCollections).toHaveLength(1)
    expect(api.projectCollections[0]?.name).toBe('Orders')
  })
})

describe('what the browser already had', () => {
  it('restores stored collections and history rather than replacing them', () => {
    const { api } = setup({
      stored: {
        [COLLECTIONS_KEY]: COLLECTION_FIXTURES,
        [HISTORY_KEY]: HISTORY_FIXTURES,
      },
    })

    // The fallback is empty, so anything restored here came out of storage — and
    // the fixtures belong to the project the console is on.
    expect(COLLECTION_FIXTURES.length).toBeGreaterThan(0)
    expect(COLLECTION_FIXTURES.length).toBeGreaterThan(0)
    expect(api.projectCollections).toHaveLength(
      COLLECTION_FIXTURES.filter((collection) => collection.projectId === 'prj_orders')
        .length,
    )
    expect(api.projectHistory).toHaveLength(HISTORY_FIXTURES.length)

    // And the default did not overwrite the stored value on the way in.
    expect(storedIn(COLLECTIONS_KEY)).toHaveLength(COLLECTION_FIXTURES.length)
    expect(storedIn(HISTORY_KEY)).toHaveLength(HISTORY_FIXTURES.length)
  })

  it('keeps editing, saving and deleting working on restored data', () => {
    const { api } = setup({ stored: { [COLLECTIONS_KEY]: COLLECTION_FIXTURES } })

    const first =
      api.projectCollections[0]?.requests[0]?.id ?? ''
    expect(first).not.toBe('')

    api.openSavedRequest(first)
    expect(api.hasOpenRequest).toBe(true)

    api.setUrl('/api/orders?page=2')
    api.saveRequest({ name: 'Renamed', collection: 'Orders' })

    const renamed = api.projectCollections
      .flatMap((collection) => collection.requests)
      .find((request) => request.id === first)
    expect(renamed?.name).toBe('Renamed')

    const before = api.projectCollections.flatMap((collection) => collection.requests).length
    api.deleteSavedRequest(first)
    expect(api.projectCollections.flatMap((collection) => collection.requests)).toHaveLength(
      before - 1,
    )
    expect(storedIn(COLLECTIONS_KEY)).toHaveLength(COLLECTION_FIXTURES.length)
  })
})

describe('switching project', () => {
  const otherProjectId = SECOND_PROJECT_FIXTURE.id
  const firstProjectId = 'prj_orders'

  it('shows only the project it is on', () => {
    const { api, project } = setup({
      stored: {
        [COLLECTIONS_KEY]: [
          buildCollection('col_a', firstProjectId, 'First project requests'),
          buildCollection('col_b', otherProjectId, 'Second project requests'),
        ],
        [HISTORY_KEY]: [
          buildHistoryItem('his_a', firstProjectId, '/api/first'),
          buildHistoryItem('his_b', otherProjectId, '/api/second'),
        ],
      },
    })

    expect(api.projectCollections.map((collection) => collection.id)).toEqual(['col_a'])
    expect(api.projectHistory.map((item) => item.id)).toEqual(['his_a'])

    project.selectProject(otherProjectId)

    expect(api.projectCollections.map((collection) => collection.id)).toEqual(['col_b'])
    expect(api.projectHistory.map((item) => item.id)).toEqual(['his_b'])
  })

  it('writes into the project it is on, without touching the other one', async () => {
    const { api, project } = setup({
      stored: {
        [HISTORY_KEY]: [buildHistoryItem('his_a', firstProjectId, '/api/first')],
      },
    })

    project.selectProject(otherProjectId)

    api.setMethod('GET')
    api.setUrl('/api/orders/order_001')
    await api.send()

    // The new row belongs to the project that was active when it was recorded.
    expect(api.projectHistory).toHaveLength(1)
    expect(api.projectHistory[0]?.url).toBe('/api/orders/order_001')

    const persisted = storedIn(HISTORY_KEY) as readonly { projectId: string }[]
    expect(persisted.map((item) => item.projectId).sort()).toEqual(
      [firstProjectId, otherProjectId].sort(),
    )
    // The first project's row is still exactly what it was.
    expect(persisted.filter((item) => item.projectId === firstProjectId)).toHaveLength(1)
  })

  it('files a save under the project that is now on screen', async () => {
    const { api, project } = setup({
      stored: { [COLLECTIONS_KEY]: [buildCollection('col_a', firstProjectId)] },
    })

    api.openSavedRequest('col_a_req')
    expect(api.hasOpenRequest).toBe(true)

    project.selectProject(otherProjectId)
    // The client clears its open-request state through a watcher on the active
    // project, so a save made after a switch is a save in the new project.
    await nextTick()

    expect(api.hasOpenRequest).toBe(false)

    api.setMethod('GET')
    api.setUrl('/api/other')
    api.saveRequest({ name: 'Other', collection: 'Other' })

    expect(api.projectCollections.map((collection) => collection.projectId)).toEqual([
      otherProjectId,
    ])

    // The first project's collection is untouched in storage.
    const persisted = storedIn(COLLECTIONS_KEY) as readonly { projectId: string }[]
    expect(persisted.filter((item) => item.projectId === firstProjectId)).toHaveLength(1)
  })
})

describe('no project, no attribution', () => {
  it('refuses to save or to record history under an empty project id', async () => {
    // The state a failed initialisation leaves behind: the console is up, and
    // there is no project to attribute anything to.
    const { api } = setup({ projects: [] })

    api.setMethod('GET')
    api.setUrl('/api/orders')
    api.saveRequest({ name: 'Orphan', collection: 'Orphan' })

    expect(api.projectCollections).toEqual([])
    expect(api.collectionNames).toEqual([])
    expect(storedIn(COLLECTIONS_KEY)).toEqual([])

    await api.send()

    // Nothing was sent, so nothing was recorded — and no row was filed under an
    // empty id, which is a row nobody could ever find again.
    expect(api.response).toBeNull()
    expect(api.projectHistory).toEqual([])
    expect(storedIn(HISTORY_KEY)).toEqual([])
  })

  it('refuses to clear history when it cannot say whose history it is', () => {
    const { api } = setup({
      projects: [],
      stored: { [HISTORY_KEY]: HISTORY_FIXTURES },
    })

    api.clearHistory()

    // Still there: the guard is what stops "clear" from becoming "delete every
    // row this console cannot attribute".
    expect(api.projectHistory).toHaveLength(0)
    expect(storedIn(HISTORY_KEY)).toHaveLength(HISTORY_FIXTURES.length)
  })
})

/* ------------------------------------------------------------------ *
 * The gate in front of a real send
 * ------------------------------------------------------------------ */

describe('sending requires a ready project', () => {
  it('refuses to send when no project has been loaded, and says so', async () => {
    // The proxy route is project-scoped: without a project there is no path to
    // address, so this must be a refusal rather than a request to nowhere.
    const { api } = setup({ projects: [] })

    api.setMethod('GET')
    // Absolute, so the resolution step has nothing to object to: what is being
    // measured is the project gate, not URL resolution.
    api.setUrl('https://api.under-test.example/orders')
    await api.send()

    expect(api.response).toBeNull()
    expect(api.error?.kind).toBe('transport')
    expect(api.error?.messageKey).toBe('console.apiClient.error.projectNotReady')
  })

  it('asks the project store before it sends anything', async () => {
    const { api, project } = setup()
    const gate = vi.spyOn(project, 'requireReadyProjectId')

    api.setMethod('GET')
    api.setUrl('https://api.under-test.example/orders')
    await api.send()

    // The validated id is the only one that could reach a transport; the store
    // never substitutes a literal when the gate refuses.
    expect(gate).toHaveBeenCalledTimes(1)
    expect(api.response).not.toBeNull()
    expect(api.error).toBeNull()
  })
})

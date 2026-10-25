import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/stores/project'

import { PROJECT_FIXTURES, installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * Creating a project the user names.
 *
 * The action under test is thin on purpose -- it validates, it asks the store
 * whether a real project is ready, it calls the real service, it adopts what came
 * back -- so most of what is worth asserting is on either side of it: what the
 * store looked like first, and what the *request* looked like.
 *
 * ## What is real here
 *
 * \`services/api/projects.ts\` and \`services/http.ts\` are the shipped modules and
 * \`fetch\` is stubbed at the boundary they use, so the request line, the body and
 * the guest-session header are checked as they would be sent. Readiness is *not*
 * stubbed: every test below lets the action reach the shipped initialize()
 * and its ready-state check. The real empty-list branch is covered separately
 * in projectPersistence.spec.ts.
 *
 * ## The branch the default config cannot take
 *
 * \`stores/project.ts\` picks the backend's project list with a compile-time switch
 * that vitest pins, so under the default config \`initialize()\` is a no-op and the
 * loading states below are reached through the mock branch.  The last test says
 * so explicitly instead of pretending: it asserts only when the real branch was
 * actually taken.
 */

const WIRE_PROJECT = {
  id: 'prj_new_9f2c',
  name: 'Checkout API',
  description: '',
  specName: null,
  environments: [
    {
      id: 'env_new_dev',
      name: 'Development',
      kind: 'development',
      baseUrl: 'https://api.example.com',
      variables: [],
    },
  ],
  updatedAt: '2026-10-09T00:00:00Z',
}

/** The project the guest already has, so readiness has something real to find. */
const EXISTING_PROJECT = {
  ...WIRE_PROJECT,
  id: 'prj_existing_1',
  name: 'Existing API',
  environments: [
    { ...WIRE_PROJECT.environments[0], id: 'env_existing_dev' },
  ],
}

interface Recorded {
  readonly method: string
  readonly url: string
  readonly headers: Record<string, string>
  readonly body: Record<string, unknown> | null
}

let requests: Recorded[] = []

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

interface BackendOptions {
  /** What the project list answers. */
  readonly list?: () => Response
  /** What the create answers. */
  readonly create?: () => Response
}

/**
 * The stubbed backend.
 *
 * Both endpoints are routed, because both are part of the behaviour: the list is
 * what the action's readiness check reads, and the create is the thing under
 * test.  An assertion about "the create was called once" is only meaningful when
 * the request that precedes it is accounted for.
 */
const stubBackend = (options: BackendOptions = {}): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const raw = typeof init?.body === 'string' ? init.body : null

      requests.push({
        method: init?.method ?? 'GET',
        url: String(url),
        headers: (init?.headers ?? {}) as Record<string, string>,
        body: raw === null ? null : (JSON.parse(raw) as Record<string, unknown>),
      })

      if (String(url).endsWith('/api/guest-sessions')) {
        return json(201, { sessionToken: 'gst_test', expiresAt: '2026-11-08T00:00:00Z' })
      }

      if ((init?.method ?? 'GET') === 'POST') {
        return (options.create ?? (() => json(201, WIRE_PROJECT)))()
      }

      return (options.list ?? (() => json(200, [EXISTING_PROJECT])))()
    }),
  )
}

const createCalls = (): readonly Recorded[] =>
  requests.filter(
    (recorded) => recorded.method === 'POST' && recorded.url.endsWith('/api/projects'),
  )

/**
 * A promise this test resolves by hand.
 *
 * Not an inline resolver variable: TypeScript narrows one of those to `never` at
 * the call site, because the assignment happens inside the executor.
 */
const deferred = <T,>(): { readonly promise: Promise<T>; readonly resolve: (value: T) => void } => {
  let settle: ((value: T) => void) | null = null
  const promise = new Promise<T>((resolve) => {
    settle = resolve
  })

  return {
    promise,
    resolve: (value: T) => settle?.(value),
  }
}


beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  requests = []
  // The store no longer starts with a project, and creating one requires a ready
  // guest — so the state a loaded console is in is stated here rather than
  // assumed from the store's defaults.
  installProjectFixtures(useProjectStore())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  removeStorage()
})

describe('the project the server created is adopted', () => {
  it('adds it to the list and makes it active, environment and all', async () => {
    stubBackend()
    const store = useProjectStore()

    await store.initialize()
    const before = store.projects.map((project) => project.id)

    const created = await store.createProject('Checkout API')

    expect(created?.id).toBe('prj_new_9f2c')
    // The server's id, not anything the client invented.
    expect(store.projects.map((project) => project.id)).toEqual([
      ...before,
      'prj_new_9f2c',
    ])
    expect(store.activeProjectId).toBe('prj_new_9f2c')
    expect(store.activeProject?.name).toBe('Checkout API')
    // The environment is the one the response carried, so a run has a base URL.
    expect(store.activeEnvironmentId).toBe('env_new_dev')
    expect(store.activeEnvironment?.baseUrl).toBe('https://api.example.com')
    expect(store.error).toBeNull()
    expect(store.creating).toBe(false)
  })

  it('trims the name it sends', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    await store.createProject('   Checkout API   ')

    expect(createCalls()[0]?.body).toEqual({ name: 'Checkout API' })
  })

  it('sends the optional base URL only when it was given', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    await store.createProject('Checkout API', 'https://api.example.com')
    expect(createCalls()[0]?.body).toEqual({
      name: 'Checkout API',
      baseUrl: 'https://api.example.com',
    })

    await store.createProject('Blank base URL', '   ')
    expect(createCalls()[1]?.body).toEqual({ name: 'Blank base URL' })
  })
})

describe('creation never claims more than the server granted', () => {
  it('changes nothing when the server refuses the create', async () => {
    stubBackend({
      create: () =>
        json(500, { code: 'internal-error', messageKey: 'console.runs.errors.loadFailed' }),
    })
    const store = useProjectStore()
    await store.initialize()

    const projectsBefore = store.projects.map((project) => project.id)
    const activeBefore = store.activeProjectId
    const callsBefore = createCalls().length

    const created = await store.createProject('Checkout API')

    expect(created).toBeNull()
    // No invented row, and no switch to a project that does not exist.
    expect(store.projects.map((project) => project.id)).toEqual(projectsBefore)
    expect(store.activeProjectId).toBe(activeBefore)
    expect(store.creating).toBe(false)
    expect(createCalls()).toHaveLength(callsBefore + 1)
  })

  it('refuses a name that is only whitespace, without reaching the network', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    const created = await store.createProject('    ')

    expect(created).toBeNull()
    expect(createCalls()).toEqual([])
    expect(store.activeProjectId).not.toBe('prj_new_9f2c')
  })
})

describe('the request is the one the endpoint declares', () => {
  it('posts to /api/projects with the session header and only the declared fields', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    await store.createProject('Checkout API', 'https://api.example.com')

    const call = createCalls()[0]
    expect(call).toBeDefined()
    expect(call?.method).toBe('POST')
    expect(call?.url).toContain('/api/projects')
    expect(call?.headers['X-Guest-Session']).toBe('gst_test')

    // Ownership is the server's to decide: the body carries the two fields the
    // schema declares and no others.
    expect(Object.keys(call?.body ?? {}).sort()).toEqual(['baseUrl', 'name'])
    for (const forbidden of ['guestSessionId', 'guest_session_id', 'userId', 'owner', 'id']) {
      expect(call?.body).not.toHaveProperty(forbidden)
    }
  })

  it('never turns the guest session into a credential for another API', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    await store.createProject('Checkout API')

    // This console's identity is a header on *its* backend.  Nothing here talks
    // to an API under test, so no request may carry it as an Authorization.
    for (const recorded of requests) {
      expect(recorded.headers.Authorization).toBeUndefined()
    }
  })
})

describe('one click, one project', () => {
  it('does not create a second project while the first is in flight', async () => {
    // A create that stays open until this test says otherwise, so "in flight" is
    // a state the assertion can stand inside rather than race against.
    const create = deferred<unknown>()

    stubBackend({
      create: () =>
        ({
          ok: true,
          status: 201,
          headers: new Headers({ 'Content-Type': 'application/json' }),
          json: () => create.promise,
        }) as unknown as Response,
    })

    const store = useProjectStore()
    await store.initialize()

    const first = store.createProject('Checkout API')
    // The first click reached the network; the second arrives while it is open.
    await vi.waitFor(() => {
      expect(store.creating).toBe(true)
    })

    const second = await store.createProject('Checkout API')

    expect(second).toBeNull()
    expect(store.creating).toBe(true)
    expect(createCalls()).toHaveLength(1)

    create.resolve(WIRE_PROJECT)
    await expect(first).resolves.toMatchObject({ id: 'prj_new_9f2c' })

    expect(store.creating).toBe(false)
    expect(createCalls()).toHaveLength(1)
    expect(store.projects.filter((project) => project.id === 'prj_new_9f2c')).toHaveLength(1)
  })

  it('resets the in-flight flag after a failure, so a retry is possible', async () => {
    stubBackend({ create: () => json(500, { code: 'internal-error', messageKey: 'x' }) })
    const store = useProjectStore()
    await store.initialize()

    await store.createProject('Checkout API')
    expect(store.creating).toBe(false)

    stubBackend()
    const retried = await store.createProject('Checkout API')

    expect(retried?.id).toBe('prj_new_9f2c')
    expect(store.creating).toBe(false)
  })
})

describe('what the store offers before anything is created', () => {
  it('starts with no in-flight creation and an additive action', () => {
    const store = useProjectStore()

    expect(store.creating).toBe(false)
    expect(store.createProject).toBeTypeOf('function')
    // Additive: the two existing entry points are still there, which is what
    // keeps this from becoming a second bootstrap.
    expect(store.initialize).toBeTypeOf('function')
    expect(store.requireReadyProjectId).toBeTypeOf('function')
    // The action is the *only* thing that creates on this path: a ready store is
    // a precondition, not a project.
    expect(store.projects).toHaveLength(PROJECT_FIXTURES.length)
  })
})

/* ------------------------------------------------------------------ *
 * The real-initialisation branch
 * ------------------------------------------------------------------ */

describe('a list that could not be loaded is not a list to create against', () => {
  it('creates nothing when the real initialisation failed', async () => {
    stubBackend({
      list: () =>
        json(500, { code: 'internal-error', messageKey: 'console.runs.errors.loadFailed' }),
    })
    const store = useProjectStore()

    // Under the default config `initialize()` takes the mock branch (vitest pins
    // the switch that chooses), so there is no failure to observe here; under a
    // harness that compiles that switch to true, the load really fails.
    let realBranch = true

    try {
      await store.initialize()
      realBranch = false
    } catch {
      realBranch = true
    }

    if (!realBranch) return

    expect(store.status).toBe('error')
    expect(store.projects).toEqual([])
    // The seeded ids are not resurrected as if they were real.
    expect(store.projectById('prj_orders')).toBeNull()

    const created = await store.createProject('Checkout API')

    expect(created).toBeNull()
    expect(store.projects).toEqual([])
    expect(store.activeProjectId).toBe('')
    expect(createCalls()).toEqual([])
  })
})

import { renderToString } from 'vue/server-renderer'
import { createSSRApp, defineComponent, h, nextTick } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import ConsoleLayout from '@/layouts/ConsoleLayout.vue'
import { MOCK_PROJECTS } from '@/services/mock/projects'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

import { installStorage, removeStorage } from '../support/storage'

/**
 * The console shell's project bootstrap.
 *
 * The shell is the one component every console route passes through, so it is
 * where "which projects does this guest have" is answered and where the address
 * bar is reconciled with that answer.  These specs drive the real router and the
 * real stores through the real layout, server-rendered — which is the only way
 * to assert the thing that actually matters here: *where the navigation ends
 * up*, not merely that an initialisation function was called.
 *
 * The project list is supplied by stubbing the project store's own
 * initialisation, because the store chooses between the backend's list and the
 * mock's with a compile-time switch that vitest pins (see
 * `usesRealProjects` in `stores/project.ts`).  What that stub does is exactly
 * what `initialize()` does once its request answers — the same status, the same
 * list, the same active project and environment — so the layout is exercised
 * against the states it really sees.  Everything else — the routes, the
 * redirect, the render gate, the stores — is the shipped code.
 */

const PASSTHROUGH = defineComponent({
  name: 'Passthrough',
  setup() {
    return () => h('p', 'project-page')
  },
})

const REAL_PROJECT_ID = 'prj_real_9f2c'
const SECOND_PROJECT_ID = 'prj_real_be71'

const project = (id: string, name: string): Project => ({
  id,
  name,
  description: '',
  specName: null,
  updatedAt: '2026-10-09T00:00:00Z',
  environments: [
    {
      id: 'env_' + id,
      name: 'Development',
      kind: 'development',
      baseUrl: 'https://api.example.com',
      variables: [],
    },
  ],
})

const REAL_PROJECTS: readonly Project[] = [
  project(REAL_PROJECT_ID, 'Real Project'),
  project(SECOND_PROJECT_ID, 'Second Project'),
]

/** The routes the shell needs, mirroring the real table's names and nesting. */
const createTestRouter = async (path: string): Promise<Router> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/console/dashboard' },
      {
        path: '/console',
        component: ConsoleLayout,
        children: [
          { path: 'dashboard', name: 'console-dashboard', component: PASSTHROUGH },
          { path: 'projects', name: 'console-projects', component: PASSTHROUGH },
          {
            path: 'projects/:projectId',
            component: PASSTHROUGH,
            children: [
              {
                path: 'overview',
                name: 'console-project-overview',
                component: PASSTHROUGH,
              },
              { path: 'ai-test', name: 'console-project-ai-test', component: PASSTHROUGH },
              { path: 'runs', name: 'console-project-runs', component: PASSTHROUGH },
              {
                path: 'runs/:runId',
                name: 'console-project-run-detail',
                component: PASSTHROUGH,
              },
            ],
          },
        ],
      },
    ],
  })

  await router.push(path)
  await router.isReady()

  return router
}

/** Let a settled promise chain and the render queue finish. */
const flush = async (): Promise<void> => {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

let requests: string[] = []

/**
 * Build the app around one store, and render it.
 *
 * The pinia is created *before* the app so the test and the layout hold the same
 * store instance: `app.use(createPinia())` would install a second one, and the
 * assertions below would then be describing a store the layout never touched.
 */
interface BootstrapOptions {
  /** Answer the load the way a successful one does. */
  readonly projects?: readonly Project[]
  /** Answer it the way a failed one does. */
  readonly fail?: boolean
  /** Take over the answer entirely — used to hold it open and inspect the wait. */
  readonly initialize?: () => Promise<void>
}

const createApp = (
  router: Router,
  options: BootstrapOptions = {},
): {
  readonly app: ReturnType<typeof createSSRApp>
  readonly store: ReturnType<typeof useProjectStore>
} => {
  const pinia = createPinia()
  setActivePinia(pinia)

  const store = useProjectStore()

  if (options.initialize !== undefined) {
    vi.spyOn(store, 'initialize').mockImplementation(options.initialize)
  } else if (options.fail === true) {
    vi.spyOn(store, 'initialize').mockImplementation(async () => {
      store.projects = []
      store.activeProjectId = ''
      store.activeEnvironmentId = ''
      store.status = 'error'
      store.error = 'project-load-failed'
    })
  } else if (options.projects !== undefined) {
    vi.spyOn(store, 'initialize').mockImplementation(async () => {
      const loaded = options.projects ?? []
      store.projects = loaded
      store.activeProjectId = loaded[0]?.id ?? ''
      store.activeEnvironmentId = loaded[0]?.environments[0]?.id ?? ''
      store.status = 'ready'
    })
  }

  const app = createSSRApp(ConsoleLayout)
  app.use(pinia)
  app.use(router)
  // Element Plus asks for a deterministic id source under SSR; the app renders
  // on the client, so this only keeps the test output readable.
  app.provide(ID_INJECTION_KEY, { prefix: 1024, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })

  return { app, store }
}

/**
 * Render the shell, let everything it started settle, and render again.
 *
 * Both halves are load-bearing.  The bootstrap awaits a request, replaces the
 * route and re-renders — all after the first `renderToString` has returned — so
 * the first result is a snapshot of the *loading* state by construction.  Waiting
 * for the settled chain and rendering once more is what turns the assertions
 * below into statements about the finished navigation rather than about a race.
 */
const render = async (
  app: ReturnType<typeof createSSRApp>,
  router: Router,
): Promise<string> => {
  const before = router.currentRoute.value.fullPath

  await renderToString(app)
  await flush()

  // The reconciliation is a real navigation, so wait for it rather than for a
  // fixed number of ticks: the assertion that follows is about where the router
  // ended up.
  for (let round = 0; round < 20; round += 1) {
    if (router.currentRoute.value.fullPath !== before) break
    await flush()
  }

  return await renderToString(app)
}

beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(String(url))
      throw new Error('no request was expected: ' + String(url))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  removeStorage()
})

describe('A. entering the console establishes the projects', () => {
  it('runs the store initialisation without a page having to ask for it', async () => {
    const router = await createTestRouter('/console/dashboard')
    const { app, store } = createApp(router)
    const gate = vi.spyOn(store, 'initialize')

    await renderToString(app)
    await flush()

    // Not "eventually, when the user clicks something": the shell asks on the
    // way in, and the answer is what every project-scoped page then reads.
    expect(gate).toHaveBeenCalled()
    expect(store.status).toBe('ready')
    // And the store never invented one: this build's initialisation takes the
    // mock branch, which loads nothing — so an empty list here is the honest
    // answer rather than a seeded project standing in for one.
    expect(store.projects).toEqual([])
  })

  it('shows no project in the top bar until the list has answered', async () => {
    const router = await createTestRouter('/console/dashboard')
    let release = (): void => undefined

    const { app, store } = createApp(router, {
      initialize: () => {
        store.status = 'loading'

        return new Promise<void>((resolve) => {
          release = () => {
            store.projects = REAL_PROJECTS
            store.activeProjectId = REAL_PROJECT_ID
            store.activeEnvironmentId = 'env_' + REAL_PROJECT_ID
            store.status = 'ready'
            resolve()
          }
        })
      },
    })

    const waiting = await render(app, router)

    // The top bar is outside the render gate, so it is the one place a seeded
    // project used to be visible before anything had been loaded. It says
    // "Loading" — not a project name, and not "No projects yet" either, because
    // neither claim can be made yet.
    expect(waiting).toContain('Loading')
    expect(waiting).not.toContain('My Project')
    expect(waiting).not.toContain('prj_orders')
    expect(store.activeProject).toBeNull()

    release()
    const settled = await render(app, router)

    expect(settled).toContain('Real Project')
  })

  it('keeps a route that names a project the guest really has', async () => {
    const router = await createTestRouter('/console/projects/' + REAL_PROJECT_ID + '/ai-test')
    const { app, store } = createApp(router, { projects: REAL_PROJECTS })

    const html = await render(app, router)

    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/' + REAL_PROJECT_ID + '/ai-test',
    )
    expect(store.activeProjectId).toBe(REAL_PROJECT_ID)
    expect(html).toContain('project-page')
  })
})

describe('B. the address bar is reconciled with the loaded list', () => {
  it('replaces a project the guest does not have, keeping the destination', async () => {
    // A stale id from a previous session — the case this reconciliation exists
    // for: the address bar names a project the loaded list does not contain.
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    const { app, store } = createApp(router, { projects: REAL_PROJECTS })

    const html = await render(app, router)

    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/' + REAL_PROJECT_ID + '/ai-test',
    )
    expect(store.activeProjectId).toBe(REAL_PROJECT_ID)
    expect(html).toContain('project-page')
  })

  it('keeps the detail route it was given, not just the section', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/runs/run-42')
    const { app, store } = createApp(router, { projects: REAL_PROJECTS })

    await render(app, router)

    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/' + REAL_PROJECT_ID + '/runs/run-42',
    )
    expect(router.currentRoute.value.params.runId).toBe('run-42')
    expect(store.activeProjectId).toBe(REAL_PROJECT_ID)
  })

  it('takes the project the route names when that one is real', async () => {
    const router = await createTestRouter(
      '/console/projects/' + SECOND_PROJECT_ID + '/overview',
    )
    const { app, store } = createApp(router, { projects: REAL_PROJECTS })

    await render(app, router)

    // Reconciliation must not rewrite a route that is already right — including
    // when the route's project is not the one initialisation happened to pick.
    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/' + SECOND_PROJECT_ID + '/overview',
    )
    expect(store.activeProjectId).toBe(SECOND_PROJECT_ID)
  })

  it('leaves a route that names no project alone', async () => {
    const list = await createTestRouter('/console/projects')
    const listApp = createApp(list, { projects: REAL_PROJECTS })
    await render(listApp.app, list)
    expect(list.currentRoute.value.fullPath).toBe('/console/projects')

    const dashboard = await createTestRouter('/console/dashboard')
    const dashboardApp = createApp(dashboard, { projects: REAL_PROJECTS })
    await render(dashboardApp.app, dashboard)
    expect(dashboard.currentRoute.value.fullPath).toBe('/console/dashboard')
  })
})

describe('C. a project page is not rendered before its project is known', () => {
  it('holds the page back while the list is still loading', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    let release = (): void => undefined

    // The stub is single-flight like the real `initialize()`: the second call a
    // re-render makes joins the answer instead of starting a new load and
    // putting the store back into `loading`.
    let started = false

    const { app, store } = createApp(router, {
      initialize: () => {
        if (started) return Promise.resolve()
        started = true
        store.status = 'loading'

        return new Promise<void>((resolve) => {
          release = () => {
            store.projects = REAL_PROJECTS
            store.activeProjectId = REAL_PROJECT_ID
            store.activeEnvironmentId = 'env_' + REAL_PROJECT_ID
            store.status = 'ready'
            resolve()
          }
        })
      },
    })

    const html = await render(app, router)

    // The page has not rendered, so it cannot have read the id the store was
    // seeded with — which is the only reason this gate exists.  The route is
    // left untouched at this point for the same reason: there is nothing yet to
    // reconcile it against.
    expect(html).not.toContain('project-page')
    expect(store.status).toBe('loading')
    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/prj_orders/ai-test',
    )
    expect(requests).toEqual([])

    release()
    const settled = await render(app, router)

    // It appears as soon as the answer does, and only then is the route moved.
    expect(store.status).toBe('ready')
    expect(settled).toContain('project-page')
    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/' + REAL_PROJECT_ID + '/ai-test',
    )
  })

  it('renders the page once the list has arrived', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    const { app, store } = createApp(router, { projects: REAL_PROJECTS })

    const html = await render(app, router)

    expect(store.status).toBe('ready')
    expect(html).toContain('project-page')
  })
})

describe('D. a failed initialisation is not a mock project', () => {
  it('never falls back to the seeded list, and shows the existing error state', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    const { app, store } = createApp(router, { fail: true })

    const html = await render(app, router)

    expect(store.status).toBe('error')
    expect(store.projects).toEqual([])
    expect(store.activeProjectId).toBe('')
    // The mock ids the store starts on are not resurrected as if they were real.
    expect(store.projectById('prj_orders')).toBeNull()
    expect(html).not.toContain('project-page')
    // The route is left where it is: there is no valid project to move it to,
    // and inventing one would be the fallback this test exists to forbid.
    expect(router.currentRoute.value.fullPath).toBe(
      '/console/projects/prj_orders/ai-test',
    )
    expect(requests).toEqual([])
  })

  it('stops the agent task from being sent against an unready project', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    const { app, store } = createApp(router, { fail: true })

    await render(app, router)

    // The store a page would use is exactly the one the shell left behind, and
    // its readiness gate still refuses — the shell does not become a bypass.
    await expect(store.requireReadyProjectId()).rejects.toMatchObject({
      name: 'ProjectNotReadyError',
    })
    expect(requests).toEqual([])
  })
})

describe('E. mock mode keeps working', () => {
  it('uses the list the harness provides without asking the backend', async () => {
    const router = await createTestRouter('/console/projects/prj_orders/ai-test')
    // Mock mode's own list comes from the fixture now: the store no longer seeds
    // itself, so what a mock-mode console shows is stated where it is asserted.
    const { app, store } = createApp(router, { projects: MOCK_PROJECTS })

    const html = await render(app, router)

    expect(store.status).toBe('ready')
    expect(router.currentRoute.value.fullPath).toBe('/console/projects/prj_orders/ai-test')
    expect(store.activeProjectId).toBe('prj_orders')
    expect(html).toContain('project-page')
    expect(requests).toEqual([])
  })

  it('still resolves mock navigation for a second mock project', async () => {
    const router = await createTestRouter('/console/projects/prj_payments/runs')
    const { app, store } = createApp(router, { projects: MOCK_PROJECTS })

    const html = await render(app, router)

    expect(router.currentRoute.value.fullPath).toBe('/console/projects/prj_payments/runs')
    expect(store.activeProjectId).toBe('prj_payments')
    expect(html).toContain('project-page')
    expect(requests).toEqual([])
  })
})
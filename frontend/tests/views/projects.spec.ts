import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import {
  PROJECT_BASE_URL_MAX,
  PROJECT_NAME_MAX,
  useProjectCreationForm,
} from '@/composables/useProjectCreationForm'
import { useProjectStore } from '@/stores/project'
import ProjectsView from '@/views/console/ProjectsView.vue'

import { installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * Creating a project from the projects page.
 *
 * Two halves, deliberately in one file because they are one feature:
 *
 * * what the *page* offers — its create entry, rendered through the real view,
 *   which is also what catches the entry being unbound from the store;
 * * what the *form* does — the rules and the chain behind the dialog's confirm
 *   button, asserted through \`useProjectCreationForm\`, which is exactly what the
 *   dialog calls.
 *
 * The chain is real end to end: the form calls the shipped store action, which
 * calls the shipped service, which goes through the shipped HTTP layer with
 * \`fetch\` stubbed at that boundary. Readiness is not stubbed either — every
 * case here reaches the shipped initialize() and its ready-state check.
 *
 * The interactive half is asserted at the seam rather than through synthetic DOM
 * events: the suite runs in the \`node\` environment (see vitest.config.ts, which
 * keeps jsdom out of the tree), so a mounted Element Plus dialog cannot be driven
 * the way a browser drives it without inventing a DOM the project does not ship.
 */

/* ------------------------------------------------------------------ *
 * Fixtures
 * ------------------------------------------------------------------ */

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

const EXISTING_PROJECT = {
  ...WIRE_PROJECT,
  id: 'prj_existing_1',
  name: 'Existing API',
  environments: [{ ...WIRE_PROJECT.environments[0], id: 'env_existing_dev' }],
}

interface Recorded {
  readonly method: string
  readonly url: string
  readonly body: Record<string, unknown> | null
}

let requests: Recorded[] = []

const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const stubBackend = (options: { create?: () => Response } = {}): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const raw = typeof init?.body === 'string' ? init.body : null
      const method = init?.method ?? 'GET'

      requests.push({
        method,
        url: String(url),
        body: raw === null ? null : (JSON.parse(raw) as Record<string, unknown>),
      })

      if (String(url).endsWith('/api/guest-sessions')) {
        return jsonResponse(201, {
          sessionToken: 'gst_test',
          expiresAt: '2026-11-08T00:00:00Z',
        })
      }

      if (method === 'POST') return (options.create ?? (() => jsonResponse(201, WIRE_PROJECT)))()

      return jsonResponse(200, [EXISTING_PROJECT])
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


const textOf = (html: string): string =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

const router = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects', name: 'console-projects', component: { template: '<div />' } },
      {
        path: '/console/projects/:projectId/overview',
        name: 'console-project-overview',
        component: { template: '<div />' },
      },
    ],
  })

  await instance.push('/console/projects')
  await instance.isReady()

  return instance
}

/**
 * The page as the browser first draws it.
 *
 * Server-rendered, the way every other view spec in this repository renders a
 * view: the store, the dictionary and the components are all real, and what is
 * asserted is the HTML a user would be looking at.
 */
const renderPage = async (
  pinia: ReturnType<typeof createPinia>,
): Promise<string> => {
  const app = createSSRApp(ProjectsView)
  app.use(pinia)
  app.use(await router())
  // Element Plus asks for deterministic id and z-index sources under SSR; the
  // app renders on the client, so these only keep the output readable.
  app.provide(ID_INJECTION_KEY, { prefix: 1024, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })

  return await renderToString(app)
}

beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  requests = []
  // A loaded console, stated rather than assumed: the store starts empty now, and
  // creating a project is only allowed against a list that was really loaded.
  installProjectFixtures(useProjectStore())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  removeStorage()
})

/* ------------------------------------------------------------------ *
 * The entry the page offers
 * ------------------------------------------------------------------ */

describe('the page offers a way to create a project', () => {
  it('shows the create entry beside a list that already has projects', async () => {
    stubBackend()
    const pinia = createPinia()
    setActivePinia(pinia)
    useProjectStore().projects = [EXISTING_PROJECT] as never

    const html = await renderPage(pinia)
    const text = textOf(html)

    expect(text).toContain('New project')
    // The list is still the list: the entry is added, nothing is replaced.
    expect(text).toContain('Existing API')
    expect(html).toContain('aria-label="Delete project"')
  })

  it('still offers it when there is nothing to list', async () => {
    stubBackend()
    const pinia = createPinia()
    setActivePinia(pinia)
    useProjectStore().projects = []

    const text = textOf(await renderPage(pinia))

    // The empty state is the moment the entry matters most: a page whose whole
    // content says "no projects yet" must not stop there.
    expect(text).toContain('No projects yet')
    expect(text).toContain('New project')
  })
})

describe('what the form will and will not submit', () => {
  it('refuses a name that is empty or only whitespace, without asking the server', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()
    const form = useProjectCreationForm()

    expect(form.canSubmit.value).toBe(false)

    form.name.value = '   '
    expect(form.canSubmit.value).toBe(false)
    await expect(form.submit()).resolves.toBeNull()
    expect(createCalls()).toEqual([])
  })

  it('trims the name it sends', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()
    const form = useProjectCreationForm()

    form.name.value = '  Checkout API  '
    expect(form.trimmedName.value).toBe('Checkout API')

    await expect(form.submit()).resolves.toBe('prj_new_9f2c')
    expect(createCalls()[0]?.body).toEqual({ name: 'Checkout API' })
  })

  it('sends the base URL only when there is one', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    const withUrl = useProjectCreationForm()
    withUrl.name.value = 'Checkout API'
    withUrl.baseUrl.value = 'https://api.example.com'
    await withUrl.submit()
    expect(createCalls()[0]?.body).toEqual({
      name: 'Checkout API',
      baseUrl: 'https://api.example.com',
    })

    const withoutUrl = useProjectCreationForm()
    withoutUrl.name.value = 'Second API'
    withoutUrl.baseUrl.value = '   '
    await withoutUrl.submit()
    expect(createCalls()[1]?.body).toEqual({ name: 'Second API' })
  })

  it('knows the wire limits it is drawing against', () => {
    // The dialog binds these to the inputs; the server enforces the same two.
    expect(PROJECT_NAME_MAX).toBe(200)
    expect(PROJECT_BASE_URL_MAX).toBe(1000)
  })
})

describe('a successful submit hands back the server id', () => {
  it('returns the id, and the store has already adopted the project', async () => {
    stubBackend()
    const store = useProjectStore()
    await store.initialize()

    const before = store.projects.map((project) => project.id)
    const form = useProjectCreationForm()
    form.name.value = 'Checkout API'

    const projectId = await form.submit()

    expect(projectId).toBe('prj_new_9f2c')
    expect(store.projects.map((project) => project.id)).toEqual([
      ...before,
      'prj_new_9f2c',
    ])
    // Which is what lets the page navigate: the project is active before the
    // route changes, so the address bar and the store cannot disagree.
    expect(store.activeProjectId).toBe('prj_new_9f2c')
    expect(store.activeEnvironmentId).toBe('env_new_dev')
  })
})

describe('a refused submit leaves the store where it was', () => {
  it('answers null and changes nothing', async () => {
    stubBackend({
      create: () =>
        jsonResponse(500, {
          code: 'internal-error',
          messageKey: 'console.runs.errors.loadFailed',
        }),
    })
    const store = useProjectStore()
    await store.initialize()

    const projectsBefore = store.projects.map((project) => project.id)
    const activeBefore = store.activeProjectId
    const form = useProjectCreationForm()
    form.name.value = 'Checkout API'

    await expect(form.submit()).resolves.toBeNull()

    expect(store.projects.map((project) => project.id)).toEqual(projectsBefore)
    expect(store.activeProjectId).toBe(activeBefore)
    // The form is usable again, so the user can retry rather than being stuck.
    expect(form.submitting.value).toBe(false)
    expect(form.canSubmit.value).toBe(true)
  })
})

describe('one submit at a time', () => {
  it('refuses a second submit while the first is in flight', async () => {
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
    const form = useProjectCreationForm()
    form.name.value = 'Checkout API'

    const first = form.submit()
    await vi.waitFor(() => {
      expect(form.submitting.value).toBe(true)
    })

    // The control is disabled while this is true — and even a click that got
    // through would not become a second project.
    expect(form.canSubmit.value).toBe(false)
    await expect(form.submit()).resolves.toBeNull()
    expect(createCalls()).toHaveLength(1)

    create.resolve(WIRE_PROJECT)
    await expect(first).resolves.toBe('prj_new_9f2c')
    expect(createCalls()).toHaveLength(1)
  })
})
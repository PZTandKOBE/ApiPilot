import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getProjectSpec } from '@/services/api/projects'
import { resetSessionForTests } from '@/services/session'
import { useProjectStore } from '@/stores/project'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * Project and environment writes through the real store and HTTP layer.
 *
 * fetch is stubbed at the boundary, so the assertions cover the request line,
 * the JSON body and what the store adopts from the response. The backend's
 * project response intentionally omits variable values; the store must keep
 * the variables it already had when applying a partial edit response.
 */
const PROJECT_ID = FIRST_PROJECT_FIXTURE.id
const ENVIRONMENT_ID = FIRST_PROJECT_FIXTURE.environments[0]!.id

interface Recorded {
  readonly method: string
  readonly url: string
  readonly body: Record<string, unknown> | null
}

let requests: Recorded[] = []
let patchProject: (body: Record<string, unknown>) => Response
let patchEnvironment: (body: Record<string, unknown>) => Response
let createEnvironment: (body: Record<string, unknown>) => Response
let getSpecResponse: () => Response

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const wireProject = (overrides: Record<string, unknown> = {}) => ({
  id: PROJECT_ID,
  name: FIRST_PROJECT_FIXTURE.name,
  description: FIRST_PROJECT_FIXTURE.description,
  specName: FIRST_PROJECT_FIXTURE.specName,
  environments: FIRST_PROJECT_FIXTURE.environments.map((environment) => ({
    id: environment.id,
    name: environment.name,
    kind: environment.kind,
    baseUrl: environment.baseUrl,
    variables: [],
  })),
  updatedAt: '2026-10-22T12:00:00.000Z',
  ...overrides,
})

const wireSpec = {
  id: 'spec_orders_1234',
  name: 'Orders API',
  filename: 'orders-openapi.json',
  specType: 'openapi-3',
  contentFormat: 'json',
  version: '1.0.0',
  source: 'upload',
  endpointCount: 12,
  createdAt: '2026-10-20T12:00:00.000Z',
  updatedAt: '2026-10-21T12:00:00.000Z',
}

const installFetch = (): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (rawUrl: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body =
        typeof init?.body === 'string'
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null

      requests.push({ method, url: String(rawUrl), body })

      if (String(rawUrl).endsWith('/api/guest-sessions')) {
        return json(201, { sessionToken: 'gst_overview', expiresAt: '2026-11-21T00:00:00Z' })
      }

      if (method === 'POST' && String(rawUrl).endsWith('/environments')) {
        return createEnvironment(body ?? {})
      }

      if (method === 'PATCH' && String(rawUrl).includes('/environments/')) {
        return patchEnvironment(body ?? {})
      }

      if (method === 'PATCH') {
        return patchProject(body ?? {})
      }

      if (method === 'GET' && String(rawUrl).endsWith('/spec')) {
        return getSpecResponse()
      }

      throw new Error('unexpected request: ' + method + ' ' + String(rawUrl))
    }),
  )
}

const patches = (): readonly Recorded[] =>
  requests.filter((request) => request.method === 'PATCH')

beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  resetSessionForTests()
  requests = []
  patchProject = (body) => json(200, wireProject({ name: body.name }))
  patchEnvironment = (body) =>
    json(
      200,
      wireProject({
        environments: FIRST_PROJECT_FIXTURE.environments.map((environment) =>
          environment.id === ENVIRONMENT_ID
            ? {
                ...environment,
                name: body.name,
                kind: body.kind,
                baseUrl: body.baseUrl,
                variables: [],
              }
            : { ...environment, variables: [] },
        ),
      }),
    )
  createEnvironment = (body) =>
    json(
      201,
      wireProject({
        environments: [
          ...FIRST_PROJECT_FIXTURE.environments.map((environment) => ({
            ...environment,
            variables: [],
          })),
          {
            id: 'env_orders_test',
            name: body.name,
            kind: body.kind,
            baseUrl: body.baseUrl,
            variables: [],
          },
        ],
      }),
    )
  getSpecResponse = () => json(200, wireSpec)
  installFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetSessionForTests()
  removeStorage()
})

describe('project name editing', () => {
  it('sends the PATCH and adopts the server name throughout the store', async () => {
    const store = useProjectStore()

    const updated = await store.updateProjectName(PROJECT_ID, '  Renamed API  ')

    expect(updated?.name).toBe('Renamed API')
    expect(store.projectById(PROJECT_ID)?.name).toBe('Renamed API')
    expect(store.activeProject?.name).toBe('Renamed API')
    expect(store.updating).toBe(false)

    const patch = patches()[0]
    expect(patch?.url).toMatch(new RegExp('/api/projects/' + PROJECT_ID + '$'))
    expect(patch?.body).toEqual({ name: 'Renamed API' })
  })

  it('leaves the project untouched and reports failure when the server refuses', async () => {
    patchProject = () =>
      json(500, { code: 'internal-error', messageKey: 'console.overview.saveFailed' })
    const store = useProjectStore()
    const before = store.activeProject?.name

    const updated = await store.updateProjectName(PROJECT_ID, 'Renamed API')

    expect(updated).toBeNull()
    expect(store.activeProject?.name).toBe(before)
    expect(store.error).not.toBeNull()
    expect(store.updating).toBe(false)
  })

  it('rejects a blank name before sending a request', async () => {
    const store = useProjectStore()
    const updated = await store.updateProjectName(PROJECT_ID, '   ')

    expect(updated).toBeNull()
    expect(patches()).toHaveLength(0)
  })
})

describe('environment editing', () => {
  it('updates the editable fields and preserves existing variables', async () => {
    const store = useProjectStore()

    const updated = await store.updateEnvironment(PROJECT_ID, ENVIRONMENT_ID, {
      name: 'QA',
      kind: 'staging',
      baseUrl: 'https://qa.example.com',
    })

    const environment = updated?.environments.find((item) => item.id === ENVIRONMENT_ID)
    expect(environment?.name).toBe('QA')
    expect(environment?.kind).toBe('staging')
    expect(environment?.baseUrl).toBe('https://qa.example.com')
    expect(environment?.variables).toHaveLength(3)
    expect(store.updating).toBe(false)

    const patch = patches()[0]
    expect(patch?.url).toContain('/environments/' + ENVIRONMENT_ID)
    expect(patch?.body).toEqual({
      name: 'QA',
      kind: 'staging',
      baseUrl: 'https://qa.example.com',
    })
  })

  it('can edit an existing environment into the testing kind', async () => {
    const store = useProjectStore()

    const updated = await store.updateEnvironment(PROJECT_ID, ENVIRONMENT_ID, {
      name: 'QA',
      kind: 'testing',
      baseUrl: 'https://qa.example.com',
    })

    const environment = updated?.environments.find((item) => item.id === ENVIRONMENT_ID)
    expect(environment?.kind).toBe('testing')
    expect(environment?.variables).toHaveLength(3)
  })

  it('keeps the old environment when the server refuses the edit', async () => {
    patchEnvironment = () =>
      json(409, { code: 'environment-name-conflict', messageKey: 'console.overview.saveFailed' })
    const store = useProjectStore()
    const before = store.activeEnvironment

    const updated = await store.updateEnvironment(PROJECT_ID, ENVIRONMENT_ID, {
      name: 'QA',
      kind: 'staging',
      baseUrl: 'https://qa.example.com',
    })

    expect(updated).toBeNull()
    expect(store.activeEnvironment?.name).toBe(before?.name)
    expect(store.updating).toBe(false)
  })
})

describe('environment creation', () => {
  it('POSTs the new environment and adds it without moving the active environment', async () => {
    const store = useProjectStore()
    const beforeActive = store.activeEnvironmentId
    const otherProjectBefore = store.projectById('prj_payments')?.environments.length

    const updated = await store.createEnvironment(PROJECT_ID, {
      name: 'Test',
      kind: 'testing',
      baseUrl: 'https://test.example.com',
    })

    const environment = updated?.environments.find((item) => item.name === 'Test')
    expect(environment?.kind).toBe('testing')
    expect(environment?.baseUrl).toBe('https://test.example.com')
    expect(environment?.variables).toEqual([])
    expect(updated?.environments).toHaveLength(4)
    expect(store.activeEnvironmentId).toBe(beforeActive)
    expect(store.activeEnvironment?.name).toBe('Development')
    expect(store.projectById('prj_payments')?.environments).toHaveLength(
      otherProjectBefore ?? 0,
    )
    expect(store.environments.some((item) => item.id === environment?.id)).toBe(true)

    store.selectEnvironment(environment?.id ?? '')
    expect(store.activeEnvironment?.baseUrl).toBe('https://test.example.com')
    expect(store.updating).toBe(false)

    const post = requests.find((request) => request.method === 'POST' && request.url.endsWith('/environments'))
    expect(post?.url).toContain('/api/projects/' + PROJECT_ID + '/environments')
    expect(post?.body).toEqual({
      name: 'Test',
      kind: 'testing',
      baseUrl: 'https://test.example.com',
    })
  })

  it('keeps the existing environments when creation fails', async () => {
    createEnvironment = () =>
      json(409, { code: 'environment-name-conflict', messageKey: 'console.overview.saveFailed' })
    const store = useProjectStore()
    const before = store.activeProject?.environments.map((environment) => environment.id)

    const updated = await store.createEnvironment(PROJECT_ID, {
      name: 'Test',
      kind: 'testing',
      baseUrl: 'https://test.example.com',
    })

    expect(updated).toBeNull()
    expect(store.activeProject?.environments.map((environment) => environment.id)).toEqual(before)
    expect(store.error).not.toBeNull()
    expect(store.updating).toBe(false)
  })
})

describe('project spec read', () => {
  it('maps the current spec summary and asks the project spec endpoint', async () => {
    const spec = await getProjectSpec(PROJECT_ID)

    expect(spec).toMatchObject({
      id: 'spec_orders_1234',
      name: 'Orders API',
      filename: 'orders-openapi.json',
      endpointCount: 12,
      specType: 'openapi-3',
    })

    expect(requests.some((request) => request.url.endsWith('/api/projects/' + PROJECT_ID + '/spec'))).toBe(true)
  })

  it('returns null for a successful no-spec response', async () => {
    getSpecResponse = () => json(200, null)

    await expect(getProjectSpec(PROJECT_ID)).resolves.toBeNull()
  })
})

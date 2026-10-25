import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionForTests } from '@/services/session'
import { useProjectStore } from '@/stores/project'

import { installStorage, removeStorage } from '../support/storage'

/**
 * Project deletion must survive a browser refresh.
 *
 * The regression this pins: when the deleted project was the guest's only
 * project, initialization used to see an empty list and create a fresh
 * "My first API" before rendering. The deleted ID stayed gone, but the project
 * the user was looking at came back under a new ID.
 */
interface WireProject {
  readonly id: string
  readonly name: string
  readonly description: string
  readonly specName: string | null
  readonly environments: readonly {
    readonly id: string
    readonly name: string
    readonly kind: string
    readonly baseUrl: string
    readonly variables: readonly { key: string; value: string; secret: boolean }[]
  }[]
  readonly updatedAt: string
}

const project = (id: string, name: string): WireProject => ({
  id,
  name,
  description: '',
  specName: null,
  environments: [
    {
      id: 'env_' + id,
      name: 'Development',
      kind: 'development',
      baseUrl: 'https://api.example.com',
      variables: [],
    },
  ],
  updatedAt: '2026-10-25T00:00:00Z',
})

let projects: WireProject[] = []
let createCalls = 0
let nextId = 0

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const installFetch = (): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (rawUrl: string, init?: RequestInit) => {
      const url = String(rawUrl)
      const method = init?.method ?? 'GET'

      if (url.endsWith('/api/guest-sessions')) {
        return json(201, { sessionToken: 'gst_refresh_same' })
      }

      if (method === 'DELETE' && url.includes('/api/projects/')) {
        const id = decodeURIComponent(url.split('/').pop() ?? '')
        projects = projects.filter((item) => item.id !== id)
        return new Response(null, { status: 204 })
      }

      if (method === 'POST' && url.endsWith('/api/projects')) {
        createCalls += 1
        nextId += 1
        const body = JSON.parse(String(init?.body ?? '{}')) as { name?: unknown }
        const created = project(
          'prj_created_' + String(nextId),
          typeof body.name === 'string' ? body.name : 'Project',
        )
        projects = [...projects, created]
        return json(201, created)
      }

      if (method === 'GET' && url.endsWith('/api/projects')) {
        return json(200, projects)
      }

      throw new Error('unexpected request: ' + method + ' ' + url)
    }),
  )
}

const firstProject = (): WireProject => project('prj_my_first_api_2b20afe0', 'My first API')

beforeEach(() => {
  installStorage({})
  setActivePinia(createPinia())
  resetSessionForTests()
  vi.stubEnv('MODE', 'development')
  projects = [firstProject()]
  createCalls = 0
  nextId = 0
  installFetch()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetSessionForTests()
  removeStorage()
})

describe('deleted project persistence', () => {
  it('does not recreate the last project on a fresh store after deletion', async () => {
    const first = useProjectStore()
    await first.initialize()
    expect(first.projects.map((item) => item.id)).toEqual([
      'prj_my_first_api_2b20afe0',
    ])

    expect(await first.deleteProject('prj_my_first_api_2b20afe0')).toBe(true)
    expect(first.projects).toEqual([])

    // A browser refresh creates a new Pinia/store but the same guest session.
    setActivePinia(createPinia())
    const refreshed = useProjectStore()
    await refreshed.initialize()

    expect(refreshed.status).toBe('ready')
    expect(refreshed.projects).toEqual([])
    expect(refreshed.activeProjectId).toBe('')
    expect(refreshed.activeEnvironmentId).toBe('')
    expect(createCalls).toBe(0)
    expect(projects).toEqual([])
  })

  it('allows creating a project after the last project was deleted', async () => {
    const first = useProjectStore()
    await first.initialize()
    await first.deleteProject('prj_my_first_api_2b20afe0')

    setActivePinia(createPinia())
    const refreshed = useProjectStore()
    await refreshed.initialize()
    expect(refreshed.projects).toEqual([])

    const created = await refreshed.createProject('Fresh API')

    expect(created?.name).toBe('Fresh API')
    expect(refreshed.projects.map((item) => item.id)).toEqual([created?.id])
    expect(refreshed.activeProjectId).toBe(created?.id)
    expect(createCalls).toBe(1)

    // A second refresh loads the created project from the server; it does not
    // invent another first project.
    setActivePinia(createPinia())
    const again = useProjectStore()
    await again.initialize()
    expect(again.projects.map((item) => item.id)).toEqual([created?.id])
    expect(createCalls).toBe(1)
  })
})

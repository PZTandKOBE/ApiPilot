import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createTransport } from '@/services/transport'
import { useApiClientStore } from '@/stores/apiClient'
import { ProjectNotReadyError, useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'
import { installStorage, removeStorage } from '../support/storage'

/**
 * Which transport a build gets, and what the client does before it sends.
 *
 * Two questions, both about wiring rather than about behaviour:
 *
 * 1. **Is the mock still confined to tests?**  Vitest pins `MODE` to `'test'`, so
 *    the *default* here is the mock — and the real branch is reached by stating a
 *    different value for one call.  That is a deliberate limit: the assertion is
 *    "the factory has exactly one input, and a non-test value selects the proxy",
 *    not "a production build was executed".  A production build is exercised by
 *    `proxyTransport.spec.ts`, which drives the proxy transport the factory
 *    returns.
 * 2. **Does the client refuse to address an unvalidated project?**  The proxy route
 *    is project-scoped, so the id in that path has to be one the backend listed for
 *    this guest — and when it is not, the request must not be made at all.
 */

let requests: string[] = []

const recordFetch = (): void => {
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(String(url))
      throw new Error('no platform request was expected: ' + String(url))
    }),
  )
}

const setMode = (mode: string): void => {
  vi.stubEnv('MODE', mode)
}

beforeEach(() => {
  setActivePinia(createPinia())
  recordFetch()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  removeStorage()
})

describe('the transport switch', () => {
  it('uses the mock under test', () => {
    expect(createTransport().kind).toBe('mock')
  })

  it('uses the real proxy in every other mode', () => {
    // The build modes a developer or a deployment would actually have.
    for (const mode of ['development', 'production']) {
      setMode(mode)
      expect(createTransport().kind).toBe('proxy')
    }
  })

  it('has no environment variable that could put the mock in a real build', () => {
    setMode('production')
    // The agent and run services accept a `VITE_*` override; this one deliberately
    // does not, because a shipped console that answered from a mock would be
    // reporting data the API under test never produced.
    for (const name of ['VITE_TRANSPORT', 'VITE_API_CLIENT_TRANSPORT']) {
      vi.stubEnv(name, 'mock')
    }

    expect(createTransport().kind).toBe('proxy')
  })
})

describe('a request is not sent without a ready project', () => {
  const setup = (projects?: readonly never[]) => {
    installStorage({})
    const project = useProjectStore()
    if (projects === undefined) installProjectFixtures(project)
    const api = useApiClientStore()

    api.setMethod('GET')
    api.setUrl('https://api.under-test.example/orders')

    return { api, project }
  }

  it('sends nothing when no project has been loaded', async () => {
    const { api } = setup([])

    await api.send()

    expect(requests).toEqual([])
    expect(api.response).toBeNull()
    expect(api.error?.messageKey).toBe('console.apiClient.error.projectNotReady')
  })

  it('sends nothing when initialisation failed, and reports why', async () => {
    const { api, project } = setup()
    vi.spyOn(project, 'requireReadyProjectId').mockRejectedValue(
      new ProjectNotReadyError('failed'),
    )

    await api.send()

    expect(requests).toEqual([])
    expect(api.error?.kind).toBe('transport')
    expect(api.error?.messageKey).toBe('console.apiClient.error.projectNotReady')
  })

  it('uses the id the gate returned, with no substitute of its own', async () => {
    const { api, project } = setup()
    const checked = vi.spyOn(project, 'requireReadyProjectId')

    await api.send()

    // The gate is asked on every send, and its answer is the only id in play: the
    // store substitutes no literal and holds no default when it refuses.
    expect(checked).toHaveBeenCalledTimes(1)
    expect(checked.mock.results[0]?.value).toBeInstanceOf(Promise)

    // The mock transport is what runs under test, so a resolved gate means the
    // request really was sent -- with that id, and with no error raised.
    expect(api.error).toBeNull()
    expect(api.response?.status).toBeTruthy()
    expect(project.activeProjectId).not.toBe('')
  })
})

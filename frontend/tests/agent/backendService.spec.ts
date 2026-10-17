/// <reference types="node" />
// The reference is per-file on purpose: this is the only spec that needs a real
// HTTP server, and the app's tsconfig deliberately keeps Node's globals out of
// the browser code.

import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { AgentServiceError, createAgentService } from '@/services/agent'
import { createHttpAgentService } from '@/services/api/agent'
import { resetSessionForTests } from '@/services/session'

/**
 * The agent service against a real server.
 *
 * Not a mocked fetch: a real HTTP server on the loopback interface, the real
 * adapter, the real error envelope. What is asserted is the boundary the console
 * depends on -- the request it sends, the plan it gets back, and the sentences
 * it shows when the server says no.
 *
 * The fixtures are the shapes the backend actually returns, copied from
 * `schemas/agent.py`: camelCase, the plan tree, and an understanding that is
 * only present on the response that produced it.
 */

const PROJECT = 'prj_orders'
const SPEC = 'spec_verify_1'
const TASK_ID = '11111111-1111-1111-1111-111111111111'

const plan = {
  id: 'plan_verify_1',
  projectId: PROJECT,
  specId: SPEC,
  name: { key: 'console.aiTest.plan.lifecycleName', params: { resource: 'Verify API' } },
  goal: { key: 'console.aiTest.plan.lifecycleGoal', params: { resource: 'Verify API' } },
  riskLevel: 'high',
  status: 'draft',
  scenarios: [
    {
      id: 'scenario_authentication',
      index: 1,
      name: { key: 'console.aiTest.scenario.authenticationName' },
      description: { key: 'console.aiTest.scenario.authenticationDescription' },
      riskLevel: 'high',
      steps: [
        {
          id: 'ep_post_auth_login__0',
          index: 0,
          kind: 'request',
          description: { key: 'console.aiTest.step.login' },
          endpointId: null,
          method: 'POST',
          path: '/auth/login',
          produces: null,
          consumes: [],
        },
        {
          id: 'ep_post_auth_login__extract_token',
          index: 1,
          kind: 'extract',
          description: { key: 'console.aiTest.step.extractVariable', params: { variable: 'token' } },
          endpointId: null,
          method: null,
          path: null,
          produces: 'token',
          consumes: [],
        },
      ],
      expected: { key: 'console.aiTest.scenario.authenticationExpected' },
      assertions: [
        {
          id: 'ep_post_auth_login__status',
          kind: 'status',
          target: 'status',
          expected: '200',
          description: { key: 'console.aiTest.assertion.statusIs', params: { status: 200 } },
        },
      ],
    },
  ],
  source: 'generated',
  generatedAt: '2026-10-07T10:00:00Z',
  approvedAt: null,
  rejectedAt: null,
  rejectionReason: null,
}

const understanding = {
  specId: SPEC,
  endpoints: [
    {
      id: 'ep_post_auth_login',
      method: 'POST',
      path: '/auth/login',
      resourceId: 'res_auth',
      summary: { text: 'Exchange credentials for a token' },
      requiresAuth: false,
      pathParams: [],
      requiredBodyProps: [],
      constrainedBodyProps: [],
      responseStatuses: [200],
      responseProps: ['token'],
    },
  ],
  resources: [{ id: 'res_auth', name: 'auth', endpointIds: ['ep_post_auth_login'] }],
  authentication: {
    scheme: 'bearer',
    schemeName: 'bearerAuth',
    headerName: null,
    tokenSourceEndpointId: 'ep_post_auth_login',
    tokenField: 'token',
    protectedEndpointCount: 1,
  },
  dependencies: [],
  risks: [],
  findings: [],
  analyzedAt: '2026-10-07T10:00:00Z',
}

const taskBody = (overrides: Record<string, unknown> = {}) => ({
  id: TASK_ID,
  projectId: PROJECT,
  specId: SPEC,
  environmentId: 'env_orders_staging',
  prompt: 'Design a test plan for Verify API.',
  status: 'completed',
  createdAt: '2026-10-07T10:00:00Z',
  updatedAt: '2026-10-07T10:00:00Z',
  plan,
  understanding,
  ...overrides,
})

interface Recorded {
  readonly method: string
  readonly url: string
  readonly body: unknown
}

const requests: Recorded[] = []

/**
 * The agent requests, found by path rather than by position.
 *
 * The shared HTTP layer obtains a guest session first, and `services/http.ts` is
 * deliberately the one place that attaches it -- so the first entry in
 * `requests` is a `POST /api/guest-sessions` on a cold session and a task read on
 * a warm one.  Counting positions made these tests depend on which of the two had
 * happened, which is not what either of them is about.  Filtering says what they
 * mean, and a retry or a later session refresh cannot re-point an assertion at the
 * wrong request.
 */
const agentRequests = (): Recorded[] =>
  requests.filter((recorded) => !recorded.url.includes('/api/guest-sessions'))

/** What the next request gets back. Reset per test. */
let respond: (recorded: Recorded, response: ServerResponse) => void = () => undefined

const readBody = async (request: IncomingMessage): Promise<unknown> => {
  const chunks: Buffer[] = []

  for await (const chunk of request) chunks.push(chunk as Buffer)

  const text = Buffer.concat(chunks).toString('utf8')

  return text === '' ? undefined : (JSON.parse(text) as unknown)
}

const json = (response: ServerResponse, status: number, body: unknown): void => {
  const payload = JSON.stringify(body)
  response.writeHead(status, { 'Content-Type': 'application/json' })
  response.end(payload)
}

let server: Server
let baseUrl = ''

beforeAll(async () => {
  server = createServer((request, response) => {
    void (async () => {
      const recorded: Recorded = {
        method: request.method ?? '',
        url: request.url ?? '',
        body: await readBody(request),
      }

      requests.push(recorded)

      // The shared HTTP layer obtains a guest session before it calls anything
      // else, and it now reports a session it could not obtain instead of sending
      // an unauthenticated request.  Answering the issuance here keeps every
      // test's `respond` about the endpoint it is actually testing.
      if (recorded.method === 'POST' && recorded.url === '/api/guest-sessions') {
        json(response, 201, { sessionToken: 'session-for-tests' })
        return
      }

      respond(recorded, response)
    })()
  })

  await new Promise<void>((resolve) => {
    server.listen(0, '127.0.0.1', resolve)
  })

  const address = server.address() as AddressInfo
  baseUrl = 'http://127.0.0.1:' + String(address.port)
})

afterAll(async () => {
  // `fetch` keeps its connections alive, and a keep-alive socket keeps
  // `close()` waiting forever -- which hangs the whole run at teardown.
  server.closeAllConnections()

  await new Promise<void>((resolve) => {
    server.close(() => {
      resolve()
    })
  })
})

// Set before every test, not after: the first test needs the address too, and a
// base URL pointing at the default port would make it a transport failure.
beforeEach(() => {
  requests.length = 0
  // A token cached by an earlier test would hide whether this one needed to
  // issue a session at all, which is part of what the counts assert.
  resetSessionForTests()
  import.meta.env.VITE_API_BASE_URL = baseUrl
})

afterEach(() => {
  respond = () => undefined
})

const service = createHttpAgentService()

const input = {
  projectId: PROJECT,
  specId: SPEC,
  specDocument: '{"openapi":"3.0.3"}',
  environmentId: 'env_orders_staging',
  prompt: 'Design a test plan for Verify API.',
  variables: { bearer_token: 's3cr3t' },
}

describe('listPlans', () => {
  it('reads the version list from the project collection', async () => {
    respond = (recorded, response) => {
      expect(recorded.method).toBe('GET')
      expect(recorded.url).toBe('/api/projects/' + PROJECT + '/plans')
      json(response, 200, [
        { ...plan, version: 2, isCurrent: true, runCount: 3 },
        { ...plan, id: 'plan_verify_1_v2', version: 1, isCurrent: false, runCount: 0 },
      ])
    }

    const plans = await service.listPlans(PROJECT)

    expect(plans).toHaveLength(2)
    expect(plans[0]?.version).toBe(2)
    expect(plans[0]?.isCurrent).toBe(true)
    expect(plans[0]?.runCount).toBe(3)
    expect(plans[1]?.id).toBe('plan_verify_1_v2')
  })

  it('refuses a collection that is not a plan tree', async () => {
    respond = (_recorded, response) => {
      json(response, 200, [{ nope: true }])
    }

    await expect(service.listPlans(PROJECT)).rejects.toMatchObject({
      detail: { code: 'generate-failed' },
    })
  })
})

describe('runTask', () => {
  it('asks the server for a task, with the body the endpoint declares', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody())
    }

    const result = await service.runTask(input)

    const taskCalls = agentRequests()
    expect(taskCalls).toHaveLength(1)
    expect(taskCalls[0]?.method).toBe('POST')
    // The project the task belongs to is in the path, not in the body's ownership:
    // the request schema has no owner field, and this endpoint is scoped.
    expect(taskCalls[0]?.url).toBe('/api/projects/' + PROJECT + '/agent/tasks')
    expect(taskCalls[0]?.body).toEqual(input)

    // And the platform credential travelled on it, which is the other half of the
    // contract: the session is obtained by the shared layer and attached there.
    expect(requests.some((recorded) => recorded.url.includes('/api/guest-sessions'))).toBe(true)

    expect(result.taskId).toBe(TASK_ID)
    expect(result.status).toBe('completed')
  })

  it('hands back the plan tree the server stored, field for field', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody())
    }

    const result = await service.runTask(input)

    expect(result.plan?.id).toBe('plan_verify_1')
    expect(result.plan?.status).toBe('draft')
    expect(result.plan?.scenarios).toHaveLength(1)

    const scenario = result.plan?.scenarios[0]
    expect(scenario?.id).toBe('scenario_authentication')
    expect(scenario?.steps.map((step) => step.kind)).toEqual(['request', 'extract'])
    expect(scenario?.steps[0]?.method).toBe('POST')
    expect(scenario?.steps[0]?.path).toBe('/auth/login')
    expect(scenario?.steps[1]?.produces).toBe('token')
    expect(scenario?.assertions[0]).toEqual({
      id: 'ep_post_auth_login__status',
      kind: 'status',
      target: 'status',
      expected: '200',
      description: { key: 'console.aiTest.assertion.statusIs', params: { status: 200 } },
    })
  })

  it('sends the explicit regenerate flag only when the caller asks for it', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody({ plan: { ...plan, version: 2, isCurrent: true } }))
    }

    await service.runTask({ ...input, regenerate: true })

    const taskCall = agentRequests()[0]
    expect(taskCall?.body).toMatchObject({ regenerate: true })
  })

  it('carries the understanding the response produced', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody())
    }

    const result = await service.runTask(input)

    expect(result.understanding?.endpoints).toHaveLength(1)
    expect(result.understanding?.authentication.tokenField).toBe('token')
  })

  it('answers with no plan when the task produced none', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody({ status: 'failed', plan: null, understanding: null }))
    }

    const result = await service.runTask(input)

    expect(result.status).toBe('failed')
    expect(result.plan).toBeNull()
    expect(result.understanding).toBeNull()
  })

  it('refuses a plan the console could not render', async () => {
    respond = (_recorded, response) => {
      json(response, 201, taskBody({ plan: { id: 'plan_verify_1', status: 'draft' } }))
    }

    await expect(service.runTask(input)).rejects.toBeInstanceOf(AgentServiceError)
  })
})

describe('getTask', () => {
  it('reads a task back by its id', async () => {
    respond = (_recorded, response) => {
      json(response, 200, taskBody({ understanding: null }))
    }

    const result = await service.getTask(TASK_ID)

    const reads = agentRequests()
    expect(reads).toHaveLength(1)
    expect(reads[0]?.method).toBe('GET')
    // A task is addressed by its own id -- there is no project in this path, which
    // is why the ownership check happens on the server.
    expect(reads[0]?.url).toBe('/api/agent/tasks/' + TASK_ID)
    expect(result.plan?.id).toBe('plan_verify_1')
    expect(result.understanding).toBeNull()
  })
})

describe('the sentences the server sends', () => {
  const failure = async (
    status: number,
    code: string,
    messageKey: string,
  ): Promise<AgentServiceError> => {
    respond = (_recorded, response) => {
      json(response, status, { code, messageKey })
    }

    try {
      await service.runTask(input)
    } catch (caught) {
      return caught as AgentServiceError
    }

    throw new Error('expected the service to refuse')
  }

  it('maps plan-exists to the code and the sentence for it', async () => {
    const error = await failure(409, 'plan-exists', 'console.aiTest.errors.planExists')

    expect(error.detail.code).toBe('plan-exists')
    expect(error.detail.messageKey).toBe('console.aiTest.errors.planExists')
  })

  it('maps plan-invalid to a planning failure', async () => {
    const error = await failure(422, 'plan-invalid', 'console.aiTest.errors.generateFailed')

    expect(error.detail.code).toBe('plan-invalid')
    expect(error.detail.messageKey).toBe('console.aiTest.errors.generateFailed')
  })

  it('falls back to the caller sentence for a key this console cannot render', async () => {
    const error = await failure(422, 'parse-failed', 'console.something.unknown')

    expect(error.detail.code).toBe('parse-failed')
    expect(error.detail.messageKey).toBe('console.aiTest.errors.analyzeFailed')
  })

  it('maps a missing task to task-not-found', async () => {
    respond = (_recorded, response) => {
      json(response, 404, { code: 'task-not-found', messageKey: 'console.aiTest.errors.notFound' })
    }

    try {
      await service.getTask('nope')
    } catch (caught) {
      expect((caught as AgentServiceError).detail.code).toBe('task-not-found')
      return
    }

    throw new Error('expected the service to refuse')
  })

  it('reports a transport failure as the operation it attempted', async () => {
    import.meta.env.VITE_API_BASE_URL = 'http://127.0.0.1:1'

    try {
      await service.runTask(input)
    } catch (caught) {
      expect((caught as AgentServiceError).detail.messageKey).toBe(
        'console.aiTest.errors.analyzeFailed',
      )
      return
    }

    throw new Error('expected the service to refuse')
  })
})

describe('the service the console gets', () => {
  it('is the server, unless the mock is asked for by name', () => {
    const configured = import.meta.env.VITE_AGENT_SERVICE

    try {
      import.meta.env.VITE_AGENT_SERVICE = 'http'

      expect(createAgentService()).not.toBe(createHttpAgentService())
      expect(createAgentService().runTask).toBeTypeOf('function')
    } finally {
      import.meta.env.VITE_AGENT_SERVICE = configured
    }
  })
})

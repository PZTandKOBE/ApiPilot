import { dump } from 'js-yaml'
import { describe, expect, it } from 'vitest'

import { AgentServiceError, createAgentService } from '@/services/agent'

/**
 * Document decoding and structural parsing.
 *
 * These run the real service against real documents — the built-in demo spec
 * is serialised and re-parsed, so it travels exactly the path an uploaded file
 * does. Nothing here re-implements a parser to test the parser.
 */
const agent = createAgentService()
const PROJECT = 'prj_test'

const swaggerDocument = {
  swagger: '2.0',
  info: { title: 'Legacy Orders', version: '0.9' },
  host: 'legacy.example.com',
  basePath: '/v1',
  schemes: ['https'],
  securityDefinitions: { basicAuth: { type: 'basic' } },
  security: [{ basicAuth: [] }],
  paths: {
    '/auth/login': {
      post: {
        tags: ['Auth'],
        security: [],
        responses: {
          200: {
            description: 'ok',
            schema: { type: 'object', properties: { token: { type: 'string' } } },
          },
        },
      },
    },
    '/orders': {
      post: {
        tags: ['Orders'],
        parameters: [
          {
            name: 'body',
            in: 'body',
            required: true,
            schema: {
              type: 'object',
              required: ['product_id', 'quantity'],
              properties: {
                product_id: { type: 'string' },
                quantity: { type: 'integer', minimum: 1 },
              },
            },
          },
        ],
        responses: {
          201: {
            description: 'created',
            schema: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      },
    },
    '/orders/{orderId}': {
      get: {
        tags: ['Orders'],
        responses: {
          200: {
            description: 'ok',
            schema: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      },
    },
  },
}

const expectAgentError = async (
  content: string,
  code: string,
): Promise<AgentServiceError> => {
  let caught: unknown
  try {
    await agent.parseSpec({
      projectId: PROJECT,
      filename: 'x.json',
      content,
      source: 'paste',
    })
  } catch (thrown) {
    caught = thrown
  }

  expect(caught).toBeInstanceOf(AgentServiceError)
  const error = caught as AgentServiceError
  expect(error.detail.code).toBe(code)
  // The message is a dictionary key; the component decides how to word it.
  expect(error.detail.messageKey.startsWith('console.aiTest.errors.')).toBe(true)
  return error
}

describe('OpenAPI 3.x parsing', () => {
  it('reads the demo document the same way it reads an upload', async () => {
    const { parsed, content } = await agent.loadDemoSpec(PROJECT)

    expect(parsed.spec.title).toBe('Orders Platform API')
    expect(parsed.spec.version).toBe('1.4.0')
    expect(parsed.spec.format).toBe('openapi-3')
    expect(parsed.spec.source).toBe('demo')
    expect(parsed.spec.serverUrl).toBe('https://api.example.com')
    expect(parsed.spec.endpointCount).toBe(18)

    // Serialised for the caller so the store can persist it, and re-decoded
    // rather than handed over as an object.
    expect(JSON.parse(content)).toMatchObject({ openapi: '3.0.3' })
  })

  it('groups endpoints into resources from the document tags', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    expect(parsed.resources.map((resource) => resource.name)).toEqual([
      'Auth',
      'Users',
      'Products',
      'Orders',
      'Payments',
    ])
    expect(parsed.resources.map((resource) => resource.endpointIds.length)).toEqual([
      3, 3, 4, 5, 3,
    ])
  })

  it('detects the security scheme and the endpoint that issues the credential', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    expect(parsed.authentication.scheme).toBe('bearer')
    expect(parsed.authentication.schemeName).toBe('bearerAuth')
    expect(parsed.authentication.tokenSourceEndpointId).toBe('ep_post_api_auth_login')
    expect(parsed.authentication.tokenField).toBe('token')
    expect(parsed.authentication.protectedEndpointCount).toBe(17)
  })

  it('resolves $ref schemas when reading bodies and responses', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    const create = parsed.endpoints.find(
      (endpoint) => endpoint.method === 'POST' && endpoint.path === '/api/orders',
    )
    expect(create).toBeDefined()
    expect(create?.requiredBodyProps).toEqual(['product_id', 'quantity', 'user_id'])
    expect(create?.constrainedBodyProps).toEqual(['quantity'])
    expect(create?.responseStatuses).toEqual([201])
    // `Order` is reached through `#/components/schemas/Order`.
    expect(create?.responseProps).toContain('status')
  })

  it('gives endpoints stable, derived ids', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    expect(parsed.endpoints.map((endpoint) => endpoint.id)).toContain(
      'ep_get_api_orders_orderid',
    )
  })
})

describe('endpoint ids stay unique across a whole document', () => {
  it('disambiguates paths that slug to the same id', async () => {
    // `slugify` flattens every non-alphanumeric run, so a path parameter and a
    // literal segment of the same name are indistinguishable. Both endpoints
    // are real; collapsing them would silently drop one from the document.
    const parsed = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'collide.json',
      content: JSON.stringify({
        openapi: '3.0.3',
        info: { title: 'Collide', version: '1' },
        paths: {
          '/api/orders/{orderId}': {
            get: { responses: { 200: { description: 'ok' } } },
          },
          '/api/orders/orderId': {
            get: { responses: { 200: { description: 'ok' } } },
          },
        },
      }),
      source: 'upload',
    })

    expect(parsed.endpoints).toHaveLength(2)
    expect(parsed.endpoints.map((endpoint) => endpoint.id)).toEqual([
      'ep_get_api_orders_orderid',
      'ep_get_api_orders_orderid_2',
    ])
    // Distinct ids are only useful if they still describe distinct things.
    expect(parsed.endpoints.map((endpoint) => endpoint.path)).toEqual([
      '/api/orders/{orderId}',
      '/api/orders/orderId',
    ])
  })

  it('leaves a document with no collisions byte-identical', async () => {
    // The suffix is only ever paid by the collision, so ids already persisted
    // in a plan keep resolving.
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    expect(parsed.endpoints.map((endpoint) => endpoint.id)).toContain(
      'ep_get_api_orders_orderid',
    )
    expect(
      parsed.endpoints.some((endpoint) => /_\d+$/.test(endpoint.id)),
    ).toBe(false)
  })
})

describe('YAML and Swagger 2.x', () => {
  it('parses a YAML document to the same endpoints as its JSON form', async () => {
    const { parsed: fromJson, content } = await agent.loadDemoSpec(PROJECT)
    const asYaml = dump(JSON.parse(content), { noRefs: true })

    const fromYaml = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'orders.yaml',
      content: asYaml,
      source: 'upload',
    })

    expect(fromYaml.spec.format).toBe('openapi-3')
    expect(fromYaml.endpoints.map((endpoint) => endpoint.id)).toEqual(
      fromJson.endpoints.map((endpoint) => endpoint.id),
    )
  })

  it('parses Swagger 2.x, including its body parameter and host/basePath', async () => {
    const parsed = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'swagger.json',
      content: JSON.stringify(swaggerDocument),
      source: 'upload',
    })

    expect(parsed.spec.format).toBe('swagger-2')
    expect(parsed.spec.serverUrl).toBe('https://legacy.example.com/v1')
    expect(parsed.endpoints).toHaveLength(3)
    expect(parsed.authentication.scheme).toBe('basic')

    const create = parsed.endpoints.find((endpoint) => endpoint.path === '/orders')
    expect(create?.requiredBodyProps).toEqual(['product_id', 'quantity'])
    // Only a *required* field with a constraint becomes a negative case.
    expect(create?.constrainedBodyProps).toEqual(['quantity'])
  })
})

describe('malformed input is reported, never guessed at', () => {
  it('rejects a document that is not a specification', async () => {
    await expectAgentError('{"hello":"world"}', 'unsupported-format')
  })

  it('reports a YAML syntax error with the parser detail', async () => {
    const error = await expectAgentError('a:\n  - b\n c: d', 'parse-failed')
    expect(error.detail.params?.detail).toBeTruthy()
  })

  it('rejects a valid document with no endpoints', async () => {
    await expectAgentError(
      '{"openapi":"3.0.0","info":{"title":"x"},"paths":{}}',
      'no-endpoints',
    )
  })

  it('rejects an empty document', async () => {
    await expectAgentError('   ', 'parse-failed')
  })

  it('rejects a scalar where a mapping is required', async () => {
    await expectAgentError('"just a string"', 'parse-failed')
  })
})

describe('determinism', () => {
  it('derives the same spec id from the same content', async () => {
    const first = await agent.loadDemoSpec(PROJECT)
    const second = await agent.loadDemoSpec(PROJECT)

    expect(second.parsed.spec.id).toBe(first.parsed.spec.id)
    expect(second.parsed.spec.slug).toBe(first.parsed.spec.slug)
  })

  it('derives a different spec id from different content', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    const other = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'swagger.json',
      content: JSON.stringify(swaggerDocument),
      source: 'upload',
    })

    expect(other.spec.id).not.toBe(parsed.spec.id)
  })
})

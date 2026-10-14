import { beforeAll, describe, expect, it } from 'vitest'

import { documentFromHandoff } from '@/services/agent'
import { createMockAgentService } from '@/services/mock/agent'
import {
  isLocalizedMessage,
  type ApiSpec,
  type LocalizedText,
  type TestPlan,
} from '@/types/agent'
import { createId } from '@/utils/id'

/** Reads the dictionary key out of an authored string; literals are a failure. */
const keyOf = (value: LocalizedText): string => {
  if (!isLocalizedMessage(value)) {
    throw new Error(`expected a dictionary key, got a literal: "${value.text}"`)
  }
  return value.key
}

/**
 * Test plan generation.
 *
 * Two properties matter most here and are asserted explicitly: every number on
 * a plan is derived from the understanding, and a generated plan is *always*
 * a draft — there is no path from this module to an approvable state.
 */
const agent = createMockAgentService()
const PROJECT = 'prj_test'

let spec: ApiSpec
let plan: TestPlan

beforeAll(async () => {
  const { parsed } = await agent.loadDemoSpec(PROJECT)
  spec = parsed.spec
  const understanding = await agent.analyze(parsed)
  plan = await agent.generatePlan(understanding, spec, 'generated')
})

describe('plan shape', () => {
  it('is always generated as a draft', () => {
    expect(plan.status).toBe('draft')
    expect(plan.approvedAt).toBeNull()
    expect(plan.rejectedAt).toBeNull()
    expect(plan.rejectionReason).toBeNull()
  })

  it('keys the plan to the document that produced it', () => {
    expect(plan.id).toBe(`plan_${spec.slug}`)
    expect(plan.specId).toBe(spec.id)
    expect(plan.projectId).toBe(PROJECT)
  })

  it('takes its risk level from the worst scenario it contains', () => {
    expect(plan.riskLevel).toBe('high')
    expect(plan.scenarios.some((scenario) => scenario.riskLevel === 'high')).toBe(true)
  })

  it('names itself after the resource it exercises', () => {
    expect(plan.name).toMatchObject({
      key: 'console.aiTest.plan.lifecycleName',
      params: { resource: 'Orders' },
    })
  })
})

describe('scenarios are read off the understanding', () => {
  it('builds one scenario per rule that fired', () => {
    expect(plan.scenarios.map((scenario) => scenario.id)).toEqual([
      'scenario_authentication',
      'scenario_lifecycle_ep_post_api_orders',
      'scenario_dependent_ep_post_api_orders_orderid_payment',
      'scenario_negative_ep_post_api_orders',
    ])
  })

  it('follows the authentication chain from token source to protected endpoint', () => {
    const authentication = plan.scenarios[0]
    expect(authentication.steps.map((step) => step.kind)).toEqual([
      'request',
      'extract',
      'request',
      'assert',
    ])
    expect(authentication.steps[0].path).toBe('/api/auth/login')
    expect(authentication.steps[1].produces).toBe('token')
    expect(authentication.steps[2].consumes).toEqual(['token'])
  })

  it('carries the id from creation into the read that follows', () => {
    const lifecycle = plan.scenarios[1]
    expect(lifecycle.steps[0].method).toBe('POST')
    expect(lifecycle.steps[1].produces).toBe('orderId')
    expect(lifecycle.steps[2].consumes).toEqual(['orderId'])
    expect(lifecycle.steps[2].path).toBe('/api/orders/{orderId}')
  })

  it('asserts the status codes the document declares', () => {
    const lifecycle = plan.scenarios[1]
    const statuses = lifecycle.assertions
      .filter((assertion) => assertion.kind === 'status')
      .map((assertion) => assertion.expected)

    expect(statuses).toEqual(['201', '200'])
  })

  it('turns a constrained field into an invalid-input step', () => {
    const negative = plan.scenarios[3]
    expect(negative.steps.map((step) => keyOf(step.description))).toEqual([
      'console.aiTest.step.invalidBody',
      'console.aiTest.step.boundaryValue',
      'console.aiTest.step.unauthenticated',
      'console.aiTest.step.assertResponse',
    ])
    expect(negative.assertions.map((assertion) => assertion.expected)).toEqual([
      '400',
      '400',
      '401',
    ])
  })

  it('numbers steps from zero within each scenario', () => {
    for (const scenario of plan.scenarios) {
      expect(scenario.steps.map((step) => step.index)).toEqual(
        scenario.steps.map((_, index) => index),
      )
    }
  })
})

describe('totals', () => {
  it('counts scenarios, steps and assertions from the plan itself', () => {
    const steps = plan.scenarios.reduce((total, scenario) => total + scenario.steps.length, 0)
    const assertions = plan.scenarios.reduce(
      (total, scenario) => total + scenario.assertions.length,
      0,
    )

    expect(plan.scenarios).toHaveLength(4)
    expect(steps).toBe(14)
    expect(assertions).toBe(11)
  })
})

describe('thin documents still produce something runnable', () => {
  it('falls back to a single smoke scenario when no rule fires', async () => {
    // One endpoint, no dependencies, no constraints, no risks.
    const thin = {
      openapi: '3.0.3',
      info: { title: 'Tiny API', version: '1.0.0' },
      paths: {
        '/ping': {
          get: { responses: { 200: { description: 'ok' } } },
        },
      },
    }

    const parsed = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'tiny.json',
      content: JSON.stringify(thin),
      source: 'upload',
    })
    const understanding = await agent.analyze(parsed)
    const generated = await agent.generatePlan(understanding, parsed.spec, 'generated')

    expect(understanding.dependencies).toHaveLength(0)
    expect(understanding.risks).toHaveLength(0)
    expect(generated.scenarios).toHaveLength(1)
    expect(generated.scenarios[0].name).toMatchObject({
      key: 'console.aiTest.scenario.smokeName',
    })
    expect(generated.riskLevel).toBe('low')
  })
})

describe('determinism', () => {
  it('produces an identical plan for identical input', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)
    const understanding = await agent.analyze(parsed)
    const again = await agent.generatePlan(understanding, parsed.spec, 'generated')

    const strip = (value: TestPlan): string =>
      JSON.stringify({ ...value, generatedAt: null })

    expect(strip(again)).toBe(strip(plan))
  })
})

describe('handoff documents', () => {
  it('turns a composed request into a one-endpoint specification', () => {
    const document = documentFromHandoff(
      {
        projectId: PROJECT,
        draft: {
          method: 'POST',
          url: '/api/orders',
          params: [],
          headers: [],
          auth: {
            type: 'bearer',
            bearerToken: '{{token}}',
            username: '',
            password: '',
            apiKeyName: '',
            apiKeyValue: '',
            apiKeyIn: 'header',
          },
          body: { mode: 'json', text: '{"product_id":"prod_001","quantity":2}' },
        },
        resolved: {
          method: 'POST',
          url: 'https://api.dev.example.com/api/orders',
          headers: [],
          body: '{"product_id":"prod_001","quantity":2}',
          timeoutMs: 30_000,
        },
        requestedAt: new Date().toISOString(),
      },
      'API Client request',
    )

    const parsed = JSON.parse(document) as Record<string, unknown>
    expect(parsed.openapi).toBe('3.0.3')
    expect(Object.keys(parsed.paths as object)).toEqual(['/api/orders'])

    const operation = (parsed.paths as Record<string, Record<string, Record<string, unknown>>>)[
      '/api/orders'
    ].post
    const body = operation.requestBody as {
      content: Record<string, { schema: { required: readonly string[] } }>
    }
    // The sample body is taken as the contract; every field is required.
    expect(body.content['application/json'].schema.required).toEqual([
      'product_id',
      'quantity',
    ])
    expect(operation.security).toEqual([{ handoffAuth: [] }])
  })
})

describe('id generation', () => {
  it('does not collide across rapid calls', () => {
    const ids = new Set(Array.from({ length: 200 }, () => createId('row')))
    expect(ids.size).toBe(200)
  })
})

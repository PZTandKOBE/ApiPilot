import { describe, expect, it } from 'vitest'

import { sanitizePlans, sanitizeStoredSpecs } from '@/utils/agentStorage'

/**
 * Sanitizer forward-compatibility.
 *
 * Storage outlives a deploy. A plan written by a newer build, opened on an
 * older one, and saved again used to come back with every field the older
 * build did not recognise stripped out — which reads as "the agent stopped
 * writing that part of the plan" rather than "the loader dropped it".
 *
 * These pin the property that makes that impossible: unknown fields ride
 * along, while every known field is still rebuilt and still wins.
 */

const step = {
  id: 'step_7',
  index: 7,
  kind: 'request',
  description: { key: 'console.aiTest.step.login' },
  endpointId: 'ep_post_api_auth_login',
  method: 'POST',
  path: '/api/auth/login',
  produces: null,
  consumes: [],
  /** Written by a build that knew about it; this one does not. */
  startedAt: '2026-01-01T00:00:00.000Z',
  retry: { attempts: 2, backoffMs: 500 },
}

const plan = {
  id: 'plan_orders',
  projectId: 'prj_orders',
  specId: 'spec_orders',
  name: { key: 'console.aiTest.plan.lifecycleName', params: { resource: 'Orders' } },
  goal: { key: 'console.aiTest.plan.lifecycleGoal', params: { resource: 'Orders' } },
  riskLevel: 'high',
  status: 'approved',
  scenarios: [
    {
      id: 'scenario_authentication',
      index: 0,
      name: { key: 'console.aiTest.scenario.authenticationName' },
      description: { key: 'console.aiTest.scenario.authenticationDescription' },
      riskLevel: 'high',
      steps: [step],
      expected: { key: 'console.aiTest.scenario.authenticationExpected' },
      assertions: [
        {
          id: 'ep_post_api_auth_login__status',
          kind: 'status',
          target: 'status',
          expected: '200',
          description: { key: 'console.aiTest.assertion.statusIs', params: { status: 200 } },
          durationMs: 41,
        },
      ],
      tags: ['smoke'],
    },
  ],
  source: 'generated',
  generatedAt: '2026-01-01T00:00:00.000Z',
  approvedAt: '2026-01-02T00:00:00.000Z',
  rejectedAt: null,
  rejectionReason: null,
  /** Fields no build has known about yet, at every nesting level. */
  lastRunId: 'run_42',
  coverage: { branches: 12 },
}

describe('unknown fields survive a load', () => {
  it('keeps them on a plan, a scenario, a step and an assertion', () => {
    const [stored] = sanitizePlans([plan])

    expect(stored).toMatchObject({
      lastRunId: 'run_42',
      coverage: { branches: 12 },
    })
    expect(stored?.scenarios[0]).toMatchObject({ tags: ['smoke'] })
    expect(stored?.scenarios[0]?.steps[0]).toMatchObject({
      startedAt: '2026-01-01T00:00:00.000Z',
      retry: { attempts: 2, backoffMs: 500 },
    })
    expect(stored?.scenarios[0]?.assertions[0]).toMatchObject({ durationMs: 41 })
  })

  it('keeps them on a stored specification too', () => {
    const [spec] = sanitizeStoredSpecs([
      {
        spec: {
          id: 'spec_orders',
          projectId: 'prj_orders',
          slug: 'orders',
          title: 'Orders Platform API',
          version: '1.4.0',
          format: 'openapi-3',
          source: 'demo',
          filename: 'demo.json',
          serverUrl: 'https://api.example.com',
          endpointCount: 18,
          loadedAt: '2026-01-01T00:00:00.000Z',
          tags: ['v1'],
        },
        content: '{"openapi":"3.0.3"}',
      },
    ])

    expect(spec?.spec).toMatchObject({ tags: ['v1'] })
  })
})

describe('known fields are still rebuilt, and still win', () => {
  it('overrides a stored value that has the wrong shape', () => {
    const [stored] = sanitizePlans([
      { ...plan, status: 'shipped', riskLevel: 'catastrophic', index: 'nope' },
    ])

    expect(stored?.status).toBe('draft')
    expect(stored?.riskLevel).toBe('medium')
  })

  it('overrides a stored field that a passthrough would otherwise shadow', () => {
    // The spread has to come *before* the known fields in each literal, or a
    // stale value would be written back over the validated one.
    const [stored] = sanitizePlans([
      {
        ...plan,
        id: 42,
        name: 'not a message',
        scenarios: [
          {
            ...plan.scenarios[0],
            index: 'two',
            steps: [{ ...step, id: 42, kind: 'launch', consumes: 'not-an-array' }],
          },
        ],
      },
    ])

    expect(stored?.id).toBe('plan_0')
    expect(stored?.name).toEqual({ text: '' })
    expect(stored?.scenarios[0]?.index).toBe(0)
    expect(stored?.scenarios[0]?.steps[0]).toMatchObject({
      id: 'step_0',
      kind: 'request',
      consumes: [],
    })
  })

  it('still drops a scenario that is not an object at all', () => {
    const [stored] = sanitizePlans([{ ...plan, scenarios: [null, 'nope', 42] }])

    expect(stored?.scenarios).toEqual([])
  })
})

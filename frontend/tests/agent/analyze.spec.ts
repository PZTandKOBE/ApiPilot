import { beforeAll, describe, expect, it } from 'vitest'

import { createMockAgentService } from '@/services/mock/agent'
import { isLocalizedMessage, type ApiUnderstanding, type LocalizedText } from '@/types/agent'

/**
 * Reads the dictionary key out of an authored string.
 *
 * Throws rather than falling back: everything the rule engine authors must be
 * translatable, so a literal appearing here is itself the failure.
 */
const keyOf = (value: LocalizedText): string => {
  if (!isLocalizedMessage(value)) {
    throw new Error(`expected a dictionary key, got a literal: "${value.text}"`)
  }
  return value.key
}

/**
 * The analysis rules.
 *
 * Every expectation below is a property of the *rule engine*, not of a fixture
 * — change the rules and these fail, which is the point. The counts are
 * asserted because the demo document is fixed, not because the numbers are
 * hard-coded anywhere in the application.
 */
const agent = createMockAgentService()
const PROJECT = 'prj_test'

let understanding: ApiUnderstanding
let endpointPathById: Map<string, string>

beforeAll(async () => {
  const { parsed } = await agent.loadDemoSpec(PROJECT)
  understanding = await agent.analyze(parsed)
  endpointPathById = new Map(
    parsed.endpoints.map((endpoint) => [endpoint.id, `${endpoint.method} ${endpoint.path}`]),
  )
})

describe('dependencies', () => {
  it('traces the lifecycle path rather than every pairwise relation', () => {
    expect(understanding.dependencies).toHaveLength(7)
    expect(understanding.dependencies.map((dependency) => dependency.kind)).toEqual([
      'token',
      'identity',
      'reference',
      'lifecycle',
      'sub-resource',
      'sub-resource',
      'sub-resource',
    ])
  })

  it('starts at the token source and lands on the identity endpoint', () => {
    const edge = understanding.dependencies[0]
    expect(endpointPathById.get(edge.fromEndpointId)).toBe('POST /api/auth/login')
    expect(endpointPathById.get(edge.toEndpointId)).toBe('GET /api/users/me')
    expect(edge.binding).toBe('token')
  })

  it('carries the concrete field name as the binding', () => {
    const reference = understanding.dependencies.find(
      (dependency) => dependency.kind === 'reference',
    )
    expect(reference?.binding).toBe('product_id')
    expect(endpointPathById.get(reference?.fromEndpointId ?? '')).toBe(
      'GET /api/products/{productId}',
    )
    expect(endpointPathById.get(reference?.toEndpointId ?? '')).toBe('POST /api/orders')
  })

  it('explains each edge in one sentence, without narrating how it was found', () => {
    for (const dependency of understanding.dependencies) {
      expect(dependency.rationale).toMatchObject({
        key: expect.stringMatching(/^console\.aiTest\.dependencies\.rationale/),
      })
      if ('params' in dependency.rationale) {
        expect(dependency.rationale.params).toMatchObject({
          from: expect.any(String),
          to: expect.any(String),
          binding: expect.any(String),
        })
      }
    }
  })

  it('attaches every sub-resource action to the resource it operates on', () => {
    const subResources = understanding.dependencies.filter(
      (dependency) => dependency.kind === 'sub-resource',
    )
    expect(
      subResources.map((dependency) => endpointPathById.get(dependency.toEndpointId)),
    ).toEqual([
      'PATCH /api/orders/{orderId}',
      'DELETE /api/orders/{orderId}',
      'POST /api/orders/{orderId}/payment',
    ])
  })

  it('starts every sub-resource action from the read that creates the item', () => {
    // Asserting only the target would pass for an edge drawn from anywhere —
    // `GET /api/orders/{orderId}` is what makes the action runnable at all.
    const subResources = understanding.dependencies.filter(
      (dependency) => dependency.kind === 'sub-resource',
    )
    expect(
      subResources.map((dependency) => endpointPathById.get(dependency.fromEndpointId)),
    ).toEqual([
      'GET /api/orders/{orderId}',
      'GET /api/orders/{orderId}',
      'GET /api/orders/{orderId}',
    ])
  })

  it('starts the lifecycle edge at the create and lands it on the read', () => {
    const lifecycle = understanding.dependencies.find(
      (dependency) => dependency.kind === 'lifecycle',
    )
    expect(endpointPathById.get(lifecycle?.fromEndpointId ?? '')).toBe('POST /api/orders')
    expect(endpointPathById.get(lifecycle?.toEndpointId ?? '')).toBe(
      'GET /api/orders/{orderId}',
    )
    expect(lifecycle?.binding).toBe('orderId')
  })
})

describe('ids are unique, and collide with nothing they are keyed by', () => {
  /**
   * Deduplication keys on `(consumer, binding)` exactly as written, so two
   * spellings of one binding both survive it. If the id is then built from a
   * *slug* of the binding, `orderId` and `OrderId` collapse onto one string —
   * and both the edge list and the risk list render by `:key`.
   */
  const collide = {
    openapi: '3.0.3',
    info: { title: 'Spellings', version: '1' },
    paths: {
      '/api/products/{productId}': {
        get: {
          tags: ['Products'],
          responses: {
            200: {
              description: 'ok',
              content: {
                'application/json': {
                  schema: { type: 'object', properties: { id: { type: 'string' } } },
                },
              },
            },
          },
        },
      },
      '/api/orders': {
        post: {
          tags: ['Orders'],
          requestBody: {
            required: true,
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  required: ['productId', 'ProductId'],
                  properties: {
                    productId: { type: 'string' },
                    ProductId: { type: 'string' },
                  },
                },
              },
            },
          },
          responses: { 201: { description: 'created' } },
        },
      },
    },
  }

  const duplicateIds = (values: readonly { readonly id: string }[]): string[] => {
    const seen = new Set<string>()
    const duplicates: string[] = []
    for (const value of values) {
      if (seen.has(value.id)) duplicates.push(value.id)
      seen.add(value.id)
    }
    return duplicates
  }

  it('gives every dependency and every risk a distinct id', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)
    const understanding = await agent.analyze(parsed)

    expect(duplicateIds(understanding.dependencies)).toEqual([])
    expect(duplicateIds(understanding.risks)).toEqual([])
  })

  it('keeps two spellings of one binding apart', async () => {
    const parsed = await agent.parseSpec({
      projectId: PROJECT,
      filename: 'spellings.json',
      content: JSON.stringify(collide),
      source: 'upload',
    })
    const understanding = await agent.analyze(parsed, { immediate: true })

    const references = understanding.dependencies.filter(
      (dependency) => dependency.kind === 'reference',
    )
    expect(references.map((dependency) => dependency.binding)).toEqual([
      'productId',
      'ProductId',
    ])
    // Distinct bindings, so distinct ids — the slug used to merge these.
    expect(new Set(references.map((reference) => reference.id)).size).toBe(2)

    const referenceRisks = understanding.risks.filter(
      (risk) => keyOf(risk.title) === 'console.aiTest.risks.referenceTitle',
    )
    expect(referenceRisks).toHaveLength(2)
    expect(duplicateIds(referenceRisks)).toEqual([])
  })
})

describe('risks', () => {
  it('raises one finding per rule that fires', () => {
    expect(understanding.risks).toHaveLength(6)
    expect(understanding.risks.map((risk) => risk.category)).toEqual([
      'authentication',
      'authorization',
      'dependency',
      'dependency',
      'negative-coverage',
      'idempotency',
    ])
  })

  it('counts the protected surface rather than asserting it exists', () => {
    const authentication = understanding.risks.find(
      (risk) => risk.category === 'authentication',
    )
    expect(authentication?.level).toBe('medium')
    expect(authentication?.title).toMatchObject({
      key: 'console.aiTest.risks.authTitle',
      params: { count: 17 },
    })
    expect(authentication?.relatedEndpointIds).toHaveLength(17)
  })

  it('flags a constrained field with no described invalid case, and names it', () => {
    const negative = understanding.risks.find(
      (risk) => risk.category === 'negative-coverage',
    )
    expect(negative?.level).toBe('medium')
    // The field travels as data, not only inside the rendered sentence.
    expect(negative?.fields).toEqual(['quantity'])
    expect(negative?.title).toMatchObject({ params: { field: 'quantity' } })
  })

  it('flags a reference to a resource that must already exist, and names the binding', () => {
    const reference = understanding.risks.find(
      (risk) => keyOf(risk.title) === 'console.aiTest.risks.referenceTitle',
    )
    expect(reference?.level).toBe('high')
    expect(reference?.fields).toEqual(['product_id'])
  })

  it('only flags DELETE idempotency when a DELETE exists', () => {
    const idempotency = understanding.risks.find(
      (risk) => risk.category === 'idempotency',
    )
    expect(idempotency?.level).toBe('low')
    expect(idempotency?.title).toMatchObject({ params: { count: 2 } })
  })
})

describe('findings', () => {
  it('reports what the agent did, in order', () => {
    expect(understanding.findings.map((finding) => finding.id)).toEqual([
      'finding_parsed',
      'finding_endpoints',
      'finding_authentication',
      'finding_dependencies',
      'finding_risks',
    ])
  })

  it('gives every finding an action, a decision and evidence', () => {
    for (const finding of understanding.findings) {
      expect(finding.result).toBe('succeeded')
      expect(keyOf(finding.action).startsWith('console.aiTest.findings.')).toBe(true)
      expect(keyOf(finding.decisionSummary).endsWith('Decision')).toBe(true)
      expect(finding.evidence.length).toBeGreaterThan(0)

      for (const item of finding.evidence) {
        expect(keyOf(item.label).startsWith('console.aiTest.evidence.')).toBe(true)
        // Evidence is a concrete artifact, not a restatement of the decision.
        expect(item.value.trim()).not.toBe('')
      }
    }
  })

  it('records the counts it actually derived as evidence', () => {
    const endpoints = understanding.findings.find(
      (finding) => finding.id === 'finding_endpoints',
    )
    expect(endpoints?.action).toMatchObject({ params: { count: 18, resources: 5 } })

    const risks = understanding.findings.find((finding) => finding.id === 'finding_risks')
    expect(risks?.action).toMatchObject({ params: { count: 6 } })
  })
})

describe('no chain-of-thought is representable', () => {
  const collectKeys = (value: unknown, keys: string[] = []): string[] => {
    if (Array.isArray(value)) {
      for (const item of value) collectKeys(item, keys)
    } else if (typeof value === 'object' && value !== null) {
      for (const [key, nested] of Object.entries(value)) {
        keys.push(key)
        collectKeys(nested, keys)
      }
    }
    return keys
  }

  it('has no field that could hold hidden reasoning', () => {
    const keys = collectKeys(understanding)
    const forbidden = keys.filter((key) =>
      /thought|reasoning|chainofthought|internal/i.test(key),
    )
    expect(forbidden).toEqual([])
  })

  it('exposes exactly the four observable fields on a finding', () => {
    for (const finding of understanding.findings) {
      expect(Object.keys(finding).sort()).toEqual([
        'action',
        'at',
        'decisionSummary',
        'evidence',
        'id',
        'result',
      ])
    }
  })
})

describe('progress reporting', () => {
  it('walks the stages in order and ends with all of them complete', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    const frames: { stage: string; completed: number }[] = []
    await agent.analyze(parsed, {
      onProgress: (progress) => {
        frames.push({ stage: progress.stage, completed: progress.completed.length })
      },
    })

    // One frame per stage as it starts, plus a final frame with everything
    // ticked so the checklist does not end mid-spin.
    expect(frames.slice(0, 5).map((frame) => frame.stage)).toEqual([
      'parsing',
      'endpoints',
      'authentication',
      'dependencies',
      'risks',
    ])
    expect(frames.at(-1)?.completed).toBe(5)
  })

  it('skips the whole schedule when asked to run immediately', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)

    let frames = 0
    const started = Date.now()
    await agent.analyze(parsed, { immediate: true, onProgress: () => { frames += 1 } })

    expect(frames).toBe(0)
    expect(Date.now() - started).toBeLessThan(500)
  })
})

describe('determinism', () => {
  it('produces an identical understanding for identical input', async () => {
    const { parsed } = await agent.loadDemoSpec(PROJECT)
    const again = await agent.analyze(parsed)

    const strip = (value: ApiUnderstanding): string =>
      JSON.stringify({
        ...value,
        analyzedAt: null,
        findings: value.findings.map((finding) => ({ ...finding, at: null })),
      })

    expect(strip(again)).toBe(strip(understanding))
  })
})

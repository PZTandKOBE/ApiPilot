import { describe, expect, it } from 'vitest'

import { enUS } from '@/locales/en-US'
import { zhCN } from '@/locales/zh-CN'
import { createMockAgentService } from '@/services/mock/agent'
import { createRunService } from '@/services/run'
import { isLocalizedMessage, type LocalizedText } from '@/types/agent'

/**
 * Dictionary completeness.
 *
 * `t()` takes a plain string, so a typo is invisible to the compiler and
 * surfaces in the UI as a raw key. Four sources of keys are checked:
 *
 * 1. Every `t('…')` written literally in the source.
 * 2. Every key written as a *field* — `labelKey`, `groupKey`, `titleKey` —
 *    which reaches `t()` through a variable instead of a literal call. These
 *    are the keys a nav item or a route record names, and the literal scan
 *    above cannot see them: a whole sidebar once shipped rendering
 *    `console.project.over…` because of exactly that blind spot.
 * 3. Every key the rule engine *emits as data* — discovered by running the
 *    real engine over the demo document rather than transcribed by hand, so a
 *    new rule cannot ship untranslated.
 * 4. Every key the run service emits the same way. It is a separate walk
 *    because a run is produced by a different engine, and a label invented
 *    there would otherwise reach the screen as `console.runs.evidence.…`
 *    with nothing to catch it — the one gap this file used to have.
 */
const sources = import.meta.glob('/src/**/*.{vue,ts}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const KEY_PATTERN = /\bt\(\s*'([a-zA-Z0-9_.]+)'/g

const FIELD_KEY_PATTERN =
  /\b(?:labelKey|groupKey|titleKey)\s*:\s*'([a-zA-Z0-9_.]+)'/g

const collectWrittenKeys = (): ReadonlySet<string> => {
  const keys = new Set<string>()

  for (const source of Object.values(sources)) {
    for (const pattern of [KEY_PATTERN, FIELD_KEY_PATTERN]) {
      for (const match of source.matchAll(pattern)) {
        if (match[1] !== undefined) keys.add(match[1])
      }
    }
  }

  return keys
}

const collectEmittedKeys = async (): Promise<ReadonlySet<string>> => {
  const agent = createMockAgentService()
  const { parsed } = await agent.loadDemoSpec('prj_keys')
  const understanding = await agent.analyze(parsed, { immediate: true })
  const plan = await agent.generatePlan(understanding, parsed.spec, 'generated')

  const keys = new Set<string>()
  const take = (value: LocalizedText): void => {
    if (isLocalizedMessage(value)) keys.add(value.key)
  }

  for (const dependency of understanding.dependencies) take(dependency.rationale)
  for (const risk of understanding.risks) {
    take(risk.title)
    take(risk.detail)
  }
  for (const finding of understanding.findings) {
    take(finding.action)
    take(finding.decisionSummary)
    for (const item of finding.evidence) take(item.label)
  }

  take(plan.name)
  take(plan.goal)
  for (const scenario of plan.scenarios) {
    take(scenario.name)
    take(scenario.description)
    take(scenario.expected)
    for (const step of scenario.steps) take(step.description)
    for (const assertion of scenario.assertions) take(assertion.description)
  }

  return keys
}

/**
 * Keys a run emits, collected the same way: by running one.
 *
 * Both the passing path and the failing one are driven, because the failure
 * sentence is the one that only ever appears when something has already gone
 * wrong — the worst possible time to discover it renders as a raw key.
 */
const collectRunKeys = async (): Promise<ReadonlySet<string>> => {
  const agent = createMockAgentService()
  const { parsed } = await agent.loadDemoSpec('prj_keys')
  const understanding = await agent.analyze(parsed, { immediate: true })
  const plan = await agent.generatePlan(understanding, parsed.spec, 'generated')
  const approved = { ...plan, status: 'approved' as const }

  const keys = new Set<string>()
  const take = (value: LocalizedText): void => {
    if (isLocalizedMessage(value)) keys.add(value.key)
  }

  const collect = async (candidate: typeof approved): Promise<void> => {
    const runs = createRunService()
    const run = await runs.createRun(
      {
        projectId: 'prj_keys',
        planId: candidate.id,
        plan: candidate,
        specId: parsed.spec.id,
        specDocument: '{"openapi":"3.0.3"}',
        environmentId: 'env_keys',
        variables: { baseUrl: 'https://api.example.com' },
        baseUrl: 'https://api.example.com',
      },
      { immediate: true },
    )

    const detail = await runs.getRunDetail(run.id)
    take(detail.run.planName)
    if (detail.run.failure !== null) take(detail.run.failure.message)

    for (const scenario of detail.scenarios) {
      take(scenario.name)
      for (const step of scenario.steps) {
        take(step.description)
        for (const item of step.evidence) take(item.label)
        if (step.failure !== null) take(step.failure.message)
      }
      for (const assertion of scenario.assertions) take(assertion.description)
    }
  }

  await collect(approved)

  // The same plan with one request step stripped of its endpoint: the only
  // path that produces a step failure, and therefore the only path that
  // produces the failure vocabulary.
  await collect({
    ...approved,
    scenarios: approved.scenarios.map((scenario, index) =>
      index !== 0
        ? scenario
        : {
            ...scenario,
            steps: scenario.steps.map((step, position) =>
              position !== 0 ? step : { ...step, endpointId: null },
            ),
          },
    ),
  })

  return keys
}

const lookup = (dictionary: unknown, key: string): unknown => {
  let node: unknown = dictionary

  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined
    node = (node as Record<string, unknown>)[segment]
  }

  return node
}

describe('dictionary completeness', () => {
  it('scans a meaningful number of source files', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(80)
  })

  it('resolves every literal t() key in both locales', () => {
    const missing: string[] = []

    for (const key of collectWrittenKeys()) {
      const zh = lookup(zhCN, key)
      const en = lookup(enUS, key)
      if (typeof zh !== 'string' || typeof en !== 'string') {
        missing.push(`${key} (zh=${typeof zh}, en=${typeof en})`)
      }
    }

    expect(missing).toEqual([])
  })

  it('resolves every key the rule engine emits, in both locales', async () => {
    const emitted = await collectEmittedKeys()
    expect(emitted.size).toBeGreaterThan(40)

    const missing: string[] = []
    for (const key of emitted) {
      const zh = lookup(zhCN, key)
      const en = lookup(enUS, key)
      if (typeof zh !== 'string' || typeof en !== 'string') {
        missing.push(`${key} (zh=${typeof zh}, en=${typeof en})`)
      }
    }

    expect(missing).toEqual([])
  })

  it('resolves every key a run emits, in both locales', async () => {
    const emitted = await collectRunKeys()
    expect(emitted.size).toBeGreaterThan(8)

    const missing: string[] = []
    for (const key of emitted) {
      const zh = lookup(zhCN, key)
      const en = lookup(enUS, key)
      if (typeof zh !== 'string' || typeof en !== 'string') {
        missing.push(`${key} (zh=${typeof zh}, en=${typeof en})`)
      }
    }

    expect(missing).toEqual([])
  })

  it('keeps the two dictionaries structurally identical', () => {
    const shapeOf = (node: unknown, path = ''): string[] => {
      if (typeof node !== 'object' || node === null) return []

      return Object.entries(node).flatMap(([key, value]) => {
        const childPath = path === '' ? key : `${path}.${key}`
        return typeof value === 'string' ? [childPath] : shapeOf(value, childPath)
      })
    }

    expect(shapeOf(enUS).sort()).toEqual(shapeOf(zhCN).sort())
  })

  it('leaves no empty translations behind', () => {
    const blanks: string[] = []

    const walk = (node: unknown, path: string): void => {
      if (typeof node === 'string') {
        if (node.trim() === '') blanks.push(path)
        return
      }
      if (typeof node !== 'object' || node === null) return

      for (const [key, value] of Object.entries(node)) {
        walk(value, path === '' ? key : `${path}.${key}`)
      }
    }

    walk(enUS, '')
    walk(zhCN, '')
    expect(blanks).toEqual([])
  })
})

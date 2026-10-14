/**
 * Sanitizers for the agent's persisted state.
 *
 * Same contract as `sanitizeDraft` and `sanitizeCollections`: localStorage is
 * user-editable and outlives any single deploy, so stored values are rebuilt
 * into valid shapes rather than merely checked. A malformed scenario is
 * dropped; it must not take the whole plan with it.
 *
 * The *derived* understanding is deliberately absent from this file. It is a
 * pure function of the document, so it is recomputed on load rather than
 * stored — which removes several hundred lines of validation surface and
 * guarantees it can never disagree with the file it came from.
 *
 * Every sanitizer rebuilds a valid object by **spreading what was stored
 * first**, then overwriting the fields it knows. Fields this build has never
 * heard of therefore survive a load: a user who opens the app on a newer
 * deploy and comes back to an older one would otherwise watch those fields
 * silently disappear, and the symptom — a plan that reads as if the agent
 * never wrote that part of it — points at the wrong file entirely. Validation
 * is unaffected, because every known field is written after the spread.
 */

import {
  APPROVAL_STATUSES,
  ASSERTION_KINDS,
  PLAN_SOURCES,
  RISK_LEVELS,
  SPEC_FORMATS,
  SPEC_SOURCES,
  TEST_STEP_KINDS,
  type ApprovalStatus,
  type ApiSpec,
  type AssertionKind,
  type LocalizedText,
  type PlanSource,
  type RiskLevel,
  type SpecFormat,
  type SpecSource,
  type TestAssertion,
  type TestPlan,
  type TestScenario,
  type TestStep,
  type TestStepKind,
} from '@/types/agent'
import { isHttpMethod } from '@/types/api'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

const asStringArray = (value: unknown): readonly string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []

const oneOf = <T extends string>(
  allowed: readonly T[],
  value: unknown,
  fallback: T,
): T =>
  typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback

/* ------------------------------------------------------------------ *
 * Text
 * ------------------------------------------------------------------ */

const sanitizeText = (value: unknown): LocalizedText => {
  if (!isRecord(value)) return { text: '' }

  const key = asString(value.key)
  if (key !== '') {
    const params = sanitizeParams(value.params)
    return params === undefined ? { key } : { key, params }
  }

  return { text: asString(value.text) }
}

const sanitizeParams = (
  value: unknown,
): Readonly<Record<string, string | number>> | undefined => {
  if (!isRecord(value)) return undefined

  const params: Record<string, string | number> = {}
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === 'string' || typeof entry === 'number') params[key] = entry
  }

  return Object.keys(params).length > 0 ? params : undefined
}

/* ------------------------------------------------------------------ *
 * Plan
 * ------------------------------------------------------------------ */

const sanitizeStep = (value: unknown, index: number): TestStep | null => {
  if (!isRecord(value)) return null

  const kind = oneOf<TestStepKind>(TEST_STEP_KINDS, value.kind, 'request')
  const method = isHttpMethod(value.method) ? value.method : null

  return {
    // Unknown fields are carried through: storage outlives a deploy, and a
    // field a newer build wrote must not be swallowed by an older one. Known
    // fields are rebuilt *after* the spread, so validation still wins.
    ...value,
    id: asString(value.id, `step_${String(index)}`),
    index: asNumber(value.index, index),
    kind,
    description: sanitizeText(value.description),
    endpointId: typeof value.endpointId === 'string' ? value.endpointId : null,
    method,
    path: typeof value.path === 'string' ? value.path : null,
    produces: typeof value.produces === 'string' ? value.produces : null,
    consumes: asStringArray(value.consumes),
  }
}

const sanitizeAssertion = (value: unknown, index: number): TestAssertion | null => {
  if (!isRecord(value)) return null

  return {
    ...value,
    id: asString(value.id, `assertion_${String(index)}`),
    kind: oneOf<AssertionKind>(ASSERTION_KINDS, value.kind, 'status'),
    target: asString(value.target),
    expected: asString(value.expected),
    description: sanitizeText(value.description),
  }
}

const sanitizeScenario = (value: unknown, index: number): TestScenario | null => {
  if (!isRecord(value)) return null

  return {
    ...value,
    id: asString(value.id, `scenario_${String(index)}`),
    index: asNumber(value.index, index),
    name: sanitizeText(value.name),
    description: sanitizeText(value.description),
    riskLevel: oneOf<RiskLevel>(RISK_LEVELS, value.riskLevel, 'medium'),
    steps: Array.isArray(value.steps)
      ? value.steps
          .map((step, position) => sanitizeStep(step, position))
          .filter((step): step is TestStep => step !== null)
      : [],
    expected: sanitizeText(value.expected),
    assertions: Array.isArray(value.assertions)
      ? value.assertions
          .map((assertion, position) => sanitizeAssertion(assertion, position))
          .filter((assertion): assertion is TestAssertion => assertion !== null)
      : [],
  }
}

export const sanitizePlans = (value: unknown): readonly TestPlan[] => {
  if (!Array.isArray(value)) return []

  return value.filter(isRecord).map((plan, index) => {
    const status = oneOf<ApprovalStatus>(APPROVAL_STATUSES, plan.status, 'draft')

    return {
      ...plan,
      id: asString(plan.id, `plan_${String(index)}`),
      projectId: asString(plan.projectId),
      specId: asString(plan.specId),
      name: sanitizeText(plan.name),
      goal: sanitizeText(plan.goal),
      riskLevel: oneOf<RiskLevel>(RISK_LEVELS, plan.riskLevel, 'medium'),
      status,
      scenarios: Array.isArray(plan.scenarios)
        ? plan.scenarios
            .map((scenario, position) => sanitizeScenario(scenario, position))
            .filter((scenario): scenario is TestScenario => scenario !== null)
        : [],
      source: oneOf<PlanSource>(PLAN_SOURCES, plan.source, 'generated'),
      generatedAt: asString(plan.generatedAt, new Date().toISOString()),
      approvedAt: typeof plan.approvedAt === 'string' ? plan.approvedAt : null,
      rejectedAt: typeof plan.rejectedAt === 'string' ? plan.rejectedAt : null,
      rejectionReason:
        typeof plan.rejectionReason === 'string' ? plan.rejectionReason : null,
    }
  })
}

/* ------------------------------------------------------------------ *
 * Spec
 * ------------------------------------------------------------------ */

/**
 * A persisted specification.
 *
 * The document text is kept alongside the metadata because the understanding
 * is recomputed from it on load — metadata alone could not be re-analysed.
 */
export interface StoredSpec {
  readonly spec: ApiSpec
  readonly content: string
}

const sanitizeSpec = (value: unknown): ApiSpec | null => {
  if (!isRecord(value)) return null

  const id = asString(value.id)
  const projectId = asString(value.projectId)
  if (id === '' || projectId === '') return null

  return {
    ...value,
    id,
    projectId,
    slug: asString(value.slug, id),
    title: asString(value.title, 'Untitled API'),
    version: asString(value.version, '—'),
    format: oneOf<SpecFormat>(SPEC_FORMATS, value.format, 'openapi-3'),
    source: oneOf<SpecSource>(SPEC_SOURCES, value.source, 'upload'),
    filename: asString(value.filename, 'spec.json'),
    serverUrl: typeof value.serverUrl === 'string' ? value.serverUrl : null,
    endpointCount: asNumber(value.endpointCount),
    loadedAt: asString(value.loadedAt, new Date().toISOString()),
  }
}

export const sanitizeStoredSpecs = (value: unknown): readonly StoredSpec[] => {
  if (!Array.isArray(value)) return []

  const stored: StoredSpec[] = []

  for (const entry of value) {
    if (!isRecord(entry)) continue

    const spec = sanitizeSpec(entry.spec)
    const content = asString(entry.content)

    // Without the document there is nothing to re-analyse, so the record is
    // useless rather than merely incomplete.
    if (spec === null || content === '') continue

    stored.push({ spec, content })
  }

  return stored
}

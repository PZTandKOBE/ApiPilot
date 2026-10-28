/**
 * Test plan generation.
 *
 * Scenarios are read off the understanding, not authored: the lifecycle
 * scenario follows a lifecycle dependency, the dependent-action scenario
 * follows a sub-resource dependency, and the negative scenario is built from
 * the risks the analyser raised. Feed it a different document and it produces
 * a different plan.
 *
 * The plan is always born `draft`. Nothing in this module can approve it —
 * approval is a human action, and it lives in the store.
 */

import type {
  ApiDependency,
  ApiEndpoint,
  ApiRisk,
  ApiUnderstanding,
  AssertionKind,
  ApiSpec,
  PlanSource,
  TestAssertion,
  TestPlan,
  TestScenario,
  TestStep,
} from '@/types/agent'

/* ------------------------------------------------------------------ *
 * Small readers
 * ------------------------------------------------------------------ */

const label = (endpoint: ApiEndpoint): string => `${endpoint.method} ${endpoint.path}`

/** First documented success status, or 200 when the document is silent. */
const successStatus = (endpoint: ApiEndpoint): number =>
  endpoint.responseStatuses.find((status) => status >= 200 && status < 300) ?? 200

/** The property that identifies a created resource, if the schema names one. */
const idFieldOf = (endpoint: ApiEndpoint): string =>
  endpoint.responseProps.find((prop) => prop === 'id') ??
  endpoint.responseProps.find((prop) => prop.endsWith('_id')) ??
  'id'

const endpointById = (
  understanding: ApiUnderstanding,
  id: string,
): ApiEndpoint | null =>
  understanding.endpoints.find((endpoint) => endpoint.id === id) ?? null

/* ------------------------------------------------------------------ *
 * Builders
 * ------------------------------------------------------------------ */

/**
 * Mutable step counter.
 *
 * One per scenario, so `TestStep.index` runs 0..n within its own scenario —
 * a flat counter across the plan would make the workflow viewer re-derive the
 * numbering from scratch.
 */
interface StepContext {
  next: number
}

const createContext = (): StepContext => ({ next: 0 })

const take = (context: StepContext): number => {
  const index = context.next
  context.next += 1
  return index
}

const requestStep = (
  context: StepContext,
  endpoint: ApiEndpoint,
  descriptionKey: string,
  params: Readonly<Record<string, string | number>>,
  consumes: readonly string[],
): TestStep => {
  const index = take(context)
  return {
    id: `${endpoint.id}__${index}`,
    index,
    kind: 'request',
    description: { key: descriptionKey, params },
    endpointId: endpoint.id,
    method: endpoint.method,
    path: endpoint.path,
    produces: null,
    consumes,
  }
}

const responsePathForField = (endpoint: ApiEndpoint, field: string): string =>
  endpoint.responsePaths?.find((path) => path.endsWith('.' + field)) ?? '$.' + field

const extractStep = (
  context: StepContext,
  endpoint: ApiEndpoint,
  variable: string,
  sourcePath: string = responsePathForField(endpoint, variable),
): TestStep => {
  const index = take(context)
  return {
    id: `${endpoint.id}__extract_${variable}`,
    index,
    kind: 'extract',
    description: { key: 'console.aiTest.step.extractVariable', params: { variable } },
    endpointId: endpoint.id,
    method: null,
    path: null,
    produces: variable,
    sourcePath,
    consumes: [],
  }
}

const assertStep = (context: StepContext): TestStep => {
  const index = take(context)
  return {
    id: `assert__${index}`,
    index,
    kind: 'assert',
    description: { key: 'console.aiTest.step.assertResponse' },
    endpointId: null,
    method: null,
    path: null,
    produces: null,
    consumes: [],
  }
}

const assertion = (
  id: string,
  kind: AssertionKind,
  target: string,
  expected: string,
  descriptionKey: string,
  params: Readonly<Record<string, string | number>> = {},
): TestAssertion => ({
  id,
  kind,
  target,
  expected,
  description: { key: descriptionKey, params },
})

const statusAssertion = (endpoint: ApiEndpoint): TestAssertion => {
  const status = successStatus(endpoint)
  return assertion(
    `${endpoint.id}__status`,
    'status',
    'status',
    String(status),
    'console.aiTest.assertion.statusIs',
    { status },
  )
}

/* ------------------------------------------------------------------ *
 * Scenarios
 * ------------------------------------------------------------------ */

const buildAuthenticationScenario = (
  understanding: ApiUnderstanding,
): TestScenario | null => {
  const { authentication } = understanding
  if (authentication.tokenSourceEndpointId === null) return null

  const tokenSource = endpointById(understanding, authentication.tokenSourceEndpointId)
  const identity = understanding.endpoints.find(
    (endpoint) => endpoint.method === 'GET' && /\/me$/i.test(endpoint.path),
  )

  if (tokenSource === null || identity === undefined) return null

  const tokenField = authentication.tokenField ?? 'token'
  const context = createContext()

  return {
    id: 'scenario_authentication',
    index: 0,
    name: { key: 'console.aiTest.scenario.authenticationName' },
    description: { key: 'console.aiTest.scenario.authenticationDescription' },
    riskLevel: 'high',
    steps: [
      requestStep(context, tokenSource, 'console.aiTest.step.login', {}, []),
      extractStep(context, tokenSource, tokenField, responsePathForField(tokenSource, tokenField)),
      requestStep(context, identity, 'console.aiTest.step.fetchIdentity', {}, [tokenField]),
      assertStep(context),
    ],
    expected: { key: 'console.aiTest.scenario.authenticationExpected' },
    assertions: [
      statusAssertion(tokenSource),
      assertion(
        `${tokenSource.id}__token`,
        'field',
        `body.${tokenField}`,
        'present',
        'console.aiTest.assertion.fieldPresent',
        { field: tokenField },
      ),
      statusAssertion(identity),
    ],
  }
}

const buildLifecycleScenario = (
  understanding: ApiUnderstanding,
  dependency: ApiDependency,
  index: number,
): TestScenario | null => {
  const create = endpointById(understanding, dependency.fromEndpointId)
  const read = endpointById(understanding, dependency.toEndpointId)
  if (create === null || read === null) return null

  const resource =
    understanding.resources.find((item) => item.id === create.resourceId)?.name ??
    create.path

  const context = createContext()
  const idField = idFieldOf(create)

  return {
    id: `scenario_lifecycle_${create.id}`,
    index,
    name: { key: 'console.aiTest.scenario.lifecycleName', params: { resource } },
    description: {
      key: 'console.aiTest.scenario.lifecycleDescription',
      params: { resource },
    },
    riskLevel: 'high',
    steps: [
      requestStep(
        context,
        create,
        'console.aiTest.step.createResource',
        { resource },
        [],
      ),
      extractStep(
        context,
        create,
        read.pathParams[0] ?? idField,
        responsePathForField(create, idField),
      ),
      requestStep(
        context,
        read,
        'console.aiTest.step.readResource',
        { resource },
        [read.pathParams[0] ?? idField],
      ),
      assertStep(context),
    ],
    expected: {
      key: 'console.aiTest.scenario.lifecycleExpected',
      params: { resource },
    },
    assertions: [
      statusAssertion(create),
      assertion(
        `${create.id}__id`,
        'field',
        `body.${idField}`,
        'present',
        'console.aiTest.assertion.fieldPresent',
        { field: idField },
      ),
      assertion(
        `${read.id}__retrievable`,
        'schema',
        'body',
        'matches',
        'console.aiTest.assertion.resourceCreated',
      ),
      statusAssertion(read),
    ],
  }
}

const buildDependentScenario = (
  understanding: ApiUnderstanding,
  dependency: ApiDependency,
  index: number,
): TestScenario | null => {
  const action = endpointById(understanding, dependency.toEndpointId)
  if (action === null) return null

  const context = createContext()
  const variable = dependency.binding

  return {
    id: `scenario_dependent_${action.id}`,
    index,
    name: { key: 'console.aiTest.scenario.paymentName' },
    description: {
      key: 'console.aiTest.scenario.paymentDescription',
      params: { endpoint: label(action) },
    },
    riskLevel: 'high',
    steps: [
      requestStep(
        context,
        action,
        'console.aiTest.step.subResourceAction',
        { action: action.path.split('/').filter(Boolean).slice(-1)[0] ?? 'action' },
        [variable],
      ),
      assertStep(context),
    ],
    expected: { key: 'console.aiTest.scenario.paymentExpected' },
    assertions: [statusAssertion(action)],
  }
}

const buildNegativeScenario = (
  understanding: ApiUnderstanding,
  risk: ApiRisk,
  index: number,
): TestScenario | null => {
  const target = risk.relatedEndpointIds
    .map((id) => endpointById(understanding, id))
    .find((endpoint): endpoint is ApiEndpoint => endpoint !== null)

  if (target === undefined) return null

  const unauthenticated =
    understanding.endpoints.find(
      (endpoint) => endpoint.requiresAuth && endpoint.method === 'GET',
    ) ?? null

  // The finding carries the field as data, so the scenario does not have to
  // read it back out of a rendered sentence.
  const field = risk.fields[0] ?? 'value'

  const context = createContext()
  const steps: TestStep[] = [
    requestStep(
      context,
      target,
      'console.aiTest.step.invalidBody',
      { endpoint: label(target) },
      [],
    ),
    requestStep(
      context,
      target,
      'console.aiTest.step.boundaryValue',
      { endpoint: label(target), field },
      [],
    ),
  ]

  const assertions: TestAssertion[] = [
    assertion(
      `${target.id}__reject_missing`,
      'status',
      'status',
      '400',
      'console.aiTest.assertion.statusIs',
      { status: 400 },
    ),
    assertion(
      `${target.id}__reject_boundary`,
      'status',
      'status',
      '400',
      'console.aiTest.assertion.statusIs',
      { status: 400 },
    ),
  ]

  if (unauthenticated !== null) {
    steps.push(
      requestStep(
        context,
        unauthenticated,
        'console.aiTest.step.unauthenticated',
        { endpoint: label(unauthenticated) },
        [],
      ),
    )
    assertions.push(
      assertion(
        `${unauthenticated.id}__reject_unauthenticated`,
        'status',
        'status',
        '401',
        'console.aiTest.assertion.statusIs',
        { status: 401 },
      ),
    )
  }

  steps.push(assertStep(context))

  return {
    id: `scenario_negative_${target.id}`,
    index,
    name: { key: 'console.aiTest.scenario.negativeName' },
    description: { key: 'console.aiTest.scenario.negativeDescription' },
    riskLevel: 'medium',
    steps,
    expected: { key: 'console.aiTest.scenario.negativeExpected' },
    assertions,
  }
}

/**
 * Last resort: one call, one status assertion.
 *
 * Used when the document is too thin for any rule to fire. Being explicit
 * about it beats returning an empty plan, which would read as a failure.
 */
const buildSmokeScenario = (
  understanding: ApiUnderstanding,
): TestScenario | null => {
  const target =
    understanding.endpoints.find((endpoint) =>
      endpoint.responseStatuses.some((status) => status >= 200 && status < 300),
    ) ?? understanding.endpoints[0]

  if (target === undefined) return null

  const context = createContext()
  const endpointLabel = label(target)

  return {
    id: `scenario_smoke_${target.id}`,
    index: 0,
    name: { key: 'console.aiTest.scenario.smokeName' },
    description: {
      key: 'console.aiTest.scenario.smokeDescription',
      params: { endpoint: endpointLabel },
    },
    riskLevel: 'low',
    steps: [
      requestStep(
        context,
        target,
        'console.aiTest.step.callEndpoint',
        { endpoint: endpointLabel },
        [],
      ),
      assertStep(context),
    ],
    expected: {
      key: 'console.aiTest.scenario.smokeExpected',
      params: { endpoint: endpointLabel },
    },
    assertions: [statusAssertion(target)],
  }
}

/* ------------------------------------------------------------------ *
 * Entry point
 * ------------------------------------------------------------------ */

const RISK_ORDER: Readonly<Record<TestScenario['riskLevel'], number>> = {
  low: 0,
  medium: 1,
  high: 2,
}

export const buildPlan = (
  understanding: ApiUnderstanding,
  spec: ApiSpec,
  source: PlanSource,
): TestPlan => {
  const scenarios: TestScenario[] = []

  const pushScenario = (scenario: TestScenario | null): void => {
    if (scenario === null) return
    scenarios.push({ ...scenario, index: scenarios.length + 1 })
  }

  pushScenario(buildAuthenticationScenario(understanding))

  const lifecycle = understanding.dependencies.find(
    (dependency) => dependency.kind === 'lifecycle',
  )
  if (lifecycle !== undefined) {
    pushScenario(buildLifecycleScenario(understanding, lifecycle, scenarios.length))
  }

  const dependent = understanding.dependencies.find(
    (dependency) =>
      dependency.kind === 'sub-resource' &&
      dependency.fromEndpointId !== dependency.toEndpointId &&
      !isSamePath(understanding, dependency),
  )
  if (dependent !== undefined) {
    pushScenario(buildDependentScenario(understanding, dependent, scenarios.length))
  }

  const negativeRisk = understanding.risks.find(
    (risk) => risk.category === 'negative-coverage',
  )
  if (negativeRisk !== undefined) {
    pushScenario(buildNegativeScenario(understanding, negativeRisk, scenarios.length))
  }

  // Nothing specific could be derived — a single-endpoint document with no
  // constraints produces no dependencies and no risks. A plan with zero
  // scenarios would tell the user nothing, so fall back to the one thing that
  // is always worth asserting: that the endpoint answers as documented.
  if (scenarios.length === 0) {
    pushScenario(buildSmokeScenario(understanding))
  }

  // The plan's own risk is the worst case it contains, not an average.
  const riskLevel = scenarios.reduce<TestScenario['riskLevel']>(
    (worst, scenario) =>
      RISK_ORDER[scenario.riskLevel] > RISK_ORDER[worst] ? scenario.riskLevel : worst,
    'low',
  )

  const lifecycleEndpoint =
    lifecycle === undefined ? null : endpointById(understanding, lifecycle.fromEndpointId)
  const resourceName =
    (lifecycleEndpoint === null
      ? undefined
      : understanding.resources.find(
          (item) => item.id === lifecycleEndpoint.resourceId,
        )?.name) ?? spec.title

  return {
    id: `plan_${spec.slug}`,
    projectId: spec.projectId,
    specId: spec.id,
    name: { key: 'console.aiTest.plan.lifecycleName', params: { resource: resourceName } },
    goal: { key: 'console.aiTest.plan.lifecycleGoal', params: { resource: resourceName } },
    riskLevel,
    // Always draft: only a human action can move this forward.
    status: 'draft',
    scenarios,
    source,
    generatedAt: new Date().toISOString(),
    approvedAt: null,
    rejectedAt: null,
    rejectionReason: null,
  }
}

/** True when the edge is an update/delete of the item itself rather than a child action. */
const isSamePath = (
  understanding: ApiUnderstanding,
  dependency: ApiDependency,
): boolean => {
  const from = endpointById(understanding, dependency.fromEndpointId)
  const to = endpointById(understanding, dependency.toEndpointId)
  return from !== null && to !== null && from.path === to.path
}

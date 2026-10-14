/**
 * The analysis rules.
 *
 * This is the whole "agent" today: a deterministic rule engine over a parsed
 * document. It is not a stand-in that returns a canned answer — every
 * dependency, risk and finding below is computed from the specification, so
 * the same rules produce a meaningful result for an uploaded file, not just
 * for the demo.
 *
 * Three properties are load-bearing:
 *
 * - **Deterministic.** No randomness, no clock-dependent branching. The same
 *   document always yields the same understanding, which is what makes the
 *   plan reproducible and the results assertable.
 * - **Explained, not narrated.** Each dependency carries a `rationale` and
 *   each finding carries a `decisionSummary`: one sentence stating the
 *   decision. There is no field for the route taken to it.
 * - **Lifecycle path, not every edge.** The dependency list is the path the
 *   agent would drive a test through. A pairwise dump of all 18 endpoints
 *   would be a hairball and would not correspond to any runnable sequence.
 */

import type { ParsedSpec } from '@/services/agent'
import type {
  AgentActionSummary,
  AgentEvidence,
  AgentActionResult,
  ApiDependency,
  ApiEndpoint,
  ApiRisk,
  ApiUnderstanding,
  DependencyKind,
  RiskLevel,
  SpecFormat,
} from '@/types/agent'

/* ------------------------------------------------------------------ *
 * Name normalisation
 * ------------------------------------------------------------------ */

/** `productId` and `product_id` both normalise to `product_id`. */
const snake = (value: string): string =>
  value.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()

/** Crude but predictable: `Orders` → `order`, `Categories` → `category`. */
const singular = (value: string): string => {
  const lower = value.toLowerCase()
  if (lower.endsWith('ies')) return `${lower.slice(0, -3)}y`
  if (lower.endsWith('ss')) return lower
  return lower.endsWith('s') ? lower.slice(0, -1) : lower
}

const label = (endpoint: ApiEndpoint): string => `${endpoint.method} ${endpoint.path}`

const slug = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')

const isRead = (endpoint: ApiEndpoint): boolean =>
  endpoint.method === 'GET' && endpoint.pathParams.length === 1 && !endpoint.path.endsWith('/me')

/* ------------------------------------------------------------------ *
 * Dependency rules
 * ------------------------------------------------------------------ */

/** i18n key for the sentence explaining why an edge exists. */
type RationaleKey =
  | 'console.aiTest.dependencies.rationaleToken'
  | 'console.aiTest.dependencies.rationaleIdentity'
  | 'console.aiTest.dependencies.rationaleReference'
  | 'console.aiTest.dependencies.rationaleLifecycle'
  | 'console.aiTest.dependencies.rationaleSubResource'

interface DependencyDraft {
  readonly from: ApiEndpoint
  readonly to: ApiEndpoint
  readonly kind: DependencyKind
  readonly binding: string
  readonly rationaleKey: RationaleKey
  readonly params: Readonly<Record<string, string>>
}

const draft = (
  from: ApiEndpoint,
  to: ApiEndpoint,
  kind: DependencyKind,
  binding: string,
  rationaleKey: RationaleKey,
): DependencyDraft => ({
  from,
  to,
  kind,
  binding,
  rationaleKey,
  params: { from: label(from), to: label(to), binding },
})

/**
 * Rules, in priority order.
 *
 * Deduplication is by `(consumer, binding)`: one value can only enter a
 * request one way, so a second rule offering the same binding on the same
 * endpoint is describing the same dependency, not a new one.
 */
const buildDependencyDrafts = (parsed: ParsedSpec): readonly DependencyDraft[] => {
  const { endpoints, authentication } = parsed
  const byId = new Map(endpoints.map((endpoint) => [endpoint.id, endpoint]))
  const drafts: DependencyDraft[] = []
  const claimed = new Set<string>()

  const claim = (candidate: DependencyDraft): boolean => {
    const key = `${candidate.to.id}::${candidate.binding}`
    if (claimed.has(key)) return false
    claimed.add(key)
    drafts.push(candidate)
    return true
  }

  /* Rule 1 — the credential gates everything else. */
  const tokenSource =
    authentication.tokenSourceEndpointId === null
      ? null
      : (byId.get(authentication.tokenSourceEndpointId) ?? null)

  // The identity endpoint is the natural first stop after authenticating, but
  // plenty of APIs do not have one — fall back to the first endpoint the token
  // actually unlocks, so the credential dependency is still reported.
  const identity =
    endpoints.find(
      (endpoint) => endpoint.method === 'GET' && /\/me$/i.test(endpoint.path),
    ) ??
    endpoints.find((endpoint) => endpoint.requiresAuth) ??
    null

  if (tokenSource !== null && identity !== null) {
    claim(
      draft(
        tokenSource,
        identity,
        'token',
        authentication.tokenField ?? authentication.headerName ?? 'token',
        'console.aiTest.dependencies.rationaleToken',
      ),
    )
  }

  /* Rule 2 — a create call made on behalf of the authenticated identity. */
  if (identity !== null) {
    const identityResource = parsed.resources.find(
      (resource) => resource.id === identity.resourceId,
    )
    const ownerField = `${singular(identityResource?.name ?? 'user')}_id`

    for (const endpoint of endpoints) {
      if (endpoint.method !== 'POST' || endpoint.pathParams.length > 0) continue

      const prop = endpoint.requiredBodyProps.find(
        (name) => snake(name) === ownerField,
      )
      if (prop === undefined) continue

      claim(
        draft(
          identity,
          endpoint,
          'identity',
          prop,
          'console.aiTest.dependencies.rationaleIdentity',
        ),
      )
    }
  }

  /* Rule 3 — a required body field pointing at another resource's item read. */
  for (const endpoint of endpoints) {
    if (endpoint.method !== 'POST' && endpoint.method !== 'PATCH') continue

    for (const prop of endpoint.requiredBodyProps) {
      const target = endpoints.find(
        (candidate) =>
          isRead(candidate) &&
          candidate.id !== endpoint.id &&
          snake(candidate.pathParams[0] ?? '') === snake(prop),
      )

      if (target === undefined) continue

      claim(
        draft(
          target,
          endpoint,
          'reference',
          prop,
          'console.aiTest.dependencies.rationaleReference',
        ),
      )
    }
  }

  /* Rule 4 — the resource lifecycle: create, read, then act on what exists. */
  for (const resource of parsed.resources) {
    const members = endpoints.filter(
      (endpoint) => endpoint.resourceId === resource.id,
    )

    const create = members.find(
      (endpoint) => endpoint.method === 'POST' && endpoint.pathParams.length === 0,
    )
    if (create === undefined) continue

    const read = members.find(
      (endpoint) =>
        isRead(endpoint) &&
        endpoint.path.startsWith(`${create.path}/`) &&
        endpoint.path !== create.path,
    )
    if (read === undefined) continue

    const readParam = read.pathParams[0] ?? 'id'
    claim(
      draft(
        create,
        read,
        'lifecycle',
        readParam,
        'console.aiTest.dependencies.rationaleLifecycle',
      ),
    )

    // Scanned across the whole document rather than within the resource: a
    // sub-resource action is often tagged with its own resource
    // (`POST /orders/{id}/payment` is a Payments operation) even though it
    // only makes sense once the order exists.
    for (const action of endpoints) {
      if (action.id === read.id) continue
      if (action.method !== 'POST' && action.method !== 'PATCH' && action.method !== 'DELETE') {
        continue
      }

      const operatesOnRead = action.path === read.path
      const operatesBelowRead = action.path.startsWith(`${read.path}/`)
      if (!operatesOnRead && !operatesBelowRead) continue

      claim(
        draft(
          read,
          action,
          'sub-resource',
          readParam,
          'console.aiTest.dependencies.rationaleSubResource',
        ),
      )
    }
  }

  return drafts
}

/* ------------------------------------------------------------------ *
 * Risk rules
 * ------------------------------------------------------------------ */

interface RiskRuleContext {
  readonly parsed: ParsedSpec
  readonly dependencies: readonly DependencyDraft[]
}

const buildRisks = ({ parsed, dependencies }: RiskRuleContext): readonly ApiRisk[] => {
  const { endpoints } = parsed
  const risks: ApiRisk[] = []

  const push = (
    id: string,
    level: RiskLevel,
    category: ApiRisk['category'],
    titleKey: string,
    detailKey: string,
    params: Readonly<Record<string, string | number>>,
    related: readonly ApiEndpoint[],
    fields: readonly string[] = [],
  ): void => {
    risks.push({
      id,
      level,
      category,
      title: { key: titleKey, params },
      detail: { key: detailKey, params },
      relatedEndpointIds: related.map((endpoint) => endpoint.id),
      fields,
    })
  }

  /* Protected surface with no described unauthenticated path. */
  const protectedEndpoints = endpoints.filter((endpoint) => endpoint.requiresAuth)
  if (protectedEndpoints.length > 0) {
    push(
      'risk_authentication',
      'medium',
      'authentication',
      'console.aiTest.risks.authTitle',
      'console.aiTest.risks.authDetail',
      { count: protectedEndpoints.length },
      protectedEndpoints,
    )
  }

  /* Reads scoped to an account: ownership checks are assumed, not stated. */
  const ownedReads = endpoints.filter(
    (endpoint) => endpoint.requiresAuth && isRead(endpoint),
  )
  if (ownedReads.length > 0) {
    push(
      'risk_authorization',
      'medium',
      'authorization',
      'console.aiTest.risks.authorizationTitle',
      'console.aiTest.risks.authorizationDetail',
      { count: ownedReads.length },
      ownedReads,
    )
  }

  /* Cross-resource references found by rule 3. */
  for (const dependency of dependencies) {
    if (dependency.rationaleKey !== 'console.aiTest.dependencies.rationaleReference') {
      continue
    }

    push(
      // Same identity rule as the dependency id above, for the same reason:
      // this risk is rendered with `risk.id` as its key.
      `risk_reference_${dependency.to.id}_${dependency.binding}`,
      'high',
      'dependency',
      'console.aiTest.risks.referenceTitle',
      'console.aiTest.risks.referenceDetail',
      { endpoint: label(dependency.to), binding: dependency.binding },
      [dependency.to],
      [dependency.binding],
    )
  }

  /* Sub-resource actions that only make sense once the parent exists. */
  for (const dependency of dependencies) {
    if (dependency.rationaleKey !== 'console.aiTest.dependencies.rationaleSubResource') {
      continue
    }
    if (dependency.to.path === dependency.from.path) continue // update / delete of the item itself

    push(
      `risk_parent_${dependency.to.id}`,
      'high',
      'dependency',
      'console.aiTest.risks.parentTitle',
      'console.aiTest.risks.parentDetail',
      { endpoint: label(dependency.to) },
      [dependency.to, dependency.from],
    )
  }

  /* Constrained fields with no described invalid-input case. */
  for (const endpoint of endpoints) {
    if (endpoint.responseStatuses.some((status) => status >= 400 && status < 500)) {
      continue // an error path is documented; assume it is covered
    }

    for (const field of endpoint.constrainedBodyProps) {
      push(
        `risk_negative_${endpoint.id}_${slug(field)}`,
        'medium',
        'negative-coverage',
        'console.aiTest.risks.negativeTitle',
        'console.aiTest.risks.negativeDetail',
        { field, endpoint: label(endpoint) },
        [endpoint],
        [field],
      )
    }
  }

  const deletes = endpoints.filter((endpoint) => endpoint.method === 'DELETE')
  if (deletes.length > 0) {
    push(
      'risk_idempotency',
      'low',
      'idempotency',
      'console.aiTest.risks.idempotencyTitle',
      'console.aiTest.risks.idempotencyDetail',
      { count: deletes.length },
      deletes,
    )
  }

  return risks
}

/* ------------------------------------------------------------------ *
 * Findings
 * ------------------------------------------------------------------ */

const evidence = (labelKey: string, value: string): AgentEvidence => ({
  label: { key: labelKey },
  value,
})

const finding = (
  id: string,
  at: string,
  actionKey: string,
  actionParams: Readonly<Record<string, string | number>>,
  decisionKey: string,
  decisionParams: Readonly<Record<string, string | number>>,
  evidenceItems: readonly AgentEvidence[],
  result: AgentActionResult = 'succeeded',
): AgentActionSummary => ({
  id,
  action: { key: actionKey, params: actionParams },
  decisionSummary: { key: decisionKey, params: decisionParams },
  result,
  evidence: evidenceItems,
  at,
})

const FORMAT_LABEL: Readonly<Record<SpecFormat, string>> = {
  'openapi-3': 'OpenAPI 3',
  'swagger-2': 'Swagger 2',
}

const buildFindings = (
  parsed: ParsedSpec,
  dependencies: readonly ApiDependency[],
  risks: readonly ApiRisk[],
  at: string,
): readonly AgentActionSummary[] => {
  const { spec, endpoints, resources, authentication } = parsed

  const tokenSource = endpoints.find(
    (endpoint) => endpoint.id === authentication.tokenSourceEndpointId,
  )

  return [
    finding(
      'finding_parsed',
      at,
      'console.aiTest.findings.parsed',
      { format: FORMAT_LABEL[spec.format] },
      'console.aiTest.findings.parsedDecision',
      {},
      [
        evidence('console.aiTest.evidence.format', FORMAT_LABEL[spec.format]),
        evidence('console.aiTest.evidence.endpoints', String(endpoints.length)),
      ],
    ),
    finding(
      'finding_endpoints',
      at,
      'console.aiTest.findings.endpoints',
      { count: endpoints.length, resources: resources.length },
      'console.aiTest.findings.endpointsDecision',
      {},
      [
        evidence('console.aiTest.evidence.endpoints', String(endpoints.length)),
        evidence('console.aiTest.evidence.resources', String(resources.length)),
      ],
    ),
    finding(
      'finding_authentication',
      at,
      'console.aiTest.findings.authentication',
      { scheme: authentication.scheme },
      'console.aiTest.findings.authenticationDecision',
      { source: tokenSource === undefined ? '—' : label(tokenSource) },
      [
        evidence('console.aiTest.evidence.protectedEndpoints', String(authentication.protectedEndpointCount)),
        evidence(
          'console.aiTest.evidence.tokenSource',
          tokenSource === undefined ? '—' : label(tokenSource),
        ),
      ],
      tokenSource === undefined ? 'skipped' : 'succeeded',
    ),
    finding(
      'finding_dependencies',
      at,
      'console.aiTest.findings.dependencies',
      { count: dependencies.length },
      'console.aiTest.findings.dependenciesDecision',
      {},
      [evidence('console.aiTest.evidence.dependencies', String(dependencies.length))],
      dependencies.length === 0 ? 'skipped' : 'succeeded',
    ),
    finding(
      'finding_risks',
      at,
      'console.aiTest.findings.risks',
      { count: risks.length },
      'console.aiTest.findings.risksDecision',
      {},
      [evidence('console.aiTest.evidence.risks', String(risks.length))],
    ),
  ]
}

/* ------------------------------------------------------------------ *
 * Entry point
 * ------------------------------------------------------------------ */

export const buildUnderstanding = (parsed: ParsedSpec): ApiUnderstanding => {
  const analyzedAt = new Date().toISOString()

  const drafts = buildDependencyDrafts(parsed)
  const risks = buildRisks({ parsed, dependencies: drafts })

  const dependencies: readonly ApiDependency[] = drafts.map((item) => ({
    // The raw binding, not a slug of it: deduplication above keys on
    // `(to, binding)` verbatim, so slugging here would give two values that
    // survived dedup as distinct — `orderId` and `OrderId` — one shared id,
    // and a duplicated `:key` wherever edges are rendered.
    id: `dep_${item.from.id}__${item.to.id}__${item.binding}`,
    fromEndpointId: item.from.id,
    toEndpointId: item.to.id,
    kind: item.kind,
    binding: item.binding,
    rationale: { key: item.rationaleKey, params: item.params },
  }))

  return {
    specId: parsed.spec.id,
    endpoints: parsed.endpoints,
    resources: parsed.resources,
    authentication: parsed.authentication,
    dependencies,
    risks,
    findings: buildFindings(parsed, dependencies, risks, analyzedAt),
    analyzedAt,
  }
}

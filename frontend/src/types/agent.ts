/**
 * Agent domain model.
 *
 * Everything the agent produces and everything a human reviews. Three rules
 * shape this file:
 *
 * 1. **No chain-of-thought, structurally.** There is no `thought`,
 *    `reasoning` or `internalReasoning` field anywhere, and no field that
 *    smuggles the same content under another name. What the agent exposes is
 *    `AgentActionSummary`: what it *did*, the decision it took, the outcome,
 *    and the evidence. That is a type-level guarantee, not a UI convention.
 *
 * 2. **Authored text is translatable, generated text is not.** Strings the
 *    app authors (risk titles, stage names, plan copy) are i18n keys; strings
 *    that come out of a document or a model are literals. `LocalizedText`
 *    expresses that distinction so a real LLM's prose can flow through the
 *    same fields later without a schema change.
 *
 * 3. **Ids are derived, not random.** Everything is keyed by a slug of the
 *    thing it describes, so a plan generated today still points at the right
 *    endpoint after a reload.
 */

import type { HttpMethod } from './api'

/* ------------------------------------------------------------------ *
 * Text
 * ------------------------------------------------------------------ */

/** A string the app authored, resolved from the dictionary at render time. */
export interface LocalizedMessage {
  readonly key: string
  readonly params?: Readonly<Record<string, string | number>>
}

/** A string that came from a document or a model; shown exactly as received. */
export interface LiteralMessage {
  readonly text: string
}

export type LocalizedText = LocalizedMessage | LiteralMessage

export const isLocalizedMessage = (
  value: LocalizedText,
): value is LocalizedMessage => 'key' in value

/* ------------------------------------------------------------------ *
 * Specification
 * ------------------------------------------------------------------ */

export const SPEC_FORMATS = ['openapi-3', 'swagger-2'] as const
export type SpecFormat = (typeof SPEC_FORMATS)[number]

export const SPEC_SOURCES = ['demo', 'upload', 'paste', 'handoff'] as const
export type SpecSource = (typeof SPEC_SOURCES)[number]

/**
 * A parsed API document.
 *
 * Holds only what was read out of the file — the understanding derived from it
 * is a separate, recomputable value.
 */
export interface ApiSpec {
  readonly id: string
  readonly projectId: string
  /** Spec slug shared by every id derived from this document. */
  readonly slug: string
  readonly title: string
  readonly version: string
  readonly format: SpecFormat
  readonly source: SpecSource
  readonly filename: string
  readonly serverUrl: string | null
  readonly endpointCount: number
  readonly loadedAt: string
}

/* ------------------------------------------------------------------ *
 * Understanding
 * ------------------------------------------------------------------ */

export interface ApiEndpoint {
  /** `ep_get_api_orders_orderid` — a slug of method + path. */
  readonly id: string
  readonly method: HttpMethod
  readonly path: string
  readonly resourceId: string
  /** From the operation's `summary`, else `description`, else derived. */
  readonly summary: LocalizedText
  readonly requiresAuth: boolean
  /** Path parameters, in declaration order: `orderId`. */
  readonly pathParams: readonly string[]
  /** Required request-body property names. */
  readonly requiredBodyProps: readonly string[]
  /**
   * Required body properties that carry a value constraint — a range, an
   * enum, a pattern. These are the fields a negative case should exercise.
   */
  readonly constrainedBodyProps: readonly string[]
  /** Documented response status codes. */
  readonly responseStatuses: readonly number[]
  /** Documented response property names of the 2xx body, if any. */
  readonly responseProps: readonly string[]
}

export interface ApiResource {
  readonly id: string
  /** From the operation's first tag, else the first path segment. */
  readonly name: string
  readonly endpointIds: readonly string[]
}

export const AUTH_SCHEMES = ['none', 'bearer', 'apiKey', 'basic', 'oauth2'] as const
export type AuthScheme = (typeof AUTH_SCHEMES)[number]

export interface ApiAuthentication {
  readonly scheme: AuthScheme
  /** Scheme name as declared in the document, e.g. `bearerAuth`. */
  readonly schemeName: string | null
  /** Header the credential travels in, when the document says so. */
  readonly headerName: string | null
  /** Endpoint that issues the credential — the login route. */
  readonly tokenSourceEndpointId: string | null
  /** Response property carrying the credential, e.g. `token`. */
  readonly tokenField: string | null
  readonly protectedEndpointCount: number
}

export const DEPENDENCY_KINDS = [
  'token',
  'identity',
  'reference',
  'lifecycle',
  'sub-resource',
] as const

/**
 * Why an edge exists — the rule that produced it.
 *
 * An explicit discriminator rather than a reading of the rationale's i18n key:
 * consumers branch on the *meaning*, and the dictionary stays free to reword.
 */
export type DependencyKind = (typeof DEPENDENCY_KINDS)[number]

/**
 * A data or sequencing edge on the lifecycle path the agent selected.
 *
 * Not a pairwise dump of every endpoint relationship: the agent reports the
 * path it would actually drive a test through, which is also the skeleton the
 * generated plan follows.
 */
export interface ApiDependency {
  readonly id: string
  readonly fromEndpointId: string
  readonly toEndpointId: string
  readonly kind: DependencyKind
  /** The value carried across the edge: `token`, `orderId`, `product_id`. */
  readonly binding: string
  /** One sentence on why the edge exists. */
  readonly rationale: LocalizedText
}

export const RISK_LEVELS = ['low', 'medium', 'high'] as const
export type RiskLevel = (typeof RISK_LEVELS)[number]

export const RISK_CATEGORIES = [
  'authentication',
  'dependency',
  'validation',
  'negative-coverage',
  'idempotency',
  'authorization',
] as const
export type RiskCategory = (typeof RISK_CATEGORIES)[number]

/** A finding. What the agent noticed about the API under test. */
export interface ApiRisk {
  readonly id: string
  readonly level: RiskLevel
  readonly category: RiskCategory
  readonly title: LocalizedText
  readonly detail: LocalizedText
  readonly relatedEndpointIds: readonly string[]
  /**
   * The concrete fields the finding is about, when it has any.
   *
   * Structured rather than lifted back out of the title's interpolation
   * params: consumers need the fact, not the sentence it was rendered into.
   */
  readonly fields: readonly string[]
}

/* ------------------------------------------------------------------ *
 * Observable agent activity
 * ------------------------------------------------------------------ */

export interface AgentEvidence {
  readonly label: LocalizedText
  /** A concrete artifact: a count, a path, a field name. */
  readonly value: string
}

export const AGENT_ACTION_RESULTS = ['succeeded', 'failed', 'skipped'] as const
export type AgentActionResult = (typeof AGENT_ACTION_RESULTS)[number]

/**
 * One thing the agent did, reported in the open.
 *
 * `decisionSummary` is a one-line statement of the *decision*, never the route
 * taken to it. "Login must run before protected endpoints" is a decision;
 * "first I considered X, then rejected Y" is not, and there is nowhere to put
 * it.
 */
export interface AgentActionSummary {
  readonly id: string
  readonly action: LocalizedText
  readonly decisionSummary: LocalizedText
  readonly result: AgentActionResult
  readonly evidence: readonly AgentEvidence[]
  readonly at: string
}

/* ------------------------------------------------------------------ *
 * Analysis progress
 * ------------------------------------------------------------------ */

export const ANALYSIS_STAGES = [
  'parsing',
  'endpoints',
  'authentication',
  'dependencies',
  'risks',
] as const
export type AnalysisStage = (typeof ANALYSIS_STAGES)[number]

export interface AnalysisProgress {
  readonly stage: AnalysisStage
  readonly completed: readonly AnalysisStage[]
}

/** Everything the agent understood about one specification. */
export interface ApiUnderstanding {
  readonly specId: string
  readonly endpoints: readonly ApiEndpoint[]
  readonly resources: readonly ApiResource[]
  readonly authentication: ApiAuthentication
  readonly dependencies: readonly ApiDependency[]
  readonly risks: readonly ApiRisk[]
  readonly findings: readonly AgentActionSummary[]
  readonly analyzedAt: string
}

/* ------------------------------------------------------------------ *
 * Test plan
 * ------------------------------------------------------------------ */

export const APPROVAL_STATUSES = [
  'draft',
  'in_review',
  'approved',
  'rejected',
] as const
export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number]

export const TEST_STEP_KINDS = ['request', 'extract', 'assert'] as const
export type TestStepKind = (typeof TEST_STEP_KINDS)[number]

export interface TestStep {
  readonly id: string
  readonly index: number
  readonly kind: TestStepKind
  readonly description: LocalizedText
  /** Set on `request` steps; `null` on extract / assert steps. */
  readonly endpointId: string | null
  readonly method: HttpMethod | null
  readonly path: string | null
  /** Variable this step produces, for `extract` steps. */
  readonly produces: string | null
  /** Variables this step consumes. */
  readonly consumes: readonly string[]
  /**
   * The JSON request body this step sends, exactly as the plan states it.
   * Absent on a plan that predates request bodies.
   */
  readonly body?: unknown
  /**
   * Whether the body is a body at all. A step with no body and a step that
   * sends the JSON literal null are different requests.
   */
  readonly body_present?: boolean
}

export const ASSERTION_KINDS = ['status', 'field', 'schema', 'header'] as const
export type AssertionKind = (typeof ASSERTION_KINDS)[number]

export interface TestAssertion {
  readonly id: string
  readonly kind: AssertionKind
  /** Dotted path within the response, e.g. `body.token` or `status`. */
  readonly target: string
  readonly expected: string
  readonly description: LocalizedText
  /**
   * The assert step this assertion reads, when the plan states one. Absent on
   * plans generated before assertions carried their own step.
   */
  readonly stepId?: string | null
}

export interface TestScenario {
  readonly id: string
  readonly index: number
  readonly name: LocalizedText
  readonly description: LocalizedText
  readonly riskLevel: RiskLevel
  readonly steps: readonly TestStep[]
  readonly expected: LocalizedText
  readonly assertions: readonly TestAssertion[]
}

export const PLAN_SOURCES = ['generated', 'handoff'] as const
export type PlanSource = (typeof PLAN_SOURCES)[number]

/**
 * The approval boundary.
 *
 * `approved` is the only status that permits execution, and only
 * `approvePlan()` can produce it — the agent generates `draft` and stops.
 */
export interface TestPlan {
  readonly id: string
  readonly projectId: string
  readonly specId: string
  readonly name: LocalizedText
  readonly goal: LocalizedText
  readonly riskLevel: RiskLevel
  readonly status: ApprovalStatus
  readonly scenarios: readonly TestScenario[]
  readonly source: PlanSource
  readonly generatedAt: string
  readonly approvedAt: string | null
  readonly rejectedAt: string | null
  /** Free text typed by the reviewer; never generated. */
  readonly rejectionReason: string | null
  /**
   * The plan's version within its project/document series. The first plan is 1;
   * a regeneration creates the next version under a new id. Absent on plans
   * persisted before versioning existed.
   */
  readonly version?: number
  /**
   * Whether this is the highest version for its document. Currentness is
   * independent of approval: a newer draft is current while the older approved
   * version remains available.
   */
  readonly isCurrent?: boolean
  /** Number of runs whose plan id points at this version, when the server supplies it. */
  readonly runCount?: number
}

/* ------------------------------------------------------------------ *
 * Agent task
 * ------------------------------------------------------------------ */

/**
 * The four states a server-side agent task can be in.
 *
 * Mirrors AgentTaskStatus in backend/src/backend/schemas/agent.py. It lives here
 * rather than in the service boundary because two modules need it at runtime --
 * the boundary that declares the task and the HTTP adapter that validates the
 * status it was answered with -- and a value they share belongs where neither
 * has to import the other.
 */
export const AGENT_TASK_STATUSES = ['pending', 'analyzing', 'completed', 'failed'] as const

export type AgentTaskStatus = (typeof AGENT_TASK_STATUSES)[number]

/* ------------------------------------------------------------------ *
 * Pipeline
 * ------------------------------------------------------------------ */

/**
 * The agent's workflow, in order.
 *
 * Position is *derived* from state rather than stored: a step cannot be
 * marked complete without the artifact it produces actually existing, so the
 * pipeline can never claim progress the user cannot see.
 */
export const PIPELINE_STEPS = [
  'spec',
  'analyze',
  'understanding',
  'plan',
  'approve',
  'execute',
] as const

export type PipelineStep = (typeof PIPELINE_STEPS)[number]

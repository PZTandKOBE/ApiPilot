/**
 * Project, environment and variable shapes.
 *
 * These are the contract the console is built against while the backend does
 * not exist yet; the mock service returns exactly this shape, so replacing the
 * mock with `GET /api/projects` is a service-layer change only.
 */

export type EnvironmentKind = 'development' | 'testing' | 'staging' | 'production'

/**
 * A single `{{name}}` substitution available to every request issued against
 * an environment.
 */
export interface EnvironmentVariable {
  readonly key: string
  readonly value: string
  /** Secret values are masked in the UI and never rendered in full. */
  readonly secret: boolean
}

export interface ProjectEnvironment {
  readonly id: string
  readonly name: string
  readonly kind: EnvironmentKind
  /** Prefix for relative request paths; also the fallback for `{{baseUrl}}`. */
  readonly baseUrl: string
  readonly variables: readonly EnvironmentVariable[]
}

export interface Project {
  readonly id: string
  readonly name: string
  readonly description: string
  /** Filename of the uploaded OpenAPI document, or `null` before upload. */
  readonly specName: string | null
  readonly environments: readonly ProjectEnvironment[]
  /** ISO-8601. Formatted for display against the reader's locale. */
  readonly updatedAt: string
}

/** The latest persisted API specification for one project. */
export interface ProjectSpecSummary {
  readonly id: string
  readonly name: string
  readonly filename: string | null
  readonly specType: string
  readonly contentFormat: string
  readonly version: string | null
  readonly source: string
  readonly endpointCount: number
  readonly createdAt: string
  readonly updatedAt: string
}

const ENVIRONMENT_KINDS: readonly EnvironmentKind[] = [
  'development',
  'testing',
  'staging',
  'production',
]

export const isEnvironmentKind = (value: unknown): value is EnvironmentKind =>
  typeof value === 'string' && ENVIRONMENT_KINDS.includes(value as EnvironmentKind)

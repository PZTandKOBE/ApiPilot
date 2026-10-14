/**
 * Projects, from the backend that now owns them.
 *
 * Two calls, both authenticated by the session the shared HTTP layer attaches:
 * list what this guest owns, and create the first one when the list is empty.
 *
 * The wire shape is ``types/project.ts`` already -- the backend's response was built
 * to it -- so this module maps nothing. What it does not return is the mock's
 * environments-and-variables richness: a project created here has exactly one
 * environment, which is what a run needs in order to have a base URL.
 */

import { request } from '@/services/http'
import type { Project } from '@/types/project'

/** A project as the API returns it: the console's shape, wire-decoded. */
export interface ProjectWire {
  readonly id: string
  readonly name: string
  readonly description: string
  readonly specName: string | null
  readonly environments: readonly {
    readonly id: string
    readonly name: string
    readonly kind: string
    readonly baseUrl: string
    readonly variables: readonly { readonly key: string; readonly value: string; readonly secret: boolean }[]
  }[]
  readonly updatedAt: string
}

const toProject = (wire: ProjectWire): Project => ({
  id: wire.id,
  name: wire.name,
  description: wire.description,
  specName: wire.specName,
  updatedAt: wire.updatedAt,
  environments: wire.environments.map((environment) => ({
    id: environment.id,
    name: environment.name,
    kind: environment.kind === 'production' || environment.kind === 'staging' ? environment.kind : 'development',
    baseUrl: environment.baseUrl,
    variables: environment.variables.map((variable) => ({
      key: variable.key,
      value: variable.value,
      secret: variable.secret,
    })),
  })),
})

export interface CreateProjectInput {
  readonly name: string
  readonly baseUrl?: string
}

/** Every project this guest owns, oldest first. */
export const listProjects = async (signal?: AbortSignal): Promise<Project[]> => {
  const body = await request<ProjectWire[]>('/api/projects', { signal })

  return body.map(toProject)
}

/**
 * Create a project owned by the caller's session.
 *
 * The body carries a name and, optionally, where the API under test lives. It
 * cannot carry an owner: the request schema forbids unknown fields, so anything
 * that tried would be a validation error rather than a quietly ignored claim.
 */
export const createProject = async (input: CreateProjectInput): Promise<Project> => {
  const body = await request<ProjectWire>('/api/projects', {
    method: 'POST',
    body: input.baseUrl === undefined ? { name: input.name } : { name: input.name, baseUrl: input.baseUrl },
  })

  return toProject(body)
}

/**
 * Projects, environments and the project's current API specification.
 *
 * Every call is authenticated by the shared HTTP layer; ownership is the
 * backend's decision, keyed by the project public id in the path. The wire
 * shape is mapped here, so the store and the views see one project shape.
 */

import { request } from '@/services/http'
import { isEnvironmentKind } from '@/types/project'
import type {
  EnvironmentKind,
  Project,
  ProjectSpecSummary,
} from '@/types/project'

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

/** The current project spec summary; content and endpoint trees are omitted. */
export interface ProjectSpecWire {
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

const toProject = (wire: ProjectWire): Project => ({
  id: wire.id,
  name: wire.name,
  description: wire.description,
  specName: wire.specName,
  updatedAt: wire.updatedAt,
  environments: wire.environments.map((environment) => ({
    id: environment.id,
    name: environment.name,
    kind: isEnvironmentKind(environment.kind) ? environment.kind : 'development',
    baseUrl: environment.baseUrl,
    variables: environment.variables.map((variable) => ({
      key: variable.key,
      value: variable.value,
      secret: variable.secret,
    })),
  })),
})

const toSpec = (wire: ProjectSpecWire): ProjectSpecSummary => ({
  id: wire.id,
  name: wire.name,
  filename: wire.filename,
  specType: wire.specType,
  contentFormat: wire.contentFormat,
  version: wire.version,
  source: wire.source,
  endpointCount: wire.endpointCount,
  createdAt: wire.createdAt,
  updatedAt: wire.updatedAt,
})

export interface CreateProjectInput {
  readonly name: string
  readonly baseUrl?: string
}

export interface UpdateProjectInput {
  readonly name: string
}

export interface UpdateEnvironmentInput {
  readonly name: string
  readonly kind: EnvironmentKind
  readonly baseUrl: string
}

export type CreateEnvironmentInput = UpdateEnvironmentInput

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

/** Permanently delete a project and all project-owned data. */
export const deleteProject = async (projectId: string): Promise<void> => {
  await request<void>('/api/projects/' + encodeURIComponent(projectId), {
    method: 'DELETE',
  })
}

/** Rename one project; the backend returns the fresh project aggregate. */
export const updateProject = async (
  projectId: string,
  input: UpdateProjectInput,
): Promise<Project> => {
  const body = await request<ProjectWire>('/api/projects/' + encodeURIComponent(projectId), {
    method: 'PATCH',
    body: input,
  })

  return toProject(body)
}

/** Create one environment under a project; the project is returned. */
export const createEnvironment = async (
  projectId: string,
  input: CreateEnvironmentInput,
): Promise<Project> => {
  const body = await request<ProjectWire>(
    '/api/projects/' + encodeURIComponent(projectId) + '/environments',
    {
      method: 'POST',
      body: input,
    },
  )

  return toProject(body)
}

/** Update the editable fields of one environment; the project is returned. */
export const updateEnvironment = async (
  projectId: string,
  environmentId: string,
  input: UpdateEnvironmentInput,
): Promise<Project> => {
  const body = await request<ProjectWire>(
    '/api/projects/' +
      encodeURIComponent(projectId) +
      '/environments/' +
      encodeURIComponent(environmentId),
    {
      method: 'PATCH',
      body: input,
    },
  )

  return toProject(body)
}

/**
 * The latest persisted spec for the project.
 *
 * A null body is a successful "no spec yet" answer, distinct from a request
 * failure. The endpoint deliberately does not return the document content.
 */
export const getProjectSpec = async (
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectSpecSummary | null> => {
  const body = await request<ProjectSpecWire | null>(
    '/api/projects/' + encodeURIComponent(projectId) + '/spec',
    { signal },
  )

  return body === null ? null : toSpec(body)
}

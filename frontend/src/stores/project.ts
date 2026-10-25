import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
// Aliased: the *service* function and the *store action* below are both the
// project-creating operation, and the action is the name callers should use.
import {
  createEnvironment as createEnvironmentRequest,
  createProject as createProjectRequest,
  deleteProject as deleteProjectRequest,
  listProjects,
  updateEnvironment as updateEnvironmentRequest,
  updateProject as updateProjectRequest,
  type CreateEnvironmentInput,
  type UpdateEnvironmentInput,
} from '@/services/api/projects'
import type { Project, ProjectEnvironment } from '@/types/project'

/**
 * Which projects this console is showing: the backend's, or the mock's.
 *
 * Same convention as the run and agent services: the real service unless the
 * build says otherwise, and the mock under test. There is no third mode -- and
 * in particular no fallback from one to the other, because a console that
 * quietly showed mock projects after a failed load would be showing projects the
 * guest does not own.
 */
const usesRealProjects = (): boolean =>
  import.meta.env.MODE !== 'test' && import.meta.env.VITE_PROJECT_SERVICE !== 'mock'

const PROJECT_STORAGE_KEY = 'aiata.console.project'
const ENVIRONMENT_STORAGE_KEY = 'aiata.console.environment'

/**
 * Projects, environments and the variables they expose.
 *
 * Environment ids are globally unique, so a single persisted "active
 * environment" is enough — `activeEnvironment` falls back to the active
 * project's first environment when the stored one belongs to a different
 * project, which is what makes switching project safe.
 */
/**
 * Thrown when a business request asks for a project that is not ready.
 *
 * `reason` separates the two ways this happens, because a page may want to
 * say different things: `failed` is an initialisation that did not complete
 * (the API refused or was unreachable), `missing` is a completed initialisation
 * with no project to hand out.  Neither is ever satisfied with a mock id.
 */
export class ProjectNotReadyError extends Error {
  readonly reason: 'failed' | 'missing'

  constructor(reason: 'failed' | 'missing') {
    super('project-not-ready:' + reason)
    this.name = 'ProjectNotReadyError'
    this.reason = reason
  }
}

/** The in-flight initialisation, shared by every concurrent caller. */
let inFlight: Promise<void> | null = null

export const useProjectStore = defineStore('project', () => {
  /**
   * The guest's projects: empty until \`initialize()\` says otherwise.
   *
   * It used to start on a seeded list, and that is exactly what made the console
   * flash a project the visitor had not been shown to own — the top bar named it,
   * the navigation linked to it, and a page could read its id, all before the
   * backend had answered.  An empty list is not "no projects"; it is "not asked
   * yet", and \`status\` is what tells the two apart.
   */
  const projects = ref<readonly Project[]>([])

  // What is stored is a *candidate*, never an authority: `initialize()` accepts it
  // only when the backend's list for the current guest contains it. A leftover
  // mock id, or one belonging to a session that has since been replaced, fails
  // that test and is replaced by a project that really exists.
  // The third argument is required by the helper; accepting any non-empty
  // candidate is what makes the *loaded list* the authority instead of a
  // hard-coded set of ids (there is none any more in real mode).
  const activeProjectId = usePersistedRef<string>(PROJECT_STORAGE_KEY, '', {
    validate: (value: unknown): value is string =>
      typeof value === 'string' && value !== '',
  })

  const activeEnvironmentId = usePersistedRef<string>(
    ENVIRONMENT_STORAGE_KEY,
    '',
    {
      validate: (value: unknown): value is string =>
        typeof value === 'string' && value !== '',
    },
  )

  /** Where initialisation has got to. `error` is a real state, not a fallback. */
  const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const error = ref<string | null>(null)

  const activeProject = computed<Project | null>(
    () =>
      projects.value.find((project) => project.id === activeProjectId.value) ??
      null,
  )

  const environments = computed<readonly ProjectEnvironment[]>(
    () => activeProject.value?.environments ?? [],
  )

  const activeEnvironment = computed<ProjectEnvironment | null>(() => {
    const project = activeProject.value
    if (project === null) return null

    const stored = project.environments.find(
      (environment) => environment.id === activeEnvironmentId.value,
    )

    return stored ?? project.environments[0] ?? null
  })

  /**
   * Flattened `{{key}}` substitutions for the active environment. This is the
   * single source the API Client and the agent read from — neither should walk
   * the environment structure itself.
   */
  const variables = computed<Readonly<Record<string, string>>>(() => {
    const environment = activeEnvironment.value
    if (environment === null) return {}

    return Object.fromEntries(
      environment.variables.map((variable) => [variable.key, variable.value]),
    )
  })

  const projectById = (id: string): Project | null =>
    projects.value.find((project) => project.id === id) ?? null

  const selectProject = (id: string): void => {
    // Only a project that is actually loaded can become the active one.
    if (projectById(id) === null) return

    activeProjectId.value = id

    // The stored environment may belong to the project we just left.
    const project = projectById(id)
    const stillValid = project?.environments.some(
      (environment) => environment.id === activeEnvironmentId.value,
    )
    if (!stillValid) {
      activeEnvironmentId.value = project?.environments[0]?.id ?? ''
    }
  }

  const selectEnvironment = (id: string): void => {
    if (!environments.value.some((environment) => environment.id === id)) return
    activeEnvironmentId.value = id
  }

  /**
   * The project id a business request may use -- or a refusal.
   *
   * This is the gate every caller that needs a project must pass through, and it
   * is deliberately stricter than "the id is not empty": the store has to be
   * `ready` *and* the id has to be one of the projects that were actually loaded
   * for this guest. A leftover `prj_orders` in localStorage, or an id belonging
   * to a session that has since been replaced, fails that second test -- which is
   * the whole point, because the backend would answer 404 for it anyway.
   *
   * In mock mode `initialize()` is already `ready` and the loaded list is the mock
   * list, so the same rules hold without a special case.
   */
  const requireReadyProjectId = async (): Promise<string> => {
    await initialize()

    if (status.value !== 'ready') {
      throw new ProjectNotReadyError('failed')
    }

    const id = activeProjectId.value

    if (id === '' || projectById(id) === null) {
      throw new ProjectNotReadyError('missing')
    }

    return id
  }

  /**
   * Load this guest's projects.
   *
   * An empty list is a real answer, not an instruction to create a placeholder.
   * Creating "My first API" here was what made a deleted last project reappear
   * after a refresh: the deletion was persistent, but the next initialization
   * made a brand-new project with the same familiar name. The project index and
   * dashboard already render the empty state and creation entry.
   *
   * Single-flight: the promise lives outside the returned state, so two views
   * mounting together share one load. A failure is recorded and *not* retried
   * here: the page is told, and it is the page's decision whether to try again.
   */
  const initialize = async (): Promise<void> => {
    if (!usesRealProjects()) {
      status.value = 'ready'

      return
    }

    if (status.value === 'ready') return
    if (inFlight !== null) return await inFlight

    status.value = 'loading'
    error.value = null

    inFlight = (async () => {
      try {
        const loaded = await listProjects()

        projects.value = loaded

        if (loaded.length === 0) {
          // Nothing was deleted by this branch and nothing is invented by it.
          // The persisted id belongs to the project the user just removed; it
          // must not become a candidate for the next list or the next request.
          activeProjectId.value = ''
          activeEnvironmentId.value = ''
          status.value = 'ready'
          return
        }

        const stored = activeProjectId.value
        const chosen = loaded.find((project) => project.id === stored) ?? loaded[0]

        activeProjectId.value = chosen.id
        activeEnvironmentId.value = chosen.environments[0]?.id ?? ''
        status.value = 'ready'
      } catch (thrown) {
        // No mock, no stale id, no partial project: an explicit error state.
        projects.value = []
        activeProjectId.value = ''
        activeEnvironmentId.value = ''
        status.value = 'error'
        error.value = thrown instanceof Error ? thrown.message : 'project-load-failed'
      } finally {
        inFlight = null
      }
    })()

    await inFlight
  }

  /**
   * Whether a project is being created right now.
   *
   * Its own flag rather than `status`: `status` describes the *list*, and the
   * list is still perfectly `ready` while a second project is being added.  What
   * this exists for is the form -- a disabled confirm button is the first line
   * against a double submit, and this is what makes it honest.
   */
  const creating = ref(false)

  /** One project/environment write at a time, so a double click is one PATCH. */
  const updating = ref(false)

  /** Set while a project deletion request is in flight. */
  const deletingProject = ref(false)

  /**
   * Create a project, owned by this guest, and make it the active one.
   *
   * Three things this deliberately does *not* do.
   *
   * **It does not re-implement initialisation.** A caller may be looking at
   * projects from a previous session; the real list is awaited first. An empty
   * list is a valid input here: it is exactly the state left after deleting the
   * last project, and the creation entry must still work.
   *
   * **It does not send an owner.**  The body is the name and, optionally, where
   * the project's API lives -- the request schema forbids anything else, and
   * ownership is the server's to decide from the verified session.
   *
   * **It does not pretend.**  On failure the list is untouched, the active project
   * is untouched, and the caller gets `null`.
   */
  const createProject = async (
    name: string,
    baseUrl?: string,
  ): Promise<Project | null> => {
    if (creating.value) return null

    const trimmed = name.trim()
    if (trimmed === '') return null

    try {
      await initialize()
    } catch {
      // Not ready is not a project: report the failure, invent nothing.
      return null
    }

    // The list must have actually answered, but it may legitimately be empty:
    // creating the first project after deleting the last one is a supported
    // path. The stricter ready-project gate would reject that legitimate state.
    if (status.value !== 'ready') return null

    // Re-checked after the await: initialisation can take a moment, and two
    // clicks that both passed the check above must not become two projects.
    if (creating.value) return null

    creating.value = true
    error.value = null

    try {
      const created = await createProjectRequest(
        baseUrl === undefined || baseUrl.trim() === ''
          ? { name: trimmed }
          : { name: trimmed, baseUrl: baseUrl.trim() },
      )

      // The server's project, added to the server's list -- no re-fetch, because
      // the response already is the row a fetch would return.
      projects.value = [...projects.value, created]

      // Same two assignments `initialize()` makes when it picks a project, so a
      // freshly created project is indistinguishable from one that was selected.
      activeProjectId.value = created.id
      activeEnvironmentId.value = created.environments[0]?.id ?? ''

      return created
    } catch (thrown) {
      error.value =
        thrown instanceof Error ? thrown.message : 'project-create-failed'

      return null
    } finally {
      creating.value = false
    }
  }

  /**
   * Replace a project with the backend's new aggregate.
   *
   * The environment summary response intentionally does not include variable
   * values, so variables held by the current client are preserved when the
   * server's summary has none.  This route only edits name/kind/base URL; it
   * must not make existing local variables disappear from the console.
   */
  const replaceProject = (updated: Project): Project => {
    const previous = projectById(updated.id)

    const merged: Project =
      previous === null
        ? updated
        : {
            ...updated,
            environments: updated.environments.map((environment) => {
              const old = previous.environments.find(
                (item) => item.id === environment.id,
              )

              return old !== undefined && environment.variables.length === 0
                ? { ...environment, variables: old.variables }
                : environment
            }),
          }

    projects.value = projects.value.map((project) =>
      project.id === merged.id ? merged : project,
    )

    if (
      activeProjectId.value === merged.id &&
      !merged.environments.some(
        (environment) => environment.id === activeEnvironmentId.value,
      )
    ) {
      activeEnvironmentId.value = merged.environments[0]?.id ?? ''
    }

    return merged
  }

  const deleteProject = async (projectId: string): Promise<boolean> => {
    if (deletingProject.value || projectById(projectId) === null) return false

    deletingProject.value = true
    error.value = null

    try {
      await deleteProjectRequest(projectId)

      const remaining = projects.value.filter((project) => project.id !== projectId)
      projects.value = remaining

      if (activeProjectId.value === projectId) {
        const next = remaining[0] ?? null
        activeProjectId.value = next?.id ?? ''
        activeEnvironmentId.value = next?.environments[0]?.id ?? ''
      }

      return true
    } catch (thrown) {
      error.value =
        thrown instanceof Error ? thrown.message : 'project-delete-failed'

      return false
    } finally {
      deletingProject.value = false
    }
  }

  const updateProjectName = async (
    projectId: string,
    name: string,
  ): Promise<Project | null> => {
    const trimmed = name.trim()

    if (trimmed === '' || updating.value) return null
    if (projectById(projectId) === null) return null

    updating.value = true
    error.value = null

    try {
      const updated = await updateProjectRequest(projectId, { name: trimmed })

      return replaceProject(updated)
    } catch (thrown) {
      error.value =
        thrown instanceof Error ? thrown.message : 'project-update-failed'

      return null
    } finally {
      updating.value = false
    }
  }

  const createEnvironment = async (
    projectId: string,
    input: CreateEnvironmentInput,
  ): Promise<Project | null> => {
    if (updating.value || projectById(projectId) === null) return null

    updating.value = true
    error.value = null

    try {
      const updated = await createEnvironmentRequest(projectId, input)

      return replaceProject(updated)
    } catch (thrown) {
      error.value =
        thrown instanceof Error ? thrown.message : 'environment-create-failed'

      return null
    } finally {
      updating.value = false
    }
  }

  const updateEnvironment = async (
    projectId: string,
    environmentId: string,
    input: UpdateEnvironmentInput,
  ): Promise<Project | null> => {
    if (updating.value) return null

    const project = projectById(projectId)
    if (
      project === null ||
      !project.environments.some((environment) => environment.id === environmentId)
    ) {
      return null
    }

    updating.value = true
    error.value = null

    try {
      const updated = await updateEnvironmentRequest(
        projectId,
        environmentId,
        input,
      )

      return replaceProject(updated)
    } catch (thrown) {
      error.value =
        thrown instanceof Error ? thrown.message : 'environment-update-failed'

      return null
    } finally {
      updating.value = false
    }
  }

  return {
    projects,
    activeProjectId,
    activeEnvironmentId,
    activeProject,
    environments,
    activeEnvironment,
    variables,
    projectById,
    selectProject,
    selectEnvironment,
    status,
    error,
    creating,
    updating,
    deletingProject,
    initialize,
    requireReadyProjectId,
    createProject,
    deleteProject,
    updateProjectName,
    createEnvironment,
    updateEnvironment,
  }
})

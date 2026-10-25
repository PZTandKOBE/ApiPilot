import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
import { useI18n } from '@/i18n'
import {
  AgentServiceError,
  createAgentService,
  documentFromHandoff,
  isAgentServiceError,
  type AgentError,
  type AgentErrorCode,
  type AgentTaskResult,
  type AgentTaskStatus,
  type ParsedSpec,
  type SpecInput,
} from '@/services/agent'
import { useApiClientStore } from '@/stores/apiClient'
import { ProjectNotReadyError, useProjectStore } from '@/stores/project'
import type { AgentHandoff } from '@/types/api'
import type {
  AgentTaskSummary,
  AnalysisProgress,
  ApiSpec,
  ApiUnderstanding,
  PipelineStep,
  PlanSource,
  TestPlan,
} from '@/types/agent'
import { PIPELINE_STEPS } from '@/types/agent'
import { sanitizePlans, sanitizeStoredSpecs, type StoredSpec } from '@/utils/agentStorage'

const STORAGE = {
  specs: 'aiata.console.agentSpecs',
  plans: 'aiata.console.agentPlans',
} as const

/**
 * The failures that belong to the planning half of a task.
 *
 * One request produces both artifacts, so the code is what tells the screen
 * which half refused: a document that could not be read belongs above the plan,
 * a plan that could not be written -- or that already exists -- belongs with it.
 */
const PLAN_ERROR_CODES: ReadonlySet<AgentErrorCode> = new Set([
  'generate-failed',
  'plan-invalid',
  'plan-exists',
])

export interface PlanMetaEdit {
  readonly name: string
  readonly goal: string
}

/**
 * The agent's state, for one project at a time.
 *
 * Two things are persisted — the specification document and the plans a human
 * has been shown — and one deliberately is not: the *understanding* is a pure
 * function of the document, so it is recomputed on load rather than stored.
 * That removes a large validation surface and guarantees the analysis can
 * never disagree with the file it came from.
 *
 * Approval is the boundary this store exists to enforce. `analyzeSpec` and
 * `generatePlan` can only ever produce a `draft`; the only paths to `approved`
 * are the `approvePlan` action and the human dialog that calls it.
 */
export const useAgentStore = defineStore('agent', () => {
  const agent = createAgentService()
  const projectStore = useProjectStore()
  const apiClientStore = useApiClientStore()
  const { t } = useI18n()

  /* --- Persisted ---------------------------------------------------- */

  const storedSpecs = usePersistedRef<readonly StoredSpec[]>(
    STORAGE.specs,
    [],
    { parse: sanitizeStoredSpecs },
  )

  const plans = usePersistedRef<readonly TestPlan[]>(STORAGE.plans, [], {
    parse: sanitizePlans,
  })

  /* --- Session ------------------------------------------------------ */

  const parsed = ref<ParsedSpec | null>(null)
  const understanding = ref<ApiUnderstanding | null>(null)

  /**
   * The task the last run produced, and the status the server gave it.
   *
   * Session state, not persisted: a task id is only useful while the tab that
   * created it is asking, and the plan it wrote is already in storage under its
   * own stable id.
   */
  const taskId = ref<string | null>(null)
  const taskStatus = ref<AgentTaskStatus | null>(null)

  const loading = ref(false)
  const analyzing = ref(false)
  const progress = ref<AnalysisProgress | null>(null)
  const analysisError = ref<AgentError | null>(null)

  const generating = ref(false)
  const planError = ref<AgentError | null>(null)

  const plansLoading = ref(false)
  const plansError = ref<AgentError | null>(null)
  const deletingPlan = ref(false)
  let plansInFlight: Promise<void> | null = null
  /** One best-effort audit recovery attempt per document per store lifetime. */
  let restoreAttemptedSpecId: string | null = null

  const tasks = ref<readonly AgentTaskSummary[]>([])
  const tasksLoading = ref(false)
  const tasksError = ref<AgentError | null>(null)
  let tasksRequestToken = 0

  const projectId = computed(() => projectStore.activeProjectId)

  /* --- Derived ------------------------------------------------------ */

  /** The active project's persisted spec, whether or not it is parsed yet. */
  const currentSpec = computed<ApiSpec | null>(() => {
    if (parsed.value !== null) return parsed.value.spec

    return (
      storedSpecs.value.find((item) => item.spec.projectId === projectId.value)
        ?.spec ?? null
    )
  })

  /**
   * The document text behind `currentSpec`.
   *
   * Reading it out is not a convenience: the metadata in `ApiSpec` carries no
   * schemas, and the endpoints derived from them are deliberately not
   * persisted. Anything that needs to *use* the document rather than describe
   * it — a run, which hands it to a backend that has never seen it — has to
   * have the original text, and this store is the only thing holding it.
   */
  const currentSpecDocument = computed<string | null>(
    () =>
      storedSpecs.value.find((item) => item.spec.projectId === projectId.value)
        ?.content ?? null,
  )

  const projectPlans = computed(() =>
    plans.value.filter((plan) => plan.projectId === projectId.value),
  )

  /** The active project's task activity, newest first. */
  const projectTasks = computed<readonly AgentTaskSummary[]>(() =>
    tasks.value
      .filter((task) => task.projectId === projectId.value)
      .sort(
        (left, right) =>
          right.createdAt.localeCompare(left.createdAt) ||
          right.id.localeCompare(left.id),
      ),
  )

  /**
   * The current plan for the loaded document.
   *
   * Versions are ordered by `version`, not by array position: a server merge
   * can append an older version after a newer one, and an old task can be
   * loaded after the current plan.  The version is the relation; the generated
   * timestamp is only the tiebreaker for plans persisted before versioning.
   */
  const activePlan = computed<TestPlan | null>(() => {
    const specId = currentSpec.value?.id
    const candidates =
      specId === undefined
        ? projectPlans.value
        : projectPlans.value.filter((plan) => plan.specId === specId)

    return candidates.reduce<TestPlan | null>((latest, plan) => {
      if (latest === null) return plan

      const latestVersion = latest.version ?? 1
      const version = plan.version ?? 1
      if (version !== latestVersion) return version > latestVersion ? plan : latest

      return plan.generatedAt > latest.generatedAt ? plan : latest
    }, null)
  })

  // Run availability is derived where it is used, from the plan on screen —
  // a cached flag here would be a second answer to "may this run?", and the
  // wrong one as soon as a different plan is displayed.

  /**
   * A request handed over from the API Client, if it belongs to this project.
   *
   * Derived rather than copied into a ref: a copied value would lag the
   * handoff by a tick, and "I clicked Generate Test and nothing happened yet"
   * is exactly the moment that lag would be visible.
   */
  const pendingHandoff = computed<AgentHandoff | null>(() => {
    const incoming = apiClientStore.handoff
    if (incoming === null) return null

    return incoming.projectId === projectId.value ? incoming : null
  })

  /**
   * Pipeline position, derived from what actually exists.
   *
   * A step cannot appear complete without its artifact, so the indicator can
   * never claim progress the user cannot see.
   */
  const completedSteps = computed<readonly PipelineStep[]>(() => {
    const done: PipelineStep[] = []

    if (parsed.value !== null) done.push('spec')

    const plan = activePlan.value

    // The understanding exists only on the response that produced it, so after a
    // reload the plan is the artifact that proves the analysis ran. A plan that
    // exists *is* that proof; a timer finishing would not be.
    if (understanding.value !== null || plan !== null) {
      done.push('analyze', 'understanding')
    }

    if (plan !== null) done.push('plan')
    if (plan?.status === 'approved') done.push('approve')

    return done
  })

  const step = computed<PipelineStep>(() => {
    const done = completedSteps.value
    return PIPELINE_STEPS.find((candidate) => !done.includes(candidate)) ?? 'execute'
  })

  /* --- Errors ------------------------------------------------------- */

  const clearErrors = (): void => {
    analysisError.value = null
    planError.value = null
    plansError.value = null
  }

  const toAgentError = (thrown: unknown, fallbackKey: string): AgentError =>
    isAgentServiceError(thrown)
      ? thrown.detail
      : { code: 'analyze-failed', messageKey: fallbackKey }

  /**
   * The project a project-scoped operation may use, or a refusal.
   *
   * This is the single gate every operation that is *scoped to a project* passes
   * through, and it is what makes the store's own project id an input rather than
   * an authority.  The id it returns is the one the operation must use: reading
   * `activeProjectId` again after the check would be reading a value the check
   * did not vouch for, and the two can differ -- initialisation can settle on a
   * different project while a caller was waiting.
   *
   * Nothing here falls back.  Not to the mock list, not to the persisted id, not
   * to an empty string used as a storage key: a request the console cannot scope
   * to a project this guest owns is a request it does not make.
   */
  const resolveProjectId = async (): Promise<string> => {
    try {
      return await projectStore.requireReadyProjectId()
    } catch (thrown) {
      // A not-ready project is a refusal, and a refusal is an error this console
      // can render -- not an exception for a component to interpret.
      if (thrown instanceof ProjectNotReadyError) {
        throw new AgentServiceError({
          code: 'project-not-ready',
          messageKey: 'console.aiTest.errors.projectNotReady',
        })
      }

      throw thrown
    }
  }

  /* --- Loading a specification -------------------------------------- */

  const persistSpec = (next: ParsedSpec, content: string): void => {
    storedSpecs.value = [
      ...storedSpecs.value.filter(
        (item) => item.spec.projectId !== next.spec.projectId,
      ),
      { spec: next.spec, content },
    ]
  }

  const applySpec = (next: ParsedSpec, content: string): void => {
    parsed.value = next
    understanding.value = null
    progress.value = null
    restoreAttemptedSpecId = null

    persistSpec(next, content)

    // Plans reference endpoints by id, so they belong to the document that
    // produced them. Re-uploading an identical file keeps its slug — and
    // therefore its plans.
    plans.value = plans.value.filter((plan) => plan.specId === next.spec.id)
  }

  const loadSpec = async (input: Omit<SpecInput, 'projectId'>): Promise<void> => {
    if (loading.value) return

    loading.value = true
    clearErrors()

    try {
      const next = await agent.parseSpec({ ...input, projectId: projectId.value })
      applySpec(next, input.content)
    } catch (thrown) {
      analysisError.value = toAgentError(
        thrown,
        'console.aiTest.errors.parseFailed',
      )
    } finally {
      loading.value = false
    }
  }

  const loadDemoSpec = async (): Promise<void> => {
    if (loading.value) return

    loading.value = true
    clearErrors()

    try {
      const { parsed: next, content } = await agent.loadDemoSpec(projectId.value)
      applySpec(next, content)
    } catch (thrown) {
      analysisError.value = toAgentError(
        thrown,
        'console.aiTest.errors.parseFailed',
      )
    } finally {
      loading.value = false
    }
  }

  const resetSpec = (): void => {
    storedSpecs.value = storedSpecs.value.filter(
      (item) => item.spec.projectId !== projectId.value,
    )
    plans.value = plans.value.filter((plan) => plan.projectId !== projectId.value)

    parsed.value = null
    understanding.value = null
    taskId.value = null
    taskStatus.value = null
    progress.value = null
    restoreAttemptedSpecId = null
    clearErrors()
  }

  /* --- The agent task ------------------------------------------------ */

  /**
   * Store the plan the server wrote, keyed by its stable id.
   *
   * Same id means the same document, so this replaces rather than accumulates --
   * and it is the *only* place a plan object is replaced. Nothing regenerates a
   * plan behind a reviewer's back, which is what keeps a local approval attached
   * to the plan the server holds.
   */
  const adoptPlan = (plan: TestPlan): void => {
    const current = plan.isCurrent !== false
    const existing = plans.value.filter((item) => item.id !== plan.id)
    const kept = current
      ? existing.map((item) =>
          item.specId === plan.specId ? { ...item, isCurrent: false } : item,
        )
      : existing

    plans.value = [...kept, plan]
  }

  /**
   * Runs one agent task: the server parses, analyses, plans, validates and
   * persists, and answers with all of it.
   *
   * This is both of the old actions. The screen still speaks of analysing and
   * planning as two stages — the pipeline indicator walks spec → analyze →
   * understanding → plan — but they are one request, which is what the endpoint
   * offers and what this store adapts to.
   */
  const runTask = async (
    options: { readonly regenerate?: boolean } = {},
  ): Promise<AgentTaskResult | null> => {
    const spec = parsed.value?.spec
    const document = currentSpecDocument.value

    if (spec === undefined || document === null || analyzing.value) return null

    analyzing.value = true
    clearErrors()
    progress.value = null

    try {
      // The project is resolved here, before the request is built, and the value
      // it returns is what the request carries -- not the id read at the top of
      // this function.  A refusal lands in the same catch as a server refusal, so
      // the screen shows one error where it already shows errors, and nothing was
      // written or sent on the way there.
      const readyProjectId = await resolveProjectId()

      // Re-read the document, because resolving the project can *change* which
      // project is active: the first task on a fresh console initialises the
      // project store, which switches the store from the id it was seeded with to
      // the one the backend returned, and the agent store's own watcher then
      // re-hydrates the project's documents.  The document this run was started
      // for can be gone by the time the project is known -- and sending the old
      // one under the new project's name would file a specification under a
      // project that never held it, while saying nothing about why.
      const currentDocument = currentSpecDocument.value

      if (currentDocument === null) {
        analysisError.value = {
          code: 'analyze-failed',
          messageKey: 'console.aiTest.errors.analyzeFailed',
        }
        taskStatus.value = 'failed'

        return null
      }

      const result = await agent.runTask(
        {
          projectId: readyProjectId,
          specId: spec.id,
          specDocument: currentDocument,
          environmentId: projectStore.activeEnvironmentId || null,
          // The server stores this verbatim. There is no prompt field on this
          // screen yet, so the request is the sentence the console would show.
          prompt: t('console.aiTest.task.prompt', { title: spec.title }),
          // Write-only, and never persisted here: the server scans these for
          // leaks and drops them.
          variables: projectStore.variables,
          // Ordinary first generation keeps its exact old body and 409
          // plan-exists contract; only the explicit regenerate action adds
          // this field.
          ...(options.regenerate === true ? { regenerate: true } : {}),
        },
        {
          onProgress: (next) => {
            progress.value = next
          },
        },
      )

      understanding.value = result.understanding
      taskId.value = result.taskId
      taskStatus.value = result.status

      if (result.plan !== null) adoptPlan(result.plan)

      return result
    } catch (thrown) {
      // A refused plan request (or a failed re-analysis) must not discard a
      // valid understanding the user is still allowed to review. The error is
      // still reported; the previous analysis remains available until a new one
      // succeeds.
      taskStatus.value = 'failed'

      const error = toAgentError(thrown, 'console.aiTest.errors.analyzeFailed')

      if (PLAN_ERROR_CODES.has(error.code)) planError.value = error
      else analysisError.value = error

      // A missing local plan must not strand the user on the ordinary 409.
      // Refresh the server's version list: if a plan already exists, the
      // ordinary action now becomes the regenerate action in the UI.
      if (error.code === 'plan-exists') await loadPlans()

      return null
    } finally {
      analyzing.value = false
      progress.value = null
    }
  }

  /**
   * Re-read a task the server already ran.
   *
   * The plan it wrote is adopted as-is -- that is what makes a reload able to
   * show a plan this browser did not just receive. The understanding is not:
   * the server keeps none, so there is nothing to read back.
   */
  const loadTask = async (id: string): Promise<void> => {
    if (loading.value) return

    loading.value = true
    clearErrors()

    try {
      const result = await agent.getTask(id)

      taskId.value = result.taskId
      taskStatus.value = result.status

      if (result.plan !== null) adoptPlan(result.plan)
    } catch (thrown) {
      analysisError.value = toAgentError(thrown, 'console.aiTest.errors.loadFailed')
    } finally {
      loading.value = false
    }
  }

  /* --- Analysis ----------------------------------------------------- */

  const analyzeSpec = async (): Promise<void> => {
    await runTask()
  }

  /**
   * Retire a plan series and remove its local versions.
   *
   * The server soft-deletes every version in the document series while keeping
   * historical runs and reports. The local list drops the same series only
   * after the request succeeds; a failed request leaves every plan where it was.
   */
  const deletePlan = async (projectId: string, planId: string): Promise<boolean> => {
    if (deletingPlan.value) return false

    const target = plans.value.find(
      (plan) => plan.projectId === projectId && plan.id === planId,
    )
    if (target === undefined) return false

    deletingPlan.value = true

    try {
      await agent.deletePlan(projectId, planId)

      plans.value = plans.value.filter(
        (plan) =>
          !(plan.projectId === projectId && plan.specId === target.specId),
      )

      return true
    } catch {
      return false
    } finally {
      deletingPlan.value = false
    }
  }

  /**
   * Drop all local, project-owned agent state after a project is deleted.
   *
   * Server rows are gone already; this removes the browser's persisted copy so
   * another project cannot inherit the deleted project's spec or plans.
   */
  const forgetProject = (projectId: string): void => {
    storedSpecs.value = storedSpecs.value.filter(
      (item) => item.spec.projectId !== projectId,
    )
    plans.value = plans.value.filter((plan) => plan.projectId !== projectId)
    tasks.value = tasks.value.filter((task) => task.projectId !== projectId)

    if (parsed.value?.spec.projectId === projectId) {
      parsed.value = null
      understanding.value = null
      taskId.value = null
      taskStatus.value = null
      progress.value = null
      restoreAttemptedSpecId = null
      clearErrors()
    }
  }

  /**
   * Restore the review after a reload from the task audit.
   *
   * The understanding is not persisted, but the backend's task audit already
   * stores the validated analysis for every task. On a fresh page load the
   * plan is restored from the server; this asks the existing audit read for the
   * matching understanding so the five-step review can render real data instead
   * of disappearing. It is deliberately best-effort: no audit, an old task, or
   * a failed request leaves the normal spec/plan view untouched.
   */
  const restoreAnalysis = async (): Promise<void> => {
    const project = projectId.value
    const spec = currentSpec.value

    if (project === '' || spec === null || understanding.value !== null || analyzing.value) return
    if (restoreAttemptedSpecId === spec.id) return

    restoreAttemptedSpecId = spec.id

    try {
      const recent = await agent.listTasks(project, 20)

      for (const summary of recent) {
        if (summary.projectId !== project || summary.status !== 'completed') continue

        try {
          const recovered = await agent.getTaskAudit(summary.id)

          if (recovered !== null && recovered.specId === spec.id) {
            understanding.value = recovered
            taskId.value = summary.id
            taskStatus.value = 'completed'
            return
          }
        } catch {
          // A task without an audit is not an error the reader needs to see;
          // try the next recent task.
        }
      }
    } catch {
      // Recovery must never turn a usable plan into an error banner.
    }
  }

  /* --- Planning ----------------------------------------------------- */

  /**
   * The ordinary "Generate plan" action.
   *
   * It is the same task as analysing, and it deliberately keeps the original
   * first-generation contract: a second ordinary request for a document whose
   * plan the server already holds comes back as `plan-exists`.  The explicit
   * regenerate action is the supported way to create a new version.
   */
  const generatePlan = async (_source: PlanSource = 'generated'): Promise<void> => {
    if (generating.value || analyzing.value) return

    generating.value = true

    try {
      await runTask()
    } finally {
      generating.value = false
    }
  }

  /**
   * Create the next plan version for the loaded document.
   *
   * The server allocates the id and version under a transaction-scoped lock;
   * this action never edits or removes the old plan.  A failure leaves the
   * existing plan array untouched and reports through the same planning error
   * surface as a first-generation failure.
   */
  const regeneratePlan = async (): Promise<void> => {
    if (generating.value || analyzing.value) return

    generating.value = true

    try {
      await runTask({ regenerate: true })
    } finally {
      generating.value = false
    }
  }

  /**
   * Merge the server's plan versions into the local list.
   *
   * The server owns plan content, version and currentness; this browser owns
   * local approval decisions and local name/goal edits.  An existing local plan
   * therefore keeps its approval fields and authored copy while taking the
   * server's version metadata.  A server plan this browser has never seen is
   * adopted as stored (normally `draft`).
   */
  const loadPlans = async (): Promise<void> => {
    const project = projectId.value
    if (project === '') return

    // One refresh at a time.  Callers that arrive while it is in flight await
    // the same request instead of racing it or returning before plans exist.
    if (plansInFlight !== null) return plansInFlight

    plansLoading.value = true
    plansError.value = null

    const request = (async () => {
      try {
        const remote = await agent.listPlans(project)
        const localById = new Map(plans.value.map((plan) => [plan.id, plan]))
        const merged = new Map(plans.value.map((plan) => [plan.id, plan]))

        for (const incoming of remote) {
          const local = localById.get(incoming.id)
          merged.set(
            incoming.id,
            local === undefined
              ? incoming
              : {
                  ...incoming,
                  name: local.name,
                  goal: local.goal,
                  status: local.status,
                  approvedAt: local.approvedAt,
                  rejectedAt: local.rejectedAt,
                  rejectionReason: local.rejectionReason,
                },
          )
        }

        plans.value = [...merged.values()]
      } catch (thrown) {
        plansError.value = toAgentError(
          thrown,
          'console.aiTest.errors.loadFailed',
        )
      } finally {
        plansLoading.value = false
        plansInFlight = null
      }
    })()

    plansInFlight = request
    return request
  }

  /**
   * Read recent tasks without replacing the dashboard's task collection.
   *
   * The notification center needs a wider window than the dashboard's three
   * rows, but it must not turn the dashboard into a twenty-row feed. This is a
   * read-only query through the same service instance, so mock and real modes
   * keep their existing task state.
   */
  const listRecentTasks = async (
    limit = 20,
  ): Promise<readonly AgentTaskSummary[]> => {
    const project = projectId.value
    if (project === '') return []

    return await agent.listTasks(project, limit)
  }

  /**
   * Load the active project's recent task activity.
   *
   * A request token, not a single-flight promise, because project switching is
   * the important race: a response for the previous project must neither land
   * in the current list nor clear the loading flag of the newer request.
   */
  const loadTasks = async (): Promise<void> => {
    const project = projectId.value
    if (project === '') return

    const token = (tasksRequestToken += 1)
    tasksLoading.value = true
    tasksError.value = null

    try {
      const remote = await agent.listTasks(project, 3)

      if (token !== tasksRequestToken) return

      tasks.value = [
        ...tasks.value.filter((task) => task.projectId !== project),
        ...remote,
      ]
    } catch (thrown) {
      if (token !== tasksRequestToken) return

      tasksError.value = toAgentError(
        thrown,
        'console.aiTest.errors.loadFailed',
      )
    } finally {
      if (token === tasksRequestToken) tasksLoading.value = false
    }
  }

  /* --- Approval boundary -------------------------------------------- */

  const startReview = (id: string): void => {
    plans.value = plans.value.map((plan) =>
      plan.id === id && plan.status === 'draft'
        ? { ...plan, status: 'in_review' }
        : plan,
    )
  }

  const approvePlan = (id: string): void => {
    plans.value = plans.value.map((plan) =>
      plan.id === id
        ? {
            ...plan,
            status: 'approved',
            approvedAt: new Date().toISOString(),
            rejectedAt: null,
            rejectionReason: null,
          }
        : plan,
    )
  }

  /** A rejection without a reason is refused: the agent needs to know why. */
  const rejectPlan = (id: string, reason: string): boolean => {
    const trimmed = reason.trim()
    if (trimmed === '') return false

    plans.value = plans.value.map((plan) =>
      plan.id === id
        ? {
            ...plan,
            status: 'rejected',
            rejectedAt: new Date().toISOString(),
            approvedAt: null,
            rejectionReason: trimmed,
          }
        : plan,
    )

    return true
  }

  /** Renaming stores the reviewer's own words, not a dictionary key. */
  const updatePlanMeta = (id: string, meta: PlanMetaEdit): void => {
    plans.value = plans.value.map((plan) =>
      plan.id === id
        ? { ...plan, name: { text: meta.name }, goal: { text: meta.goal } }
        : plan,
    )
  }

  /* --- API Client handoff ------------------------------------------- */

  const adoptHandoff = async (): Promise<void> => {
    const incoming = pendingHandoff.value
    if (incoming === null || loading.value) return

    loading.value = true
    clearErrors()

    try {
      // The project first, for the same reason as everywhere else -- and here it
      // is the difference between "not adopted yet" and "adopted into nothing":
      // the handoff is consumed *after* both the parse and the analysis it starts,
      // so a refusal anywhere in that chain leaves the card on screen with the
      // request still in it, ready to be retried against a ready project.
      const readyProjectId = await resolveProjectId()

      // Re-read it, for the same reason `runTask` re-reads the document: resolving
      // the project is what initialises the project store on a fresh console, and
      // that switch re-points this store at another project's state.  `pendingHandoff`
      // is already the store's own answer to "does this handoff belong to the
      // project we are on" -- reading it again applies that rule to the project we
      // have just resolved instead of the one we had when the click happened.
      const handoff = pendingHandoff.value

      if (handoff === null) return

      const content = documentFromHandoff(
        handoff,
        t('console.aiTest.handoff.specTitle'),
      )

      const next = await agent.parseSpec({
        projectId: readyProjectId,
        filename: 'api-client-request.json',
        content,
        source: 'handoff',
      })

      applySpec(next, content)

      // One click, not two: "Generate test" in the API Client already said
      // what the user wants, so accepting the handoff carries straight on into
      // the analysis rather than parking them on an unanalysed spec.
      loading.value = false
      await analyzeSpec()

      apiClientStore.clearHandoff()
      return
    } catch (thrown) {
      analysisError.value = toAgentError(
        thrown,
        'console.aiTest.errors.parseFailed',
      )
    } finally {
      loading.value = false
    }
  }

  const dismissHandoff = (): void => {
    apiClientStore.clearHandoff()
  }

  /* --- Rehydration -------------------------------------------------- */

  /**
   * Rebuilds the active project's state from storage.
   *
   * The document is decoded locally; the analysis is **not** replayed. It cannot
   * be: a second task for the same document would be refused by the server (the
   * plan it produced is still there), and the understanding has no read surface
   * to come back from. So the plan on screen comes from storage -- where the
   * server's own response put it -- and the understanding panels wait for the
   * next task.
   */
  let hydrationToken = 0

  const hydrate = async (id: string): Promise<void> => {
    const token = (hydrationToken += 1)
    restoreAttemptedSpecId = null
    const stored = storedSpecs.value.find((item) => item.spec.projectId === id)

    if (stored === undefined) {
      parsed.value = null
      understanding.value = null
      return
    }

    try {
      const next = await agent.parseSpec({
        projectId: id,
        filename: stored.spec.filename,
        content: stored.content,
        source: stored.spec.source,
      })

      // A newer switch started while this one was parsing; its result wins.
      if (token !== hydrationToken) return

      parsed.value = next
      understanding.value = null
      taskId.value = null
      taskStatus.value = null

      // The document is now decoded; the persisted analysis can be restored
      // from the audit without racing this hydration pass.
      void restoreAnalysis()
    } catch {
      if (token !== hydrationToken) return

      parsed.value = null
      understanding.value = null
    }
  }

  watch(
    projectId,
    (id) => {
      clearErrors()
      void hydrate(id)
    },
    { immediate: true },
  )

  return {
    // state
    parsed,
    understanding,
    taskId,
    taskStatus,
    loading,
    analyzing,
    progress,
    analysisError,
    generating,
    planError,
    plansLoading,
    plansError,
    deletingPlan,
    pendingHandoff,
    tasksLoading,
    tasksError,

    // derived
    currentSpec,
    currentSpecDocument,
    projectPlans,
    projectTasks,
    activePlan,
    step,
    completedSteps,

    // actions
    loadSpec,
    loadDemoSpec,
    resetSpec,
    analyzeSpec,
    restoreAnalysis,
    loadTask,
    generatePlan,
    regeneratePlan,
    loadPlans,
    listRecentTasks,
    deletePlan,
    forgetProject,
    loadTasks,
    startReview,
    approvePlan,
    rejectPlan,
    updatePlanMeta,
    adoptHandoff,
    dismissHandoff,
    clearErrors,
  }
})

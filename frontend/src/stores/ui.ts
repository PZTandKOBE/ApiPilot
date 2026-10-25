import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
import { listReports } from '@/services/api/reports'
import { readToken } from '@/services/session'
import { useAgentStore } from '@/stores/agent'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { ConsoleNotification } from '@/types/console'

type ReadState = Readonly<Record<string, readonly string[]>>

const NOTIFICATION_READ_KEY = 'aiata.console.notificationsRead.v1'

const sanitizeReadState = (value: unknown): ReadState => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}

  const state: Record<string, readonly string[]> = {}

  for (const [scope, ids] of Object.entries(value as Record<string, unknown>)) {
    if (!Array.isArray(ids) || !ids.every((id): id is string => typeof id === 'string')) {
      continue
    }

    state[scope] = [...new Set(ids)].slice(-200)
  }

  return state
}

const timestamp = (value: string): number => {
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * A non-sensitive fingerprint of the guest token.
 *
 * Read state is scoped to an identity and a project. Storing the token itself
 * in a second localStorage key would duplicate a credential for no benefit, so
 * only a stable hash of it enters the read-state map.
 */
const tokenFingerprint = (token: string): string => {
  let hash = 2166136261

  for (let index = 0; index < token.length; index += 1) {
    hash ^= token.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }

  return (hash >>> 0).toString(36)
}

/**
 * Console chrome state: sidebar geometry and the application notification feed.
 *
 * Notifications are derived from the existing project-scoped data sources:
 * completed agent tasks, current draft/in-review plans, and saved PDF reports.
 * There is no notification table and no new backend endpoint; the feed is a
 * read-only projection of records the pages already fetch.
 */
export const useUiStore = defineStore('ui', () => {
  const projectStore = useProjectStore()
  const auth = useAuthStore()
  const agentStore = useAgentStore()

  const sidebarCollapsed = usePersistedRef<boolean>(
    'aiata.console.sidebar',
    false,
    { validate: (value): value is boolean => typeof value === 'boolean' },
  )

  /**
   * Collections / history rail inside the API Client. Persisted for the same
   * reason as the sidebar: how much chrome a user wants is a stable preference,
   * not a per-visit decision.
   */
  const apiRailCollapsed = usePersistedRef<boolean>(
    'aiata.console.apiRail',
    false,
    { validate: (value): value is boolean => typeof value === 'boolean' },
  )

  const mobileNavOpen = ref(false)

  const notifications = ref<readonly ConsoleNotification[]>([])
  const notificationLoading = ref(false)
  const notificationError = ref<string | null>(null)

  const readState = usePersistedRef<ReadState>(NOTIFICATION_READ_KEY, {}, {
    parse: sanitizeReadState,
  })

  /** Identity plus project: two guests never share a read marker by accident. */
  const currentScope = (projectId: string): string => {
    const user = auth.user
    const token = readToken()
    const identity =
      user !== null
        ? 'user:' + user.id
        : 'guest:' + (token === null ? 'anonymous' : tokenFingerprint(token))

    return identity + ':project:' + projectId
  }

  let requestSequence = 0
  let loadingProject: string | null = null
  let loadingScope = ''
  let displayedProject = ''
  let displayedScope = ''

  const unreadCount = computed(
    () => notifications.value.filter((item) => !item.read).length,
  )

  /**
   * Rebuild the current project's notification list from real business rows.
   *
   * All three requests are project-scoped. Loading plans merges the server list
   * with this browser's local approval decisions, which is the authoritative
   * source for still-waiting approval; a server draft row alone is not trusted
   * over an approval this browser already recorded.
   */
  const loadNotifications = async (): Promise<void> => {
    const project = projectStore.activeProjectId

    if (project === '') {
      notifications.value = []
      notificationError.value = null
      notificationLoading.value = false
      displayedProject = ''
      displayedScope = ''
      return
    }

    const scope = currentScope(project)

    if (displayedProject !== project || displayedScope !== scope) {
      notifications.value = []
      notificationError.value = null
      displayedProject = project
      displayedScope = scope
    }

    if (
      notificationLoading.value &&
      loadingProject === project &&
      loadingScope === scope
    ) {
      return
    }

    const token = (requestSequence += 1)
    loadingProject = project
    loadingScope = scope
    notificationLoading.value = true
    notificationError.value = null

    const tasksRequest = agentStore.listRecentTasks(20)
    const plansRequest = (async () => {
      await agentStore.loadPlans()
      if (agentStore.plansError !== null) throw agentStore.plansError
      return agentStore.projectPlans
    })()
    const reportsRequest = listReports(project)

    try {
      const [tasksResult, plansResult, reportsResult] = await Promise.allSettled([
        tasksRequest,
        plansRequest,
        reportsRequest,
      ])

      if (
        token !== requestSequence ||
        projectStore.activeProjectId !== project ||
        currentScope(project) !== scope
      ) {
        return
      }

      const readIds = new Set(readState.value[scope] ?? [])
      const projectName = projectStore.activeProject?.name ?? project
      const projectPath = '/console/projects/' + encodeURIComponent(project)
      const items = new Map<string, ConsoleNotification>()

      if (tasksResult.status === 'fulfilled') {
        for (const task of tasksResult.value) {
          if (task.projectId !== project || task.status !== 'completed') continue

          const id = 'agent:' + project + ':' + task.id + ':' + task.updatedAt

          items.set(id, {
            id,
            projectId: project,
            kind: 'success',
            titleKey: 'console.topbar.notification.agentTitle',
            detailKey: 'console.topbar.notification.agentBody',
            detailParams: { project: projectName, prompt: task.prompt },
            to: projectPath + '/ai-test',
            // Agent summaries expose updatedAt, not a separate completedAt;
            // for a completed task this is the terminal update timestamp.
            createdAt: timestamp(task.updatedAt),
            read: readIds.has(id),
          })
        }
      }

      if (plansResult.status === 'fulfilled') {
        for (const plan of plansResult.value) {
          if (plan.projectId !== project || plan.isCurrent === false) continue
          if (plan.status !== 'draft' && plan.status !== 'in_review') continue

          const version = plan.version ?? 1
          const id = 'plan:' + project + ':' + plan.id + ':v' + String(version)

          items.set(id, {
            id,
            projectId: project,
            kind: 'warning',
            titleKey: 'console.topbar.notification.planTitle',
            detailKey: 'console.topbar.notification.planBody',
            detailParams: { project: projectName },
            localizedName: plan.name,
            to: projectPath + '/plans/' + encodeURIComponent(plan.id),
            createdAt: timestamp(plan.generatedAt),
            read: readIds.has(id),
          })
        }
      }

      if (reportsResult.status === 'fulfilled') {
        for (const report of reportsResult.value) {
          if (report.projectId !== project) continue

          const id = 'report:' + project + ':' + report.id

          items.set(id, {
            id,
            projectId: project,
            kind: 'success',
            titleKey: 'console.topbar.notification.reportTitle',
            detailKey: 'console.topbar.notification.reportBody',
            detailParams: { name: report.name },
            to: projectPath + '/reports',
            createdAt: timestamp(report.generatedAt),
            read: readIds.has(id),
          })
        }
      }

      notifications.value = [...items.values()].sort(
        (left, right) =>
          right.createdAt - left.createdAt ||
          left.id.localeCompare(right.id),
      )

      const failed =
        tasksResult.status === 'rejected' ||
        plansResult.status === 'rejected' ||
        reportsResult.status === 'rejected'

      notificationError.value = failed
        ? 'console.topbar.notification.loadFailed'
        : null
    } finally {
      if (token === requestSequence) {
        notificationLoading.value = false
        loadingProject = null
        loadingScope = ''
      }
    }
  }

  const markRead = (id: string): void => {
    const notification = notifications.value.find((item) => item.id === id)
    if (notification === undefined || notification.read) return

    const scope = displayedScope
    if (scope === '') return

    const current = readState.value[scope] ?? []
    if (!current.includes(id)) {
      readState.value = {
        ...readState.value,
        [scope]: [...current, id].slice(-200),
      }
    }

    notifications.value = notifications.value.map((item) =>
      item.id === id ? { ...item, read: true } : item,
    )
  }

  const markAllRead = (): void => {
    const scope = displayedScope
    const unreadIds = notifications.value
      .filter((item) => !item.read)
      .map((item) => item.id)

    if (scope === '' || unreadIds.length === 0) return

    const current = readState.value[scope] ?? []
    readState.value = {
      ...readState.value,
      [scope]: [...new Set([...current, ...unreadIds])].slice(-200),
    }

    notifications.value = notifications.value.map((item) => ({
      ...item,
      read: true,
    }))
  }

  const toggleSidebar = (): void => {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  const toggleApiRail = (): void => {
    apiRailCollapsed.value = !apiRailCollapsed.value
  }

  const setMobileNav = (open: boolean): void => {
    mobileNavOpen.value = open
  }

  return {
    sidebarCollapsed,
    apiRailCollapsed,
    mobileNavOpen,
    notifications,
    notificationLoading,
    notificationError,
    unreadCount,
    toggleSidebar,
    toggleApiRail,
    setMobileNav,
    loadNotifications,
    markRead,
    markAllRead,
  }
})

import { computed, type ComputedRef } from 'vue'
import {
  DataAnalysis,
  MagicStick,
  Odometer,
  Promotion,
  Tickets,
  VideoPlay,
} from '@element-plus/icons-vue'

import { useProjectStore } from '@/stores/project'
import type { ConsoleNavItem, ResolvedNavItem } from '@/types/console'
import { useResolvedNav, type ResolvedNav } from './useResolvedNav'

export interface ConsoleNav extends ResolvedNav {
  /** Entries rendered in the rail's footer, outside the scrolling list. */
  readonly footerItems: ComputedRef<readonly ResolvedNavItem[]>
}

/**
 * The console's navigation — the only one.
 *
 * Grouped by what the user is doing (where they are, how they test, what they
 * design, what they run) rather than by which feature owns the route. The two
 * "how you test" entries are the case that matters: the API Client drives a
 * request by hand and the AI Test Lab has the agent read a specification, and
 * the group heading says they are alternatives. Nothing here sequences them —
 * designing or running tests does not begin with an agent run, and the copy
 * must not imply it does.
 *
 * Project-scoped destinations resolve against the *active* project rather than
 * a fixed id, so they are never dead ends: switching project in the top bar
 * re-points them. That is also why one rail is enough at every breakpoint. The
 * top bar already carries the project and the environment, so a second,
 * project-only rail was a third column restating what it had just said.
 */
export const useConsoleNav = (): ConsoleNav => {
  const projectStore = useProjectStore()

  const activeProjectId = computed(() => projectStore.activeProjectId)

  const source = computed<readonly ConsoleNavItem[]>(() => [
    {
      labelKey: 'console.nav.dashboard',
      icon: Odometer,
      routeName: 'console-dashboard',
      groupKey: 'console.nav.sectionWorkspace',
    },
    {
      labelKey: 'console.nav.apiClient',
      icon: Promotion,
      routeName: 'console-project-api',
      params: { projectId: activeProjectId.value },
      groupKey: 'console.nav.sectionTesting',
    },
    {
      labelKey: 'console.nav.aiTestLab',
      icon: MagicStick,
      routeName: 'console-project-ai-test',
      params: { projectId: activeProjectId.value },
    },
    {
      labelKey: 'console.nav.testPlans',
      icon: Tickets,
      routeName: 'console-project-plans',
      params: { projectId: activeProjectId.value },
      groupKey: 'console.nav.sectionDesign',
    },
    {
      labelKey: 'console.nav.testRuns',
      icon: VideoPlay,
      routeName: 'console-project-runs',
      params: { projectId: activeProjectId.value },
      groupKey: 'console.nav.sectionExecution',
    },
    {
      labelKey: 'console.nav.reports',
      icon: DataAnalysis,
      routeName: 'console-project-reports',
      params: { projectId: activeProjectId.value },
    },
  ])

  /**
   * The footer is reserved for chrome controls. It currently has no
   * destinations: Workflows and Settings were removed from the sidebar, while
   * their underlying routes and implementations remain available directly.
   */
  const footerSource = computed<readonly ConsoleNavItem[]>(() => [])

  const main = useResolvedNav(source)
  const footer = useResolvedNav(footerSource)

  // A footer destination is as much "where you are" as a listed one, so the
  // key spans both: the rail draws one highlight, never two.
  const activeKey = computed<string | null>(
    () => main.activeKey.value ?? footer.activeKey.value,
  )

  return { items: main.items, footerItems: footer.items, activeKey }
}

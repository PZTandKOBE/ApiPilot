import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
import type { ConsoleNotification, NotificationKind } from '@/types/console'

interface NotificationInput {
  readonly kind: NotificationKind
  /** i18n key — see `ConsoleNotification` for why this is not a string. */
  readonly titleKey: string
  readonly params?: Readonly<Record<string, string | number>>
  readonly to?: string
}

/**
 * Console chrome state: sidebar geometry and the notification tray.
 *
 * Nothing here is domain data. It lives in its own store so that a later
 * server-driven notification feed can replace `pushNotification` without
 * touching the project or agent stores.
 */
export const useUiStore = defineStore('ui', () => {
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

  const unreadCount = computed(
    () => notifications.value.filter((item) => !item.read).length,
  )

  const toggleSidebar = (): void => {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  const toggleApiRail = (): void => {
    apiRailCollapsed.value = !apiRailCollapsed.value
  }

  const setMobileNav = (open: boolean): void => {
    mobileNavOpen.value = open
  }

  /**
   * Prepend a notification. Ids are derived from a counter rather than
   * `Date.now()` so two notifications pushed in the same millisecond stay
   * distinct keys in the list.
   */
  let sequence = 0
  const pushNotification = (input: NotificationInput): void => {
    sequence += 1
    const notification: ConsoleNotification = {
      id: `ntf_${sequence}`,
      kind: input.kind,
      titleKey: input.titleKey,
      params: input.params,
      to: input.to,
      createdAt: Date.now(),
      read: false,
    }
    notifications.value = [notification, ...notifications.value]
  }

  const markAllRead = (): void => {
    notifications.value = notifications.value.map((item) => ({
      ...item,
      read: true,
    }))
  }

  const clearNotifications = (): void => {
    notifications.value = []
  }

  return {
    sidebarCollapsed,
    apiRailCollapsed,
    mobileNavOpen,
    notifications,
    unreadCount,
    toggleSidebar,
    toggleApiRail,
    setMobileNav,
    pushNotification,
    markAllRead,
    clearNotifications,
  }
})

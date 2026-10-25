<script setup lang="ts">
import {
  Bell,
  CircleCheck,
  CircleClose,
  Close,
  InfoFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElBadge, ElIcon, ElPopover } from 'element-plus'
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type Component,
} from 'vue'
import { useRouter } from 'vue-router'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useNow } from '@/composables/useNow'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { formatRelativeTime } from '@/utils/time'
import type { ConsoleNotification, NotificationKind } from '@/types/console'

/**
 * Application notification center.
 *
 * The feed is a projection of records the console already owns: completed
 * agent tasks, current plans awaiting review, and saved PDF reports. It never
 * writes business state and never fabricates an event; opening it only refreshes
 * those project-scoped reads.
 */
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const ui = useUiStore()
const projectStore = useProjectStore()
const auth = useAuthStore()
const router = useRouter()
const now = useNow()

const open = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const KIND_COLOR: Readonly<Record<NotificationKind, string>> = {
  info: 'var(--accent)',
  success: 'var(--status-pass)',
  warning: 'var(--status-warn)',
  error: 'var(--status-fail)',
}

const KIND_ICON: Readonly<Record<NotificationKind, Component>> = {
  info: InfoFilled,
  success: CircleCheck,
  warning: Warning,
  error: CircleClose,
}

const items = computed(() => ui.notifications)
const errorText = computed(() =>
  ui.notificationError === null ? '' : t(ui.notificationError),
)

const titleOf = (notification: ConsoleNotification): string =>
  t(notification.titleKey)

const detailOf = (notification: ConsoleNotification): string =>
  notification.detailKey === undefined
    ? ''
    : t(notification.detailKey, notification.detailParams)

const timeOf = (notification: ConsoleNotification): string =>
  formatRelativeTime(notification.createdAt, locale.value, {
    now: now.value,
    justNow: t('console.common.justNow'),
  })

const refresh = (): void => {
  void ui.loadNotifications()
}

/** Refresh when the user asks, not when a page happens to mount. */
const onOpenChanged = (value: boolean): void => {
  if (value) refresh()
}

const select = (notification: ConsoleNotification): void => {
  ui.markRead(notification.id)
  open.value = false

  // A notification is scoped to the project that produced it. Never follow a
  // stale target after a project switch.
  if (
    notification.to !== undefined &&
    notification.to !== '' &&
    notification.projectId === projectStore.activeProjectId
  ) {
    void router.push(notification.to)
  }
}

const onVisibilityChange = (): void => {
  if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
    refresh()
  }
}

onMounted(() => {
  refresh()

  // A light poll keeps background completions visible while the console is
  // open. It is one timer, and it reads three existing list endpoints only.
  pollTimer = setInterval(() => {
    if (typeof document === 'undefined' || document.visibilityState !== 'hidden') {
      refresh()
    }
  }, 60_000)

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }
})

onUnmounted(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }

  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
})

watch(open, onOpenChanged)
watch(() => projectStore.activeProjectId, refresh)
watch(() => auth.user?.id, refresh)
</script>

<template>
  <ElPopover
    v-model:visible="open"
    trigger="click"
    placement="bottom-end"
    :width="360"
    popper-class="console-notification-popper"
  >
    <template #reference>
      <button
        type="button"
        class="relative flex size-8 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-dim)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
        :aria-label="t('console.topbar.notifications')"
        :aria-expanded="open"
        aria-haspopup="dialog"
      >
        <ElBadge
          :value="ui.unreadCount"
          :hidden="ui.unreadCount === 0"
          :offset="[-2, 2]"
        >
          <ElIcon :size="17"><Bell /></ElIcon>
        </ElBadge>
      </button>
    </template>

    <div
      class="flex flex-col"
      data-testid="notification-center"
      :data-open="open"
      role="dialog"
      :aria-label="t('console.topbar.notifications')"
    >
      <header
        class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] pb-2"
      >
        <div class="flex min-w-0 items-baseline gap-2">
          <span class="console-label">
            {{ t('console.topbar.notifications') }}
          </span>
          <span
            v-if="ui.unreadCount > 0"
            class="font-mono text-[10.5px] text-[var(--console-text-muted)]"
          >
            {{ ui.unreadCount }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="ui.unreadCount > 0"
            type="button"
            class="cursor-pointer border-0 bg-transparent text-[11px] text-[var(--accent-soft)] hover:underline"
            @click="ui.markAllRead()"
          >
            {{ t('console.topbar.markAllRead') }}
          </button>
          <button
            type="button"
            class="flex size-6 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] transition-colors hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
            :aria-label="t('console.common.close')"
            @click="open = false"
          >
            <ElIcon :size="13"><Close /></ElIcon>
          </button>
        </div>
      </header>

      <div
        v-if="ui.notificationError !== null"
        class="mt-2 flex items-start justify-between gap-2 rounded-md border px-2 py-1.5 text-[11px] leading-relaxed"
        :style="{
          borderColor: 'color-mix(in srgb, var(--status-fail) 28%, transparent)',
          color: 'var(--status-fail)',
        }"
        role="alert"
      >
        <span class="min-w-0">{{ errorText }}</span>
        <button
          type="button"
          class="shrink-0 cursor-pointer border-0 bg-transparent text-[11px] text-[var(--accent-soft)] hover:underline"
          @click="refresh"
        >
          {{ t('console.common.retry') }}
        </button>
      </div>

      <p
        v-if="ui.notificationLoading && items.length === 0"
        class="py-6 text-center text-[12px] text-[var(--console-text-muted)]"
      >
        {{ t('console.common.loading') }}
      </p>

      <p
        v-else-if="items.length === 0 && ui.notificationError === null"
        class="py-6 text-center text-[12px] text-[var(--console-text-muted)]"
      >
        {{ t('console.topbar.notificationsEmpty') }}
      </p>

      <ul
        v-else-if="items.length > 0"
        class="max-h-[360px] overflow-y-auto"
        data-testid="notification-list"
      >
        <li
          v-for="notification in items"
          :key="notification.id"
          class="border-b border-[var(--console-border)] last:border-b-0"
        >
          <button
            type="button"
            class="flex w-full cursor-pointer items-start gap-2.5 border-0 bg-transparent px-2 py-2.5 text-left transition-colors duration-150 hover:bg-[var(--console-surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)]"
            :class="notification.read ? '' : 'bg-[var(--console-surface-hover)]'"
            :data-notification-id="notification.id"
            @click="select(notification)"
          >
            <ElIcon
              class="mt-0.5 shrink-0"
              :size="15"
              :style="{ color: KIND_COLOR[notification.kind] }"
            >
              <component :is="KIND_ICON[notification.kind]" />
            </ElIcon>

            <span class="min-w-0 flex-1">
              <span class="flex items-start justify-between gap-2">
                <span
                  class="text-[12.5px] leading-snug text-[var(--console-text)]"
                  :class="notification.read ? '' : 'font-medium'"
                >
                  {{ titleOf(notification) }}
                </span>
                <span
                  v-if="!notification.read"
                  class="mt-1 size-1.5 shrink-0 rounded-full bg-[var(--accent)]"
                  aria-hidden="true"
                />
              </span>

              <span
                v-if="notification.localizedName !== undefined"
                class="mt-0.5 block truncate text-[11.5px] text-[var(--console-text-dim)]"
              >
                {{ localize(notification.localizedName) }}
              </span>

              <span
                v-if="detailOf(notification) !== ''"
                class="mt-0.5 line-clamp-2 block text-[11px] leading-relaxed text-[var(--console-text-muted)]"
              >
                {{ detailOf(notification) }}
              </span>

              <span class="mt-1 block font-mono text-[10.5px] text-[var(--console-text-muted)]">
                {{ timeOf(notification) }}
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </ElPopover>
</template>

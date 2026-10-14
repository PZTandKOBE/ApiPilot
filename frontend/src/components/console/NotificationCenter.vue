<script setup lang="ts">
import { Bell } from '@element-plus/icons-vue'
import { ElBadge, ElIcon, ElPopover } from 'element-plus'
import { computed, ref } from 'vue'

import { useI18n } from '@/i18n'
import { useUiStore } from '@/stores/ui'
import { formatRelativeTime } from '@/utils/time'
import type { ConsoleNotification, NotificationKind } from '@/types/console'

/**
 * Notification tray.
 *
 * Currently only ever populated by the app itself; the store's
 * `pushNotification` is the same entry point a server-sent event will use, so
 * wiring the backend later changes nothing here.
 *
 * Notification text is resolved from an i18n key at render time. A notification
 * pushed while the UI was in English must still read correctly after the user
 * switches to Chinese — a pre-rendered string could not do that.
 */
const { t, locale } = useI18n()
const ui = useUiStore()

const open = ref(false)

const KIND_COLOR: Readonly<Record<NotificationKind, string>> = {
  info: 'var(--accent)',
  success: 'var(--status-pass)',
  warning: 'var(--status-warn)',
  error: 'var(--status-fail)',
}

const items = computed(() => ui.notifications)

const titleOf = (notification: ConsoleNotification): string =>
  t(notification.titleKey, notification.params)

const timeOf = (notification: ConsoleNotification): string =>
  formatRelativeTime(notification.createdAt, locale.value)
</script>

<template>
  <ElPopover
    v-model:visible="open"
    trigger="click"
    placement="bottom-end"
    :width="320"
    popper-class="console-notification-popper"
  >
    <template #reference>
      <button
        type="button"
        class="relative flex size-8 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-dim)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
        :aria-label="t('console.topbar.notifications')"
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

    <div class="flex flex-col">
      <header
        class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] pb-2"
      >
        <span class="console-label">
          {{ t('console.topbar.notifications') }}
        </span>
        <button
          v-if="ui.unreadCount > 0"
          type="button"
          class="cursor-pointer border-0 bg-transparent text-[11px] text-[var(--accent-soft)] hover:underline"
          @click="ui.markAllRead()"
        >
          {{ t('console.topbar.markAllRead') }}
        </button>
      </header>

      <p
        v-if="items.length === 0"
        class="py-6 text-center text-[12px] text-[var(--console-text-muted)]"
      >
        {{ t('console.topbar.notificationsEmpty') }}
      </p>

      <ul v-else class="max-h-[320px] overflow-y-auto">
        <li
          v-for="notification in items"
          :key="notification.id"
          class="flex gap-2.5 border-b border-[var(--console-border)] py-2.5 last:border-b-0"
        >
          <span
            class="mt-1.5 size-1.5 shrink-0 rounded-full"
            :style="{ backgroundColor: KIND_COLOR[notification.kind] }"
          />
          <div class="min-w-0 flex-1">
            <p class="text-[12.5px] leading-snug text-[var(--console-text)]">
              {{ titleOf(notification) }}
            </p>
            <p class="mt-0.5 font-mono text-[10.5px] text-[var(--console-text-muted)]">
              {{ timeOf(notification) }}
            </p>
          </div>
        </li>
      </ul>
    </div>
  </ElPopover>
</template>

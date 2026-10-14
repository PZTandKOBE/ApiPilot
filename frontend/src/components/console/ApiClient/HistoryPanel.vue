<script setup lang="ts">
import { Clock, Delete } from '@element-plus/icons-vue'
import { ElIcon, ElMessageBox, ElTooltip } from 'element-plus'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import { formatDuration } from '@/utils/format'
import { methodColor, statusColor } from '@/utils/http'
import { formatRelativeTime } from '@/utils/time'

/**
 * Recently sent requests.
 *
 * Stores the *unresolved* draft, so restoring an entry brings back
 * `{{token}}` rather than the value that happened to be configured when it was
 * sent — the same request, re-runnable in a different environment.
 *
 * The status is shown for every entry, including failures: "which calls are
 * failing" is the question history answers most often.
 */
const { t, locale } = useI18n()
const store = useApiClientStore()

const clear = async (): Promise<void> => {
  try {
    await ElMessageBox.confirm(
      t('console.apiClient.history.clearConfirm'),
      t('console.apiClient.history.clear'),
      {
        confirmButtonText: t('console.common.confirm'),
        cancelButtonText: t('console.common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return // Dismissed.
  }

  store.clearHistory()
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="flex shrink-0 justify-end pb-1.5">
      <ElTooltip
        v-if="store.projectHistory.length > 0"
        :content="t('console.apiClient.history.clear')"
        placement="top"
        :show-after="300"
      >
        <button
          type="button"
          class="flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1 text-[11px] text-[var(--console-text-muted)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--status-fail)]"
          :aria-label="t('console.apiClient.history.clear')"
          @click="clear"
        >
          <ElIcon :size="12"><Delete /></ElIcon>
          {{ t('console.apiClient.history.clear') }}
        </button>
      </ElTooltip>
    </div>

    <div v-if="store.projectHistory.length === 0" class="flex flex-1 items-center">
      <ConsoleEmptyState
        class="w-full"
        :icon="Clock"
        :title="t('console.apiClient.history.empty')"
        :body="t('console.apiClient.history.emptyHint')"
      />
    </div>

    <!-- Scrolls for the same reason the collections list does: the rail owns a
         fixed height, so the list has to be the part that gives. -->
    <ul v-else class="console-scroll flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
      <li v-for="item in store.projectHistory" :key="item.id">
        <button
          type="button"
          class="flex w-full cursor-pointer flex-col gap-1 rounded-md border-0 bg-transparent px-2 py-1.5 text-start hover:bg-[var(--console-surface-hover)]"
          @click="store.restoreFromHistory(item.id)"
        >
          <span class="flex w-full items-center gap-2">
            <span
              class="w-[42px] shrink-0 font-mono text-[10px] font-semibold"
              :style="{ color: methodColor(item.method) }"
            >
              {{ item.method }}
            </span>
            <span class="min-w-0 flex-1 truncate font-mono text-[11.5px] text-[var(--console-text-dim)]">
              {{ item.url }}
            </span>
          </span>

          <span class="flex w-full items-center gap-2.5 ps-[50px] font-mono text-[10.5px]">
            <span :style="{ color: statusColor(item.status) }">{{ item.status }}</span>
            <span class="text-[var(--console-text-muted)]">{{ formatDuration(item.timeMs) }}</span>
            <span class="ms-auto text-[var(--console-text-muted)]">
              {{ formatRelativeTime(item.at, locale) }}
            </span>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

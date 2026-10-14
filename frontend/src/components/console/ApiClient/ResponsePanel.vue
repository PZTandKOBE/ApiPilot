<script setup lang="ts">
import { Loading, Warning } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'
import { computed, ref } from 'vue'

import ConsoleTabs from '@/components/console/ConsoleTabs.vue'
import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import type { ConsoleTab } from '@/types/console'
import { formatBytes, formatDuration } from '@/utils/format'
import { formatStatus, statusColor } from '@/utils/http'
import JsonViewer from './JsonViewer.vue'

/**
 * Response pane.
 *
 * Four states, and all four matter: loading, transport failure, no response
 * yet, and a response. An HTTP error status is *not* a failure state here — a
 * 404 renders exactly like a 200, differing only in the status colour and the
 * body. That is how a real client behaves, and it is what makes the response
 * panel useful for debugging the unhappy paths.
 *
 * `min-h-[140px]` is the pane's floor under the splitter — deliberately the
 * same one the request pane carries, so the pair always fits the pane they
 * share and neither can be pushed off the bottom of the shell. It is a floor
 * rather than a height, so the pane still grows with the viewport.
 */
const { t } = useI18n()
const store = useApiClientStore()

const active = ref('body')

const response = computed(() => store.response)

const tabs = computed<readonly ConsoleTab[]>(() => [
  { key: 'body', label: t('console.apiClient.tabs.responseBody') },
  {
    key: 'headers',
    label: t('console.apiClient.tabs.responseHeaders'),
    badge: response.value?.headers.length ?? 0,
  },
  {
    key: 'cookies',
    label: t('console.apiClient.tabs.cookies'),
    badge: response.value?.cookies.length ?? 0,
  },
])

const errorMessage = computed(() => {
  const current = store.error
  return current === null ? '' : t(current.messageKey, current.params)
})
</script>

<template>
  <section class="flex min-h-[140px] flex-1 flex-col console-panel p-3.5">
    <!-- Header: status, timing, size -->
    <header
      class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--console-border)] pb-3"
    >
      <div class="flex min-w-0 items-center gap-3">
        <span class="console-label">{{ t('console.apiClient.response') }}</span>

        <!-- In flight. The previous response stays on screen underneath rather
             than being cleared: replacing it with a spinner would throw away
             something the user may still be reading. -->
        <span
          v-if="store.sending"
          class="flex items-center gap-1.5 text-[11.5px] text-[var(--accent-soft)]"
          role="status"
        >
          <ElIcon :size="13" class="animate-spin"><Loading /></ElIcon>
          {{ t('console.apiClient.sending') }}
        </span>

        <template v-if="response !== null && !store.sending">
          <span
            class="rounded-md px-1.5 py-0.5 font-mono text-[11.5px] font-semibold"
            :style="{
              color: statusColor(response.status),
              backgroundColor: `color-mix(in srgb, ${statusColor(response.status)} 14%, transparent)`,
            }"
          >
            {{ formatStatus(response.status) }}
          </span>

          <span class="font-mono text-[11.5px] text-[var(--console-text-muted)]">
            {{ formatDuration(response.timeMs) }}
          </span>

          <span class="font-mono text-[11.5px] text-[var(--console-text-muted)]">
            {{ formatBytes(response.sizeBytes) }}
          </span>
        </template>
      </div>

      <ConsoleTabs
        v-if="response !== null"
        v-model="active"
        :tabs="tabs"
        :aria-label="t('console.apiClient.response')"
      />
    </header>

    <!-- Transport failure -->
    <div
      v-if="store.error !== null"
      class="mt-3 flex shrink-0 items-start gap-2 rounded-lg border p-3"
      :style="{
        borderColor: 'color-mix(in srgb, var(--status-fail) 32%, transparent)',
        backgroundColor: 'color-mix(in srgb, var(--status-fail) 10%, transparent)',
      }"
      role="alert"
    >
      <ElIcon :size="14" class="mt-0.5 shrink-0 text-[var(--status-fail)]">
        <Warning />
      </ElIcon>

      <div class="min-w-0 flex-1">
        <p class="text-[11px] font-semibold tracking-wide text-[var(--status-fail)]">
          {{ t('console.apiClient.error.title') }}
        </p>
        <p class="mt-0.5 text-[12px] leading-relaxed text-[var(--console-text-dim)]">
          {{ errorMessage }}
        </p>
      </div>

      <button
        type="button"
        class="shrink-0 cursor-pointer border-0 bg-transparent text-[11.5px] text-[var(--console-text-muted)] hover:text-[var(--console-text)]"
        @click="store.dismissError()"
      >
        {{ t('console.apiClient.error.dismiss') }}
      </button>
    </div>

    <!-- No response yet -->
    <div
      v-if="response === null && store.error === null"
      class="flex flex-1 flex-col items-center justify-center gap-1.5 text-center"
    >
      <p class="text-[13px] font-medium text-[var(--console-text-dim)]">
        {{ t('console.apiClient.responsePanel.waiting') }}
      </p>
      <p class="max-w-sm text-[12px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('console.apiClient.responsePanel.waitingHint') }}
      </p>
    </div>

    <!-- Response -->
    <div v-else-if="response !== null" class="mt-3 flex min-h-0 flex-1 flex-col">
      <JsonViewer v-if="active === 'body'" :text="response.body" />

      <div v-else-if="active === 'headers'" class="console-scroll min-h-0 flex-1 overflow-y-auto">
        <p
          v-if="response.headers.length === 0"
          class="py-6 text-center text-[12.5px] text-[var(--console-text-muted)]"
        >
          {{ t('console.apiClient.responsePanel.noHeaders') }}
        </p>

        <dl v-else class="flex flex-col gap-1.5">
          <div
            v-for="header in response.headers"
            :key="header.name"
            class="flex items-baseline gap-3 font-mono text-[12px]"
          >
            <dt class="w-[190px] shrink-0 break-all text-[var(--console-text-muted)]">
              {{ header.name }}
            </dt>
            <dd class="min-w-0 break-all text-[var(--console-text-dim)]">
              {{ header.value }}
            </dd>
          </div>
        </dl>
      </div>

      <div v-else class="console-scroll min-h-0 flex-1 overflow-y-auto">
        <p
          v-if="response.cookies.length === 0"
          class="py-6 text-center text-[12.5px] text-[var(--console-text-muted)]"
        >
          {{ t('console.apiClient.responsePanel.noCookies') }}
        </p>

        <ul v-else class="flex flex-col gap-2">
          <li
            v-for="cookie in response.cookies"
            :key="cookie.name"
            class="rounded-lg border border-[var(--console-border)] p-2.5"
          >
            <p class="font-mono text-[12.5px] text-[var(--accent-soft)]">
              {{ cookie.name }}
            </p>
            <p class="mt-1 font-mono text-[11.5px] break-all text-[var(--console-text-dim)]">
              {{ cookie.value }}
            </p>
            <p class="mt-1 font-mono text-[11px] text-[var(--console-text-muted)]">
              domain={{ cookie.domain }} path={{ cookie.path }}
              <template v-if="cookie.httpOnly"> · HttpOnly</template>
              <template v-if="cookie.secure"> · Secure</template>
            </p>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

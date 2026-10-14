<script setup lang="ts">
import { computed, ref } from 'vue'

import ConsoleTabs from '@/components/console/ConsoleTabs.vue'
import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import type { ConsoleTab } from '@/types/console'
import { activeRows } from '@/utils/apiDraft'
import AuthEditor from './AuthEditor.vue'
import BodyEditor from './BodyEditor.vue'
import HeadersEditor from './HeadersEditor.vue'
import ParamsEditor from './ParamsEditor.vue'

/**
 * Request editor tabs.
 *
 * Counts sit on the params and headers tabs so the shape of a request is
 * legible without opening anything — a common failure mode is forgetting that
 * three headers are still enabled from an earlier session.
 *
 * The root absorbs the request pane's height (`flex-1`) rather than sitting at
 * its content height: the pane is sized by the splitter, so anything less
 * leaves a dead band under the tab strip, and the editor below needs a bounded
 * box to scroll inside instead of growing the pane.
 */
const { t } = useI18n()
const store = useApiClientStore()

const active = ref('params')

const tabs = computed<readonly ConsoleTab[]>(() => [
  {
    key: 'params',
    label: t('console.apiClient.tabs.params'),
    badge: activeRows(store.draft.params).length,
  },
  {
    key: 'headers',
    label: t('console.apiClient.tabs.headers'),
    badge: activeRows(store.draft.headers).length,
  },
  {
    key: 'auth',
    label: t('console.apiClient.tabs.auth'),
    dot: store.draft.auth.type !== 'none',
  },
  {
    key: 'body',
    label: t('console.apiClient.tabs.body'),
    dot: store.draft.body.mode !== 'none' && store.draft.body.text.trim() !== '',
  },
])
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="shrink-0 pb-3">
      <ConsoleTabs v-model="active" :tabs="tabs" />
    </div>

    <!-- A flex column so the body editor can claim the leftover height; the
         shorter tabs stay at their content height. -->
    <div class="console-scroll flex min-h-0 flex-1 flex-col overflow-y-auto pe-0.5">
      <ParamsEditor v-if="active === 'params'" />
      <HeadersEditor v-else-if="active === 'headers'" />
      <AuthEditor v-else-if="active === 'auth'" />
      <BodyEditor v-else />
    </div>
  </div>
</template>

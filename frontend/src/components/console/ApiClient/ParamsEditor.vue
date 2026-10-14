<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import type { ApiKeyValue } from '@/types/api'
import KeyValueEditor from './KeyValueEditor.vue'

/**
 * Query parameters tab.
 *
 * Thin by design: it knows *which* slice of the draft it edits, while all the
 * editing mechanics live in `KeyValueEditor`.
 */
const { t } = useI18n()
const store = useApiClientStore()

const rows = computed<readonly ApiKeyValue[]>(() => store.draft.params)

const onUpdate = (next: readonly ApiKeyValue[]): void => {
  store.setParams(next)
}
</script>

<template>
  <div class="flex flex-col gap-2.5">
    <p class="text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
      {{ t('console.apiClient.paramsHint') }}
    </p>

    <KeyValueEditor
      :rows="rows"
      key-placeholder="page"
      value-placeholder="1"
      @update="onUpdate"
    />
  </div>
</template>

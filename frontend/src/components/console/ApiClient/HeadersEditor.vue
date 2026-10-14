<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import type { ApiKeyValue } from '@/types/api'
import KeyValueEditor from './KeyValueEditor.vue'

const { t } = useI18n()
const store = useApiClientStore()

const rows = computed<readonly ApiKeyValue[]>(() => store.draft.headers)

const onUpdate = (next: readonly ApiKeyValue[]): void => {
  store.setHeaders(next)
}
</script>

<template>
  <div class="flex flex-col gap-2.5">
    <p class="text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
      {{ t('console.apiClient.headersHint') }}
    </p>

    <KeyValueEditor
      :rows="rows"
      key-placeholder="Authorization"
      value-placeholder="Bearer {{token}}"
      @update="onUpdate"
    />
  </div>
</template>

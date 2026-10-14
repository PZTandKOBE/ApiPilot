<script setup lang="ts">
import { Delete } from '@element-plus/icons-vue'
import { ElIcon, ElInput, ElTooltip } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { ApiKeyValue } from '@/types/api'
import { withTrailingBlank } from '@/utils/apiDraft'

/**
 * Editable key/value table.
 *
 * Shared by the params and headers tabs because the two differ only in what
 * the values mean — the editing model (enable, rename, reorder by editing,
 * delete) is identical, and duplicating it would let the two drift.
 *
 * There is no "add row" button by design. The list always ends in a blank row
 * and typing into *that* is how a row is added, which is both how Postman and
 * Insomnia work and the only button-free way to guarantee the editor never
 * accumulates empty rows. A dedicated button could not add anything the
 * trailing row does not already offer.
 */
const props = defineProps<{
  rows: readonly ApiKeyValue[]
  keyPlaceholder?: string
  valuePlaceholder?: string
}>()

const emit = defineEmits<{ update: [rows: readonly ApiKeyValue[]] }>()

const { t } = useI18n()

/** Props plus the guaranteed trailing row. `withTrailingBlank` is id-stable. */
const displayRows = computed(() => withTrailingBlank(props.rows))

const patch = (id: string, changes: Partial<Omit<ApiKeyValue, 'id'>>): void => {
  emit(
    'update',
    displayRows.value.map((row) =>
      row.id === id ? { ...row, ...changes } : row,
    ),
  )
}

/**
 * Typing a key activates the row.
 *
 * Without this, text entered into the trailing row would sit there inert — the
 * user would have typed a parameter that silently never gets sent, which is
 * the worst failure this editor can produce.
 */
const onKeyInput = (row: ApiKeyValue, value: string): void => {
  patch(row.id, {
    key: value,
    enabled: value.trim() === '' ? row.enabled : true,
  })
}

const onValueInput = (row: ApiKeyValue, value: string): void => {
  patch(row.id, { value })
}

const onDescriptionInput = (row: ApiKeyValue, value: string): void => {
  patch(row.id, { description: value })
}

const remove = (id: string): void => {
  emit(
    'update',
    displayRows.value.filter((row) => row.id !== id),
  )
}
</script>

<template>
  <div class="flex flex-col gap-0.5">
    <div
      v-for="row in displayRows"
      :key="row.id"
      class="group/kv flex items-center gap-1"
    >
      <input
        type="checkbox"
        class="size-3.5 shrink-0 cursor-pointer accent-[var(--accent)]"
        :checked="row.enabled"
        :aria-label="t('console.apiClient.keyValue.enabled')"
        @change="patch(row.id, { enabled: ($event.target as HTMLInputElement).checked })"
      />

      <ElInput
        :model-value="row.key"
        class="console-kv-input min-w-0 flex-1"
        :placeholder="keyPlaceholder ?? t('console.apiClient.keyValue.keyPlaceholder')"
        :aria-label="t('console.apiClient.keyValue.key')"
        @update:model-value="onKeyInput(row, $event)"
      />

      <ElInput
        :model-value="row.value"
        class="console-kv-input min-w-0 flex-1"
        :placeholder="valuePlaceholder ?? t('console.apiClient.keyValue.valuePlaceholder')"
        :aria-label="t('console.apiClient.keyValue.value')"
        @update:model-value="onValueInput(row, $event)"
      />

      <ElInput
        :model-value="row.description"
        class="console-kv-input hidden min-w-0 flex-1 lg:inline-flex"
        :placeholder="t('console.apiClient.keyValue.descriptionPlaceholder')"
        :aria-label="t('console.apiClient.keyValue.description')"
        @update:model-value="onDescriptionInput(row, $event)"
      />

      <ElTooltip
        :content="t('console.apiClient.keyValue.delete')"
        placement="top"
        :show-after="300"
      >
        <button
          type="button"
          class="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] opacity-0 transition-opacity duration-150 hover:bg-[var(--console-surface-hover)] hover:text-[var(--status-fail)] focus-visible:opacity-100 group-hover/kv:opacity-100"
          :aria-label="t('console.apiClient.keyValue.delete')"
          @click="remove(row.id)"
        >
          <ElIcon :size="14"><Delete /></ElIcon>
        </button>
      </ElTooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElButton, ElDialog, ElInput, ElMessage, ElOption, ElSelect } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'

/**
 * Save prompt.
 *
 * Saving an already-open request updates it in place, so the collection field
 * is hidden in that case rather than offered and then ignored — a control that
 * does nothing is worse than no control.
 */
const visible = defineModel<boolean>({ required: true })

const { t } = useI18n()
const store = useApiClientStore()

const name = ref('')
const collection = ref('')

const isEditing = computed(() => store.hasOpenRequest)

/** Last path segment, which is almost always what the endpoint is called. */
const suggestedName = (): string => {
  const path = (store.draft.url.split('?')[0] ?? '').replace(/\/+$/, '')
  const segments = path.split('/').filter((segment) => segment !== '')
  const last = segments[segments.length - 1] ?? ''

  return last === '' ? `${store.draft.method} ${store.draft.url}` : last
}

watch(visible, (open) => {
  if (!open) return

  name.value = store.openRequestName !== '' ? store.openRequestName : suggestedName()
  collection.value = store.collectionNames[0] ?? ''
})

const confirm = (): void => {
  if (name.value.trim() === '') return

  store.saveRequest({ name: name.value, collection: collection.value })
  ElMessage.success(t('console.apiClient.saved'))
  visible.value = false
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.apiClient.saveTitle')"
    width="420px"
    align-center
    class="console-dialog"
  >
    <div class="flex flex-col gap-4">
      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.apiClient.saveName') }}</span>
        <ElInput
          v-model="name"
          :placeholder="t('console.apiClient.saveNamePlaceholder')"
          @keyup.enter="confirm"
        />
      </label>

      <label v-if="!isEditing" class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.apiClient.saveCollection') }}</span>
        <!-- `allow-create` lets a new collection be named inline; making the
             user create an empty collection first would be a detour. -->
        <ElSelect
          v-model="collection"
          filterable
          allow-create
          default-first-option
          :placeholder="t('console.apiClient.saveCollectionPlaceholder')"
        >
          <ElOption
            v-for="existing in store.collectionNames"
            :key="existing"
            :label="existing"
            :value="existing"
          />
        </ElSelect>
      </label>

      <p v-else class="text-[11.5px] text-[var(--console-text-muted)]">
        {{ t('console.apiClient.editing', { name: store.openRequestName }) }}
      </p>
    </div>

    <template #footer>
      <ElButton text @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton type="primary" :disabled="name.trim() === ''" @click="confirm">
        {{ t('console.apiClient.saveConfirm') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

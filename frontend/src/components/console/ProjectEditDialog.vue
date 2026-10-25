<script setup lang="ts">
import { ElButton, ElDialog, ElInput, ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { PROJECT_NAME_MAX } from '@/composables/useProjectCreationForm'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

/**
 * Rename one project.
 *
 * The dialog owns the draft and the failure state; the store owns the request
 * and the project list.  A failed save keeps the dialog open and the typed
 * name in place, because the usual correction is right there.
 */
const visible = defineModel<boolean>({ required: true })

const props = defineProps<{ project: Project }>()

const { t } = useI18n()
const store = useProjectStore()

const name = ref(props.project.name)
const touched = ref(false)
const failed = ref(false)

const trimmedName = computed(() => name.value.trim())
const nameValid = computed(
  () => trimmedName.value !== '' && trimmedName.value.length <= PROJECT_NAME_MAX,
)
const canSubmit = computed(
  () =>
    nameValid.value &&
    trimmedName.value !== props.project.name.trim() &&
    !store.updating,
)

watch(visible, (open) => {
  if (!open) return

  name.value = props.project.name
  touched.value = false
  failed.value = false
})

watch(
  () => props.project.id,
  () => {
    if (!visible.value) return
    name.value = props.project.name
    touched.value = false
    failed.value = false
  },
)

watch(name, () => {
  failed.value = false
})

const save = async (): Promise<void> => {
  touched.value = true
  if (!canSubmit.value) return

  const updated = await store.updateProjectName(
    props.project.id,
    trimmedName.value,
  )

  if (updated === null) {
    failed.value = true
    return
  }

  visible.value = false
  ElMessage.success(t('console.overview.projectSaved'))
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.overview.editProject')"
    width="420px"
    align-center
    class="console-dialog"
    :close-on-click-modal="!store.updating"
    :close-on-press-escape="!store.updating"
  >
    <div class="flex flex-col gap-4">
      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.project.nameLabel') }}</span>
        <ElInput
          v-model="name"
          :maxlength="PROJECT_NAME_MAX"
          :placeholder="t('console.project.namePlaceholder')"
          :disabled="store.updating"
          @keyup.enter="save"
        />
        <span
          v-if="touched && !nameValid"
          class="text-[11px] leading-relaxed text-[var(--status-fail)]"
        >
          {{ t('console.overview.invalidName') }}
        </span>
      </label>

      <p
        v-if="failed"
        class="text-[12px] leading-relaxed text-[var(--status-fail)]"
        role="alert"
      >
        {{ t('console.overview.saveFailed') }}
      </p>
    </div>

    <template #footer>
      <ElButton text :disabled="store.updating" @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton
        type="primary"
        :disabled="store.updating"
        :loading="store.updating"
        @click="save"
      >
        {{ t('console.common.save') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

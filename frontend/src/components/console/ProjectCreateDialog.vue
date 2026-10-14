<script setup lang="ts">
import { ElButton, ElDialog, ElInput, ElMessage } from 'element-plus'
import { watch } from 'vue'

import {
  PROJECT_BASE_URL_MAX,
  PROJECT_NAME_MAX,
  useProjectCreationForm,
} from '@/composables/useProjectCreationForm'
import { useI18n } from '@/i18n'

/**
 * New-project prompt.
 *
 * The dialog collects two things and owns neither of them: the form rules live in
 * \`useProjectCreationForm\`, the project is created by the store's action, and the
 * navigation that follows belongs to the page that opened this.  A dialog that
 * pushed routes would be a second opinion about where "the new project" lands.
 *
 * **Failure keeps the dialog open, with the typing still in it.** The mistake a
 * user can act on is usually the name, so the form is the last thing that should
 * be thrown away — and nothing about the server's internals is shown, because the
 * only text that reaches the screen is a sentence this console owns.
 */
const visible = defineModel<boolean>({ required: true })

const emit = defineEmits<{ readonly created: [projectId: string] }>()

const { t } = useI18n()
const { name, baseUrl, canSubmit, submitting, submit } = useProjectCreationForm()

/**
 * A fresh form each time it opens.
 *
 * Not "remember what was abandoned": a dialog reopened minutes later, prefilled
 * with a name the user did not choose, is a trap rather than a convenience.
 */
watch(visible, (open) => {
  if (!open) return

  name.value = ''
  baseUrl.value = ''
})

const confirm = async (): Promise<void> => {
  const projectId = await submit()

  if (projectId === null) {
    ElMessage.error(t('console.project.createFailed'))

    return
  }

  visible.value = false
  emit('created', projectId)
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.project.createTitle')"
    width="420px"
    align-center
    class="console-dialog"
  >
    <div class="flex flex-col gap-4">
      <p class="text-[12px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('console.project.createBody') }}
      </p>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.project.nameLabel') }}</span>
        <ElInput
          v-model="name"
          :maxlength="PROJECT_NAME_MAX"
          :placeholder="t('console.project.namePlaceholder')"
          :disabled="submitting"
        />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.project.baseUrlLabel') }}</span>
        <ElInput
          v-model="baseUrl"
          :maxlength="PROJECT_BASE_URL_MAX"
          :placeholder="t('console.project.baseUrlPlaceholder')"
          :disabled="submitting"
        />
        <span class="text-[11px] leading-relaxed text-[var(--console-text-muted)]">
          {{ t('console.project.baseUrlHint') }}
        </span>
      </label>
    </div>

    <template #footer>
      <ElButton text :disabled="submitting" @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton
        type="primary"
        :disabled="!canSubmit"
        :loading="submitting"
        @click="confirm"
      >
        {{ t('console.project.createConfirm') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

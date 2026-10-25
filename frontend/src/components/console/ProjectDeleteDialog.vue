<script setup lang="ts">
import { ElButton, ElDialog, ElInput, ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { useApiClientStore } from '@/stores/apiClient'
import { useProjectStore } from '@/stores/project'
import { useReportsStore } from '@/stores/reports'
import { useRunsStore } from '@/stores/runs'
import type { Project } from '@/types/project'

/**
 * Irreversible project deletion.
 *
 * The backend deletes the project's entire business graph, including its PDF
 * report rows. The dialog clears the same project's browser caches on success
 * and, when the active project was deleted, sends the user to the project list
 * so the next project is never shown as if it were the deleted one.
 */
const visible = defineModel<boolean>({ required: true })

const props = defineProps<{ project: Project }>()

const emit = defineEmits<{ readonly deleted: [] }>()

const { t } = useI18n()
const projectStore = useProjectStore()
const agentStore = useAgentStore()
const runsStore = useRunsStore()
const reportsStore = useReportsStore()
const apiClientStore = useApiClientStore()
const router = useRouter()

const name = ref('')
const failed = ref(false)

const matches = computed(() => name.value.trim() === props.project.name)
const canDelete = computed(
  () => matches.value && !projectStore.deletingProject,
)

watch(visible, (open) => {
  if (!open) return

  name.value = ''
  failed.value = false
})

const remove = async (): Promise<void> => {
  if (!canDelete.value) return

  const wasActive = projectStore.activeProjectId === props.project.id
  const deleted = await projectStore.deleteProject(props.project.id)

  if (!deleted) {
    failed.value = true
    return
  }

  agentStore.forgetProject(props.project.id)
  runsStore.forgetProject(props.project.id)
  reportsStore.forgetProject(props.project.id)
  apiClientStore.forgetProject(props.project.id, wasActive)

  visible.value = false
  ElMessage.success(t('console.project.deleted'))
  emit('deleted')

  if (wasActive) {
    void router.push({ name: 'console-projects' })
  }
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.project.deleteTitle')"
    width="min(480px, calc(100vw - 32px))"
    align-center
    class="console-dialog"
    :close-on-click-modal="!projectStore.deletingProject"
    :close-on-press-escape="!projectStore.deletingProject"
  >
    <div class="flex flex-col gap-3">
      <p class="text-[13px] leading-relaxed text-[var(--console-text)]">
        {{ t('console.project.deleteBody', { name: project.name }) }}
      </p>
      <p class="text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('console.project.deleteConsequences') }}
      </p>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.project.deleteNameLabel') }}</span>
        <ElInput
          v-model="name"
          :placeholder="project.name"
          :disabled="projectStore.deletingProject"
          @keyup.enter="remove"
        />
        <span
          v-if="name.length > 0 && !matches"
          class="text-[11px] leading-relaxed text-[var(--status-fail)]"
        >
          {{ t('console.project.deleteNameMismatch') }}
        </span>
      </label>

      <p
        v-if="failed"
        class="rounded-md border border-[var(--console-border-strong)] bg-[var(--console-surface-hover)] p-2 text-[12px] leading-relaxed text-[var(--status-fail)]"
        role="alert"
      >
        {{ t('console.project.deleteFailed') }}
      </p>
    </div>

    <template #footer>
      <ElButton text :disabled="projectStore.deletingProject" @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton
        type="danger"
        :loading="projectStore.deletingProject"
        :disabled="!canDelete"
        @click="remove"
      >
        {{ t('console.project.deleteConfirm') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

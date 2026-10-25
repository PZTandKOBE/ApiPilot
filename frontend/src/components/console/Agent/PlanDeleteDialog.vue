<script setup lang="ts">
import { ElButton, ElDialog, ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { TestPlan } from '@/types/agent'

/**
 * The destructive confirmation for one plan series.
 *
 * The server soft-retires every version; existing runs and their PDF reports
 * are intentionally outside this action and the copy says so. The dialog owns
 * only the confirmation and the in-flight state.
 */
const visible = defineModel<boolean>({ required: true })

const props = defineProps<{ plan: TestPlan }>()

const emit = defineEmits<{ readonly deleted: [] }>()

const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

const failed = ref(false)

const name = computed(() => localize(props.plan.name))
const versionCount = computed(
  () =>
    store.projectPlans.filter(
      (plan) =>
        plan.projectId === props.plan.projectId && plan.specId === props.plan.specId,
    ).length || 1,
)
const body = computed(() =>
  t('console.plans.deleteBody', { name: name.value, count: versionCount.value }),
)

watch(visible, (open) => {
  if (open) failed.value = false
})

const remove = async (): Promise<void> => {
  const deleted = await store.deletePlan(props.plan.projectId, props.plan.id)

  if (!deleted) {
    failed.value = true
    return
  }

  visible.value = false
  ElMessage.success(t('console.plans.deleted'))
  emit('deleted')
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.plans.deleteTitle')"
    width="min(440px, calc(100vw - 32px))"
    align-center
    class="console-dialog"
    :close-on-click-modal="!store.deletingPlan"
    :close-on-press-escape="!store.deletingPlan"
  >
    <div class="flex flex-col gap-3">
      <p class="text-[13px] leading-relaxed text-[var(--console-text)]">
        {{ body }}
      </p>
      <p class="text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('console.plans.deleteHistoryNote') }}
      </p>

      <p
        v-if="failed"
        class="rounded-md border border-[var(--console-border-strong)] bg-[var(--console-surface-hover)] p-2 text-[12px] leading-relaxed text-[var(--status-fail)]"
        role="alert"
      >
        {{ t('console.plans.deleteFailed') }}
      </p>
    </div>

    <template #footer>
      <ElButton text :disabled="store.deletingPlan" @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton
        type="danger"
        :loading="store.deletingPlan"
        :disabled="store.deletingPlan"
        @click="remove"
      >
        {{ t('console.plans.deleteConfirm') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

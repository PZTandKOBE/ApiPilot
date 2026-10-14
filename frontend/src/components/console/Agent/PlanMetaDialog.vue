<script setup lang="ts">
import { ElButton, ElDialog, ElInput } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { TestPlan } from '@/types/agent'

/**
 * Plan metadata editor.
 *
 * Name and goal only. Everything else on a plan — its scenarios, its steps,
 * its assertions, its risk level — is the agent's proposal, and letting a
 * reviewer rewrite those would mean "approved" no longer refers to the plan
 * the agent actually produced.
 *
 * Editing never touches approval state: a renamed plan is the same plan, so an
 * approved one stays approved and keeps its timestamp.
 */
const visible = defineModel<boolean>({ required: true })

const props = defineProps<{ plan: TestPlan }>()

const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

const name = ref('')
const goal = ref('')

watch(visible, (open) => {
  if (!open) return

  // Seeded from what the reviewer is looking at, so the field starts as the
  // plan they just read rather than as its dictionary key.
  name.value = localize(props.plan.name)
  goal.value = localize(props.plan.goal)
})

const canSave = computed(
  () => name.value.trim() !== '' && goal.value.trim() !== '',
)

const confirm = (): void => {
  if (!canSave.value) return

  store.updatePlanMeta(props.plan.id, {
    name: name.value.trim(),
    goal: goal.value.trim(),
  })

  visible.value = false
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.aiTest.plan.editTitle')"
    width="460px"
    align-center
    class="console-dialog"
  >
    <div class="flex flex-col gap-4">
      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.aiTest.plan.nameLabel') }}</span>
        <ElInput v-model="name" @keyup.enter="confirm" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.aiTest.plan.goal') }}</span>
        <ElInput v-model="goal" type="textarea" :rows="3" resize="none" />
      </label>
    </div>

    <template #footer>
      <ElButton text @click="visible = false">
        {{ t('console.aiTest.approval.cancel') }}
      </ElButton>
      <ElButton type="primary" :disabled="!canSave" @click="confirm">
        {{ t('console.aiTest.plan.save') }}
      </ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { VideoPlay } from '@element-plus/icons-vue'
import { ElButton, ElDialog, ElIcon, ElInput, ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { RiskLevel, TestPlan } from '@/types/agent'
import PlanStatusTag from './PlanStatusTag.vue'

/**
 * The human boundary.
 *
 * The agent generated the plan; nothing here lets it run. Approval is a
 * deliberate two-step — put the plan in front of a reviewer, then confirm what
 * it covers — and every status change goes through a store action, so there is
 * no path around the gate.
 *
 * `plan` defaults to the store's active plan; the detail page passes the plan
 * its route points at. Run availability is derived from *that* plan, never
 * from a cached flag — a stale `canRun` would be a way through the boundary.
 */
const props = withDefaults(defineProps<{ plan?: TestPlan | null }>(), { plan: null })

const { t } = useI18n()
const store = useAgentStore()
const route = useRoute()
const router = useRouter()

const LEVEL_KEY: Readonly<Record<RiskLevel, string>> = {
  low: 'console.aiTest.risks.levelLow',
  medium: 'console.aiTest.risks.levelMedium',
  high: 'console.aiTest.risks.levelHigh',
}

const approveOpen = ref(false)
const rejectOpen = ref(false)
const rejectReason = ref('')

const plan = computed(() => props.plan ?? store.activePlan)

/** The single gate. Only an approved plan is executable. */
const canRun = computed(() => plan.value?.status === 'approved')

/** Execution belongs to the next phase; the button arms itself when it lands. */
const executionRouteReady = computed(() => router.hasRoute('console-project-runs'))

/** Still open for a decision — approved and rejected plans are settled. */
const decidable = computed(
  () =>
    plan.value !== null &&
    (plan.value.status === 'draft' || plan.value.status === 'in_review'),
)

const requestCount = computed(
  () =>
    plan.value?.scenarios.reduce(
      (total, scenario) =>
        total + scenario.steps.filter((step) => step.kind === 'request').length,
      0,
    ) ?? 0,
)

const approveSummary = computed(() =>
  t('console.aiTest.approval.approveSummary', {
    scenarios: plan.value?.scenarios.length ?? 0,
    requests: requestCount.value,
    risk: t(LEVEL_KEY[plan.value?.riskLevel ?? 'medium']),
  }),
)

/**
 * Opening the dialog is what moves a plan out of `draft`: it has been put in
 * front of a reviewer, which is exactly what `in_review` means.
 */
const openApprove = (): void => {
  const current = plan.value
  if (current === null) return

  store.startReview(current.id)
  approveOpen.value = true
}

const confirmApprove = (): void => {
  const current = plan.value
  if (current === null) return

  store.approvePlan(current.id)
  approveOpen.value = false
  ElMessage.success(t('console.aiTest.approval.approved'))
}

const confirmReject = (): void => {
  const current = plan.value
  if (current === null) return

  if (!store.rejectPlan(current.id, rejectReason.value)) {
    ElMessage.warning(t('console.aiTest.approval.reasonRequired'))
    return
  }

  rejectOpen.value = false
  rejectReason.value = ''
  ElMessage.info(t('console.aiTest.approval.rejected'))
}

const onRun = (): void => {
  if (!canRun.value) return

  if (executionRouteReady.value) {
    void router.push({
      name: 'console-project-runs',
      params: { projectId: route.params.projectId },
    })
    return
  }

  ElMessage.info(t('console.aiTest.plan.executionNextPhase'))
}
</script>

<template>
  <section v-if="plan !== null" class="console-panel p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2.5">
        <span class="console-label">{{ t('console.aiTest.plan.status') }}</span>
        <PlanStatusTag :status="plan.status" />
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <ElButton v-if="decidable" size="small" @click="rejectOpen = true">
          {{ t('console.aiTest.approval.reject') }}
        </ElButton>

        <ElButton v-if="decidable" size="small" type="primary" @click="openApprove">
          {{ t('console.aiTest.approval.approve') }}
        </ElButton>

        <!-- Run is gated on approval; the reason is stated, not implied. -->
        <ElButton
          size="small"
          :type="canRun ? 'success' : 'default'"
          :disabled="!canRun"
          :title="canRun ? undefined : t('console.aiTest.plan.runBlocked')"
          @click="onRun"
        >
          <ElIcon class="mr-1.5"><VideoPlay /></ElIcon>
          {{ t('console.aiTest.plan.run') }}
        </ElButton>
      </div>
    </div>

    <p v-if="!canRun" class="mt-2 text-[11.5px] text-[var(--console-text-muted)]">
      {{ t('console.aiTest.plan.runBlocked') }}
    </p>

    <p
      v-if="plan.status === 'rejected' && plan.rejectionReason !== null"
      class="mt-2 rounded-lg border px-3 py-2 text-[11.5px] leading-relaxed"
      :style="{
        borderColor: 'color-mix(in srgb, var(--status-fail) 30%, transparent)',
        color: 'var(--console-text-dim)',
      }"
    >
      <span class="font-medium text-[var(--status-fail)]">
        {{ t('console.aiTest.approval.rejectReason') }}:
      </span>
      {{ plan.rejectionReason }}
    </p>

    <!-- Approve confirmation -->
    <ElDialog
      v-model="approveOpen"
      :title="t('console.aiTest.approval.approveTitle')"
      width="420px"
      align-center
      class="console-dialog"
    >
      <p class="text-[13px] text-[var(--console-text-dim)]">
        {{ t('console.aiTest.approval.approveBody') }}
      </p>
      <p class="mt-3 font-mono text-[12px] text-[var(--console-text)]">
        {{ approveSummary }}
      </p>

      <template #footer>
        <ElButton text @click="approveOpen = false">
          {{ t('console.aiTest.approval.cancel') }}
        </ElButton>
        <ElButton type="primary" @click="confirmApprove">
          {{ t('console.aiTest.approval.approveConfirm') }}
        </ElButton>
      </template>
    </ElDialog>

    <!-- Reject requires a reason -->
    <ElDialog
      v-model="rejectOpen"
      :title="t('console.aiTest.approval.rejectTitle')"
      width="420px"
      align-center
      class="console-dialog"
    >
      <p class="text-[13px] text-[var(--console-text-dim)]">
        {{ t('console.aiTest.approval.rejectBody') }}
      </p>

      <label class="mt-3 flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.aiTest.approval.rejectReason') }}</span>
        <ElInput
          v-model="rejectReason"
          type="textarea"
          :rows="3"
          resize="none"
          :placeholder="t('console.aiTest.approval.rejectReasonPlaceholder')"
        />
      </label>

      <template #footer>
        <ElButton text @click="rejectOpen = false">
          {{ t('console.aiTest.approval.cancel') }}
        </ElButton>
        <ElButton
          type="danger"
          :disabled="rejectReason.trim() === ''"
          @click="confirmReject"
        >
          {{ t('console.aiTest.approval.rejectConfirm') }}
        </ElButton>
      </template>
    </ElDialog>
  </section>
</template>

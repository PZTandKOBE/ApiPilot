<script setup lang="ts">
import { MagicStick, Right } from '@element-plus/icons-vue'
import { ElAlert, ElButton, ElIcon, ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AgentAnalysisProgress from '@/components/console/Agent/AgentAnalysisProgress.vue'
import AgentHandoffCard from '@/components/console/Agent/AgentHandoffCard.vue'
import AgentPipelineSteps from '@/components/console/Agent/AgentPipelineSteps.vue'
import AgentSpecSummary from '@/components/console/Agent/AgentSpecSummary.vue'
import AnalysisReviewPanel from '@/components/console/Agent/AnalysisReviewPanel.vue'
import SpecUploader from '@/components/console/Agent/SpecUploader.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'

/**
 * AI Test Lab.
 *
 * The page is a state machine over the store, and every branch is one the user
 * can actually reach: nothing loaded, loaded but unanalysed, analysing,
 * analysed.  The plan is deliberately *not* rendered here any more: the lab
 * produces the analysis and the plan, but the plan's scenarios, steps,
 * assertions and approval controls belong to Test Plans.
 *
 * The compact handoff at the end of the page is the only plan-shaped thing in
 * the lab.  It reports whether a plan exists and navigates to the real plan
 * destination; it never becomes a second copy of the plan page.
 */
const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()
const projectStore = useProjectStore()
const route = useRoute()
const router = useRouter()

/** Set by "Replace" so an existing spec can be swapped without discarding it first. */
const replacing = ref(false)

/**
 * The spec that belongs to the project now selected.
 *
 * Active project changes can leave the previous parsed document and analysis in
 * the agent store until asynchronous rehydration finishes. The page must not
 * show that previous project's document, plan or review in the gap.
 */
const activeSpec = computed(() =>
  store.currentSpec?.projectId === projectStore.activeProjectId
    ? store.currentSpec
    : null,
)

/** The project id the route is showing; used for plan destination safety. */
const pageProjectId = computed(() => {
  const id = route.params.projectId
  return typeof id === 'string' ? id : projectStore.activeProjectId
})

const showUploader = computed(() => activeSpec.value === null || replacing.value)
const analysing = computed(() => store.analyzing)
const showUnderstanding = computed(() => {
  const understanding = store.understanding
  const spec = activeSpec.value

  return (
    understanding !== null &&
    spec !== null &&
    understanding.specId === spec.id &&
    !store.analyzing
  )
})

/**
 * The plan handoff stands on its own.
 *
 * The plan is written by the server and comes back on every task, so it survives
 * a reload; the understanding is never persisted and exists only on the response
 * that produced it. Gating the handoff on the understanding would hide a stored,
 * reviewable plan from a user who merely refreshed the page.
 */
const hasPlan = computed(() => store.activePlan !== null)
const activePlan = computed(() => store.activePlan)
const showPlanHandoff = computed(
  () => activeSpec.value !== null && (showUnderstanding.value || hasPlan.value),
)

const activeVersion = computed(() => activePlan.value?.version ?? 1)
const activePlanName = computed(() =>
  activePlan.value === null ? '' : localize(activePlan.value.name),
)

/** A plan-conflict is an answer with a real destination, not a dead generation. */
const planConflict = computed(
  () =>
    activeSpec.value !== null &&
    hasPlan.value &&
    store.planError?.code === 'plan-exists',
)

/** A parse failure and a generation failure are both worth one banner. */
const activeError = computed(() => store.planError ?? store.analysisError)
const showErrorBanner = computed(
  () => activeError.value !== null && !planConflict.value,
)

const errorMessage = computed(() => {
  const error = activeError.value
  return error === null ? '' : t(error.messageKey, error.params)
})

/**
 * The current plan's real detail route, or null when no plan belongs to the
 * project the page is showing.  The project id comes from the plan itself and
 * is checked against the route; a plan id from another project is never used.
 */
const planDestination = computed(() => {
  const plan = activePlan.value
  if (plan === null || plan.projectId !== pageProjectId.value) return null

  return {
    name: 'console-project-plan-detail' as const,
    params: { projectId: plan.projectId, planId: plan.id },
  }
})

/**
 * Open the current plan when one is safe to locate; otherwise open the existing
 * plan list for this project.  This is navigation only: no approval, no
 * generation and no execution is triggered.
 */
const openPlan = (): void => {
  if (planDestination.value !== null) {
    void router.push(planDestination.value)
    return
  }

  if (pageProjectId.value !== '') {
    void router.push({
      name: 'console-project-plans',
      params: { projectId: pageProjectId.value },
    })
  }
}

onMounted(async () => {
  // The plans a browser shows are also server state.  Without this refresh a
  // fresh tab sees no local plan, labels the action "Generate", and its
  // ordinary request is refused with 409 even though the plan exists.
  await store.loadPlans()

  // The understanding itself is not persisted, but the task audit is. Restore
  // it after the plan so a reload shows the real five-step review instead of
  // only the plan.
  await store.restoreAnalysis()
})

const onPlanAction = async (): Promise<void> => {
  // Refresh before choosing the branch, so the button acts on the server's
  // current version list rather than on a possibly stale local cache.
  await store.loadPlans()

  if (store.activePlan === null) {
    await store.generatePlan()
    return
  }

  try {
    await ElMessageBox.confirm(
      t('console.aiTest.plan.regenerateBody'),
      t('console.aiTest.plan.regenerateTitle'),
      {
        confirmButtonText: t('console.aiTest.plan.regenerateConfirm'),
        cancelButtonText: t('console.aiTest.plan.regenerateCancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const before = store.projectPlans.length
  await store.regeneratePlan()

  if (store.planError === null && store.projectPlans.length > before) {
    ElMessage.success(t('console.aiTest.plan.regenerateSuccess'))
  }
}

// A spec that has just landed is the one the user was asking for, so the
// uploader stands down on its own.
watch(
  () => store.currentSpec?.id,
  (id) => {
    if (id !== undefined) replacing.value = false
  },
)
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      :title="t('console.aiTest.title')"
      :subtitle="t('console.aiTest.subtitle')"
    />

    <div class="flex flex-col gap-4">
      <AgentPipelineSteps />

      <AgentHandoffCard />

      <ElAlert
        v-if="showErrorBanner"
        type="error"
        :closable="true"
        show-icon
        @close="store.clearErrors()"
      >
        <template #title>{{ t('console.aiTest.errors.title') }}</template>
        <span class="text-[12px] leading-relaxed">{{ errorMessage }}</span>
      </ElAlert>

      <!-- Nothing loaded yet, or the user asked to swap the spec -->
      <SpecUploader v-if="showUploader" />

      <template v-else>
        <!-- Before analysis the spec summary is the only context. After analysis
             it becomes the first step of the review and is not repeated here. -->
        <AgentSpecSummary v-if="!showUnderstanding" @replace="replacing = true" />

        <AgentAnalysisProgress v-if="analysing" />

        <div v-if="showUnderstanding">
          <AnalysisReviewPanel
            @replace="replacing = true"
            @continue-to-plan="openPlan"
          />
        </div>

        <!-- The lab ends with a plan handoff, not a second copy of Test Plans.
             The real plan page owns scenarios, assertions, editing, approval and
             execution; this card only says whether a plan exists and where it is. -->
        <section
          v-if="showPlanHandoff"
          data-testid="plan-handoff"
          class="console-panel p-4"
        >
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="min-w-0">
              <p class="console-label">{{ t('console.aiTest.plan.nextStep') }}</p>
              <h2 class="mt-1 text-[14px] font-semibold text-[var(--console-text)]">
                {{
                  hasPlan
                    ? t('console.aiTest.plan.readyTitle')
                    : t('console.aiTest.plan.generateTitle')
                }}
              </h2>
              <p class="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
                {{
                  hasPlan
                    ? t('console.aiTest.plan.readyBody')
                    : t('console.aiTest.plan.generateBody')
                }}
              </p>

              <p v-if="hasPlan" class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
                <span class="font-medium text-[var(--console-text)]">
                  {{ activePlanName }}
                </span>
                <span
                  class="rounded border border-[var(--console-border)] px-1.5 py-px font-mono text-[10px] text-[var(--console-text-muted)]"
                >
                  {{ t('console.plans.version', { version: activeVersion }) }}
                </span>
              </p>

              <p
                v-if="planConflict"
                class="mt-1.5 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]"
              >
                {{ t('console.aiTest.plan.existsHint') }}
              </p>
            </div>

            <div class="flex shrink-0 flex-wrap items-center gap-2">
              <template v-if="hasPlan">
                <ElButton type="primary" @click="openPlan">
                  {{ t('console.aiTest.plan.viewPlan') }}
                  <ElIcon class="ml-1.5"><Right /></ElIcon>
                </ElButton>
                <ElButton
                  text
                  :loading="store.generating"
                  @click="onPlanAction"
                >
                  {{ t('console.aiTest.plan.regenerate') }}
                </ElButton>
              </template>

              <template v-else>
                <ElButton
                  type="primary"
                  :loading="store.generating"
                  @click="onPlanAction"
                >
                  <ElIcon v-if="!store.generating" class="mr-1.5"><MagicStick /></ElIcon>
                  {{ t('console.aiTest.plan.generate') }}
                </ElButton>
                <ElButton text @click="openPlan">
                  {{ t('console.aiTest.plan.openPlans') }}
                </ElButton>
              </template>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

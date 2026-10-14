<script setup lang="ts">
import { MagicStick, Right } from '@element-plus/icons-vue'
import { ElAlert, ElButton, ElIcon } from 'element-plus'
import { computed, ref, watch } from 'vue'

import AgentAnalysisProgress from '@/components/console/Agent/AgentAnalysisProgress.vue'
import AgentFindingCard from '@/components/console/Agent/AgentFindingCard.vue'
import AgentHandoffCard from '@/components/console/Agent/AgentHandoffCard.vue'
import AgentPipelineSteps from '@/components/console/Agent/AgentPipelineSteps.vue'
import AgentSpecSummary from '@/components/console/Agent/AgentSpecSummary.vue'
import ApiDependencyGraph from '@/components/console/Agent/ApiDependencyGraph.vue'
import ApiRiskList from '@/components/console/Agent/ApiRiskList.vue'
import ApiUnderstandingPanel from '@/components/console/Agent/ApiUnderstandingPanel.vue'
import ApprovalPanel from '@/components/console/Agent/ApprovalPanel.vue'
import SpecUploader from '@/components/console/Agent/SpecUploader.vue'
import TestPlan from '@/components/console/Agent/TestPlan.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'

/**
 * AI Test Lab.
 *
 * The page is a state machine over the store, and every branch is one the user
 * can actually reach: nothing loaded, loaded but unanalysed, analysing,
 * analysed, planned. There is no separate "dashboard" of empty cards waiting
 * to be filled — an empty lab shows the one thing you can do next.
 *
 * This is also where the difference between the two halves of the product is
 * most visible: the API Client is where *you* call the API, and this is where
 * the agent reads the API and proposes what to call.
 */
const { t } = useI18n()
const store = useAgentStore()

/** Set by "Replace" so an existing spec can be swapped without discarding it first. */
const replacing = ref(false)

const showUploader = computed(() => store.currentSpec === null || replacing.value)
const analysing = computed(() => store.analyzing)
const showUnderstanding = computed(
  () => store.understanding !== null && !store.analyzing,
)

/**
 * The plan section stands on its own.
 *
 * The plan is written by the server and comes back on every task, so it survives
 * a reload; the understanding is never persisted and exists only on the response
 * that produced it. Gating the plan on the understanding would hide a stored,
 * reviewable plan from a user who merely refreshed the page -- and the approval
 * gate is the only thing that should decide whether a plan can be run.
 */
const showPlan = computed(() => store.currentSpec !== null)

/** A parse failure and a generation failure are both worth one banner. */
const activeError = computed(() => store.planError ?? store.analysisError)

const errorMessage = computed(() => {
  const error = activeError.value
  return error === null ? '' : t(error.messageKey, error.params)
})

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
        v-if="activeError !== null"
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
        <AgentSpecSummary @replace="replacing = true" />

        <AgentAnalysisProgress v-if="analysing" />

        <template v-if="showUnderstanding">
          <ApiUnderstandingPanel />

          <div class="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <ApiDependencyGraph />
            <ApiRiskList />
          </div>

          <!-- Agent activity -->
          <section class="console-panel">
            <header class="border-b border-[var(--console-border)] px-4 py-3">
              <h2 class="text-[13px] font-semibold text-[var(--console-text)]">
                {{ t('console.aiTest.findings.title') }}
              </h2>
            </header>

            <p
              v-if="(store.understanding?.findings.length ?? 0) === 0"
              class="px-4 py-6 text-center text-[12px] text-[var(--console-text-muted)]"
            >
              {{ t('console.aiTest.findings.empty') }}
            </p>

            <ul v-else class="flex flex-col divide-y divide-[var(--console-border)]">
              <AgentFindingCard
                v-for="finding in store.understanding?.findings ?? []"
                :key="finding.id"
                :finding="finding"
              />
            </ul>
          </section>

        </template>

        <!-- Test plan: shown whenever a specification is loaded, whether or not
             this browser has seen the understanding that goes with it. -->
        <template v-if="showPlan">
          <section class="flex flex-col gap-4">
            <header class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-3">
                <h2 class="text-[14px] font-semibold text-[var(--console-text)]">
                  {{ t('console.aiTest.plan.title') }}
                </h2>

                <RouterLink
                  :to="{ name: 'console-project-plans' }"
                  class="flex items-center gap-1 text-[11.5px] text-[var(--accent-soft)] hover:underline"
                >
                  {{ t('console.plans.viewAll') }}
                  <ElIcon :size="11"><Right /></ElIcon>
                </RouterLink>
              </div>

              <ElButton
                size="small"
                type="primary"
                :loading="store.generating"
                @click="store.generatePlan()"
              >
                <ElIcon v-if="!store.generating" class="mr-1.5"><MagicStick /></ElIcon>
                {{ t('console.aiTest.plan.generate') }}
              </ElButton>
            </header>

            <TestPlan show-open-link />
            <ApprovalPanel />
          </section>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { MagicStick, Tickets } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'

import PlanRiskTag from '@/components/console/Agent/PlanRiskTag.vue'
import PlanStatusTag from '@/components/console/Agent/PlanStatusTag.vue'
import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { TestPlan } from '@/types/agent'
import { formatRelativeTime } from '@/utils/time'

/**
 * Every plan this project has.
 *
 * Reads `agentStore.projectPlans` directly — there is one source of plans in
 * the application, and a page that kept its own copy would be a second one to
 * keep in sync.
 *
 * Deliberately not a copy of the AI Test Lab's plan view: this answers "what
 * has the agent proposed for this project, and where does each one stand",
 * which needs one line per plan rather than the full scenario breakdown.
 */
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

/** Newest first: the plan just generated is the one being looked for. */
const plans = computed(() =>
  [...store.projectPlans].sort((a, b) => b.generatedAt.localeCompare(a.generatedAt)),
)

const counts = (plan: TestPlan) => {
  const steps = plan.scenarios.reduce((total, scenario) => total + scenario.steps.length, 0)
  const assertions = plan.scenarios.reduce(
    (total, scenario) => total + scenario.assertions.length,
    0,
  )

  return `${plan.scenarios.length} ${t('console.aiTest.plan.scenarios')} · ${steps} ${t('console.aiTest.plan.steps')} · ${assertions} ${t('console.aiTest.plan.assertions')}`
}

const detailTarget = (plan: TestPlan) => ({
  name: 'console-project-plan-detail',
  params: { planId: plan.id },
})
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader :title="t('console.plans.title')" :subtitle="t('console.plans.subtitle')">
      <template #actions>
        <ElButton size="small" @click="$router.push({ name: 'console-project-ai-test' })">
          <ElIcon class="mr-1.5"><MagicStick /></ElIcon>
          {{ t('console.plans.openLab') }}
        </ElButton>
      </template>
    </ConsolePageHeader>

    <div v-if="plans.length === 0" class="console-panel">
      <ConsoleEmptyState
        :icon="Tickets"
        :title="t('console.plans.empty')"
        :body="t('console.plans.emptyHint')"
      >
        <ElButton
          size="small"
          type="primary"
          @click="$router.push({ name: 'console-project-ai-test' })"
        >
          {{ t('console.plans.openLab') }}
        </ElButton>
      </ConsoleEmptyState>
    </div>

    <ul v-else class="flex flex-col gap-2.5">
      <li v-for="plan in plans" :key="plan.id">
        <RouterLink
          :to="detailTarget(plan)"
          class="console-panel block p-4 transition-colors duration-150 hover:border-[var(--console-border-strong)]"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <h2
                class="truncate text-[13.5px] font-medium text-[var(--console-text)]"
              >
                {{ localize(plan.name) }}
              </h2>
              <p class="mt-1 max-w-2xl text-[12px] leading-relaxed text-[var(--console-text-dim)]">
                {{ localize(plan.goal) }}
              </p>
            </div>

            <div class="flex shrink-0 items-center gap-2">
              <PlanRiskTag :level="plan.riskLevel" />
              <PlanStatusTag :status="plan.status" />
            </div>
          </div>

          <p class="mt-2.5 font-mono text-[11px] text-[var(--console-text-muted)]">
            {{ counts(plan) }}
          </p>

          <dl class="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            <div class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.plans.generatedAt') }}
              </dt>
              <dd class="font-mono text-[var(--console-text-dim)]">
                {{ formatRelativeTime(plan.generatedAt, locale) }}
              </dd>
            </div>

            <div v-if="plan.approvedAt !== null" class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.plans.approvedAt') }}
              </dt>
              <dd class="font-mono text-[var(--status-pass)]">
                {{ formatRelativeTime(plan.approvedAt, locale) }}
              </dd>
            </div>

            <div class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.plans.source') }}
              </dt>
              <dd class="text-[var(--console-text-dim)]">
                {{
                  plan.source === 'handoff'
                    ? t('console.aiTest.plan.sourceHandoff')
                    : t('console.aiTest.plan.sourceGenerated')
                }}
              </dd>
            </div>
          </dl>
        </RouterLink>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { EditPen, Right } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { TestPlan } from '@/types/agent'
import { formatRelativeTime } from '@/utils/time'
import AgentScenarioCard from './AgentScenarioCard.vue'
import PlanMetaDialog from './PlanMetaDialog.vue'
import PlanRiskTag from './PlanRiskTag.vue'
import PlanStatusTag from './PlanStatusTag.vue'

/**
 * The plan, previewed.
 *
 * Read-only apart from its own name and goal: reviewing a plan means reading
 * what it will do, and a plan a human silently rewrote is no longer the thing
 * they approved.
 *
 * `plan` defaults to the store's active plan so the AI Test Lab can render it
 * with no props at all; the detail page passes the plan its route points at.
 */
const props = withDefaults(
  defineProps<{
    plan?: TestPlan | null
    /** Rendered by the lab, where this view is a preview rather than the page. */
    showOpenLink?: boolean
  }>(),
  { plan: null, showOpenLink: false },
)

const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()
const route = useRoute()

const resolved = computed(() => props.plan ?? store.activePlan)

const editOpen = ref(false)

const stats = computed(() => {
  const plan = resolved.value
  if (plan === null) return []

  const steps = plan.scenarios.reduce((total, scenario) => total + scenario.steps.length, 0)
  const assertions = plan.scenarios.reduce(
    (total, scenario) => total + scenario.assertions.length,
    0,
  )

  return [
    { key: 'scenarios', label: t('console.aiTest.plan.scenarios'), value: plan.scenarios.length },
    { key: 'steps', label: t('console.aiTest.plan.steps'), value: steps },
    { key: 'assertions', label: t('console.aiTest.plan.assertions'), value: assertions },
  ]
})

const generatedLabel = computed(() => {
  const plan = resolved.value
  if (plan === null) return ''

  return `${t('console.aiTest.plan.generatedBy')} · ${formatRelativeTime(plan.generatedAt, locale.value)}`
})

const detailTarget = computed(() => ({
  name: 'console-project-plan-detail',
  params: { projectId: route.params.projectId, planId: resolved.value?.id },
}))
</script>

<template>
  <section v-if="resolved !== null" class="console-panel">
    <!-- Header -->
    <header class="border-b border-[var(--console-border)] px-4 py-3.5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <h2 class="text-[15px] font-semibold text-[var(--console-text)]">
            {{ localize(resolved.name) }}
          </h2>
          <p class="mt-1 max-w-2xl text-[12px] leading-relaxed text-[var(--console-text-dim)]">
            {{ localize(resolved.goal) }}
          </p>
        </div>

        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <PlanRiskTag :level="resolved.riskLevel" />
          <PlanStatusTag :status="resolved.status" />

          <ElButton size="small" @click="editOpen = true">
            <ElIcon class="mr-1.5"><EditPen /></ElIcon>
            {{ t('console.aiTest.plan.edit') }}
          </ElButton>
        </div>
      </div>

      <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <p class="font-mono text-[11px] text-[var(--console-text-muted)]">
          {{ generatedLabel }}
          <template v-if="resolved.source === 'handoff'">
            · {{ t('console.aiTest.plan.sourceHandoff') }}
          </template>
          <template v-else>
            · {{ t('console.aiTest.plan.sourceGenerated') }}
          </template>
        </p>

        <RouterLink
          v-if="showOpenLink"
          :to="detailTarget"
          class="flex items-center gap-1 text-[11.5px] text-[var(--accent-soft)] hover:underline"
        >
          {{ t('console.aiTest.plan.openDetail') }}
          <ElIcon :size="11"><Right /></ElIcon>
        </RouterLink>
      </div>

      <dl class="mt-3 flex flex-wrap gap-x-6 gap-y-2">
        <div v-for="stat in stats" :key="stat.key" class="flex items-baseline gap-1.5">
          <dt class="console-label">{{ stat.label }}</dt>
          <dd class="font-mono text-[13px] text-[var(--console-text)]">{{ stat.value }}</dd>
        </div>
      </dl>
    </header>

    <!-- Scenarios -->
    <div>
      <AgentScenarioCard
        v-for="scenario in resolved.scenarios"
        :key="scenario.id"
        :scenario="scenario"
      />
    </div>

    <PlanMetaDialog v-if="resolved !== null" v-model="editOpen" :plan="resolved" />
  </section>

  <section v-else class="console-panel px-4 py-8 text-center">
    <p class="text-[12.5px] text-[var(--console-text-muted)]">
      {{ t('console.aiTest.plan.empty') }}
    </p>
  </section>
</template>

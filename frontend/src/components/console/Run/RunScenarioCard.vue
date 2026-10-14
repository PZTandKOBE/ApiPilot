<script setup lang="ts">
import PlanRiskTag from '@/components/console/Agent/PlanRiskTag.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import type { RunScenario } from '@/types/run'

import RunAssertionRow from './RunAssertionRow.vue'
import RunStepRow from './RunStepRow.vue'
import RunStepStatusTag from './RunStepStatusTag.vue'

/**
 * One scenario as it came out, read top to bottom.
 *
 * The scenarios come from the run payload, never from the local plan: a plan
 * can be regenerated under the same id while a run is in flight, and joining
 * against it would repaint a finished run with steps that never ran.
 *
 * Assertions are listed apart from the steps because they are checked against
 * the scenario's state, not at one point in the sequence — a plan can assert
 * something no single step produced.
 */
defineProps<{ scenario: RunScenario }>()

const { t } = useI18n()
const { localize } = useLocalizedText()
</script>

<template>
  <section class="console-panel">
    <header class="flex flex-wrap items-start justify-between gap-3 px-4 py-3.5">
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="font-mono text-[11px] text-[var(--console-text-muted)]">
          {{ String(scenario.index).padStart(2, '0') }}
        </span>
        <h2 class="min-w-0 text-[13px] font-medium text-[var(--console-text)]">
          {{ localize(scenario.name) }}
        </h2>
      </div>

      <div class="flex shrink-0 items-center gap-2">
        <PlanRiskTag :level="scenario.riskLevel" />
        <RunStepStatusTag :status="scenario.status" />
      </div>
    </header>

    <div class="border-t border-[var(--console-border)] px-4 py-3">
      <p
        v-if="scenario.steps.length === 0"
        class="text-[11.5px] text-[var(--console-text-muted)]"
      >
        {{ t('console.runs.noSteps') }}
      </p>

      <ul v-else class="flex flex-col border-s border-[var(--console-border)] ps-1">
        <RunStepRow v-for="step in scenario.steps" :key="step.id" :step="step" />
      </ul>
    </div>

    <div
      v-if="scenario.assertions.length > 0"
      class="border-t border-[var(--console-border)] px-4 py-3"
    >
      <p class="console-label">{{ t('console.aiTest.plan.assertions') }}</p>
      <ul class="mt-1.5 flex flex-col divide-y divide-[var(--console-border)]">
        <RunAssertionRow
          v-for="assertion in scenario.assertions"
          :key="assertion.id"
          :assertion="assertion"
        />
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import type { RiskLevel, TestScenario } from '@/types/agent'
import AgentStep from './AgentStep.vue'

/**
 * One scenario, read top to bottom: what it is for, the sequence it runs, and
 * what has to be true at the end.
 *
 * The steps are shown as an ordered list rather than a diagram — this is the
 * preview of a plan, and the thing a reviewer needs to check is the order and
 * the assertions, both of which are easier to verify as text.
 */
const props = defineProps<{ scenario: TestScenario }>()

const { t } = useI18n()
const { localize } = useLocalizedText()

const LEVEL_KEY: Readonly<Record<RiskLevel, string>> = {
  low: 'console.aiTest.risks.levelLow',
  medium: 'console.aiTest.risks.levelMedium',
  high: 'console.aiTest.risks.levelHigh',
}

const LEVEL_COLOR: Readonly<Record<RiskLevel, string>> = {
  low: 'var(--console-text-muted)',
  medium: 'var(--status-warn)',
  high: 'var(--status-fail)',
}

const requestCount = computed(
  () => props.scenario.steps.filter((step) => step.kind === 'request').length,
)
</script>

<template>
  <article class="border-b border-[var(--console-border)] px-4 py-4 last:border-b-0">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="font-mono text-[11px] text-[var(--console-text-muted)]">
          {{ String(scenario.index).padStart(2, '0') }}
        </span>
        <div class="min-w-0">
          <h3 class="text-[13px] font-medium text-[var(--console-text)]">
            {{ localize(scenario.name) }}
          </h3>
          <p class="mt-0.5 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
            {{ localize(scenario.description) }}
          </p>
        </div>
      </div>

      <div class="flex shrink-0 items-center gap-2">
        <span class="font-mono text-[10.5px] text-[var(--console-text-muted)]">
          {{ requestCount }} / {{ scenario.steps.length }}
        </span>
        <span
          class="rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-semibold"
          :style="{
            color: LEVEL_COLOR[scenario.riskLevel],
            backgroundColor: `color-mix(in srgb, ${LEVEL_COLOR[scenario.riskLevel]} 14%, transparent)`,
          }"
        >
          {{ t(LEVEL_KEY[scenario.riskLevel]) }}
        </span>
      </div>
    </header>

    <!-- Steps -->
    <ol class="mt-3 border-s border-[var(--console-border)] ps-1">
      <AgentStep v-for="step in scenario.steps" :key="step.id" :step="step" />
    </ol>

    <!-- Expected -->
    <div class="mt-3 rounded-lg border border-[var(--console-border)] bg-black/20 px-3 py-2.5">
      <p class="console-label">{{ t('console.aiTest.plan.expected') }}</p>
      <p class="mt-1 text-[12px] leading-relaxed text-[var(--console-text-dim)]">
        {{ localize(scenario.expected) }}
      </p>
    </div>

    <!-- Assertions -->
    <div v-if="scenario.assertions.length > 0" class="mt-2.5">
      <p class="console-label">{{ t('console.aiTest.plan.assertions') }}</p>
      <ul class="mt-1.5 flex flex-col gap-1">
        <li
          v-for="assertion in scenario.assertions"
          :key="assertion.id"
          class="flex items-baseline gap-2 text-[11.5px]"
        >
          <span
            class="shrink-0 font-mono text-[10.5px] text-[var(--console-text-muted)]"
          >
            {{ assertion.target }}
          </span>
          <span class="min-w-0 text-[var(--console-text-dim)]">
            {{ localize(assertion.description) }}
          </span>
        </li>
      </ul>
    </div>
  </article>
</template>

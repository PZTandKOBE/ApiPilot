<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { RiskCategory, RiskLevel } from '@/types/agent'

/**
 * What the agent thinks is worth testing, and why.
 *
 * These are findings, not warnings: each one is a statement about the document
 * that a reviewer can check for themselves — a field with a constraint and no
 * invalid case, an action that presumes a resource exists. Nothing here
 * reports a conclusion whose basis is hidden.
 */
const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

const risks = computed(() => store.understanding?.risks ?? [])

const LEVEL_KEY: Readonly<Record<RiskLevel, string>> = {
  low: 'console.aiTest.risks.levelLow',
  medium: 'console.aiTest.risks.levelMedium',
  high: 'console.aiTest.risks.levelHigh',
}

/** Risk levels reuse the console's status palette rather than inventing one. */
const LEVEL_COLOR: Readonly<Record<RiskLevel, string>> = {
  low: 'var(--console-text-muted)',
  medium: 'var(--status-warn)',
  high: 'var(--status-fail)',
}

const CATEGORY_KEY: Readonly<Record<RiskCategory, string>> = {
  authentication: 'console.aiTest.risks.categoryAuthentication',
  dependency: 'console.aiTest.risks.categoryDependency',
  validation: 'console.aiTest.risks.categoryValidation',
  'negative-coverage': 'console.aiTest.risks.categoryNegativeCoverage',
  idempotency: 'console.aiTest.risks.categoryIdempotency',
  authorization: 'console.aiTest.risks.categoryAuthorization',
}

/** Worst first: a reviewer should meet the high findings before the low ones. */
const ORDER: Readonly<Record<RiskLevel, number>> = { high: 0, medium: 1, low: 2 }

const sorted = computed(() =>
  [...risks.value].sort((a, b) => ORDER[a.level] - ORDER[b.level]),
)
</script>

<template>
  <section class="console-panel">
    <header
      class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
    >
      <h2 class="text-[13px] font-semibold text-[var(--console-text)]">
        {{ t('console.aiTest.understanding.risks') }}
      </h2>
      <span class="font-mono text-[11px] text-[var(--console-text-muted)]">
        {{ risks.length }}
      </span>
    </header>

    <p
      v-if="sorted.length === 0"
      class="px-4 py-6 text-center text-[12px] text-[var(--console-text-muted)]"
    >
      {{ t('console.aiTest.risks.empty') }}
    </p>

    <ul v-else class="flex flex-col">
      <li
        v-for="risk in sorted"
        :key="risk.id"
        class="border-b border-[var(--console-border)] px-4 py-3 last:border-b-0"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-semibold"
            :style="{
              color: LEVEL_COLOR[risk.level],
              backgroundColor: `color-mix(in srgb, ${LEVEL_COLOR[risk.level]} 14%, transparent)`,
            }"
          >
            {{ t(LEVEL_KEY[risk.level]) }}
          </span>

          <span class="text-[10.5px] text-[var(--console-text-muted)]">
            {{ t(CATEGORY_KEY[risk.category]) }}
          </span>
        </div>

        <p class="mt-1.5 text-[12.5px] font-medium text-[var(--console-text)]">
          {{ localize(risk.title) }}
        </p>
        <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
          {{ localize(risk.detail) }}
        </p>
      </li>
    </ul>
  </section>
</template>

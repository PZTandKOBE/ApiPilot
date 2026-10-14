<script setup lang="ts">
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import type { RunAssertion } from '@/types/run'

import RunStepStatusTag from './RunStepStatusTag.vue'

/**
 * One assertion as it came out, next to what was asked for.
 *
 * Expected and actual are shown together and in monospace because the whole
 * value of the row is the comparison: a reader checking a failure should not
 * have to hold one value in their head while scrolling to find the other. A
 * missing `actual` prints an em dash rather than an empty cell — "nothing came
 * back" and "the renderer gave up" must not look the same.
 */
defineProps<{ assertion: RunAssertion }>()

const { t } = useI18n()
const { localize } = useLocalizedText()
</script>

<template>
  <li class="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-1.5">
    <div class="flex min-w-0 items-baseline gap-2">
      <RunStepStatusTag :status="assertion.status" />
      <span class="min-w-0 text-[11.5px] leading-snug text-[var(--console-text-dim)]">
        {{ localize(assertion.description) }}
      </span>
    </div>

    <div class="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-[10.5px]">
      <span class="flex items-baseline gap-1.5">
        <span class="text-[var(--console-text-muted)]">{{ t('console.runs.expected') }}</span>
        <span class="font-mono text-[11px] text-[var(--console-text)]">
          {{ assertion.expected }}
        </span>
      </span>

      <span class="flex items-baseline gap-1.5">
        <span class="text-[var(--console-text-muted)]">{{ t('console.runs.actual') }}</span>
        <span
          class="font-mono text-[11px]"
          :class="assertion.actual === null ? 'text-[var(--console-text-muted)]' : 'text-[var(--console-text)]'"
        >
          {{ assertion.actual ?? '—' }}
        </span>
      </span>
    </div>
  </li>
</template>

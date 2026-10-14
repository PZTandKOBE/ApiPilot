<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { RunStepStatus } from '@/types/run'

/**
 * Step and assertion status chip.
 *
 * The same chip as `RunStatusTag`, one notch quieter: a run carries one of
 * these per step, and a column of chips at the run's own weight would read as
 * a page of verdicts rather than a sequence being followed.
 *
 * `RunAssertionStatus` is a subset of this type, so an assertion reuses the
 * step words — a passed check and a passed step are the same verdict.
 */
const props = defineProps<{ status: RunStepStatus }>()

const { t } = useI18n()

const LABEL_KEY: Readonly<Record<RunStepStatus, string>> = {
  pending: 'console.runs.stepStatus.pending',
  running: 'console.runs.stepStatus.running',
  passed: 'console.runs.stepStatus.passed',
  failed: 'console.runs.stepStatus.failed',
  skipped: 'console.runs.stepStatus.skipped',
}

/** `skipped` is mute for the same reason `cancelled` is: nothing went wrong. */
const COLOR: Readonly<Record<RunStepStatus, string>> = {
  pending: 'var(--console-text-muted)',
  running: 'var(--status-warn)',
  passed: 'var(--status-pass)',
  failed: 'var(--status-fail)',
  skipped: 'var(--console-text-muted)',
}

const label = computed(() => t(LABEL_KEY[props.status]))
const color = computed(() => COLOR[props.status])
</script>

<template>
  <span
    class="shrink-0 rounded border px-1.5 py-px text-[9.5px] whitespace-nowrap"
    :style="{
      color,
      borderColor: `color-mix(in srgb, ${color} 26%, transparent)`,
    }"
  >
    {{ label }}
  </span>
</template>

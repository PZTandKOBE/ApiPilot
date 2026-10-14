<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { RunStatus } from '@/types/run'

/**
 * Run status chip.
 *
 * The same shape as `PlanStatusTag` because it answers the same question one
 * level down: where does this stand. A run that is still going is the only
 * one whose colour means "wait" rather than "judgement" — hence `running`
 * borrowing the warning tone rather than a third pass/fail shade.
 */
const props = defineProps<{ status: RunStatus }>()

const { t } = useI18n()

const LABEL_KEY: Readonly<Record<RunStatus, string>> = {
  queued: 'console.runs.status.queued',
  running: 'console.runs.status.running',
  passed: 'console.runs.status.passed',
  failed: 'console.runs.status.failed',
  cancelled: 'console.runs.status.cancelled',
}

/**
 * Cancelled reads as muted rather than failed: the user stopped it, and
 * painting their own decision like an error would be an accusation.
 */
const COLOR: Readonly<Record<RunStatus, string>> = {
  queued: 'var(--console-text-muted)',
  running: 'var(--status-warn)',
  passed: 'var(--status-pass)',
  failed: 'var(--status-fail)',
  cancelled: 'var(--console-text-muted)',
}

const label = computed(() => t(LABEL_KEY[props.status]))
const color = computed(() => COLOR[props.status])
</script>

<template>
  <span
    class="shrink-0 rounded-md border px-1.5 py-0.5 text-[10.5px] font-medium whitespace-nowrap"
    :style="{
      color,
      borderColor: `color-mix(in srgb, ${color} 34%, transparent)`,
    }"
  >
    {{ label }}
  </span>
</template>

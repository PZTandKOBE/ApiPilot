<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { AgentTaskStatus } from '@/types/agent'

/**
 * The persisted state of one agent task.
 *
 * Kept separate from PlanStatusTag: these are task lifecycle states
 * (pending / analyzing / completed / failed), not approval states. Sharing a
 * chip would make two different vocabularies look like one.
 */
const props = defineProps<{ status: AgentTaskStatus }>()

const { t } = useI18n()

const LABEL_KEY: Readonly<Record<AgentTaskStatus, string>> = {
  pending: 'console.dashboard.taskStatus.pending',
  analyzing: 'console.dashboard.taskStatus.analyzing',
  completed: 'console.dashboard.taskStatus.completed',
  failed: 'console.dashboard.taskStatus.failed',
}

const COLOR: Readonly<Record<AgentTaskStatus, string>> = {
  pending: 'var(--console-text-muted)',
  analyzing: 'var(--status-warn)',
  completed: 'var(--status-pass)',
  failed: 'var(--status-fail)',
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

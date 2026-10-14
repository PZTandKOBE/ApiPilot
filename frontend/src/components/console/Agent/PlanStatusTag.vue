<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { ApprovalStatus } from '@/types/agent'

/**
 * Approval status chip.
 *
 * Shared by the plan list, the plan header and the approval panel. The colour
 * map lived in three files before this — the kind of duplication that drifts
 * silently, because a status that looks right in one place and wrong in
 * another is only noticed by accident.
 */
const props = defineProps<{ status: ApprovalStatus }>()

const { t } = useI18n()

const LABEL_KEY: Readonly<Record<ApprovalStatus, string>> = {
  draft: 'console.aiTest.status.draft',
  in_review: 'console.aiTest.status.in_review',
  approved: 'console.aiTest.status.approved',
  rejected: 'console.aiTest.status.rejected',
}

/** Reuses the console's status palette rather than inventing a second one. */
const COLOR: Readonly<Record<ApprovalStatus, string>> = {
  draft: 'var(--console-text-muted)',
  in_review: 'var(--status-warn)',
  approved: 'var(--status-pass)',
  rejected: 'var(--status-fail)',
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

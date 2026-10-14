<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { RiskLevel } from '@/types/agent'

/**
 * Risk level chip.
 *
 * Filled rather than outlined, so it reads as the louder of the two chips on a
 * row that also carries a status. High risk is the thing a reviewer should see
 * first.
 */
const props = defineProps<{ level: RiskLevel }>()

const { t } = useI18n()

const LABEL_KEY: Readonly<Record<RiskLevel, string>> = {
  low: 'console.aiTest.risks.levelLow',
  medium: 'console.aiTest.risks.levelMedium',
  high: 'console.aiTest.risks.levelHigh',
}

const COLOR: Readonly<Record<RiskLevel, string>> = {
  low: 'var(--console-text-muted)',
  medium: 'var(--status-warn)',
  high: 'var(--status-fail)',
}

const label = computed(() => t(LABEL_KEY[props.level]))
const color = computed(() => COLOR[props.level])
</script>

<template>
  <span
    class="shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-semibold whitespace-nowrap"
    :style="{
      color,
      backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
    }"
  >
    {{ label }}
  </span>
</template>

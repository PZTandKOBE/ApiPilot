<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import type { TestStep, TestStepKind } from '@/types/agent'
import { methodColor } from '@/utils/http'

/**
 * One line of a scenario's sequence.
 *
 * A step is either a call, a value pulled out of a response, or an assertion
 * checkpoint — and the row shows which, because the three read very
 * differently when you are checking whether the plan makes sense.
 */
const props = defineProps<{ step: TestStep }>()

const { t } = useI18n()
const { localize } = useLocalizedText()

const KIND_KEY: Readonly<Record<TestStepKind, string>> = {
  request: 'console.aiTest.step.request',
  extract: 'console.aiTest.step.extract',
  assert: 'console.aiTest.step.assert',
}

/** Extractions are the agent's own bookkeeping; requests are the substance. */
const KIND_COLOR = computed(() => {
  switch (props.step.kind) {
    case 'request':
      return 'var(--console-text-muted)'
    case 'extract':
      return 'var(--accent)'
    default:
      return 'var(--status-pass)'
  }
})
</script>

<template>
  <li class="flex items-start gap-2.5 py-1.5">
    <span class="w-4 shrink-0 pt-0.5 text-end font-mono text-[10.5px] text-[var(--console-text-muted)]">
      {{ step.index }}
    </span>

    <span
      class="mt-[3px] w-[46px] shrink-0 text-[10px] font-medium"
      :style="{ color: KIND_COLOR }"
    >
      {{ t(KIND_KEY[step.kind]) }}
    </span>

    <span class="min-w-0 flex-1">
      <span class="flex flex-wrap items-baseline gap-x-2">
        <span
          v-if="step.method !== null"
          class="font-mono text-[10.5px] font-semibold"
          :style="{ color: methodColor(step.method) }"
        >
          {{ step.method }}
        </span>
        <span v-if="step.path !== null" class="font-mono text-[12px] text-[var(--console-text)]">
          {{ step.path }}
        </span>
      </span>

      <span class="mt-0.5 block text-[11.5px] leading-snug text-[var(--console-text-muted)]">
        {{ localize(step.description) }}
      </span>

      <span
        v-if="step.produces !== null || step.consumes.length > 0"
        class="mt-1 flex flex-wrap items-center gap-1.5"
      >
        <span
          v-if="step.sourcePath"
          class="rounded-md border border-[var(--console-border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--console-text-muted)]"
        >
          {{ step.sourcePath }}
        </span>
        <span
          v-if="step.produces !== null"
          class="rounded-md px-1.5 py-0.5 font-mono text-[10px]"
          :style="{
            color: 'var(--accent-soft)',
            backgroundColor: 'color-mix(in srgb, var(--accent) 14%, transparent)',
          }"
        >
          → {{ step.produces }}
        </span>
        <span
          v-for="variable in step.consumes"
          :key="variable"
          class="rounded-md border border-[var(--console-border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--console-text-muted)]"
        >
          {{ variable }}
        </span>
      </span>
    </span>
  </li>
</template>

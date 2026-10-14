<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { isLocalizedMessage, type LocalizedText, type TestStepKind } from '@/types/agent'
import type { RunStep } from '@/types/run'
import { methodColor } from '@/utils/http'

import RunFailureNote from './RunFailureNote.vue'
import RunStepStatusTag from './RunStepStatusTag.vue'

/**
 * One step as it came out.
 *
 * The same row the plan preview uses, plus the three things only a run can
 * answer: how long it took, what it left behind, and whether it failed. The
 * description is still the plan's words — a run describes what it *did*, and
 * a rewritten sentence here would be the frontend's commentary rather than a
 * record.
 *
 * Root is an `<li>` because that is what the scenario's `<ul>` holds, and
 * because a step is an entry in an ordered sequence, not a standalone card.
 */
const props = defineProps<{ step: RunStep }>()

const { t } = useI18n()
const { localize } = useLocalizedText()

const KIND_KEY: Readonly<Record<TestStepKind, string>> = {
  request: 'console.aiTest.step.request',
  extract: 'console.aiTest.step.extract',
  assert: 'console.aiTest.step.assert',
}

/** Extractions are the agent's own bookkeeping; requests are the substance. */
const KIND_COLOR: Readonly<Record<TestStepKind, string>> = {
  request: 'var(--console-text-muted)',
  extract: 'var(--accent)',
  assert: 'var(--status-pass)',
}

/** Stable list key: authored labels have a key, literal ones have their text. */
const evidenceKey = (label: LocalizedText): string =>
  isLocalizedMessage(label) ? label.key : label.text

/** A step is measured in milliseconds; a second is already a slow call. */
const duration = computed(() =>
  props.step.durationMs === null ? '' : `${Math.round(props.step.durationMs)} ms`,
)
</script>

<template>
  <li class="flex items-start gap-2.5 py-1.5">
    <span class="w-4 shrink-0 pt-0.5 text-end font-mono text-[10.5px] text-[var(--console-text-muted)]">
      {{ step.index }}
    </span>

    <span
      class="mt-[3px] w-[46px] shrink-0 text-[10px] font-medium"
      :style="{ color: KIND_COLOR[step.kind] }"
    >
      {{ t(KIND_KEY[step.kind]) }}
    </span>

    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-baseline gap-x-2">
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
        <span
          v-if="duration !== ''"
          class="font-mono text-[10.5px] text-[var(--console-text-muted)]"
        >
          {{ duration }}
        </span>
        <RunStepStatusTag class="ms-auto" :status="step.status" />
      </div>

      <p class="mt-0.5 text-[11.5px] leading-snug text-[var(--console-text-muted)]">
        {{ localize(step.description) }}
      </p>

      <!-- What the step left behind: the call it made, the value it pulled out.
           Titled, because "Requested POST /api/orders" is the difference
           between "it passed" and "here is why you should believe that". -->
      <div v-if="step.evidence.length > 0" class="mt-1.5">
        <p class="console-label">{{ t('console.runs.evidence.heading') }}</p>

        <dl class="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          <div
            v-for="item in step.evidence"
            :key="`${evidenceKey(item.label)}-${item.value}`"
            class="flex items-baseline gap-1.5"
          >
            <dt class="text-[10.5px] text-[var(--console-text-muted)]">
              {{ localize(item.label) }}
            </dt>
            <dd class="font-mono text-[11px] text-[var(--console-text-dim)]">
              {{ item.value }}
            </dd>
          </div>
        </dl>
      </div>

      <RunFailureNote v-if="step.failure !== null" class="mt-1.5" :failure="step.failure" />
    </div>
  </li>
</template>

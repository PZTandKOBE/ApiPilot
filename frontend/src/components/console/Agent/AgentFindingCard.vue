<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import {
  isLocalizedMessage,
  type AgentActionSummary,
  type AgentActionResult,
  type LocalizedText,
} from '@/types/agent'

/** Stable list key: authored labels have a key, literal ones have their text. */
const evidenceKey = (label: LocalizedText): string =>
  isLocalizedMessage(label) ? label.key : label.text

/**
 * One thing the agent did, reported in the open.
 *
 * Four fields and nothing else: what it did, the decision it took, whether it
 * worked, and the concrete artifact behind it. There is no expandable
 * "details" section, because there is no further detail to disclose — the
 * type has nowhere to keep it.
 *
 * `evidence` is what makes the line checkable: "17 protected endpoints" and
 * "POST /api/auth/login" are facts the reader can verify against the
 * understanding below.
 */
const props = defineProps<{ finding: AgentActionSummary }>()

const { localize } = useLocalizedText()

const RESULT_COLOR: Readonly<Record<AgentActionResult, string>> = {
  succeeded: 'var(--status-pass)',
  failed: 'var(--status-fail)',
  skipped: 'var(--console-text-muted)',
}

const resultColor = computed(() => RESULT_COLOR[props.finding.result])
</script>

<template>
  <li class="flex gap-3 px-4 py-3">
    <span
      class="mt-1.5 size-1.5 shrink-0 rounded-full"
      :style="{ backgroundColor: resultColor }"
      :title="finding.result"
    />

    <div class="min-w-0 flex-1">
      <p class="text-[12.5px] text-[var(--console-text)]">
        {{ localize(finding.action) }}
      </p>
      <p class="mt-0.5 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
        {{ localize(finding.decisionSummary) }}
      </p>

      <dl v-if="finding.evidence.length > 0" class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
        <div
          v-for="item in finding.evidence"
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
  </li>
</template>

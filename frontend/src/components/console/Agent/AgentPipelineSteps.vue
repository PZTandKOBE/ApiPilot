<script setup lang="ts">
import { Check } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { PIPELINE_STEPS, type PipelineStep } from '@/types/agent'

/**
 * Where the agent is in its workflow.
 *
 * Every state here is read from the store — there is no local pipeline
 * variable. That matters more than it looks: a step is only ever shown as
 * complete because the artifact it produces actually exists, so the bar can
 * never claim progress the user cannot go and inspect.
 *
 * Labels are hidden below `md` rather than allowed to wrap or scroll: six
 * stages do not fit on a phone, and a horizontally scrolling progress bar is
 * worse than a row of numbers.
 */
const { t } = useI18n()
const store = useAgentStore()

const LABEL_KEY: Readonly<Record<PipelineStep, string>> = {
  spec: 'console.aiTest.pipeline.spec',
  analyze: 'console.aiTest.pipeline.analyze',
  understanding: 'console.aiTest.pipeline.understanding',
  plan: 'console.aiTest.pipeline.plan',
  approve: 'console.aiTest.pipeline.approve',
  execute: 'console.aiTest.pipeline.execute',
}

type StepState = 'done' | 'current' | 'pending'

const stateOf = (step: PipelineStep): StepState => {
  if (store.completedSteps.includes(step)) return 'done'
  return store.step === step ? 'current' : 'pending'
}

const steps = computed(() =>
  PIPELINE_STEPS.map((step, index) => ({
    step,
    index,
    label: t(LABEL_KEY[step]),
    state: stateOf(step),
  })),
)
</script>

<template>
  <ol
    class="flex items-center gap-1.5 rounded-xl border border-[var(--console-border)] bg-[var(--console-surface)] px-2.5 py-3 sm:gap-2 sm:px-3.5"
  >
    <li
      v-for="item in steps"
      :key="item.step"
      class="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2"
      :aria-current="item.state === 'current' ? 'step' : undefined"
    >
      <span class="flex min-w-0 items-center gap-2">
        <span
          class="flex size-5 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] font-semibold transition-colors duration-150"
          :class="{
            'border-[var(--accent)] bg-[var(--accent)] text-[var(--console-bg)]':
              item.state === 'done',
            'border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] text-[var(--accent-soft)]':
              item.state === 'current',
            'border-[var(--console-border)] text-[var(--console-text-muted)]':
              item.state === 'pending',
          }"
        >
          <ElIcon v-if="item.state === 'done'" :size="11"><Check /></ElIcon>
          <template v-else>{{ item.index + 1 }}</template>
        </span>

        <span
          class="hidden truncate text-[11.5px] md:inline"
          :class="{
            'text-[var(--console-text)]': item.state === 'done',
            'font-medium text-[var(--accent-soft)]': item.state === 'current',
            'text-[var(--console-text-muted)]': item.state === 'pending',
          }"
        >
          {{ item.label }}
        </span>
      </span>

      <span
        v-if="item.index < steps.length - 1"
        class="h-px min-w-1.5 flex-1"
        :class="
          item.state === 'done'
            ? 'bg-[var(--accent)]'
            : 'bg-[var(--console-border)]'
        "
        aria-hidden="true"
      />
    </li>
  </ol>
</template>

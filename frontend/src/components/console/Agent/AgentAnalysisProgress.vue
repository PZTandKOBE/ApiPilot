<script setup lang="ts">
import { Check, Loading } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { ANALYSIS_STAGES, type AnalysisStage } from '@/types/agent'

/**
 * The observable agent, running.
 *
 * This is the whole "watch it work" surface: one line per stage, ticked as the
 * service reports completion. There is nothing here about *how* a stage
 * reaches its conclusion — the checklist is a progress indicator over work the
 * user will be able to inspect in full once it lands.
 *
 * Progress is the real `onProgress` stream from the agent service, not a timer
 * this component owns.
 */
const { t } = useI18n()
const store = useAgentStore()

const STAGE_KEY: Readonly<Record<AnalysisStage, string>> = {
  parsing: 'console.aiTest.stages.parsing',
  endpoints: 'console.aiTest.stages.endpoints',
  authentication: 'console.aiTest.stages.authentication',
  dependencies: 'console.aiTest.stages.dependencies',
  risks: 'console.aiTest.stages.risks',
}

const stages = computed(() =>
  ANALYSIS_STAGES.map((stage) => {
    const progress = store.progress
    const done = progress?.completed.includes(stage) ?? false

    return {
      stage,
      label: t(STAGE_KEY[stage]),
      done,
      active: !done && progress?.stage === stage,
    }
  }),
)
</script>

<template>
  <section class="console-panel p-4" role="status" aria-live="polite">
    <div class="flex items-center gap-2">
      <ElIcon :size="14" class="animate-spin text-[var(--accent)]"><Loading /></ElIcon>
      <h2 class="text-[13px] font-medium text-[var(--console-text)]">
        {{ t('console.aiTest.analyzing.title') }}
      </h2>
    </div>

    <p class="mt-1 text-[11.5px] text-[var(--console-text-muted)]">
      {{ t('console.aiTest.analyzing.subtitle') }}
    </p>

    <ul class="mt-3.5 flex flex-col gap-1.5">
      <li
        v-for="item in stages"
        :key="item.stage"
        class="flex items-center gap-2 text-[12px]"
        :class="{
          'text-[var(--console-text-dim)]': item.done,
          'text-[var(--accent-soft)]': item.active,
          'text-[var(--console-text-muted)]': !item.done && !item.active,
        }"
      >
        <ElIcon v-if="item.done" :size="13" class="text-[var(--status-pass)]">
          <Check />
        </ElIcon>
        <span
          v-else
          class="size-[13px] shrink-0 rounded-full border"
          :class="
            item.active
              ? 'border-[var(--accent)]'
              : 'border-[var(--console-border)]'
          "
        />
        {{ item.label }}
      </li>
    </ul>
  </section>
</template>

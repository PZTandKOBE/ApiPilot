<script setup lang="ts">
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed, nextTick, ref } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import AgentFindingCard from './AgentFindingCard.vue'
import AgentSpecSummary from './AgentSpecSummary.vue'
import ApiDependencyGraph from './ApiDependencyGraph.vue'
import ApiRiskList from './ApiRiskList.vue'
import ApiUnderstandingPanel from './ApiUnderstandingPanel.vue'

/**
 * Secondary, user-controlled navigation over the analysis result.
 *
 * The six-stage pipeline above the page is Agent state; this five-step strip is
 * only the reader's position inside the finished analysis.  It owns no server
 * state, calls no store action when a step changes, and leaves every existing
 * panel mounted so a switch cannot discard data or a local edit.
 */
type ReviewStep = 'spec' | 'understanding' | 'dependencies' | 'risks' | 'actions'

const STEPS: readonly ReviewStep[] = [
  'spec',
  'understanding',
  'dependencies',
  'risks',
  'actions',
]

const STEP_LABEL_KEY: Readonly<Record<ReviewStep, string>> = {
  spec: 'console.aiTest.review.steps.spec',
  understanding: 'console.aiTest.review.steps.understanding',
  dependencies: 'console.aiTest.review.steps.dependencies',
  risks: 'console.aiTest.review.steps.risks',
  actions: 'console.aiTest.review.steps.actions',
}

const emit = defineEmits<{
  readonly replace: []
  readonly continueToPlan: []
}>()

const { t } = useI18n()
const store = useAgentStore()

const currentIndex = ref(0)
const content = ref<HTMLElement | null>(null)

const currentStep = computed(() => STEPS[currentIndex.value] ?? 'spec')
const currentLabel = computed(() => t(STEP_LABEL_KEY[currentStep.value]))
const position = computed(
  () =>
    String(currentIndex.value + 1).padStart(2, '0') +
    ' / ' +
    String(STEPS.length).padStart(2, '0'),
)
const isFirst = computed(() => currentIndex.value === 0)
const isLast = computed(() => currentIndex.value === STEPS.length - 1)
const findings = computed(() => store.understanding?.findings ?? [])

const stepLabel = (step: ReviewStep): string => t(STEP_LABEL_KEY[step])

const afterStepChange = async (): Promise<void> => {
  await nextTick()

  const element = content.value
  if (element === null) return

  element.focus({ preventScroll: true })

  // Keep the reader's position when the panel is already on screen, but bring
  // it back when the previous panel was taller than the viewport. This scrolls
  // the panel, never the whole document to the top.
  if (typeof element.getBoundingClientRect !== 'function') return
  const rect = element.getBoundingClientRect()
  const outOfView = rect.top < 0 || rect.top > window.innerHeight - 120

  if (outOfView && typeof element.scrollIntoView === 'function') {
    element.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
}

const go = (index: number): void => {
  if (index < 0 || index >= STEPS.length || index === currentIndex.value) return

  currentIndex.value = index
  void afterStepChange()
}

const previous = (): void => go(currentIndex.value - 1)
const next = (): void => go(currentIndex.value + 1)
</script>

<template>
  <section
    class="analysis-review flex flex-col gap-3"
    data-testid="analysis-review"
    aria-labelledby="analysis-review-title"
  >
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="min-w-0">
        <p class="console-label">{{ t('console.aiTest.review.title') }}</p>
        <div class="mt-1 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <h2
            id="analysis-review-title"
            class="text-[14px] font-semibold text-[var(--console-text)]"
          >
            {{ currentLabel }}
          </h2>
          <span class="font-mono text-[11px] text-[var(--console-text-muted)]">
            {{ position }}
          </span>
        </div>
        <p class="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
          {{ t('console.aiTest.review.subtitle') }}
        </p>
      </div>
    </div>

    <p class="sr-only" aria-live="polite">
      {{ position }} — {{ currentLabel }}
    </p>

    <nav :aria-label="t('console.aiTest.review.navLabel')">
      <ol
        class="flex gap-1.5 overflow-x-auto rounded-xl border border-[var(--console-border)] bg-[var(--console-surface)] p-1.5"
      >
        <li
          v-for="(step, index) in STEPS"
          :key="step"
          class="min-w-[132px] flex-1"
        >
          <button
            type="button"
            data-testid="analysis-step"
            class="flex w-full min-w-0 items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            :class="
              index === currentIndex
                ? 'border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] text-[var(--accent-soft)]'
                : 'border-transparent text-[var(--console-text-muted)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]'
            "
            :aria-current="index === currentIndex ? 'step' : undefined"
            @click="go(index)"
          >
            <span class="shrink-0 font-mono text-[10px] opacity-80">
              {{ String(index + 1).padStart(2, '0') }}
            </span>
            <span class="truncate text-[11.5px] font-medium">
              {{ stepLabel(step) }}
            </span>
          </button>
        </li>
      </ol>
    </nav>

    <div
      ref="content"
      data-testid="analysis-review-panel"
      role="region"
      tabindex="-1"
      class="min-w-0 rounded-xl outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-soft)]"
      :aria-label="t('console.aiTest.review.title') + ': ' + currentLabel"
    >
      <div v-show="currentStep === 'spec'">
        <AgentSpecSummary
          v-if="store.currentSpec !== null"
          @replace="emit('replace')"
        />
        <p
          v-else
          class="console-panel px-4 py-6 text-center text-[12px] text-[var(--console-text-muted)]"
        >
          {{ t('console.aiTest.review.noSpec') }}
        </p>
      </div>

      <div v-show="currentStep === 'understanding'">
        <ApiUnderstandingPanel />
      </div>

      <div v-show="currentStep === 'dependencies'">
        <ApiDependencyGraph />
      </div>

      <div v-show="currentStep === 'risks'">
        <ApiRiskList />
      </div>

      <div v-show="currentStep === 'actions'">
        <section class="console-panel">
          <header
            class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
          >
            <h2 class="text-[13px] font-semibold text-[var(--console-text)]">
              {{ t('console.aiTest.findings.title') }}
            </h2>
            <span class="font-mono text-[11px] text-[var(--console-text-muted)]">
              {{ findings.length }}
            </span>
          </header>

          <p
            v-if="findings.length === 0"
            class="px-4 py-6 text-center text-[12px] text-[var(--console-text-muted)]"
          >
            {{ t('console.aiTest.findings.empty') }}
          </p>

          <ul v-else class="flex flex-col divide-y divide-[var(--console-border)]">
            <AgentFindingCard
              v-for="finding in findings"
              :key="finding.id"
              :finding="finding"
            />
          </ul>
        </section>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-3">
      <ElButton :disabled="isFirst" @click="previous">
        <ElIcon class="mr-1.5"><ArrowLeft /></ElIcon>
        {{ t('console.aiTest.review.previous') }}
      </ElButton>

      <div class="flex items-center gap-2">
        <ElButton v-if="!isLast" @click="next">
          {{ t('console.aiTest.review.next') }}
          <ElIcon class="ml-1.5"><ArrowRight /></ElIcon>
        </ElButton>

        <ElButton v-else type="primary" @click="emit('continueToPlan')">
          {{ t('console.aiTest.review.continueToPlan') }}
          <ElIcon class="ml-1.5"><ArrowRight /></ElIcon>
        </ElButton>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import RunErrorNote from '@/components/console/Run/RunErrorNote.vue'
import { useI18n } from '@/i18n'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { ApiError } from '@/services/http'
import { fetchReportPdf, generateReport } from '@/services/api/reports'
import { useRunsStore } from '@/stores/runs'
import type { RunDetail, RunStatus, RunStepStatus } from '@/types/run'
import type { RunReportSummary } from '@/types/report'
import { formatDate } from '@/utils/time'
import {
  buildRunReport,
  isReportableRun,
  reportFilename,
  type RunReport,
} from '@/utils/runReport'

/**
 * A printable report of one finished run.
 *
 * It reads the same server detail as the run page and never the current plan or
 * environment. The browser's print dialog is the PDF export: the page offers a
 * preview, and the button says so rather than pretending a file was downloaded.
 */
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const store = useRunsStore()
const route = useRoute()

const runId = computed<string | null>(() => {
  const value = route.params.runId
  return typeof value === 'string' && value !== '' ? value : null
})

const detail = computed<RunDetail | null>(() => {
  if (runId.value === null) return null
  return store.details.find((candidate) => candidate.run.id === runId.value) ?? null
})

const generatedAt = ref(new Date().toISOString())
const report = computed<RunReport | null>(() =>
  detail.value === null ? null : buildRunReport(detail.value, generatedAt.value),
)

const notFound = computed(
  () => runId.value === null || (detail.value === null && !store.loading),
)
const unavailable = computed(
  () => detail.value !== null && !isReportableRun(detail.value.run.status),
)
const canPrint = computed(
  () => report.value !== null && isReportableRun(report.value.status),
)

const projectId = computed<string>(() => {
  const value = route.params.projectId
  return typeof value === 'string' ? value : ''
})

const generating = ref(false)
const generateError = ref<string | null>(null)
const savedReport = ref<RunReportSummary | null>(null)

const reportErrorText = (thrown: unknown, fallback: string): string =>
  thrown instanceof ApiError && thrown.messageKey !== ''
    ? t(thrown.messageKey)
    : t(fallback)

const load = async (): Promise<void> => {
  if (runId.value === null) return

  await store.loadRun(runId.value)
  generatedAt.value = new Date().toISOString()

  // A report is a snapshot, not a live view. If the run is still in flight the
  // page shows why it cannot print yet; it must not keep an SSE stream open.
  if (detail.value !== null && !isReportableRun(detail.value.run.status)) {
    store.unsubscribe(runId.value)
  }
}

onMounted(() => {
  void load()
})

watch(runId, () => {
  generatedAt.value = new Date().toISOString()
  void load()
})

onUnmounted(() => {
  if (runId.value !== null) store.unsubscribe(runId.value)
})

const RUN_STATUS_KEYS: Readonly<Record<RunStatus, string>> = {
  queued: 'console.runs.status.queued',
  running: 'console.runs.status.running',
  passed: 'console.runs.status.passed',
  failed: 'console.runs.status.failed',
  cancelled: 'console.runs.status.cancelled',
}

const STEP_STATUS_KEYS: Readonly<Record<RunStepStatus, string>> = {
  pending: 'console.runs.stepStatus.pending',
  running: 'console.runs.stepStatus.running',
  passed: 'console.runs.stepStatus.passed',
  failed: 'console.runs.stepStatus.failed',
  skipped: 'console.runs.stepStatus.skipped',
}

const STEP_KIND_KEYS: Readonly<Record<string, string>> = {
  request: 'console.aiTest.step.request',
  extract: 'console.aiTest.step.extract',
  assert: 'console.aiTest.step.assert',
}

const runStatusLabel = (status: RunStatus): string => t(RUN_STATUS_KEYS[status])

const stepStatusLabel = (status: RunStepStatus): string => t(STEP_STATUS_KEYS[status])

const stepKindLabel = (kind: string): string =>
  t(STEP_KIND_KEYS[kind] ?? 'console.aiTest.step.request')

const durationOf = (millis: number | null): string => {
  if (millis === null) return '—'
  return millis < 1000
    ? String(Math.round(millis)) + ' ms'
    : (millis / 1000).toFixed(1) + ' s'
}

const dateOf = (value: string | null): string =>
  value === null ? '—' : formatDate(value, locale.value)

const generateAndSave = async (): Promise<void> => {
  const current = report.value
  if (current === null || !isReportableRun(current.status) || projectId.value === '') {
    return
  }

  generating.value = true
  generateError.value = null
  savedReport.value = null

  try {
    const saved = await generateReport(projectId.value, current.runId)
    savedReport.value = saved
    ElMessage.success(t('console.report.saved'))
  } catch (thrown) {
    generateError.value = reportErrorText(thrown, 'console.report.generateFailed')
  } finally {
    generating.value = false
  }
}

const openSaved = async (): Promise<void> => {
  const saved = savedReport.value
  if (saved === null) return

  try {
    const blob = await fetchReportPdf(projectId.value, saved.id)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (thrown) {
    generateError.value = reportErrorText(thrown, 'console.report.downloadFailed')
  }
}

const printReport = (): void => {
  const current = report.value
  if (
    current === null ||
    !isReportableRun(current.status) ||
    typeof window === 'undefined'
  ) {
    return
  }

  const previous = document.title
  document.title = reportFilename(current.runId)

  const restoreTitle = (): void => {
    document.title = previous
    window.removeEventListener('afterprint', restoreTitle)
  }

  window.addEventListener('afterprint', restoreTitle, { once: true })

  try {
    window.print()
  } finally {
    // Some browsers return before the dialog closes; keep the safe filename
    // long enough for the dialog to read it, then restore the page title.
    window.setTimeout(restoreTitle, 2000)
  }
}

const conclusionKey = (status: RunStatus): string =>
  status === 'passed'
    ? 'console.report.conclusionPassed'
    : status === 'failed'
      ? 'console.report.conclusionFailed'
      : 'console.report.conclusionCancelled'
</script>

<template>
  <div class="report-page">
    <div class="report-toolbar">
      <RouterLink
        :to="{
          name: 'console-project-run-detail',
          params: { projectId: route.params.projectId, runId },
        }"
        class="text-[12px] text-[var(--accent-soft)] hover:underline"
      >
        {{ t('console.report.back') }}
      </RouterLink>

      <div class="flex flex-wrap items-center gap-2">
        <p class="text-[11px] text-[var(--console-text-muted)]">
          {{ t('console.report.printHint') }}
        </p>
        <RouterLink
          :to="{ name: 'console-project-reports', params: { projectId } }"
          class="text-[11.5px] text-[var(--accent-soft)] hover:underline"
        >
          {{ t('console.report.centerTitle') }}
        </RouterLink>
        <ElButton
          type="primary"
          size="small"
          :loading="generating"
          :disabled="!canPrint || generating"
          @click="generateAndSave"
        >
          {{ generating ? t('console.report.generating') : t('console.report.generateAndSave') }}
        </ElButton>
        <ElButton size="small" :disabled="!canPrint" @click="printReport">
          {{ t('console.report.print') }}
        </ElButton>
      </div>
    </div>

    <p v-if="generateError !== null" class="mb-3 text-[12px] text-[var(--status-fail)]">
      {{ generateError }}
    </p>

    <div v-if="savedReport !== null" class="console-panel mb-3 flex flex-wrap items-center justify-between gap-3 p-3">
      <div>
        <p class="text-[12px] font-medium text-[var(--console-text)]">
          {{ t('console.report.saved') }}
        </p>
        <p class="mt-0.5 text-[11px] text-[var(--console-text-muted)]">
          {{ t('console.report.savedHint') }}
        </p>
      </div>
      <ElButton size="small" @click="openSaved">
        {{ t('console.report.openSaved') }}
      </ElButton>
    </div>

    <div v-if="notFound" class="console-panel">
      <ConsoleEmptyState
        :title="t('console.report.notFound')"
        :body="t('console.report.notFoundBody')"
      />
    </div>

    <div v-else-if="unavailable" class="console-panel">
      <ConsoleEmptyState
        :title="t('console.report.unavailable')"
        :body="t('console.report.unavailableBody')"
      />
    </div>

    <RunErrorNote
      v-if="store.error !== null"
      :error="store.error"
      @dismiss="store.clearError()"
    />

    <p v-if="report === null && !notFound && !unavailable" class="text-[12px] text-[var(--console-text-muted)]">
      {{ t('console.common.loading') }}
    </p>

    <article v-if="report !== null && !notFound && !unavailable" class="report-document">
      <header>
        <p class="report-kicker">ApiPilot</p>
        <h1 class="report-title">{{ t('console.report.title') }}</h1>
        <p class="report-generated">
          {{ t('console.report.subtitle') }} ·
          {{ t('console.report.generatedAt') }}:
          {{ formatDate(report.generatedAt, locale) }}
        </p>
      </header>

      <dl class="report-meta">
        <div>
          <dt class="report-meta__label">{{ t('console.report.runId') }}</dt>
          <dd class="report-meta__value">{{ report.runId }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.status') }}</dt>
          <dd class="report-meta__value">{{ runStatusLabel(report.status) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.project') }}</dt>
          <dd class="report-meta__value">{{ report.projectId }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.plan') }}</dt>
          <dd class="report-meta__value">{{ localize(report.planName) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.planId') }}</dt>
          <dd class="report-meta__value">{{ report.planId }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.environment') }}</dt>
          <dd class="report-meta__value">{{ report.environmentId }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.baseUrl') }}</dt>
          <dd class="report-meta__value">{{ report.baseUrl }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.createdAt') }}</dt>
          <dd class="report-meta__value">{{ dateOf(report.createdAt) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.startedAt') }}</dt>
          <dd class="report-meta__value">{{ dateOf(report.startedAt) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.finishedAt') }}</dt>
          <dd class="report-meta__value">{{ dateOf(report.finishedAt) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.report.duration') }}</dt>
          <dd class="report-meta__value">{{ durationOf(report.durationMs) }}</dd>
        </div>
        <div>
          <dt class="report-meta__label">{{ t('console.runs.variables') }}</dt>
          <dd class="report-meta__value">{{ report.variableCount }}</dd>
        </div>
      </dl>

      <section class="report-section">
        <h2>{{ t('console.report.summary') }}</h2>
        <div class="report-counts">
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.scenarios') }}</p>
            <p class="report-count__value">{{ report.summary.scenarios }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.steps') }}</p>
            <p class="report-count__value">{{ report.summary.steps }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.assertions') }}</p>
            <p class="report-count__value">{{ report.summary.assertions }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.passedSteps') }}</p>
            <p class="report-count__value">{{ report.summary.passedSteps }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.failedSteps') }}</p>
            <p class="report-count__value">{{ report.summary.failedSteps }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.skippedSteps') }}</p>
            <p class="report-count__value">{{ report.summary.skippedSteps }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.passedAssertions') }}</p>
            <p class="report-count__value">{{ report.summary.passedAssertions }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.failedAssertions') }}</p>
            <p class="report-count__value">{{ report.summary.failedAssertions }}</p>
          </div>
          <div class="report-count">
            <p class="report-count__label">{{ t('console.report.skippedAssertions') }}</p>
            <p class="report-count__value">{{ report.summary.skippedAssertions }}</p>
          </div>
        </div>
      </section>

      <section class="report-section">
        <h2>{{ t('console.report.conclusion') }}</h2>
        <p>{{ t(conclusionKey(report.status)) }}</p>
        <div v-if="report.failure !== null" class="report-failure">
          <strong>{{ t('console.report.error') }}:</strong>
          {{ localize(report.failure.message) }}
          <span v-if="report.failure.detail !== null"> — {{ report.failure.detail }}</span>
        </div>
      </section>

      <section class="report-section">
        <h2>{{ t('console.report.execution') }}</h2>

        <p v-if="report.scenarios.length === 0" class="report-empty">
          {{ t('console.report.noScenarios') }}
        </p>

        <div v-for="scenario in report.scenarios" :key="scenario.id" class="report-scenario">
          <h3>
            {{ scenario.index + 1 }}. {{ localize(scenario.name) }} —
            {{ stepStatusLabel(scenario.status) }}
          </h3>
          <p class="report-scenario__meta">
            {{ t('console.report.assertions') }}: {{ scenario.assertions.length }}
          </p>

          <table v-if="scenario.steps.length > 0" class="report-table">
            <thead>
              <tr>
                <th style="width: 7%">#</th>
                <th style="width: 10%">{{ t('console.report.type') }}</th>
                <th style="width: 35%">{{ t('console.report.description') }}</th>
                <th style="width: 18%">{{ t('console.report.http') }}</th>
                <th style="width: 15%">{{ t('console.report.status') }}</th>
                <th style="width: 15%">{{ t('console.report.duration') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="step in scenario.steps" :key="step.id">
                <td>{{ step.index + 1 }}</td>
                <td>{{ stepKindLabel(step.kind) }}</td>
                <td>
                  <div>{{ localize(step.description) }}</div>
                  <ul v-if="step.evidence.length > 0" class="report-evidence">
                    <li v-for="item in step.evidence" :key="item.value">
                      {{ localize(item.label) }}: {{ item.value }}
                    </li>
                  </ul>
                  <div v-if="step.failure !== null" class="report-failure">
                    {{ localize(step.failure.message) }}
                    <span v-if="step.failure.detail !== null"> — {{ step.failure.detail }}</span>
                  </div>
                </td>
                <td>
                  <span v-if="step.method !== null">{{ step.method }}</span>
                  <span v-if="step.path !== null"> {{ step.path }}</span>
                  <span v-if="step.method === null && step.path === null">—</span>
                </td>
                <td>{{ stepStatusLabel(step.status) }}</td>
                <td>{{ durationOf(step.durationMs) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="report-empty">{{ t('console.report.noEvidence') }}</p>

          <p v-if="scenario.assertions.length === 0" class="report-empty">
            {{ t('console.report.noAssertions') }}
          </p>
          <table v-else class="report-table">
            <thead>
              <tr>
                <th style="width: 35%">{{ t('console.report.assertion') }}</th>
                <th style="width: 20%">{{ t('console.report.target') }}</th>
                <th style="width: 15%">{{ t('console.report.expected') }}</th>
                <th style="width: 15%">{{ t('console.report.actual') }}</th>
                <th style="width: 15%">{{ t('console.report.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="assertion in scenario.assertions" :key="assertion.id">
                <td>{{ localize(assertion.description) }}</td>
                <td>{{ assertion.target }}</td>
                <td>{{ assertion.expected }}</td>
                <td>
                  {{ assertion.actual === null ? t('console.report.noActual') : assertion.actual }}
                </td>
                <td>{{ stepStatusLabel(assertion.status) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="report-section">
        <h2>{{ t('console.report.limitations') }}</h2>
        <p>{{ t('console.report.limitationsBody') }}</p>
        <p class="report-empty">{{ t('console.report.generatedFromRun') }}</p>
      </section>

      <footer class="report-footnote">
        ApiPilot · {{ t('console.report.runId') }}: {{ report.runId }} ·
        {{ t('console.report.generatedAt') }}: {{ formatDate(report.generatedAt, locale) }}
        <span class="block">{{ t('console.report.pageNumbersHint') }}</span>
      </footer>
    </article>
  </div>
</template>

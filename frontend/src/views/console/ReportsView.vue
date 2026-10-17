<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import RunStatusTag from '@/components/console/Run/RunStatusTag.vue'
import { useI18n } from '@/i18n'
import { ApiError } from '@/services/http'
import {
  downloadReportPdf,
  fetchReportPdf,
} from '@/services/api/reports'
import { useReportsStore } from '@/stores/reports'
import type { RunReportSummary } from '@/types/report'
import { formatDate } from '@/utils/time'

/**
 * The project's saved report shelf.
 *
 * Every row comes from the server report table, never from a Run list or local
 * storage. Opening and downloading use the authenticated binary endpoint; the
 * browser's PDF viewer supplies the final print action.
 */
const { t, locale } = useI18n()
const route = useRoute()
const store = useReportsStore()

const reports = computed<readonly RunReportSummary[]>(() => store.reports)
const error = ref<string | null>(null)
const busyId = ref<string | null>(null)

const displayError = computed<string | null>(() =>
  error.value ?? (store.error === null ? null : t(store.error)),
)

const projectId = (): string => {
  const value = route.params.projectId
  return typeof value === 'string' ? value : ''
}

const errorText = (thrown: unknown, fallback: string): string =>
  thrown instanceof ApiError && thrown.messageKey !== ''
    ? t(thrown.messageKey)
    : t(fallback)

const load = async (): Promise<void> => {
  if (projectId() === '') return
  error.value = null
  await store.load(projectId())
}

onMounted(() => {
  void load()
})

watch(
  () => projectId(),
  () => {
    void load()
  },
)

const openPdf = async (report: RunReportSummary): Promise<void> => {
  if (busyId.value !== null) return
  busyId.value = report.id
  error.value = null
  try {
    const blob = await fetchReportPdf(projectId(), report.id)
    const url = URL.createObjectURL(blob)
    const opened = window.open(url, '_blank', 'noopener,noreferrer')
    // The tab owns the URL while the PDF viewer is open. Revoke later rather
    // than at once, which would close the document underneath the viewer.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    if (opened === null) {
      window.location.assign(url)
    }
  } catch (thrown) {
    error.value = errorText(thrown, 'console.report.loadFailed')
  } finally {
    busyId.value = null
  }
}

const download = async (report: RunReportSummary): Promise<void> => {
  if (busyId.value !== null) return
  busyId.value = report.id
  error.value = null
  try {
    const blob = await downloadReportPdf(projectId(), report.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = report.filename
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (thrown) {
    error.value = errorText(thrown, 'console.report.downloadFailed')
  } finally {
    busyId.value = null
  }
}

const printPdf = async (report: RunReportSummary): Promise<void> => {
  await openPdf(report)
  ElMessage.info(t('console.report.printHint'))
}
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      :title="t('console.report.centerTitle')"
      :subtitle="t('console.report.centerSubtitle')"
    />

    <p v-if="displayError !== null" class="mb-3 text-[12px] text-[var(--status-fail)]">
      {{ displayError }}
    </p>

    <p v-if="store.loading" class="text-[12px] text-[var(--console-text-muted)]">
      {{ t('console.common.loading') }}
    </p>

    <div v-else-if="reports.length === 0" class="console-panel">
      <ConsoleEmptyState
        :title="t('console.report.noReports')"
        :body="t('console.report.noReportsHint')"
      />
    </div>

    <div v-else class="console-panel overflow-hidden">
      <table class="w-full table-fixed border-collapse text-left text-[12px]">
        <thead class="bg-[var(--console-surface-hover)] text-[var(--console-text-muted)]">
          <tr>
            <th class="w-[28%] px-3 py-2 font-medium">{{ t('console.report.reportName') }}</th>
            <th class="w-[26%] px-3 py-2 font-medium">{{ t('console.report.runId') }}</th>
            <th class="w-[14%] px-3 py-2 font-medium">{{ t('console.report.runStatus') }}</th>
            <th class="w-[18%] px-3 py-2 font-medium">{{ t('console.report.generatedAt') }}</th>
            <th class="w-[14%] px-3 py-2 font-medium text-end">{{ t('console.report.openReport') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="report in reports"
            :key="report.id"
            class="border-t border-[var(--console-border)] align-top"
          >
            <td class="px-3 py-3">
              <p class="truncate font-medium text-[var(--console-text)]">{{ report.name }}</p>
              <p class="mt-0.5 truncate font-mono text-[10.5px] text-[var(--console-text-muted)]">
                {{ report.filename }} · {{ report.byteSize }} B
              </p>
            </td>
            <td class="px-3 py-3 font-mono text-[11px] text-[var(--console-text-dim)]">
              {{ report.runId }}
            </td>
            <td class="px-3 py-3">
              <RunStatusTag :status="report.runStatus" />
            </td>
            <td class="px-3 py-3 text-[var(--console-text-dim)]">
              {{ formatDate(report.generatedAt, locale) }}
            </td>
            <td class="px-3 py-3">
              <div class="flex flex-wrap justify-end gap-1.5">
                <ElButton
                  size="small"
                  :loading="busyId === report.id"
                  :disabled="busyId !== null && busyId !== report.id"
                  @click="openPdf(report)"
                >
                  {{ t('console.report.openReport') }}
                </ElButton>
                <ElButton
                  size="small"
                  :disabled="busyId !== null"
                  @click="download(report)"
                >
                  {{ t('console.report.download') }}
                </ElButton>
                <ElButton
                  size="small"
                  :disabled="busyId !== null"
                  @click="printPdf(report)"
                >
                  {{ t('console.report.print') }}
                </ElButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

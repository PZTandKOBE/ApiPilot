import { defineStore } from 'pinia'
import { ref } from 'vue'

import { listReports } from '@/services/api/reports'
import type { RunReportSummary } from '@/types/report'

export const useReportsStore = defineStore('reports', () => {
  const reports = ref<readonly RunReportSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const load = async (projectId: string): Promise<void> => {
    if (projectId === '' || loading.value) return
    loading.value = true
    error.value = null

    try {
      reports.value = await listReports(projectId)
    } catch {
      error.value = 'console.report.loadFailed'
    } finally {
      loading.value = false
    }
  }

  return { reports, loading, error, load }
})

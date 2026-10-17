import { request, requestBlob } from '@/services/http'
import type { RunReportSummary } from '@/types/report'

const reportsPath = (projectId: string): string =>
  '/api/projects/' + encodeURIComponent(projectId) + '/reports'

const reportPath = (projectId: string, reportId: string): string =>
  reportsPath(projectId) + '/' + encodeURIComponent(reportId)

const isReport = (value: unknown): value is RunReportSummary => {
  if (typeof value !== 'object' || value === null) return false
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'string' &&
    typeof item.projectId === 'string' &&
    typeof item.runId === 'string' &&
    typeof item.name === 'string' &&
    typeof item.filename === 'string' &&
    typeof item.generatedAt === 'string' &&
    typeof item.runStatus === 'string'
  )
}

export const listReports = async (projectId: string): Promise<readonly RunReportSummary[]> => {
  const body = await request<readonly unknown[]>(reportsPath(projectId))
  if (!Array.isArray(body) || !body.every(isReport)) {
    throw new Error('the report list did not have the expected shape')
  }
  return body
}

export const generateReport = async (
  projectId: string,
  runId: string,
): Promise<RunReportSummary> => {
  const body = await request<unknown>(
    '/api/projects/' +
      encodeURIComponent(projectId) +
      '/runs/' +
      encodeURIComponent(runId) +
      '/reports',
    { method: 'POST' },
  )
  if (!isReport(body)) throw new Error('the saved report did not have the expected shape')
  return body
}

export const fetchReportPdf = async (
  projectId: string,
  reportId: string,
): Promise<Blob> => requestBlob(reportPath(projectId, reportId) + '/file')

export const downloadReportPdf = async (
  projectId: string,
  reportId: string,
): Promise<Blob> => requestBlob(reportPath(projectId, reportId) + '/download')

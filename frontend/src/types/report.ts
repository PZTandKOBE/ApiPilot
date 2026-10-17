import type { RunStatus } from '@/types/run'

/** One saved report as the report center reads it. */
export interface RunReportSummary {
  readonly id: string
  readonly projectId: string
  readonly runId: string
  readonly name: string
  readonly filename: string
  readonly contentType: string
  readonly byteSize: number
  readonly sha256: string
  readonly generatedAt: string
  readonly runStatus: RunStatus
}

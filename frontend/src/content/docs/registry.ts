import type { AppLocale } from '@/i18n/types'
import type { DocEntry, DocGroup, SearchResult } from './types'

import overviewZh from './zh-CN/overview.md?raw'
import quickstartZh from './zh-CN/quickstart.md?raw'
import selfHostingZh from './zh-CN/self-hosting.md?raw'
import configurationZh from './zh-CN/configuration.md?raw'
import projectsZh from './zh-CN/projects-and-specs.md?raw'
import aiLabZh from './zh-CN/ai-test-lab.md?raw'
import plansZh from './zh-CN/plans-and-approval.md?raw'
import runTestsZh from './zh-CN/run-tests.md?raw'
import runHistoryZh from './zh-CN/run-history.md?raw'
import reportsZh from './zh-CN/pdf-reports.md?raw'
import troubleshootingZh from './zh-CN/troubleshooting.md?raw'
import securityZh from './zh-CN/security-and-privacy.md?raw'
import faqZh from './zh-CN/faq.md?raw'

import overviewEn from './en-US/overview.md?raw'
import quickstartEn from './en-US/quickstart.md?raw'
import selfHostingEn from './en-US/self-hosting.md?raw'
import configurationEn from './en-US/configuration.md?raw'
import projectsEn from './en-US/projects-and-specs.md?raw'
import aiLabEn from './en-US/ai-test-lab.md?raw'
import plansEn from './en-US/plans-and-approval.md?raw'
import runTestsEn from './en-US/run-tests.md?raw'
import runHistoryEn from './en-US/run-history.md?raw'
import reportsEn from './en-US/pdf-reports.md?raw'
import troubleshootingEn from './en-US/troubleshooting.md?raw'
import securityEn from './en-US/security-and-privacy.md?raw'
import faqEn from './en-US/faq.md?raw'

export const DOC_GROUPS: readonly DocGroup[] = [
  { id: 'start' },
  { id: 'use' },
  { id: 'reference' },
]

export const DOCS: readonly DocEntry[] = [
  {
    slug: 'overview',
    group: 'start',
    title: { 'zh-CN': 'ApiPilot 概览', 'en-US': 'Overview' },
    summary: {
      'zh-CN': 'ApiPilot 是什么、适合做什么，以及 Try Us 与 Learn Us 的区别。',
      'en-US': 'What ApiPilot does, who it is for, and how Try Us differs from Learn Us.',
    },
    body: { 'zh-CN': overviewZh, 'en-US': overviewEn },
  },
  {
    slug: 'quickstart',
    group: 'start',
    title: { 'zh-CN': '快速开始', 'en-US': 'Quickstart' },
    summary: {
      'zh-CN': '从本地启动到跑通第一个 API 测试的最短路径。',
      'en-US': 'The shortest path from a local checkout to your first API test.',
    },
    body: { 'zh-CN': quickstartZh, 'en-US': quickstartEn },
  },
  {
    slug: 'self-hosting',
    group: 'start',
    title: { 'zh-CN': '本地部署', 'en-US': 'Self-hosting' },
    summary: {
      'zh-CN': '安装依赖、配置 PostgreSQL、执行 migration 并启动前后端。',
      'en-US': 'Install dependencies, configure PostgreSQL, migrate, and run both apps.',
    },
    body: { 'zh-CN': selfHostingZh, 'en-US': selfHostingEn },
  },
  {
    slug: 'configuration',
    group: 'start',
    title: { 'zh-CN': '配置', 'en-US': 'Configuration' },
    summary: {
      'zh-CN': '数据库、模型供应商、前端 API 地址和确定性运行模式。',
      'en-US': 'Database, model provider, frontend API address, and deterministic mode.',
    },
    body: { 'zh-CN': configurationZh, 'en-US': configurationEn },
  },
  {
    slug: 'projects-and-specs',
    group: 'use',
    title: { 'zh-CN': '项目与 API 规格', 'en-US': 'Projects and API specs' },
    summary: {
      'zh-CN': '创建项目、导入 OpenAPI 规格，并进入 AI Test Lab。',
      'en-US': 'Create a project, import an OpenAPI spec, and open the AI Test Lab.',
    },
    body: { 'zh-CN': projectsZh, 'en-US': projectsEn },
  },
  {
    slug: 'ai-test-lab',
    group: 'use',
    title: { 'zh-CN': 'AI Test Lab', 'en-US': 'AI Test Lab' },
    summary: {
      'zh-CN': '分析规格、查看理解结果，并生成候选测试计划。',
      'en-US': 'Analyze a spec, inspect the understanding, and generate a candidate plan.',
    },
    body: { 'zh-CN': aiLabZh, 'en-US': aiLabEn },
  },
  {
    slug: 'plans-and-approval',
    group: 'use',
    title: { 'zh-CN': '计划与审批', 'en-US': 'Plans and approval' },
    summary: {
      'zh-CN': '检查计划、批准或拒绝，以及计划版本和重新生成语义。',
      'en-US': 'Review, approve or reject, and understand plan versions and regeneration.',
    },
    body: { 'zh-CN': plansZh, 'en-US': plansEn },
  },
  {
    slug: 'run-tests',
    group: 'use',
    title: { 'zh-CN': '运行测试', 'en-US': 'Run tests' },
    summary: {
      'zh-CN': '执行已批准计划，观察步骤、断言、Extract 和运行状态。',
      'en-US': 'Execute an approved plan and follow steps, assertions, extracts, and status.',
    },
    body: { 'zh-CN': runTestsZh, 'en-US': runTestsEn },
  },
  {
    slug: 'run-history',
    group: 'use',
    title: { 'zh-CN': '运行历史', 'en-US': 'Run history' },
    summary: {
      'zh-CN': '按项目查看历史 Run，定位失败步骤和已保存的证据。',
      'en-US': 'Browse a project’s past runs and locate failed steps and saved evidence.',
    },
    body: { 'zh-CN': runHistoryZh, 'en-US': runHistoryEn },
  },
  {
    slug: 'pdf-reports',
    group: 'use',
    title: { 'zh-CN': 'PDF 测试报告', 'en-US': 'PDF reports' },
    summary: {
      'zh-CN': '从终态 Run 生成真实 PDF，在报告中心查看、下载和打印。',
      'en-US': 'Generate a real PDF from a terminal run, then view, download, or print it.',
    },
    body: { 'zh-CN': reportsZh, 'en-US': reportsEn },
  },
  {
    slug: 'troubleshooting',
    group: 'reference',
    title: { 'zh-CN': '故障排查', 'en-US': 'Troubleshooting' },
    summary: {
      'zh-CN': '启动、数据库 migration、模型调用、计划生成、Run 和 PDF 的常见问题。',
      'en-US': 'Common issues with startup, migrations, models, plans, runs, and PDFs.',
    },
    body: { 'zh-CN': troubleshootingZh, 'en-US': troubleshootingEn },
  },
  {
    slug: 'security-and-privacy',
    group: 'reference',
    title: { 'zh-CN': '安全与隐私', 'en-US': 'Security and privacy' },
    summary: {
      'zh-CN': '秘密配置、报告脱敏、项目隔离，以及报告实际包含的数据。',
      'en-US': 'Secret handling, report redaction, project isolation, and report data.',
    },
    body: { 'zh-CN': securityZh, 'en-US': securityEn },
  },
  {
    slug: 'faq',
    group: 'reference',
    title: { 'zh-CN': '常见问题', 'en-US': 'FAQ' },
    summary: {
      'zh-CN': '当前能力边界、已知限制，以及尚未开发的工作流模块。',
      'en-US': 'Current limits, known gaps, and the unbuilt workflow module.',
    },
    body: { 'zh-CN': faqZh, 'en-US': faqEn },
  },
]

export const DEFAULT_DOC_SLUG = 'overview'

export const findDoc = (slug: string): DocEntry | undefined =>
  DOCS.find((doc) => doc.slug === slug)

export const docsForGroup = (group: DocGroup['id']): readonly DocEntry[] =>
  DOCS.filter((doc) => doc.group === group)

export const neighborDocs = (doc: DocEntry): { previous?: DocEntry; next?: DocEntry } => {
  const index = DOCS.findIndex((item) => item.slug === doc.slug)
  return {
    previous: index > 0 ? DOCS[index - 1] : undefined,
    next: index >= 0 && index < DOCS.length - 1 ? DOCS[index + 1] : undefined,
  }
}

const normalized = (value: string): string => value.toLocaleLowerCase().normalize('NFKC')

export const searchDocs = (locale: AppLocale, query: string): readonly SearchResult[] => {
  const needle = normalized(query.trim())
  if (needle === '') return []

  return DOCS.filter((doc) => {
    const haystack = normalized(
      doc.title[locale] + ' ' + doc.summary[locale] + ' ' + doc.body[locale],
    )
    return haystack.includes(needle)
  })
    .slice(0, 12)
    .map((doc) => ({
      doc,
      title: doc.title[locale],
      summary: doc.summary[locale],
    }))
}

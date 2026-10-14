import type { MessageSchema } from '@/i18n/types'
import { consoleZhCN } from './console/zh-CN'

export const zhCN = {
  console: consoleZhCN,
  nav: {
    github: 'GitHub',
    language: '语言',
    home: '首页',
  },
  hero: {
    titleLines: ['AI API', 'TESTING AGENT'],
    subtitleLine1: '让 Agent 真正理解你的 API，',
    subtitleLine2: '从测试计划到自动执行。',
    tryUs: 'TRY US',
    learnUs: 'LEARN US',
    badge: '开源 · Agentic API 测试平台',
    ctaHint: '无需注册即可了解测试计划流程',
  },
  showcase: {
    eyebrow: '如何工作',
    title: '从 API 文档到一次可验证的测试执行。',
    description:
      'Agent 阅读你的 API，推断接口之间的依赖关系，生成测试计划，等待你批准，然后执行并收集证据。',
    cardLabel: '预览',
    steps: ['理解', '发现', '计划', '批准', '执行', '验证'],
  },
  apiTesting: {
    kicker: 'API 客户端',
    method: 'POST',
    path: '/api/orders',
    headers: '请求头',
    authKey: 'Authorization',
    authValue: 'Bearer ••••••••',
    contentTypeKey: 'Content-Type',
    contentTypeValue: 'application/json',
    body: '请求体',
    send: '发送',
    timeLabel: '耗时',
    timeValue: '142 ms',
    responseTitle: '响应',
    responseStatusValue: '201 Created',
  },
  plan: {
    kicker: 'AI 测试计划',
    generatedBy: '由 Agent 生成',
    cases: ['身份认证', '创建订单', '查询订单', '非法参数', '权限校验'],
    riskLabel: '风险等级',
    riskValue: '中',
    countLabel: '测试用例',
    countValue: '12',
    reject: '驳回',
    approve: '批准',
    note: '未经你的批准，Agent 不会执行任何测试。',
  },
  workflow: {
    kicker: 'AGENT 工作流',
    /** `步骤名 [变量]` — 方括号内为该步骤产出的变量。 */
    nodes: [
      '登录',
      '提取 Token [token]',
      '创建订单',
      '提取 order_id [order_id]',
      '查询订单',
      '断言 [pass]',
    ],
    /** 每个步骤传递给下一步的值。 */
    edges: ['token', 'Bearer', 'order_id', '200 OK'],
    passed: '通过',
    evidence: '证据',
    evidenceValue: '4 个产物',
  },
} satisfies MessageSchema

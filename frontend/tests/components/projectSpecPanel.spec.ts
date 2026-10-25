import { renderToString } from 'vue/server-renderer'
import { createSSRApp, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ProjectSpecPanel from '@/components/console/ProjectSpecPanel.vue'
import { useLocaleStore } from '@/stores/locale'
import type { ProjectSpecSummary } from '@/types/project'

const spec: ProjectSpecSummary = {
  id: 'spec_orders_1234',
  name: 'Orders API',
  filename: 'orders-openapi.json',
  specType: 'openapi-3',
  contentFormat: 'json',
  version: '1.0.0',
  source: 'upload',
  endpointCount: 12,
  createdAt: '2026-10-20T12:00:00.000Z',
  updatedAt: '2026-10-21T12:00:00.000Z',
}

const render = async (props: {
  spec: ProjectSpecSummary | null
  loading: boolean
  error: boolean
}): Promise<string> => {
  const app = createSSRApp({ render: () => h(ProjectSpecPanel, props) })
  return renderToString(app)
}

const textOf = (html: string): string =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('ProjectSpecPanel', () => {
  it('shows the real spec summary when one exists', async () => {
    const html = await render({ spec, loading: false, error: false })
    const text = textOf(html)

    expect(text).toContain('Orders API')
    expect(text).toContain('orders-openapi.json')
    expect(text).toContain('OpenAPI 3 · JSON')
    expect(text).toContain('接口数量')
    expect(text).toContain('12')
  })

  it('shows a successful empty state only after loading completes', async () => {
    const html = await render({ spec: null, loading: false, error: false })

    expect(textOf(html)).toContain('尚未上传 OpenAPI 文档')
    expect(textOf(html)).toContain('生成测试计划')
  })

  it('shows an explicit request failure with retry', async () => {
    const html = await render({ spec: null, loading: false, error: true })

    expect(textOf(html)).toContain('API 规范加载失败')
    expect(textOf(html)).toContain('重试')
    expect(textOf(html)).not.toContain('尚未上传 OpenAPI 文档')
  })

  it('shows loading rather than an empty state while the request runs', async () => {
    const html = await render({ spec: null, loading: true, error: false })

    expect(html).toContain('aria-label="加载中"')
    expect(textOf(html)).not.toContain('尚未上传 OpenAPI 文档')
  })
})

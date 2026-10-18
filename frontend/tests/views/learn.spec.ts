import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useLocaleStore } from '@/stores/locale'
import LearnView from '@/views/LearnView.vue'

const createTestRouter = async (path: string): Promise<Router> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: {} },
      { path: '/console', name: 'console-dashboard', component: {} },
      { path: '/learn', name: 'learn', component: {} },
      { path: '/learn/:slug', name: 'learn-doc', component: {} },
    ],
  })
  await router.push(path)
  await router.isReady()
  return router
}

const render = async (path: string): Promise<string> => {
  const router = await createTestRouter(path)
  const app = createSSRApp(LearnView)
  app.use(router)
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
})

describe('Learn Us portal', () => {
  it('renders the real quickstart content, navigation, TOC, and Try Us link', async () => {
    const html = await render('/learn/quickstart')
    const text = textOf(html)

    expect(text).toContain('Quickstart')
    expect(text).toContain('Install, migrate, and start the backend')
    expect(text).toContain('Get started')
    expect(text).toContain('On this page')
    expect(text).toContain('Try Us')
    expect(html).toContain('href="/console"')
    expect(html).toContain('href="#1-prepare"')
    expect(html).toContain('data-theme="dark"')
    expect(html).toContain('data-copy-code')
    expect(html).toContain('href="/learn/projects-and-specs"')
  })

  it('switches article content and navigation labels to Chinese', async () => {
    useLocaleStore().setLocale('zh-CN')
    const html = await render('/learn/quickstart')
    const text = textOf(html)

    expect(text).toContain('快速开始')
    expect(text).toContain('安装、迁移并启动后端')
    expect(text).toContain('开始使用')
    expect(text).toContain('本页目录')
  })

  it('renders a not-found state for an unknown documentation slug', async () => {
    const html = await render('/learn/not-a-real-doc')
    const text = textOf(html)

    expect(text).toContain('Document not found')
    expect(text).toContain('Back to documentation')
    expect(html).toContain('href="/learn/overview"')
  })

  it('keeps docs links and the product entry inside the router', async () => {
    const html = await render('/learn/pdf-reports')
    const text = textOf(html)

    expect(text).toContain('PDF reports')
    expect(html).toContain('href="/learn/security-and-privacy"')
    expect(html).toContain('href="/learn/troubleshooting"')
    expect(html).toContain('href="/console"')
  })
})

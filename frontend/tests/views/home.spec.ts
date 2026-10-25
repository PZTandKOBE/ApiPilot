/// <reference types="node" />

import { readFileSync } from 'node:fs'

import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import HomeHero from '@/components/home/HomeHero.vue'
import ProductShowcase from '@/components/home/ProductShowcase.vue'
import { useLocaleStore } from '@/stores/locale'

/**
 * Landing-page copy and its readable hierarchy.
 *
 * These assertions are intentionally about the rendered strings, not about a
 * screenshot: the owner asked for concrete copy and a less mechanical label
 * treatment, and both are observable in the DOM. The large display lettering
 * is untouched, so it is not asserted here.
 */
const createTestRouter = async (): Promise<Router> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: {} },
      { path: '/learn', name: 'learn', component: {} },
    ],
  })
  await router.push('/')
  await router.isReady()
  return router
}

const render = async (component: unknown): Promise<string> => {
  const app = createSSRApp(component as never)
  app.use(await createTestRouter())
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

const has = (html: string, needle: string): boolean => textOf(html).includes(needle)

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('landing-page copy', () => {
  it('gives the hero a readable value proposition without duplicated process copy', async () => {
    const html = await render(HomeHero)
    const text = textOf(html)

    expect(has(html, '让 AI 帮你规划 API 测试')).toBe(true)
    expect(has(html, '计划先由你确认，再执行测试')).toBe(true)
    expect(has(html, '开源 · Agent 驱动的 API 测试平台')).toBe(true)
    for (const step of ['导入文档', '梳理依赖', '生成计划', '批准计划', '执行测试', '查看结果']) {
      expect(has(html, step)).toBe(true)
    }
    expect(has(html, '无需注册即可了解测试计划流程')).toBe(true)
    expect(has(html, '让 Agent 真正理解你的 API')).toBe(false)
    expect(text).not.toContain('。')
    // The process caption is an ordered list, not a decorative ul of labels.
    expect(html).toContain('<ol')
    expect(html).not.toContain('mockup-label')
  })

  it('states the document-to-plan workflow on the right without trailing periods', async () => {
    const html = await render(ProductShowcase)

    expect(has(html, '从 API 文档生成可执行的测试计划')).toBe(true)
    expect(has(html, '从 API 文档生成可执行的测试计划。')).toBe(false)
    expect(has(html, '导入 OpenAPI 文档后')).toBe(true)
    expect(
      has(
        html,
        '导入 OpenAPI 文档后，Agent 会梳理接口依赖、补全请求与断言，生成可审核的测试计划，等你批准后再执行并保留结果与证据',
      ),
    ).toBe(true)
    expect(has(html, '从 API 文档到一次可验证的测试执行')).toBe(false)
  })

  it('pins the viewport-accounting and heading-width fixes', () => {
    const css = readSource('../../src/styles/home.css')
    const hero = readSource('../../src/components/home/HomeHero.vue')

    // The navbar is outside the hero stage, so a full 100svh here would add
    // another 72px of document height and force an unnecessary scrollbar.
    expect(css).toContain('--home-nav-h: 72px')
    expect(css).toContain('min-height: calc(100svh - var(--home-nav-h))')
    expect(css).not.toContain('min-height: 100svh;')

    // The heading max-width must be measured against its own readable column,
    // not against a 16px paragraph's "36ch" zero glyph.
    expect(hero).toContain('max-w-[34rem]')
    expect(hero).not.toContain('max-w-[36ch]')
  })
})

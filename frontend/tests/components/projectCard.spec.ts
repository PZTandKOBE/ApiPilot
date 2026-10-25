/// <reference types="node" />

import { renderToString } from 'vue/server-renderer'
import { createSSRApp, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import ProjectCard from '@/components/console/ProjectCard.vue'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures } from '../support/projects'

/**
 * The project card's relative timestamp.
 *
 * The formatter has threshold tests of its own; this pins the actual card
 * composition (the updated-at sentence, the just-now sentence and the locale).
 * SSR gets a snapshot clock from useNow, so the asserted moment is controlled.
 */
const createTestRouter = async (): Promise<Router> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/console/projects/:projectId/overview',
        name: 'console-project-overview',
        component: {},
      },
    ],
  })
  await router.push('/console/projects/' + FIRST_PROJECT_FIXTURE.id + '/overview')
  await router.isReady()
  return router
}

const render = async (project: Project): Promise<string> => {
  const router = await createTestRouter()
  const app = createSSRApp({ render: () => h(ProjectCard, { project }) })
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

const projectAt = (updatedAt: string): Project => ({
  ...FIRST_PROJECT_FIXTURE,
  updatedAt,
})

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-21T12:00:00.000Z'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('project card updated time', () => {
  it('renders just now, minutes, hours and days in Chinese', async () => {
    const cases = [
      ['2026-10-21T11:59:30.000Z', '更新于 刚刚'],
      ['2026-10-21T11:48:00.000Z', '更新于 12分钟前'],
      ['2026-10-21T11:00:00.000Z', '更新于 1小时前'],
      ['2026-10-19T12:00:00.000Z', '更新于 2天前'],
    ] as const

    for (const [updatedAt, expected] of cases) {
      const html = await render(projectAt(updatedAt))
      expect(textOf(html)).toContain(expected)
      expect(html).toContain('aria-label="删除项目"')
    }
  })

  it('renders natural English relative time', async () => {
    useLocaleStore().setLocale('en-US')
    const html = await render(projectAt('2026-10-21T11:00:00.000Z'))

    expect(textOf(html)).toContain('Updated 1 hour ago')
  })

  it('shows an unknown fallback for an invalid timestamp', async () => {
    const html = await render(projectAt('not-a-date'))

    expect(textOf(html)).toContain('更新于 未知')
  })
})

// @vitest-environment happy-dom
import { createApp, h, nextTick, ref, type App } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import ProjectDeleteDialog from '@/components/console/ProjectDeleteDialog.vue'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures } from '../support/projects'

let app: App | null = null
let container: HTMLDivElement | null = null
let router: Router
let visible = ref(true)
const project: Project = FIRST_PROJECT_FIXTURE
let deleted = vi.fn()

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const mount = async (): Promise<void> => {
  visible = ref(true)
  container = document.createElement('div')
  document.body.appendChild(container)

  app = createApp({
    render: () =>
      h(ProjectDeleteDialog, {
        modelValue: visible.value,
        'onUpdate:modelValue': (value: boolean) => {
          visible.value = value
        },
        project,
        onDeleted: deleted,
      }),
  })
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 5000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
}

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

const nameInput = (): HTMLInputElement | null =>
  document.querySelector('input[placeholder="' + project.name + '"]')

const typeName = async (value: string): Promise<void> => {
  const input = nameInput() as HTMLInputElement
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
}

beforeEach(async () => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects', name: 'console-projects', component: {} },
      {
        path: '/console/projects/:projectId/overview',
        name: 'console-project-overview',
        component: {},
      },
    ],
  })
  await router.push('/console/projects')
  await router.isReady()
  deleted = vi.fn()
})

afterEach(() => {
  app?.unmount()
  app = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('ProjectDeleteDialog', () => {
  it('shows the project name and requires the exact name before enabling deletion', async () => {
    await mount()
    const text = document.body.textContent ?? ''
    const confirm = buttonByText('永久删除项目')

    expect(text).toContain(project.name)
    expect(text).toContain('无法撤销')
    expect(confirm?.disabled).toBe(true)

    await typeName('wrong name')
    expect(buttonByText('永久删除项目')?.disabled).toBe(true)
    expect(document.body.textContent).toContain('项目名称不匹配')

    await typeName(project.name)
    expect(buttonByText('永久删除项目')?.disabled).toBe(false)
  })

  it('cancels without calling the store', async () => {
    const store = useProjectStore()
    const remove = vi.spyOn(store, 'deleteProject').mockResolvedValue(true)
    await mount()

    buttonByText('取消')?.click()
    await flush()

    expect(remove).not.toHaveBeenCalled()
    expect(visible.value).toBe(false)
    expect(deleted).not.toHaveBeenCalled()
  })

  it('calls the real store action and closes after success', async () => {
    const store = useProjectStore()
    const remove = vi.spyOn(store, 'deleteProject').mockResolvedValue(true)
    await mount()
    await typeName(project.name)

    buttonByText('永久删除项目')?.click()
    await flush()

    expect(remove).toHaveBeenCalledWith(project.id)
    expect(visible.value).toBe(false)
    expect(deleted).toHaveBeenCalledTimes(1)
  })

  it('keeps the dialog and project visible when deletion fails', async () => {
    const store = useProjectStore()
    vi.spyOn(store, 'deleteProject').mockResolvedValue(false)
    await mount()
    await typeName(project.name)
    const before = store.projectById(project.id)

    buttonByText('永久删除项目')?.click()
    await flush()

    expect(document.body.textContent).toContain('项目删除失败，请重试。')
    expect(visible.value).toBe(true)
    expect(store.projectById(project.id)).toBe(before)
    expect(deleted).not.toHaveBeenCalled()
  })
})

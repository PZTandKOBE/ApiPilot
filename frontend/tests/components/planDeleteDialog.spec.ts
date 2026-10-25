// @vitest-environment happy-dom
import { createApp, h, nextTick, ref, type App } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlanDeleteDialog from '@/components/console/Agent/PlanDeleteDialog.vue'
import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

let app: App | null = null
let container: HTMLDivElement | null = null
let visible = ref(true)
let plan: ReturnType<typeof useAgentStore>['activePlan'] = null
let deleted = vi.fn()

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const mount = async (): Promise<void> => {
  const agent = useAgentStore()
  plan = agent.activePlan
  visible = ref(true)
  container = document.createElement('div')
  document.body.appendChild(container)

  app = createApp({
    render: () =>
      h(PlanDeleteDialog, {
        modelValue: visible.value,
        'onUpdate:modelValue': (value: boolean) => {
          visible.value = value
        },
        plan: plan!,
        onDeleted: deleted,
      }),
  })
  app.provide(ID_INJECTION_KEY, { prefix: 4000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
}

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

beforeEach(async () => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
  deleted = vi.fn()

  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
})

afterEach(() => {
  app?.unmount()
  app = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('PlanDeleteDialog', () => {
  it('shows the plan name, version count and history preservation note', async () => {
    await mount()
    const text = document.body.textContent ?? ''

    expect(text).toContain('Orders 生命周期验证')
    expect(text).toContain('全部 1 个版本')
    expect(text).toContain('测试执行记录和 PDF 报告会保留')
  })

  it('cancels without deleting anything', async () => {
    const store = useAgentStore()
    const remove = vi.spyOn(store, 'deletePlan').mockResolvedValue(true)
    await mount()

    buttonByText('取消')?.click()
    await flush()

    expect(remove).not.toHaveBeenCalled()
    expect(visible.value).toBe(false)
    expect(deleted).not.toHaveBeenCalled()
  })

  it('calls the real store action once and closes on success', async () => {
    const store = useAgentStore()
    const remove = vi.spyOn(store, 'deletePlan').mockResolvedValue(true)
    await mount()

    buttonByText('删除计划')?.click()
    await flush()

    expect(remove).toHaveBeenCalledTimes(1)
    expect(remove).toHaveBeenCalledWith('prj_orders', plan?.id)
    expect(visible.value).toBe(false)
    expect(deleted).toHaveBeenCalledTimes(1)
  })

  it('keeps the dialog open and shows an error when deletion fails', async () => {
    const store = useAgentStore()
    vi.spyOn(store, 'deletePlan').mockResolvedValue(false)
    await mount()

    buttonByText('删除计划')?.click()
    await flush()

    expect(document.body.textContent).toContain('删除计划失败，请重试。')
    expect(visible.value).toBe(true)
    expect(deleted).not.toHaveBeenCalled()
  })
})

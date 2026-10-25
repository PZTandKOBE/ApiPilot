// @vitest-environment happy-dom
import { createApp, h, nextTick, ref, type App } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EnvironmentCreateDialog from '@/components/console/EnvironmentCreateDialog.vue'
import { resetSessionForTests } from '@/services/session'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures } from '../support/projects'

const PROJECT_ID = FIRST_PROJECT_FIXTURE.id

let app: App | null = null
let visible = ref(true)

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const wireProject = (name: string, kind: string, baseUrl: string) => ({
  id: PROJECT_ID,
  name: FIRST_PROJECT_FIXTURE.name,
  description: FIRST_PROJECT_FIXTURE.description,
  specName: FIRST_PROJECT_FIXTURE.specName,
  environments: [
    ...FIRST_PROJECT_FIXTURE.environments.map((environment) => ({
      id: environment.id,
      name: environment.name,
      kind: environment.kind,
      baseUrl: environment.baseUrl,
      variables: [],
    })),
    { id: 'env_new_test', name, kind, baseUrl, variables: [] },
  ],
  updatedAt: '2026-10-22T12:00:00.000Z',
})

const mount = async (): Promise<void> => {
  visible = ref(true)
  app = createApp({
    setup() {
      return () =>
        h(EnvironmentCreateDialog, {
          modelValue: visible.value,
          'onUpdate:modelValue': (value: boolean) => {
            visible.value = value
          },
          projectId: PROJECT_ID,
        })
    },
  })
  const container = document.createElement('div')
  document.body.appendChild(container)
  app.mount(container)
  await nextTick()
  await nextTick()
}

const buttons = (): HTMLButtonElement[] =>
  Array.from(document.querySelectorAll('button'))

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  buttons().find((button) => button.textContent?.trim() === text)

const inputByPlaceholder = (placeholder: string): HTMLInputElement | null =>
  document.querySelector('input[placeholder="' + placeholder + '"]')

const typeInto = async (input: HTMLInputElement, value: string): Promise<void> => {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
}

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
  resetSessionForTests()
  document.body.innerHTML = ''
})

afterEach(() => {
  app?.unmount()
  app = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetSessionForTests()
})

const stubCreateFetch = (status = 201): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (rawUrl: string, init?: RequestInit) => {
      if (String(rawUrl).endsWith('/api/guest-sessions')) {
        return json(201, { sessionToken: 'gst_create_dialog' })
      }
      if (String(rawUrl).endsWith('/api/projects/' + PROJECT_ID + '/environments') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as {
          name: string
          kind: string
          baseUrl: string
        }
        if (status !== 201) {
          return json(status, { code: 'environment-name-conflict', messageKey: 'console.overview.saveFailed' })
        }
        return json(201, wireProject(body.name, body.kind, body.baseUrl))
      }
      throw new Error('unexpected request')
    }),
  )
}

describe('EnvironmentCreateDialog', () => {
  it('shows validation errors and does not call the API for an empty form', async () => {
    await mount()
    stubCreateFetch()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockClear()

    buttonByText('创建')?.click()
    await flush()

    expect(document.body.textContent).toContain('请输入有效的名称')
    expect(document.body.textContent).toContain('请输入有效的 http:// 或 https:// 地址')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(visible.value).toBe(true)
  })

  it('sends trimmed values and adds the returned environment to the store', async () => {
    await mount()
    stubCreateFetch()
    const store = useProjectStore()

    const select = document.querySelector('.el-select') as HTMLElement | null
    select?.click()
    await nextTick()
    const testingOption = Array.from(
      document.querySelectorAll('.el-select-dropdown__item'),
    ).find((option) => option.textContent?.trim() === '测试') as HTMLElement | undefined
    testingOption?.click()
    await nextTick()

    await typeInto(
      inputByPlaceholder('例如：Test 或 Staging') as HTMLInputElement,
      '  Test EU  ',
    )
    await typeInto(
      inputByPlaceholder('https://api.example.com') as HTMLInputElement,
      ' https://eu.test.example.com ',
    )
    buttonByText('创建')?.click()
    await flush()

    expect(
      store
        .projectById(PROJECT_ID)
        ?.environments.some(
          (environment) => environment.name === 'Test EU' && environment.kind === 'testing',
        ),
    ).toBe(true)
    expect(visible.value).toBe(false)
  })

  it('keeps the form open and the input intact when creation fails', async () => {
    await mount()
    stubCreateFetch(409)
    const store = useProjectStore()

    await typeInto(
      inputByPlaceholder('例如：Test 或 Staging') as HTMLInputElement,
      'Test EU',
    )
    await typeInto(
      inputByPlaceholder('https://api.example.com') as HTMLInputElement,
      'https://eu.test.example.com',
    )
    const before = store.projectById(PROJECT_ID)?.environments.length
    buttonByText('创建')?.click()
    await flush()

    expect(document.body.textContent).toContain('创建失败，请检查名称是否已存在后重试。')
    expect((inputByPlaceholder('例如：Test 或 Staging') as HTMLInputElement).value).toBe('Test EU')
    expect(visible.value).toBe(true)
    expect(store.projectById(PROJECT_ID)?.environments).toHaveLength(before ?? 0)
  })

  it('rejects a name already used in the project without calling the API', async () => {
    await mount()
    stubCreateFetch()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockClear()

    await typeInto(
      inputByPlaceholder('例如：Test 或 Staging') as HTMLInputElement,
      'Development',
    )
    await typeInto(
      inputByPlaceholder('https://api.example.com') as HTMLInputElement,
      'https://other.example.com',
    )
    buttonByText('创建')?.click()
    await flush()

    expect(document.body.textContent).toContain('当前项目已存在同名环境。')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('offers all four environment kinds', async () => {
    await mount()

    const select = document.querySelector('.el-select') as HTMLElement | null
    select?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const options = Array.from(
      document.querySelectorAll('.el-select-dropdown__item'),
    ).map((option) => option.textContent?.trim())

    expect(options).toEqual(expect.arrayContaining(['开发', '测试', '预发', '生产']))
  })

  it('cancels without calling the API', async () => {
    await mount()
    stubCreateFetch()
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockClear()

    buttonByText('取消')?.click()
    await flush()

    expect(visible.value).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

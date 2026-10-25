import { renderToString } from 'vue/server-renderer'
import { createSSRApp, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import AgentTaskStatusTag from '@/components/console/Agent/AgentTaskStatusTag.vue'
import { useLocaleStore } from '@/stores/locale'
import type { AgentTaskStatus } from '@/types/agent'

/**
 * The task-status chip uses the task lifecycle vocabulary, not the plan
 * approval vocabulary. This pins all four labels the API can persist.
 */
const labels: ReadonlyArray<readonly [AgentTaskStatus, string]> = [
  ['pending', '等待中'],
  ['analyzing', '分析中'],
  ['completed', '已完成'],
  ['failed', '失败'],
]

const render = async (status: AgentTaskStatus): Promise<string> => {
  const app = createSSRApp({ render: () => h(AgentTaskStatusTag, { status }) })
  return renderToString(app)
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('AgentTaskStatusTag', () => {
  it('renders every persisted task state', async () => {
    for (const [status, label] of labels) {
      const html = await render(status)
      expect(html).toContain(label)
    }
  })
})

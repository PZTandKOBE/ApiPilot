import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures, SECOND_PROJECT_FIXTURE } from '../support/projects'

/**
 * The project-scoped task activity list.
 *
 * The API is per project and the store owns one active project at a time, so
 * the important frontend invariant is that switching project cannot leave the
 * previous project's tasks on screen. The mock service creates a real task
 * summary through the same store action the app uses.
 */
beforeEach(() => {
  setActivePinia(createPinia())
})

const setup = () => {
  const project = useProjectStore()
  installProjectFixtures(project)
  useLocaleStore().setLocale('zh-CN')
  return { project, agent: useAgentStore() }
}

describe('agent task activity', () => {
  it('loads the active project tasks and drops the old project on switch', async () => {
    const { project, agent } = setup()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.loadTasks()

    expect(agent.projectTasks.length).toBe(1)
    expect(agent.projectTasks[0]?.projectId).toBe(FIRST_PROJECT_FIXTURE.id)
    expect(agent.projectTasks[0]?.prompt).toContain('设计一份测试计划')
    expect(agent.projectTasks[0]?.status).toBe('completed')

    project.selectProject(SECOND_PROJECT_FIXTURE.id)
    expect(agent.projectTasks).toHaveLength(0)

    await agent.loadTasks()
    expect(agent.projectTasks).toHaveLength(0)

    project.selectProject(FIRST_PROJECT_FIXTURE.id)
    await agent.loadTasks()
    expect(agent.projectTasks).toHaveLength(1)
  })
})

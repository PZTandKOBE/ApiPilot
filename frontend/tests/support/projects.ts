import { MOCK_PROJECTS } from '@/services/mock/projects'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

/**
 * Projects for tests that need some.
 *
 * The project store no longer starts with a list: its first render is *empty*
 * until `initialize()` answers, because a console that shows a seeded project
 * while the real one is still loading is a console showing a project the guest
 * may not own.  That change means a test which wants projects has to say so,
 * which is the point — the data a test asserts against is now visible in the
 * test rather than implied by the store's defaults.
 *
 * The values themselves are the old seeds in `services/mock/projects.ts`, still
 * the most convenient set of well-formed projects in the repository (ids,
 * several environments, secret and plain variables).  They are a *fixture* now:
 * nothing in `src/` reads them as a starting state.
 */
export const PROJECT_FIXTURES: readonly Project[] = MOCK_PROJECTS

/** The first fixture, for tests that only need one project to exist. */
export const FIRST_PROJECT_FIXTURE: Project = MOCK_PROJECTS[0] as Project

/** The second project in the fixture set, used for switching tests. */
export const SECOND_PROJECT_FIXTURE: Project = MOCK_PROJECTS[1] as Project

/**
 * Give the store the fixture list, and active state consistent with it.
 *
 * Deliberately the same three assignments a real `initialize()` makes on
 * success, so a test that installs fixtures is in the state a loaded console is
 * in — not a state only tests can reach.
 */
export const installProjectFixtures = (
  store: ReturnType<typeof useProjectStore>,
  projects: readonly Project[] = PROJECT_FIXTURES,
): void => {
  store.projects = projects
  store.activeProjectId = projects[0]?.id ?? ''
  store.activeEnvironmentId = projects[0]?.environments[0]?.id ?? ''
  store.status = 'ready'
}

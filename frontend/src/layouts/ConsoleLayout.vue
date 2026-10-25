<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsoleSidebar from '@/components/console/ConsoleSidebar.vue'
import ConsoleTopBar from '@/components/console/ConsoleTopBar.vue'
import { useI18n } from '@/i18n'
import { readToken } from '@/services/session'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'

/**
 * Application shell.
 *
 * The shell is viewport-height and never scrolls; each pane scrolls itself.
 * That is the whole point: a request composer needs a URL bar that stays put
 * above an independently scrolling response, which a page-level scroll cannot
 * give it.
 *
 * One sidebar, and it lives here rather than in a view because it has to be a
 * *sibling* of the scrolling pane. Nested inside the page it would be a
 * full-height column inside a scroll container. Project destinations are in
 * that same sidebar as everything else — the top bar already names the project
 * and the environment, so a project-only rail beside it said nothing new.
 *
 * `main` is a flex column, not a plain block, so a page that needs the whole
 * pane can claim it by growing (`flex-1`) instead of by asking for
 * `height: 100%`. The percentage route is the trap here: it only resolves
 * against a containing block whose `height` is *definite*, and a chain of
 * `min-height`/auto ancestors quietly hands the page `auto` instead — which
 * is how the API Client ended up collapsed to its content height with its two
 * columns stretched to match each other. Content-height pages are unaffected:
 * as flex items they keep their own height and this pane scrolls them.
 *
 * ## The shell is where the console's projects are established
 *
 * It is the one component every console route passes through, so it is the only
 * honest place to answer "which projects does this guest have" — once, before
 * anything project-scoped is on screen. Leaving that to the first page that
 * happened to need a project id made the id a guess: the store starts on a
 * seeded project, and a page could read that id, or the one in the address bar,
 * long before either had been checked against the backend.
 *
 * So this component does two things no page should have to:
 *
 * 1. **Starts `initialize()` and waits for it.** The store's own single-flight
 *    promise is reused, not re-implemented, so a second caller — the agent
 *    store's readiness gate, for instance — joins the same load rather than
 *    starting another one or creating a second project for an empty guest.
 * 2. **Reconciles the address bar with the loaded list.** A project id in the
 *    URL is accepted only when the *loaded* list contains it; otherwise the
 *    route is replaced with the same destination under the project that is
 *    actually active. That is what stops an id left over from a previous
 *    session — or one of the mock ids the store is seeded with — from being
 *    treated as a real project just because it is in the path.
 *
 * Children are not rendered until that answer exists. A page that mounts
 * against a project id nobody has checked is a page that will ask the backend
 * about somebody else's project; showing the shell until the list arrives costs
 * a moment, and the alternative costs a wrong request.
 *
 * The redirect preserves the destination: only the `projectId` param is
 * replaced, so "runs" stays "runs" and a run detail stays that run's detail.
 */
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const ui = useUiStore()
const projectStore = useProjectStore()
const auth = useAuthStore()

const mainRef = ref<HTMLElement | null>(null)

/**
 * The project id in the address bar, or `null` when this route names none.
 *
 * Read from `params` rather than from a route record: `:projectId` is declared
 * on the `projects/:projectId` record, which is this layout's *child*, so the
 * param is inherited here and the record that owns it is not one of
 * `route.matched`.  Routes outside a project — the dashboard, the project list —
 * simply have no such param, and that is the signal to leave them alone.
 *
 * A plain string on purpose: it is a watcher source below, and a computed that
 * built a fresh object every evaluation would look changed on every tick.
 */
const routeProjectParam = computed<string | null>(() => {
  const value = route.params.projectId

  return typeof value === 'string' && value !== '' ? value : null
})

/**
 * The address bar's project, but only once the loaded list vouches for it.
 *
 * Deliberately not "the route says so": the whole failure this guards against is
 * a route that names a project the guest does not have.
 */
const routeProjectId = computed(() => {
  const id = routeProjectParam.value
  if (id === null) return ''
  if (projectStore.status !== 'ready') return ''
  if (projectStore.projectById(id) === null) return ''

  return id
})

/** The project a project-scoped route should be showing once there is one. */
const reconciledProjectId = computed<string | null>(() => {
  if (projectStore.status !== 'ready') return null

  const id = routeProjectParam.value
  if (id === null) return null
  if (projectStore.projectById(id) !== null) return null

  return projectStore.activeProject?.id ?? null
})

/**
 * Replace only the project id, keeping the page the user asked for.
 *
 * `router.resolve` is what makes that safe: it turns the current location into
 * the location *we are actually on* — params and all — so the replacement
 * cannot invent a path the route table does not have.
 */
const replaceProjectInRoute = (projectId: string): void => {
  const name = route.name
  if (routeProjectParam.value === null || typeof name !== 'string') return

  const target = router.resolve({
    name,
    params: { ...route.params, projectId },
    query: route.query,
    hash: route.hash,
  })

  if (target.fullPath === route.fullPath) return

  void router.replace(target)
}

/**
 * Establish the projects, then make the address agree with them.
 *
 * A watcher rather than a one-shot `onMounted` body: the reconciliation has to
 * happen when the list *arrives*, which is after the mount, and again if the
 * list changes under a route that was already fine.
 */
const bootstrap = async (): Promise<void> => {
  // app bootstrap (main.ts) initializes auth before the router/views mount.
  // Direct component tests do not, and must not issue an extra config request.
  if (auth.initialized && auth.isOfficialCloud && !auth.isAuthenticated) {
    // Account auth is preferred, but an explicitly started browser guest may
    // enter the console when the server enabled guest experience. A guest
    // without a token still goes through the login/guest chooser first.
    const hasGuestToken = auth.guestEnabled && readToken() !== null
    if (!hasGuestToken) {
      await router.replace({
        name: 'login',
        query: { next: route.fullPath },
      })
      return
    }
  }

  await projectStore.initialize()

  if (projectStore.status !== 'ready') return

  // No project was invented on the way in. If the address bar still points at
  // a project-scoped page, there is no real destination for it; land on the
  // project index, which is the existing empty state and creation entry point.
  if (projectStore.projects.length === 0) {
    if (routeProjectParam.value !== null) {
      await router.replace({ name: 'console-projects' })
    }
    return
  }

  const projectId = reconciledProjectId.value
  if (projectId === null) return

  replaceProjectInRoute(projectId)
}

/**
 * Run once when the shell is set up, and again when the answer changes.
 *
 * `immediate` rather than `onMounted` on purpose: a lifecycle hook would make the
 * bootstrap a client-only event, and the reconciliation below is not a browser
 * concern -- it is what makes the address bar agree with the loaded list, and it
 * has to hold however the shell was rendered.
 */
watch([() => projectStore.status, routeProjectParam], () => void bootstrap(), {
  immediate: true,
})

// Overlays and scroll position belong to a navigation, not to the session.
watch(
  () => route.fullPath,
  () => {
    ui.setMobileNav(false)
    if (mainRef.value !== null) mainRef.value.scrollTop = 0
  },
)

/**
 * The URL owns "which project" — once it names one this guest actually has.
 *
 * Selecting the route's project is what keeps the switcher and the global
 * navigation on the project the address bar is showing.
 */
watch(
  routeProjectId,
  (id) => {
    if (id !== '') projectStore.selectProject(id)
  },
  { immediate: true },
)

/** Whether a project-scoped destination has been vouched for yet. */
const projectResolved = computed(
  () => routeProjectParam.value === null || routeProjectId.value !== '',
)
</script>

<template>
  <div class="console-shell">
    <ConsoleTopBar />

    <div class="flex min-h-0 flex-1">
      <ConsoleSidebar />

      <main ref="mainRef" class="console-scroll flex min-w-0 flex-1 flex-col">
        <!--
          A project-scoped page waits for its project. Rendering it early would
          let it read the seeded id the store starts on.
        -->
        <RouterView v-if="projectResolved" />

        <div v-else-if="projectStore.status === 'error'" class="console-page">
          <div class="console-panel">
            <ConsoleEmptyState
              :title="t('console.project.notFound')"
              :body="t('console.project.notFoundBody')"
            >
              <RouterLink
                :to="{ name: 'console-projects' }"
                class="text-[12.5px] text-[var(--accent-soft)] hover:underline"
              >
                {{ t('console.project.backToProjects') }}
              </RouterLink>
            </ConsoleEmptyState>
          </div>
        </div>

        <div v-else class="console-page">
          <p class="text-[12.5px] text-[var(--console-text-muted)]">
            {{ t('console.common.loading') }}
          </p>
        </div>
      </main>
    </div>
  </div>
</template>

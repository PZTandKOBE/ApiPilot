import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { PROJECT_NAME } from '@/config/project'

/**
 * Route metadata.
 *
 * `titleKey` is an i18n key and is preferred over `title`, because a console
 * page title has to follow the language switcher and a literal string cannot.
 * `title` remains for names that are intentionally not translated.
 *
 * `src/composables/useDocumentTitle.ts` is what actually applies these — the
 * router itself has no opinion about the document.
 */
declare module 'vue-router' {
  interface RouteMeta {
    readonly title?: string
    readonly titleKey?: string
  }
}

/**
 * Console routes live under a single lazy layout. Destination names are
 * namespaced `console-project-*` for workspace-scoped pages, which is how the
 * navigation tells whether it is inside a project.
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/Home.vue'),
    meta: { title: PROJECT_NAME },
  },
  {
    // Reserved by the landing page's primary CTA before the console existed.
    // Kept as a redirect so links captured against the placeholder still land.
    path: '/try',
    redirect: { name: 'console-dashboard' },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { titleKey: 'auth.title' },
  },
  {
    path: '/learn',
    name: 'learn',
    component: () => import('@/views/LearnView.vue'),
    meta: { titleKey: 'learn.docsLabel' },
  },
  {
    path: '/learn/:slug',
    name: 'learn-doc',
    component: () => import('@/views/LearnView.vue'),
    meta: { titleKey: 'learn.docsLabel' },
  },
  {
    path: '/console',
    component: () => import('@/layouts/ConsoleLayout.vue'),
    children: [
      {
        path: '',
        redirect: { name: 'console-dashboard' },
      },
      {
        path: 'dashboard',
        name: 'console-dashboard',
        component: () => import('@/views/console/DashboardView.vue'),
        meta: { titleKey: 'console.dashboard.title' },
      },
      {
        path: 'projects',
        name: 'console-projects',
        component: () => import('@/views/console/ProjectsView.vue'),
        meta: { titleKey: 'console.nav.projects' },
      },
      {
        path: 'projects/:projectId',
        component: () => import('@/views/console/ProjectLayout.vue'),
        props: true,
        children: [
          {
            path: '',
            // A function redirect so the param survives the hop.
            redirect: (to) => ({
              name: 'console-project-overview',
              params: to.params,
            }),
          },
          {
            path: 'overview',
            name: 'console-project-overview',
            component: () => import('@/views/console/ProjectOverviewView.vue'),
            props: true,
            meta: { titleKey: 'console.nav.overview' },
          },
          {
            path: 'api',
            name: 'console-project-api',
            component: () => import('@/views/console/ApiClientView.vue'),
            props: true,
            meta: { titleKey: 'console.apiClient.title' },
          },
          {
            path: 'ai-test',
            name: 'console-project-ai-test',
            component: () => import('@/views/console/AiTestLabView.vue'),
            props: true,
            meta: { titleKey: 'console.aiTest.title' },
          },
          {
            path: 'plans',
            name: 'console-project-plans',
            component: () => import('@/views/console/TestPlansView.vue'),
            props: true,
            meta: { titleKey: 'console.plans.title' },
          },
          {
            path: 'plans/:planId',
            name: 'console-project-plan-detail',
            component: () => import('@/views/console/TestPlanDetailView.vue'),
            props: true,
            meta: { titleKey: 'console.plans.title' },
          },
          {
            // `console-project-runs` was already named by both navigation
            // lists and by the approval panel before this route existed, and
            // `hasRoute` is what kept them disabled. Registering it turns
            // those entries into links without touching any of them.
            path: 'runs',
            name: 'console-project-runs',
            component: () => import('@/views/console/RunsView.vue'),
            props: true,
            meta: { titleKey: 'console.runs.title' },
          },
          {
            path: 'runs/:runId',
            name: 'console-project-run-detail',
            component: () => import('@/views/console/RunDetailView.vue'),
            props: true,
            meta: { titleKey: 'console.runs.title' },
          },
          {
            path: 'runs/:runId/report',
            name: 'console-project-run-report',
            component: () => import('@/views/console/RunReportView.vue'),
            props: true,
            meta: { titleKey: 'console.report.title' },
          },
          {
            path: 'reports',
            name: 'console-project-reports',
            component: () => import('@/views/console/ReportsView.vue'),
            props: true,
            meta: { titleKey: 'console.report.centerTitle' },
          },
        ],
      },
      {
        path: ':pathMatch(.*)*',
        name: 'console-not-found',
        component: () => import('@/views/console/ConsoleNotFoundView.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: { name: 'home' },
  },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    // The console shell owns its own scroll panes, so this only ever applies
    // to the marketing pages.
    return savedPosition ?? { top: 0 }
  },
})

export default router

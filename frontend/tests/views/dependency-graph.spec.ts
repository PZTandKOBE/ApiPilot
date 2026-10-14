import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ApiDependencyGraph from '@/components/console/Agent/ApiDependencyGraph.vue'
import ApiUnderstandingPanel from '@/components/console/Agent/ApiUnderstandingPanel.vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { installProjectFixtures } from '../support/projects'

/**
 * The dependency graph, rendered from the real analysis.
 *
 * Every group in this component can disappear without a trace: a source or
 * target that fails to resolve is skipped, and a source left with no branches
 * is never collected. Nothing reports the difference, so a graph missing half
 * its edges looks exactly like a document with half as many edges. The counts
 * below are the only thing that can tell those apart — which is why they are
 * asserted rather than left to the demo's visual read.
 */
beforeEach(() => {
  setActivePinia(createPinia())
  // The project store starts empty now; the agent store scopes a document to the
  // active project, so these tests state which project that is.
  installProjectFixtures(useProjectStore())
})

const withUnderstanding = async () => {
  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  return agent
}

const render = async (component: unknown): Promise<string> => {
  const app = createSSRApp(component as never)
  return renderToString(app)
}

const countOf = (html: string, testid: string): number =>
  html.split(`data-testid="${testid}"`).length - 1

const textOf = (html: string): string =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

describe('dependency graph', () => {
  it('renders every group and every branch the analysis produced', async () => {
    const agent = await withUnderstanding()
    const html = await render(ApiDependencyGraph)

    // Pinned to the analysis, not to a constant in the component: if a rule
    // stops firing, this test is supposed to fail too.
    expect(agent.understanding?.dependencies).toHaveLength(7)
    expect(countOf(html, 'dependency-group')).toBe(5)
    expect(countOf(html, 'dependency-branch')).toBe(7)
  })

  it('explains every edge on screen, not just the ones that fit', async () => {
    const agent = await withUnderstanding()
    const html = await render(ApiDependencyGraph)

    const rationale = (html.match(/data-testid="dependency-rationale"/g) ?? []).length
    expect(rationale).toBe(agent.understanding?.dependencies.length)

    for (const dependency of agent.understanding?.dependencies ?? []) {
      if (!('key' in dependency.rationale)) continue
      // Each rendered edge carries its binding; the sentence is the reason.
      expect(textOf(html)).toContain(dependency.binding)
    }
  })

  it('shows the source of an edge, not only where it leads', async () => {
    const agent = await withUnderstanding()
    const html = await render(ApiDependencyGraph)
    const text = textOf(html)

    const byId = new Map(
      agent.understanding?.endpoints.map((endpoint) => [endpoint.id, endpoint]) ?? [],
    )
    const sources = agent.understanding?.dependencies.map((dependency) =>
      byId.get(dependency.fromEndpointId),
    )

    expect(new Set(sources?.map((source) => source?.id)).size).toBe(5)
    for (const path of [
      '/api/auth/login',
      '/api/users/me',
      '/api/products/{productId}',
      '/api/orders',
      '/api/orders/{orderId}',
    ]) {
      expect(text).toContain(path)
    }
  })
})

describe('endpoint list', () => {
  it('renders one row per endpoint, not one per unique path', async () => {
    const agent = await withUnderstanding()
    const html = await render(ApiUnderstandingPanel)

    // `GET /api/orders` and `GET /api/orders/{orderId}` share a prefix and
    // `/api/orders/{orderId}` and `/api/orders/orderId` would share a slug;
    // a row is an endpoint, so the counts have to come from the list.
    expect(countOf(html, 'understanding-endpoint')).toBe(
      agent.understanding?.endpoints.length,
    )
    expect(agent.understanding?.endpoints).toHaveLength(18)
  })
})

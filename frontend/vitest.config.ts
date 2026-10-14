import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

/**
 * Test configuration.
 *
 * Merged onto the real Vite config rather than written alongside it, so tests
 * resolve `@/…` through the same alias and compile `.vue` files through the
 * same plugin the app does. A separate config that drifted would let tests
 * pass against a build that does not exist.
 *
 * `environment: 'node'` on purpose. Nothing here needs a DOM: the agent and
 * API-Client logic is pure, the stores guard their `window` access, and the
 * view smoke tests render through `vue/server-renderer` — which is also what
 * keeps jsdom out of the dependency tree.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'node',
      include: ['tests/**/*.spec.ts'],
      // Assertions about "nothing was called" are only trustworthy when the
      // previous test's call history cannot leak into this one.
      restoreMocks: true,
    },
  }),
)

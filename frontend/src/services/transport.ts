/**
 * Transport seam, and the switch that picks one.
 *
 * The API Client never talks to the network directly — it hands a resolved
 * request to an `ApiTransport` and gets an `ApiResponse` back. That is what makes
 * the browser's CORS model a deployment detail rather than an architectural one,
 * and it is what this phase finally exercises:
 *
 *   Browser → MockTransport                            (tests)
 *   Browser → ProxyTransport → FastAPI → target API    (development, production)
 *
 * **The switch is `MODE`, and there is no other input.** A development or
 * production build gets the real proxy; `MODE === 'test'` — which Vitest pins —
 * gets the mock, because the store and view specs drive the client through a
 * known script and must not need a backend. That is the same rule
 * `services/agent.ts` and `services/run.ts` already follow.
 *
 * **There is no fallback, and no flag that could create one.** A missing backend,
 * a refused guest session, a blocked target or an upstream timeout is reported as
 * an error; none of them turns into a mock response, and there is deliberately no
 * `VITE_*` variable that could put the mock in a shipped build. A console that
 * quietly answered with invented data would be lying about what the API under
 * test said — which is the whole product.
 */

import { createMockTransport } from './mock/transport'
import { createProxyTransport } from './api/transport'
import type { ApiResponse, ResolvedApiRequest } from '@/types/api'

export interface TransportSendInput {
  readonly request: ResolvedApiRequest
  /**
   * The project the request belongs to, already validated by the caller.
   *
   * Required because the platform's proxy route is project-scoped, and the store
   * is the only layer that can answer "which project is this console on?" — see
   * `requireReadyProjectId`.  The transport must not guess it from storage: a
   * leftover id from another session is exactly what that check exists to reject.
   */
  readonly projectId: string
  /** Aborting this rejects the returned promise with an `AbortError`. */
  readonly signal?: AbortSignal
}

export interface ApiTransport {
  readonly kind: 'mock' | 'proxy'
  send(input: TransportSendInput): Promise<ApiResponse>
}

export { createProxyTransport, ProxyTransportError } from './api/transport'
export type {
  ProxyTransportOptions,
  ProxyWireRequest,
  ProxyWireResponse,
} from './api/transport'

/**
 * The transport this build uses.
 *
 * Note what is *not* here: no environment variable, no feature flag, no try/catch
 * that could hand back the mock. The only branch is the build mode.
 */
export const createTransport = (): ApiTransport =>
  import.meta.env.MODE === 'test' ? createMockTransport() : createProxyTransport()

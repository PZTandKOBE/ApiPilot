/**
 * Central place for product-level constants.
 *
 * Nothing in the UI should hard-code an external URL or a route target —
 * they all resolve through this module so a single edit updates the whole
 * landing page.
 */

export const PROJECT_NAME = 'AI API Testing Agent'

/** Repository slug, used for display and to build outbound links. */
export const GITHUB_REPO = 'ai-api-testing-agent'

/**
 * TODO(owner): set the real repository URL, e.g.
 *   'https://github.com/<org>/ai-api-testing-agent'
 *
 * Left intentionally empty rather than guessed: a wrong link on the landing
 * page is worse than a clearly disabled one. While empty, the navbar renders
 * the GitHub entry as a disabled control with an explanatory title instead of
 * a link that 404s.
 */
export const GITHUB_URL = ''

export const hasGithubUrl = (): boolean => GITHUB_URL.trim().length > 0

/**
 * Where the primary CTA ("TRY US") lands: the console's default view.
 *
 * `/try` still resolves (it redirects here) so any link captured against the
 * earlier placeholder keeps working.
 */
export const APP_ENTRY_ROUTE = '/console'

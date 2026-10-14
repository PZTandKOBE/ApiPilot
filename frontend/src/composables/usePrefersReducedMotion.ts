import { useMediaQuery } from './useMediaQuery'

/** Gates optional motion so the page stays usable when motion is unwelcome. */
export const usePrefersReducedMotion = () =>
  useMediaQuery('(prefers-reduced-motion: reduce)')

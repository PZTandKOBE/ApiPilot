/**
 * Identifier generation.
 *
 * `crypto.randomUUID` is only available in secure contexts, and a dev server
 * reached over plain HTTP on a LAN address is not one — so it is treated as an
 * optimisation, not a requirement.
 */

let fallbackCounter = 0

export const createId = (prefix: string): string => {
  const random =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${(fallbackCounter += 1).toString(36)}`

  return `${prefix}_${random}`
}

/**
 * `{{variable}}` template handling.
 *
 * The API Client never rewrites the user's draft: placeholders stay in the
 * stored request and are substituted only when a request is about to be sent.
 * That is what lets a saved request keep working after the token behind
 * `{{token}}` rotates.
 */

const VARIABLE_PATTERN = /\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g

export interface TemplateResolution {
  /** The substituted text. Unresolved placeholders are left intact. */
  readonly value: string
  /** Names referenced but absent from the variable set, de-duplicated. */
  readonly missing: readonly string[]
}

/** Every placeholder name referenced by `text`, in first-seen order. */
export const findVariableNames = (text: string): readonly string[] => {
  const names: string[] = []

  // `matchAll` needs the global flag, which the shared pattern carries; the
  // regex is stateless between calls because `lastIndex` is reset by matchAll.
  for (const match of text.matchAll(VARIABLE_PATTERN)) {
    const name = match[1]
    if (name !== undefined && !names.includes(name)) names.push(name)
  }

  return names
}

/**
 * Substitute every placeholder that has a value.
 *
 * Missing names are reported rather than replaced with an empty string: a
 * request sent with a silently blanked token would fail at the far end with a
 * 401, which points the user at the wrong problem.
 */
export const resolveTemplate = (
  text: string,
  variables: Readonly<Record<string, string>>,
): TemplateResolution => {
  const missing: string[] = []

  const value = text.replace(VARIABLE_PATTERN, (placeholder, name: string) => {
    const resolved = variables[name]
    if (resolved === undefined) {
      if (!missing.includes(name)) missing.push(name)
      return placeholder
    }
    return resolved
  })

  return { value, missing }
}

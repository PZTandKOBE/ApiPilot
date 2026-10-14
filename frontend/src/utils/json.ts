/**
 * JSON parsing and inspection.
 *
 * The viewer is hand-rolled rather than delegated to a library: a full JSON
 * editor is hundreds of kilobytes for what is, here, a read-only tree plus a
 * copy button.
 */

export type JsonNodeKind =
  | 'object'
  | 'array'
  | 'string'
  | 'number'
  | 'boolean'
  | 'null'

export interface JsonParseSuccess {
  readonly ok: true
  readonly value: unknown
}

export interface JsonParseFailure {
  readonly ok: false
  readonly message: string
  /** 1-based line of the syntax error, when it can be recovered. */
  readonly line: number | null
}

export type JsonParseResult = JsonParseSuccess | JsonParseFailure

/**
 * Recover a line number from a `JSON.parse` failure.
 *
 * V8's message embeds either `(line N column M)` or `at position N`, and the
 * wording around those numbers has changed across versions. Rather than match
 * the prose — which is not a stable interface — both numbers are read
 * opportunistically, and a position is converted to a line by counting
 * newlines.
 */
const locateFailure = (message: string, text: string): number | null => {
  const lineMatch = /line (\d+)/.exec(message)
  if (lineMatch?.[1] !== undefined) return Number.parseInt(lineMatch[1], 10)

  const positionMatch = /position (\d+)/.exec(message)
  if (positionMatch?.[1] !== undefined) {
    const position = Number.parseInt(positionMatch[1], 10)
    return text.slice(0, position).split('\n').length
  }

  return null
}

export const parseJson = (text: string): JsonParseResult => {
  if (text.trim() === '') return { ok: false, message: 'Empty input', line: null }

  try {
    return { ok: true, value: JSON.parse(text) as unknown }
  } catch (thrown) {
    const message = thrown instanceof Error ? thrown.message : 'Invalid JSON'
    return { ok: false, message, line: locateFailure(message, text) }
  }
}

/** Pretty-print `text`. Returns it unchanged when it is not valid JSON. */
export const formatJson = (text: string): string => {
  const parsed = parseJson(text)
  if (!parsed.ok) return text

  return JSON.stringify(parsed.value, null, 2)
}

export const jsonKindOf = (value: unknown): JsonNodeKind => {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'

  switch (typeof value) {
    case 'object':
      return 'object'
    case 'number':
      return 'number'
    case 'boolean':
      return 'boolean'
    default:
      return 'string'
  }
}

/**
 * One rendered line of the tree.
 *
 * The tree is flattened into rows so the viewer can render a plain `v-for`
 * with indentation, instead of recursively mounting a component per node —
 * which keeps deep payloads cheap and the DOM flat.
 *
 * Closing braces are rows of their own (`isCloser`), which is what makes the
 * output read as actual JSON rather than as an outline.
 */
export interface JsonRow {
  /** Stable path such as `$.items[0].id`; also the expansion key. */
  readonly path: string
  readonly depth: number
  /** Property name or array index as displayed; empty on a closer row. */
  /** Display-ready: object keys are quoted, array indices are bare, the root is empty. */
  readonly label: string
  readonly kind: JsonNodeKind
  /** Rendered value for primitives and for closer punctuation. */
  readonly value: string
  readonly expandable: boolean
  readonly expanded: boolean
  /** Child count, shown when a container is collapsed. */
  readonly childCount: number
  /** Whether this row is the last child of its parent (drives the comma). */
  readonly last: boolean
  /** `}`, `]` or `},` — a line that closes a container. */
  readonly isCloser: boolean
}

const previewOf = (value: unknown): string => {
  if (typeof value === 'string') return JSON.stringify(value)
  return String(value)
}

const childEntries = (
  value: unknown,
): readonly (readonly [string, unknown])[] => {
  if (Array.isArray(value)) return value.map((item, index) => [String(index), item])

  if (typeof value === 'object' && value !== null) {
    return Object.entries(value as Record<string, unknown>)
  }

  return []
}

/**
 * Flatten `value` into rows, descending only into containers listed in
 * `expanded`. Depth is unbounded, but nothing below a collapsed node is
 * walked — so a 5 MB response costs one row until the user opens it.
 */
export const flattenJson = (
  value: unknown,
  expanded: ReadonlySet<string>,
): readonly JsonRow[] => {
  const rows: JsonRow[] = []

  const walk = (
    node: unknown,
    label: string,
    path: string,
    depth: number,
    isLast: boolean,
  ): void => {
    const kind = jsonKindOf(node)
    const entries = childEntries(node)
    const expandable = entries.length > 0
    const isExpanded = expandable && expanded.has(path)

    rows.push({
      path,
      depth,
      label,
      kind,
      value: expandable ? '' : previewOf(node),
      expandable,
      expanded: isExpanded,
      childCount: entries.length,
      last: isLast,
      isCloser: false,
    })

    if (!isExpanded) return

    entries.forEach(([key, child], index) => {
      const childPath = kind === 'array' ? `${path}[${key}]` : `${path}.${key}`
      // Object keys are quoted as JSON requires; array indices are not.
      const childLabel = kind === 'array' ? key : JSON.stringify(key)

      walk(child, childLabel, childPath, depth + 1, index === entries.length - 1)
    })

    rows.push({
      // Distinct from the opening row so both can be `v-for` keys.
      path: `${path}#close`,
      depth,
      label: '',
      kind,
      value: kind === 'array' ? ']' : '}',
      expandable: false,
      expanded: false,
      childCount: 0,
      last: isLast,
      isCloser: true,
    })
  }

  // The root has no key of its own — it is the document.
  walk(value, '', '$', 0, true)
  return rows
}

/** Container paths that exist in `value`, for "expand all". */
export const collectContainerPaths = (value: unknown): readonly string[] => {
  const paths: string[] = []

  const walk = (node: unknown, path: string): void => {
    const entries = childEntries(node)
    if (entries.length === 0) return

    paths.push(path)
    const isArray = Array.isArray(node)

    for (const [key, child] of entries) {
      walk(child, isArray ? `${path}[${key}]` : `${path}.${key}`)
    }
  }

  walk(value, '$')
  return paths
}

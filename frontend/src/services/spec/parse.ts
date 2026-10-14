/**
 * Document decoding and structural parsing.
 *
 * Two distinct steps, kept apart on purpose:
 *
 *   decode   bytes → a plain object (JSON natively, YAML via js-yaml)
 *   parse    a plain object → endpoints, resources, authentication
 *
 * Only the decode step cares which syntax the file was written in; everything
 * downstream works on the same object, so a YAML Swagger 2.x upload and a JSON
 * OpenAPI 3.x upload take exactly the same path from here on.
 */

import { AgentServiceError } from '@/services/agentError'
import type { ParsedSpec, SpecInput } from '@/services/agent'
import type {
  ApiAuthentication,
  ApiEndpoint,
  ApiResource,
  ApiSpec,
  AuthScheme,
  SpecFormat,
  SpecSource,
} from '@/types/agent'
import { HTTP_METHODS, type HttpMethod } from '@/types/api'

/* ------------------------------------------------------------------ *
 * Generic guards
 * ------------------------------------------------------------------ */

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const asString = (value: unknown): string | null =>
  typeof value === 'string' ? value : null

/** String entries of an array, dropping anything else. */
const asStringArray = (value: unknown): readonly string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

const slugify = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')

/** Stable short hash, so ids differ between documents but never between runs. */
const hashString = (value: string): string => {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

/* ------------------------------------------------------------------ *
 * Decoding
 * ------------------------------------------------------------------ */

const asDocument = (value: unknown, detail: string): Record<string, unknown> => {
  if (!isRecord(value)) {
    throw new AgentServiceError({
      code: 'parse-failed',
      messageKey: 'console.aiTest.errors.parseFailed',
      params: { detail },
    })
  }
  return value
}

/**
 * JSON first, YAML second.
 *
 * A JSON document is valid YAML, so trying JSON first is unambiguous and much
 * cheaper; the YAML parser is only reached for documents that are genuinely
 * YAML. It is imported dynamically so its ~35 kB never lands in the console's
 * main chunk.
 */
export const decodeDocument = async (content: string): Promise<Record<string, unknown>> => {
  const trimmed = content.trim()

  if (trimmed === '') {
    throw new AgentServiceError({
      code: 'parse-failed',
      messageKey: 'console.aiTest.errors.parseFailed',
      params: { detail: 'the document is empty' },
    })
  }

  try {
    const parsed: unknown = JSON.parse(trimmed)
    return asDocument(parsed, 'the document is not a JSON object')
  } catch (thrown) {
    if (thrown instanceof AgentServiceError) throw thrown
    // Not JSON — fall through and let the YAML parser have it.
  }

  let yaml: { load: (source: string) => unknown }

  try {
    yaml = await import('js-yaml')
  } catch {
    throw new AgentServiceError({
      code: 'parse-failed',
      messageKey: 'console.aiTest.errors.parseFailed',
      params: { detail: 'the YAML parser could not be loaded' },
    })
  }

  try {
    return asDocument(yaml.load(trimmed), 'the document is not a mapping')
  } catch (thrown) {
    if (thrown instanceof AgentServiceError) throw thrown

    // js-yaml messages are multi-line and end with a snippet of the document;
    // only the first line identifies the problem.
    const detail =
      thrown instanceof Error
        ? (thrown.message.split('\n')[0] ?? thrown.message)
        : 'unknown parser error'

    throw new AgentServiceError({
      code: 'parse-failed',
      messageKey: 'console.aiTest.errors.parseFailed',
      params: { detail },
    })
  }
}

/* ------------------------------------------------------------------ *
 * Format detection
 * ------------------------------------------------------------------ */

export const detectFormat = (document: Record<string, unknown>): SpecFormat | null => {
  const openapi = asString(document.openapi)
  if (openapi !== null && openapi.startsWith('3.')) return 'openapi-3'

  const swagger = asString(document.swagger)
  if (swagger !== null && swagger.startsWith('2.')) return 'swagger-2'

  return null
}

/* ------------------------------------------------------------------ *
 * $ref resolution
 * ------------------------------------------------------------------ */

/**
 * Follow one `$ref` level.
 *
 * Deliberately not recursive: self-referencing schemas are common in real
 * documents, and one level is enough to read the property names and the
 * `required` list this parser needs.
 */
const resolveRef = (
  document: Record<string, unknown>,
  node: unknown,
): Record<string, unknown> | null => {
  if (!isRecord(node)) return null

  const ref = asString(node.$ref)
  if (ref === null) return node

  const segments = ref.replace(/^#\//, '').split('/')
  let current: unknown = document

  for (const segment of segments) {
    if (!isRecord(current)) return null
    current = current[segment]
  }

  return isRecord(current) ? current : null
}

/** Keywords that make a value worth probing with an invalid input. */
const CONSTRAINT_KEYWORDS = [
  'minimum',
  'maximum',
  'exclusiveMinimum',
  'exclusiveMaximum',
  'enum',
  'minLength',
  'maxLength',
  'pattern',
  'minItems',
  'maxItems',
] as const

interface SchemaSummary {
  readonly required: readonly string[]
  readonly properties: readonly string[]
  readonly constrained: readonly string[]
}

const schemaProperties = (
  document: Record<string, unknown>,
  schema: unknown,
): SchemaSummary => {
  const resolved = resolveRef(document, schema)
  if (resolved === null) return { required: [], properties: [], constrained: [] }

  const definitions = isRecord(resolved.properties) ? resolved.properties : {}
  const required = asStringArray(resolved.required)

  const constrained = required.filter((name) => {
    const definition = resolveRef(document, definitions[name])
    if (definition === null) return false

    return CONSTRAINT_KEYWORDS.some((keyword) => definition[keyword] !== undefined)
  })

  return { required, properties: Object.keys(definitions), constrained }
}

/* ------------------------------------------------------------------ *
 * Endpoint extraction
 * ------------------------------------------------------------------ */

const PATH_PARAM_PATTERN = /\{([^}]+)\}/g

const pathParamsOf = (path: string): readonly string[] => {
  const names: string[] = []
  for (const match of path.matchAll(PATH_PARAM_PATTERN)) {
    if (match[1] !== undefined) names.push(match[1])
  }
  return names
}

const createEndpointId = (method: HttpMethod, path: string): string =>
  `ep_${method.toLowerCase()}_${slugify(path) || 'root'}`

/**
 * Collision-free ids, without disturbing the ones that do not collide.
 *
 * `slugify` flattens every non-alphanumeric run, so `/api/orders/{orderId}`
 * and `/api/orders/orderId` slug to the same string. Left alone, the second
 * endpoint overwrote the first downstream — the document appeared to describe
 * one endpoint fewer than it does, and nothing reported the loss.
 *
 * The suffix is assigned only on a real collision, so a document with no
 * collisions produces byte-identical ids to before, and every id already
 * persisted in a plan still resolves. The trade — who wins `_2` depends on
 * document order — is confined to the collisions themselves.
 */
const createEndpointIdAllocator = (): ((method: HttpMethod, path: string) => string) => {
  const seen = new Set<string>()

  return (method, path) => {
    const base = createEndpointId(method, path)

    let id = base
    let suffix = 2
    while (seen.has(id)) {
      id = `${base}_${String(suffix)}`
      suffix += 1
    }

    seen.add(id)
    return id
  }
}

/**
 * Resource name for an untagged operation.
 *
 * Leading `api` / version segments are skipped, so `/api/v1/orders/{id}`
 * groups under `orders` rather than under `api`.
 */
const resourceNameOf = (operation: Record<string, unknown>, path: string): string => {
  const tags = asStringArray(operation.tags)
  const firstTag = tags[0]
  if (firstTag !== undefined && firstTag.trim() !== '') return firstTag.trim()

  const segments = path.split('/').filter((segment) => segment !== '')
  const meaningful = segments.filter(
    (segment) => !/^(api|v\d+)$/i.test(segment) && !segment.startsWith('{'),
  )

  return meaningful[0] ?? segments[0] ?? 'default'
}

const bodySchemaOf = (
  document: Record<string, unknown>,
  operation: Record<string, unknown>,
  format: SpecFormat,
): unknown => {
  if (format === 'openapi-3') {
    const requestBody = resolveRef(document, operation.requestBody)
    if (requestBody === null) return null

    const content = requestBody.content
    if (!isRecord(content)) return null

    const json = resolveRef(document, content['application/json'])
    return json?.schema ?? null
  }

  // Swagger 2.x carries the body as a parameter.
  const parameters = operation.parameters
  if (!Array.isArray(parameters)) return null

  for (const parameter of parameters) {
    const resolved = resolveRef(document, parameter)
    if (resolved !== null && resolved.in === 'body') return resolved.schema ?? null
  }

  return null
}

const responseInfoOf = (
  document: Record<string, unknown>,
  operation: Record<string, unknown>,
  format: SpecFormat,
): { readonly statuses: readonly number[]; readonly props: readonly string[] } => {
  const responses = operation.responses
  if (!isRecord(responses)) return { statuses: [], props: [] }

  const statuses: number[] = []
  const props: string[] = []

  for (const [key, value] of Object.entries(responses)) {
    const status = Number.parseInt(key, 10)
    if (!Number.isFinite(status)) continue
    statuses.push(status)

    // Only the first success response describes the resource; error bodies are
    // an envelope, not the payload.
    if (status < 200 || status >= 300 || props.length > 0) continue

    const response = resolveRef(document, value)
    if (response === null) continue

    const schemaNode =
      format === 'openapi-3'
        ? (isRecord(response.content)
            ? resolveRef(document, response.content['application/json'])?.schema
            : undefined)
        : response.schema

    const resolved = resolveRef(document, schemaNode)
    if (resolved !== null && isRecord(resolved.properties)) {
      props.push(...Object.keys(resolved.properties))
    }
  }

  return { statuses, props }
}

const isProtected = (
  document: Record<string, unknown>,
  operation: Record<string, unknown>,
): boolean => {
  const own = operation.security
  if (Array.isArray(own)) return own.length > 0

  const global = document.security
  return Array.isArray(global) && global.length > 0
}

const summaryOf = (operation: Record<string, unknown>, method: HttpMethod, path: string) => {
  const summary = asString(operation.summary)
  if (summary !== null && summary.trim() !== '') return { text: summary.trim() }

  const description = asString(operation.description)
  if (description !== null && description.trim() !== '') {
    return { text: description.trim().split('\n')[0] ?? description.trim() }
  }

  return { text: `${method} ${path}` }
}

interface ExtractedEndpoints {
  readonly endpoints: readonly ApiEndpoint[]
  /** Display label per resource id, recorded as each resource is first seen. */
  readonly labels: ReadonlyMap<string, string>
}

const extractEndpoints = (
  document: Record<string, unknown>,
  format: SpecFormat,
): ExtractedEndpoints => {
  const paths = document.paths
  if (!isRecord(paths)) return { endpoints: [], labels: new Map() }

  const endpoints: ApiEndpoint[] = []
  const labels = new Map<string, string>()
  const endpointId = createEndpointIdAllocator()

  for (const [path, pathItem] of Object.entries(paths)) {
    if (!isRecord(pathItem)) continue

    for (const method of HTTP_METHODS) {
      const operation = pathItem[method.toLowerCase()]
      if (!isRecord(operation)) continue

      const label = resourceNameOf(operation, path)
      const resourceId = `res_${slugify(label)}`

      // First writer wins, so the label is the one the document introduced
      // the resource with rather than the last tag it happened to carry.
      if (!labels.has(resourceId)) labels.set(resourceId, label)

      const body = schemaProperties(document, bodySchemaOf(document, operation, format))
      const response = responseInfoOf(document, operation, format)

      endpoints.push({
        id: endpointId(method, path),
        method,
        path,
        resourceId,
        summary: summaryOf(operation, method, path),
        requiresAuth: isProtected(document, operation),
        pathParams: pathParamsOf(path),
        requiredBodyProps: body.required,
        constrainedBodyProps: body.constrained,
        responseStatuses: [...new Set(response.statuses)].sort((a, b) => a - b),
        responseProps: response.props,
      })
    }
  }

  return { endpoints, labels }
}

/* ------------------------------------------------------------------ *
 * Authentication
 * ------------------------------------------------------------------ */

const SCHEME_MAP: Readonly<Record<string, AuthScheme>> = {
  basic: 'basic',
  bearer: 'bearer',
  oauth2: 'oauth2',
  apiKey: 'apiKey',
}

interface DetectedScheme {
  readonly scheme: AuthScheme
  readonly schemeName: string | null
  readonly headerName: string | null
}

const detectScheme = (
  document: Record<string, unknown>,
  format: SpecFormat,
): DetectedScheme => {
  const container =
    format === 'openapi-3'
      ? (isRecord(document.components) ? document.components.securitySchemes : undefined)
      : document.securityDefinitions

  if (!isRecord(container)) {
    return { scheme: 'none', schemeName: null, headerName: null }
  }

  for (const [name, definition] of Object.entries(container)) {
    if (!isRecord(definition)) continue

    const type = asString(definition.type)
    if (type === null) continue

    if (type === 'http') {
      const httpScheme = asString(definition.scheme)
      const mapped = httpScheme === null ? undefined : SCHEME_MAP[httpScheme]
      if (mapped !== undefined) {
        return { scheme: mapped, schemeName: name, headerName: null }
      }
      continue
    }

    if (type === 'apiKey') {
      return {
        scheme: 'apiKey',
        schemeName: name,
        headerName: definition.in === 'header' ? asString(definition.name) : null,
      }
    }

    const mapped = SCHEME_MAP[type]
    if (mapped !== undefined) {
      return { scheme: mapped, schemeName: name, headerName: null }
    }
  }

  return { scheme: 'none', schemeName: null, headerName: null }
}

/** Endpoint that hands out the credential: an unauthenticated POST that mints one. */
const findTokenSource = (endpoints: readonly ApiEndpoint[]): ApiEndpoint | null => {
  const candidates = endpoints.filter(
    (endpoint) =>
      endpoint.method === 'POST' &&
      !endpoint.requiresAuth &&
      /(login|sign-?in|token|auth)/i.test(endpoint.path),
  )

  if (candidates.length === 0) return null

  // Shortest path first — `/auth/login` beats `/auth/login/otp/verify` — with
  // document order as the tie-breaker.
  return [...candidates].sort((a, b) => a.path.length - b.path.length)[0] ?? null
}

const findTokenField = (endpoint: ApiEndpoint | null): string | null => {
  if (endpoint === null) return null

  return (
    endpoint.responseProps.find((prop) => /^(access_)?token$|^jwt$/i.test(prop)) ?? null
  )
}

/* ------------------------------------------------------------------ *
 * Entry point
 * ------------------------------------------------------------------ */

const serverUrlOf = (
  document: Record<string, unknown>,
  format: SpecFormat,
): string | null => {
  if (format === 'openapi-3') {
    const servers = document.servers
    if (Array.isArray(servers)) {
      for (const server of servers) {
        if (isRecord(server)) {
          const url = asString(server.url)
          if (url !== null && url.trim() !== '') return url.trim()
        }
      }
    }
    return null
  }

  const host = asString(document.host)
  if (host === null) return null

  const schemes = asStringArray(document.schemes)
  const scheme = schemes[0] ?? 'https'
  const basePath = asString(document.basePath) ?? ''

  return `${scheme}://${host}${basePath}`
}

export const parseDocument = (
  document: Record<string, unknown>,
  meta: {
    readonly projectId: string
    readonly filename: string
    readonly source: SpecSource
    readonly content: string
  },
): ParsedSpec => {
  const format = detectFormat(document)

  if (format === null) {
    throw new AgentServiceError({
      code: 'unsupported-format',
      messageKey: 'console.aiTest.errors.unsupportedFormat',
    })
  }

  const info = isRecord(document.info) ? document.info : {}
  const title = asString(info.title)?.trim() ?? ''
  const version = asString(info.version)?.trim() ?? ''

  // The slug is derived from the document itself, so re-uploading the same
  // file produces the same ids and a regenerated plan replaces the old one.
  const slug = `${slugify(title === '' ? meta.filename : title)}_${hashString(meta.content)}`

  const { endpoints, labels } = extractEndpoints(document, format)

  if (endpoints.length === 0) {
    throw new AgentServiceError({
      code: 'no-endpoints',
      messageKey: 'console.aiTest.errors.noEndpoints',
    })
  }

  // Map preserves insertion order, which is the order resources appear in the
  // document — the order a reader would meet them in.
  const resources: readonly ApiResource[] = [...labels].map(([id, name]) => ({
    id,
    name,
    endpointIds: endpoints
      .filter((endpoint) => endpoint.resourceId === id)
      .map((endpoint) => endpoint.id),
  }))

  const detected = detectScheme(document, format)
  const tokenSource = findTokenSource(endpoints)

  const authentication: ApiAuthentication = {
    scheme: detected.scheme,
    schemeName: detected.schemeName,
    headerName: detected.headerName,
    tokenSourceEndpointId: tokenSource?.id ?? null,
    tokenField: findTokenField(tokenSource),
    protectedEndpointCount: endpoints.filter((endpoint) => endpoint.requiresAuth).length,
  }

  const spec: ApiSpec = {
    id: `spec_${slug}`,
    projectId: meta.projectId,
    slug,
    title: title === '' ? meta.filename : title,
    version: version === '' ? '—' : version,
    format,
    source: meta.source,
    filename: meta.filename,
    serverUrl: serverUrlOf(document, format),
    endpointCount: endpoints.length,
    loadedAt: new Date().toISOString(),
  }

  return { spec, endpoints, resources, authentication }
}

/** Decode + parse, for callers that only have the raw document. */
export const parseSpecContent = async (input: SpecInput): Promise<ParsedSpec> => {
  const document = await decodeDocument(input.content)

  return parseDocument(document, {
    projectId: input.projectId,
    filename: input.filename,
    source: input.source,
    content: input.content,
  })
}

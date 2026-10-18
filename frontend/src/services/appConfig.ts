import { apiBaseUrl } from '@/services/baseUrl'

export type DeploymentMode = 'self_hosted' | 'official_cloud'

export interface PublicAuthProvider {
  readonly id: 'github' | 'google'
  readonly configured: boolean
}

export interface PublicAuthConfig {
  readonly deploymentMode: DeploymentMode
  readonly loginRequired: boolean
  readonly guestEnabled: boolean
  readonly providers: readonly PublicAuthProvider[]
}

let cachedConfig: PublicAuthConfig | null = null
let deploymentMode: DeploymentMode = 'self_hosted'

export const getDeploymentMode = (): DeploymentMode => deploymentMode

export const getCachedAuthConfig = (): PublicAuthConfig | null => cachedConfig

export const isGuestExperienceEnabled = (): boolean => {
  const config = cachedConfig
  return config !== null ? config.guestEnabled : getDeploymentMode() === 'self_hosted'
}

const isProvider = (value: unknown): value is PublicAuthProvider => {
  if (typeof value !== 'object' || value === null) return false
  const item = value as Record<string, unknown>
  return (
    (item.id === 'github' || item.id === 'google') &&
    typeof item.configured === 'boolean'
  )
}

const parse = (value: unknown): PublicAuthConfig => {
  if (typeof value !== 'object' || value === null) {
    throw new Error('invalid auth config')
  }
  const item = value as Record<string, unknown>
  if (item.deploymentMode !== 'self_hosted' && item.deploymentMode !== 'official_cloud') {
    throw new Error('invalid deployment mode')
  }
  if (!Array.isArray(item.providers) || !item.providers.every(isProvider)) {
    throw new Error('invalid providers')
  }
  return {
    deploymentMode: item.deploymentMode,
    loginRequired: item.loginRequired === true,
    guestEnabled: item.guestEnabled === true,
    providers: item.providers,
  }
}

export const fetchPublicAuthConfig = async (): Promise<PublicAuthConfig> => {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5_000)
  try {
    const response = await fetch(apiBaseUrl() + '/api/auth/config', {
      credentials: 'include',
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new Error('auth config unavailable')
    }
    const parsed = parse(await response.json())
    cachedConfig = parsed
    deploymentMode = parsed.deploymentMode
    return parsed
  } finally {
    clearTimeout(timeout)
  }
}

export const resetAuthRuntimeForTests = (): void => {
  cachedConfig = null
  deploymentMode = 'self_hosted'
}

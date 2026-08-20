export const ACCESS_TOKEN_KEY = 'modstore_token'
export const REFRESH_TOKEN_KEY = 'modstore_refresh_token'

function getStorage(): Storage | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}

export function getAccessToken(): string {
  return getStorage()?.getItem(ACCESS_TOKEN_KEY) || ''
}

export function getRefreshToken(): string {
  return getStorage()?.getItem(REFRESH_TOKEN_KEY) || ''
}

export function setAuthTokens(tokens: { access_token?: string; refresh_token?: string } | null | undefined): void {
  const storage = getStorage()
  if (!storage) return
  if (tokens?.access_token) storage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
  if (tokens?.refresh_token) storage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
}

export function clearAuthTokens(): void {
  const storage = getStorage()
  if (!storage) return
  storage.removeItem(ACCESS_TOKEN_KEY)
  storage.removeItem(REFRESH_TOKEN_KEY)
}

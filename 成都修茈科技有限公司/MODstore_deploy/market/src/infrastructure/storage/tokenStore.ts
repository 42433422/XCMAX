export const ACCESS_TOKEN_KEY = 'modstore_token'
export const REFRESH_TOKEN_KEY = 'modstore_refresh_token'

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_TOKEN_KEY) || ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
}

export function setAuthTokens(tokens: { access_token?: string; refresh_token?: string } | null | undefined): void {
  if (tokens?.access_token) localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
  if (tokens?.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
}

export function clearAuthTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

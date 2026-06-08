import {
  requestJson,
  fetchZipBlob,
  requestBlob,
  requestStreamBlob,
  requestStreamResponse,
} from '../infrastructure/http/client'
import { getAccessToken, setAuthTokens } from '../infrastructure/storage/tokenStore'

export const req = requestJson
export { fetchZipBlob, requestBlob, requestStreamBlob, requestStreamResponse }
export { getAccessToken, setAuthTokens }

export type AuthResponse = {
  access_token?: string
  refresh_token?: string
  ok?: boolean
  user?: { id: number; username?: string; email?: string }
}

export function setTokensFromAuthResponse(res: AuthResponse | null | undefined) {
  setAuthTokens(res)
}

export function catalogWriteHeaders(): Record<string, string> | undefined {
  const token = (import.meta.env?.VITE_MODSTORE_CATALOG_UPLOAD_TOKEN ?? '').toString().trim()
  return token ? { Authorization: `Bearer ${token}` } : undefined
}

export function authHeaders(): Record<string, string> | undefined {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : undefined
}

export async function authRequest(path: string, init: RequestInit = {}) {
  return req(path, init)
}

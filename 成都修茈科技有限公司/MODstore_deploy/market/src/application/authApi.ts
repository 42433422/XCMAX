import { requestJson } from '../infrastructure/http/client'
import { setAuthTokens } from '../infrastructure/storage/tokenStore'
import type { AuthTokens, MeResponse } from '../domain/auth/types'

export async function login(username: string, password: string): Promise<AuthTokens> {
  const res = await requestJson<AuthTokens>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  setAuthTokens(res)
  return res
}

/**
 * `/api/auth/me` 在 FastAPI 直连下是扁平的 `CurrentUser`，经 Java 网关时
 * 可能多包一层 `{ user: ... }`，调用方应通过 `domain/accountLevel#normalizeMeResponse` 统一处理。
 */
export function me(): Promise<MeResponse> {
  return requestJson<MeResponse>('/api/auth/me')
}

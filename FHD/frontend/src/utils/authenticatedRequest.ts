import { primeCsrfCookie } from '@/api/core'
import { LS_MARKET_ACCESS_TOKEN } from '@/api/marketAccount'
import { clientShellRequestHeaders } from '@/utils/clientShell'
import { readCsrfTokenFromCookie, shouldAttachCsrfHeader } from '@/utils/csrfCookie'

export type AuthenticatedRequestInit = Pick<RequestInit, 'credentials' | 'headers'> & {
  credentials: 'include'
  headers: Record<string, string>
}

function headerRecord(source: HeadersInit = {}): Record<string, string> {
  if (Array.isArray(source)) {
    return Object.fromEntries(
      source
        .filter(([key]) => Boolean(String(key || '').trim()))
        .map(([key, value]) => [String(key), String(value)]),
    )
  }
  if (typeof Headers !== 'undefined' && source instanceof Headers) {
    return Object.fromEntries(source.entries())
  }
  return Object.fromEntries(
    Object.entries(source as Record<string, unknown>)
      .filter(([key, value]) => Boolean(String(key || '').trim()) && value != null)
      .map(([key, value]) => [key, String(value)]),
  )
}

function hasHeader(headers: Record<string, string>, name: string): boolean {
  const wanted = name.toLowerCase()
  return Object.keys(headers).some((key) => key.toLowerCase() === wanted)
}

function readMarketBearer(): string {
  if (typeof window === 'undefined') return ''
  const token = String(window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim()
  if (!token) return ''
  return token.toLowerCase().startsWith('bearer ') ? token : `Bearer ${token}`
}

/**
 * Build credentials and headers for raw desktop fetch calls that mutate business
 * data. Market sessions use their Bearer token; cookie sessions receive a
 * primed double-submit CSRF token instead. Explicit caller authorization always
 * wins over a stored market token.
 */
export async function authenticatedRequestInit(
  method: string,
  initialHeaders: HeadersInit = {},
): Promise<AuthenticatedRequestInit> {
  const headers: Record<string, string> = {
    ...clientShellRequestHeaders(),
    ...headerRecord(initialHeaders),
  }
  if (!hasHeader(headers, 'authorization')) {
    const bearer = readMarketBearer()
    if (bearer) headers.Authorization = bearer
  }

  if (shouldAttachCsrfHeader(method, headers)) {
    let csrfToken = String(readCsrfTokenFromCookie() || '').trim()
    if (!csrfToken) {
      await primeCsrfCookie()
      csrfToken = String(readCsrfTokenFromCookie() || '').trim()
    }
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  }

  return { credentials: 'include', headers }
}

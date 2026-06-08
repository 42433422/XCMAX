import { requestJson } from '../infrastructure/http/client'

function withQuery(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
  if (!params) return path
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    q.set(k, String(v))
  }
  const qs = q.toString()
  return qs ? `${path}?${qs}` : path
}

export async function get<T = unknown>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
): Promise<T> {
  return requestJson<T>(withQuery(path, params), { method: 'GET' })
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

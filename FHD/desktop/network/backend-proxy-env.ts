/** Isolate backend process proxy policy from Electron bootstrapping. */

export function sanitizeBackendProxyEnvValues(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
  bypassRules: string,
): Record<string, string | undefined> {
  const next: Record<string, string | undefined> = { ...env }
  const fallbackProxy =
    String(next.XCAGI_MARKET_FALLBACK_PROXY || '').trim() ||
    String(next.HTTPS_PROXY || next.https_proxy || next.HTTP_PROXY || next.http_proxy || '').trim()
  for (const key of [
    'ALL_PROXY', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'XCMAX_CLI_PROXY',
  ] as const) {
    delete next[key]
  }
  if (fallbackProxy) next.XCAGI_MARKET_FALLBACK_PROXY = fallbackProxy
  next.XCAGI_MARKET_CONNECT_TIMEOUT = String(next.XCAGI_MARKET_CONNECT_TIMEOUT || '20')
  next.XCAGI_MARKET_CONNECT_ATTEMPTS = String(next.XCAGI_MARKET_CONNECT_ATTEMPTS || '3')
  const bypass = bypassRules.split(',').map(s => s.trim()).filter(s => s && s !== '<local>')
  const existing = String(next.NO_PROXY || next.no_proxy || '').split(',').map(s => s.trim()).filter(Boolean)
  const joined = Array.from(new Set([...existing, ...bypass, '::1'])).join(',')
  next.NO_PROXY = joined
  next.no_proxy = joined
  return next
}

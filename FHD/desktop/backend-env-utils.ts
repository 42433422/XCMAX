import fs from 'node:fs'

export function readJsonTextFile(filePath: string): string {
  const buffer = fs.readFileSync(filePath)
  const text = buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe
    ? buffer.toString('utf16le')
    : buffer.toString('utf8')
  return text.replace(/^\uFEFF/, '')
}

export function sanitizeBackendProxyEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
): Record<string, string | undefined> {
  const next: Record<string, string | undefined> = { ...env }
  for (const key of ['ALL_PROXY', 'all_proxy'] as const) {
    const raw = String(next[key] || '').trim().toLowerCase()
    if (
      raw.startsWith('socks://') ||
      raw.startsWith('socks4://') ||
      raw.startsWith('socks5://') ||
      raw.startsWith('socks5h://')
    ) {
      // Prefer HTTP_PROXY for backend httpx; SOCKS needs optional socksio.
      delete next[key]
    }
  }
  return next
}

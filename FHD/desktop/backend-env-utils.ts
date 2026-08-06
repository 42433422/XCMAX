import fs from 'node:fs'

export function readJsonTextFile(filePath: string): string {
  const buffer = fs.readFileSync(filePath)
  const text = buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe
    ? buffer.toString('utf16le')
    : buffer.toString('utf8')
  return text.replace(/^\uFEFF/, '')
}

// OTA / 更新站 / 市场直连绕过清单（与 main.ts 的 OTA_PROXY_BYPASS_RULES 保持一致）。
// 分离到本工具模块，便于单测直接验证，避免依赖 main 模块的运行时副作用。
const OTA_PROXY_BYPASS_RULES =
  'xiu-ci.com,*.xiu-ci.com,update.xcagi.com,*.update.xcagi.com,localhost,127.0.0.1,<local>'

/**
 * 生成传递给后端进程的净化代理环境：
 * - 删除所有代理变量（HTTP/HTTPS/ALL_PROXY 及小写变体、XCMAX_CLI_PROXY），
 *   避免桌面端系统代理被后端 httpx 继承导致流出/升级失败；
 * - 将 OTA 更新站/市场域名并入 NO_PROXY，保证后端直连内部服务。
 */
export function sanitizeBackendProxyEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
): Record<string, string | undefined> {
  const next: Record<string, string | undefined> = { ...env }
  for (const key of [
    'ALL_PROXY',
    'all_proxy',
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'http_proxy',
    'https_proxy',
    'XCMAX_CLI_PROXY',
  ] as const) {
    delete next[key]
  }
  const bypass = OTA_PROXY_BYPASS_RULES.split(',')
    .map(s => s.trim())
    .filter(s => s && s !== '<local>')
  const existing = String(next.NO_PROXY || next.no_proxy || '')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
  const merged = Array.from(new Set([...existing, ...bypass, '::1']))
  const joined = merged.join(',')
  next.NO_PROXY = joined
  next.no_proxy = joined
  return next
}

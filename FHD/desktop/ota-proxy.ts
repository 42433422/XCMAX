import { app, session } from 'electron'
import { execFileSync } from 'node:child_process'
import net from 'node:net'

/** OTA / 更新站直连绕过（setProxy 用逗号；commandLine 用分号）。 */
export const OTA_PROXY_BYPASS_RULES =
  'xiu-ci.com,*.xiu-ci.com,update.xcagi.com,*.update.xcagi.com,localhost,127.0.0.1,<local>'

export function readWindowsInternetProxy(): string | null {
  if (process.platform !== 'win32') {
    return null
  }
  try {
    const enable = execFileSync(
      'reg',
      [
        'query',
        'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings',
        '/v',
        'ProxyEnable',
      ],
      { encoding: 'utf8', windowsHide: true },
    )
    if (!/0x1/.test(enable)) {
      return null
    }
    const server = execFileSync(
      'reg',
      [
        'query',
        'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings',
        '/v',
        'ProxyServer',
      ],
      { encoding: 'utf8', windowsHide: true },
    )
    const match = server.match(/ProxyServer\s+REG_SZ\s+(\S+)/)
    return match?.[1]?.trim() || null
  } catch {
    return null
  }
}

export function buildOtaPacScript(proxyServer: string): string {
  const proxy = proxyServer.replace(/'/g, '')
  return `
function FindProxyForURL(url, host) {
  if (host === 'xiu-ci.com' || dnsDomainIs(host, '.xiu-ci.com') ||
      host === 'update.xcagi.com' || dnsDomainIs(host, '.update.xcagi.com') ||
      host === 'localhost' || host === '127.0.0.1') {
    return 'DIRECT';
  }
  return 'PROXY ${proxy}; DIRECT';
}
`.trim()
}

export function parseProxyEndpoint(proxyServer: string): { host: string; port: number } | null {
  const raw = proxyServer.trim().replace(/^https?:\/\//i, '')
  const parts = raw.split(':')
  if (parts.length !== 2) {
    return null
  }
  const port = Number(parts[1])
  if (!parts[0] || !Number.isFinite(port) || port <= 0) {
    return null
  }
  return { host: parts[0], port: Math.floor(port) }
}

export function isProxyEndpointReachable(proxyServer: string, timeoutMs = 1500): Promise<boolean> {
  const endpoint = parseProxyEndpoint(proxyServer)
  if (!endpoint) {
    return Promise.resolve(false)
  }
  return new Promise(resolve => {
    const socket = net.connect({ host: endpoint.host, port: endpoint.port })
    const done = (ok: boolean) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(ok)
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => done(true))
    socket.once('timeout', () => done(false))
    socket.once('error', () => done(false))
  })
}

export function isProxyEndpointReachableSync(proxyServer: string, timeoutMs = 1200): boolean {
  const endpoint = parseProxyEndpoint(proxyServer)
  if (!endpoint) {
    return false
  }
  if (process.platform === 'win32') {
    try {
      const result = execFileSync(
        'powershell.exe',
        [
          '-NoProfile',
          '-Command',
          `(Test-NetConnection ${endpoint.host} -Port ${endpoint.port} -WarningAction SilentlyContinue).TcpTestSucceeded`,
        ],
        { encoding: 'utf8', timeout: timeoutMs + 800, windowsHide: true },
      ).trim()
      return result === 'True'
    } catch {
      return false
    }
  }
  return false
}

let systemProxyBypassMode: 'direct' | 'pac' | 'system' = 'system'

export function resolveSystemProxyBypassMode(): 'direct' | 'pac' | 'system' {
  return systemProxyBypassMode
}

export async function applyOtaProxyBypass(): Promise<void> {
  const proxyServer =
    readWindowsInternetProxy() ||
    String(process.env.HTTPS_PROXY || process.env.HTTP_PROXY || '').trim() ||
    null
  if (proxyServer) {
    const reachable = await isProxyEndpointReachable(proxyServer)
    if (!reachable) {
      systemProxyBypassMode = 'direct'
      await session.defaultSession.setProxy({ mode: 'direct' })
      return
    }
    systemProxyBypassMode = 'pac'
    await session.defaultSession.setProxy({
      pacScript: buildOtaPacScript(proxyServer),
    })
    return
  }
  systemProxyBypassMode = 'system'
  await session.defaultSession.setProxy({
    mode: 'system',
    proxyBypassRules: OTA_PROXY_BYPASS_RULES,
  })
}

/**
 * 启动早期（app ready 前）注入 OTA 代理相关 commandLine 开关。
 * 系统代理（如 127.0.0.1:7890）未运行时，仍须直连更新站拉取 OTA 元数据与安装包。
 * 必须在主窗口创建前调用；单测环境（XCAGI_DESKTOP_TEST=1）跳过同步探测。
 */
export function configureOtaProxyCommandLine(): void {
  app.commandLine.appendSwitch(
    'proxy-bypass-list',
    OTA_PROXY_BYPASS_RULES.replace(/,/g, ';')
  )
  if (process.env.XCAGI_DESKTOP_TEST !== '1') {
    const configuredProxy = readWindowsInternetProxy()
    if (configuredProxy && !isProxyEndpointReachableSync(configuredProxy)) {
      systemProxyBypassMode = 'direct'
      app.commandLine.appendSwitch('no-proxy-server')
    }
  }
}

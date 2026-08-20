/** 平台运维台（admin-console）与 enterprise frontend 分离构建时的 URL 解析 */
import { isDesktopShell } from '@/utils/desktopShell'

export function isAdminConsoleSpa(): boolean {
  return String(import.meta.env.VITE_XCMAX_ADMIN_CONSOLE || '').trim() === '1'
}

/** 桌面壳或本机桌面后端端口：禁止把管理端指回当前 origin 的 /admin */
function isLocalDesktopBackendOrigin(): boolean {
  if (typeof window === 'undefined') return false
  if (isDesktopShell()) return true
  const { hostname, port } = window.location
  const host = hostname || ''
  if (host !== '127.0.0.1' && host !== 'localhost') return false
  return port === '17500' || port === '5000'
}

export function resolveAdminConsoleOrigin(): string {
  const fromEnv = String(import.meta.env.VITE_ADMIN_CONSOLE_ORIGIN || '')
    .trim()
    .replace(/\/$/, '')
  if (fromEnv) return fromEnv
  if (typeof window !== 'undefined') {
    const { protocol, hostname, port } = window.location
    const host = hostname || '127.0.0.1'
    // 企业 dev :5001 → 管理端 dev :5011（同机不同端口）
    if ((host === '127.0.0.1' || host === 'localhost') && port === '5001') {
      return `${protocol}//${host}:5011`
    }
    // 桌面壳 / 本机 17500：不得回跳本地 /admin（管理端仅独立网页部署）
    if (isLocalDesktopBackendOrigin()) {
      return ''
    }
    return window.location.origin
  }
  return 'http://127.0.0.1:5011'
}

/** 是否可打开管理端 URL（桌面无独立 origin 时为 false） */
export function canOpenAdminConsole(): boolean {
  if (isAdminConsoleSpa()) return true
  return Boolean(resolveAdminConsoleOrigin())
}

function adminConsoleBasePath(): string {
  const origin = resolveAdminConsoleOrigin()
  if (!origin) return ''
  return `${origin}/admin`
}

export function resolveAdminConsoleLoginUrl(redirectPath?: string): string {
  const base = adminConsoleBasePath()
  if (!base) return ''
  const redirect = String(redirectPath || '').trim()
  const q = redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? `?redirect=${encodeURIComponent(redirect)}` : ''
  return `${base}/login${q}`
}

export function resolveAdminConsoleHomeUrl(): string {
  const base = adminConsoleBasePath()
  if (!base) return ''
  return `${base}/xcmax-admin`
}

/** 桌面壳禁止进管理端时的对外提示（与 SSOT：管理端仅网页） */
export const DESKTOP_ADMIN_FORBIDDEN_MESSAGE = '桌面端不支持管理员账号登录，请使用网页版管理端'

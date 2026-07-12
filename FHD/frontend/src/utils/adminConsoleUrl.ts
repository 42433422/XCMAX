/** 平台运维台（admin-console）与 enterprise frontend 分离构建时的 URL 解析 */
export function isAdminConsoleSpa(): boolean {
  return String(import.meta.env.VITE_XCMAX_ADMIN_CONSOLE || '').trim() === '1';
}

export function resolveAdminConsoleOrigin(): string {
  const fromEnv = String(import.meta.env.VITE_ADMIN_CONSOLE_ORIGIN || '').trim().replace(/\/$/, '');
  if (fromEnv) return fromEnv;
  if (typeof window !== 'undefined') {
    const { protocol, hostname, port } = window.location;
    const host = hostname || '127.0.0.1';
    // 企业 dev :5001 → 管理端 dev :5011（同机不同端口）
    if ((host === '127.0.0.1' || host === 'localhost') && port === '5001') {
      return `${protocol}//${host}:5011`;
    }
    // 桌面端（17500/5000/自定义端口）与生产环境：管理端同端口挂载在 /admin，不跳转独立端口
    return window.location.origin;
  }
  return 'http://127.0.0.1:5011';
}

function adminConsoleBasePath(): string {
  return `${resolveAdminConsoleOrigin()}/admin`;
}

export function resolveAdminConsoleLoginUrl(redirectPath?: string): string {
  const redirect = String(redirectPath || '').trim();
  const q =
    redirect && redirect.startsWith('/') && !redirect.startsWith('//')
      ? `?redirect=${encodeURIComponent(redirect)}`
      : '';
  return `${adminConsoleBasePath()}/login${q}`;
}

export function resolveAdminConsoleHomeUrl(): string {
  return `${adminConsoleBasePath()}/xcmax-admin`;
}

/** 桌面壳禁止进管理端时的对外提示（与 SSOT：管理端仅网页） */
export const DESKTOP_ADMIN_FORBIDDEN_MESSAGE =
  '桌面端不支持管理员账号登录，请使用网页版管理端';

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
    if ((host === '127.0.0.1' || host === 'localhost') && port !== '5011') {
      return `${protocol}//${host}:5011`;
    }
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

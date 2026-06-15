import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';

export type ClientShellId = 'admin' | 'enterprise';

/** 与后端 ``X-XCMAX-Client-Shell`` / 分壳 Cookie 对齐 */
export function resolveClientShellId(): ClientShellId {
  return isAdminConsoleSpa() ? 'admin' : 'enterprise';
}

export function clientShellRequestHeaders(): Record<string, string> {
  return { 'X-XCMAX-Client-Shell': resolveClientShellId() };
}

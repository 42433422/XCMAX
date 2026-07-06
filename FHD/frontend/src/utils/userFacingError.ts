import { ApiError } from '@/api/core';

/**
 * 用户可见错误文案统一层（PRODUCT_POLISH_CHECKLIST P0 路径一 / P2 路径六）。
 *
 * 目标：登录、绑定、IM 等界面不得把原始 HTTP/SDK 文案（`请求失败：401`、
 * `Unauthorized`、`Failed to fetch`…）直接 toast 给用户；统一映射为产品级中文，
 * 已是产品文案的服务端 message（如「二维码已过期」）原样透传。
 */

const STATUS_COPY: Record<number, string> = {
  400: '请求无法处理，请检查输入后重试',
  401: '登录已过期，请重新登录或重新扫码绑定',
  403: '当前账号没有权限执行该操作，请切换账号或联系管理员',
  404: '没有找到对应的数据，请刷新后重试',
  408: '连接超时，请检查网络后重试',
  409: '操作冲突，请刷新页面后重试',
  410: '内容已过期，请刷新后重试',
  429: '操作过于频繁，请稍后再试',
};

const NETWORK_COPY = '无法连接服务器，请检查网络或稍后重试';
const SERVER_COPY = '服务暂时不可用，请稍后重试';

/** 服务端偶发返回的过短占位词，不适合直接展示，需按 status 升级为完整文案。 */
const TERSE_MESSAGES = new Set(['未授权', '禁止访问', '无权限', '失败', 'error']);

/** 原始 HTTP/网络/SDK 痕迹：出现即视为「非产品文案」。 */
const RAW_MARKERS =
  /(HTTP\s*\d{3}|status\s*code|request\s*failed|请求失败：?\s*\d|failed\s+to\s+fetch|networkerror|econn|etimedout|timeout|unauthorized|forbidden|internal\s+server\s+error|bad\s+gateway|traceback|exception)/i;

/** message 是否已是可直接展示的中文产品文案。 */
export function looksLikeProductCopy(message: string): boolean {
  const text = String(message || '').trim();
  if (!text) return false;
  if (TERSE_MESSAGES.has(text.toLowerCase())) return false;
  const hasCjk = /[\u4e00-\u9fff]/.test(text);
  return hasCjk && !RAW_MARKERS.test(text);
}

/** 按 HTTP 状态码返回产品级兜底文案。 */
export function statusFallbackCopy(status: number, fallback = '操作失败，请稍后重试'): string {
  if (status === 0) return NETWORK_COPY;
  if (STATUS_COPY[status]) return STATUS_COPY[status];
  if (status >= 500) return SERVER_COPY;
  return fallback;
}

/**
 * 把任意错误转成用户可见文案。
 *
 * 规则：
 * 1. 服务端返回的中文产品文案（如「二维码已过期，请刷新」）原样透传；
 * 2. 原始 HTTP/网络文案按状态码映射为产品级中文；
 * 3. 其余情况使用调用方提供的 fallback。
 */
export function userFacingErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  if (error instanceof ApiError) {
    if (looksLikeProductCopy(error.message)) return error.message;
    return statusFallbackCopy(error.status, fallback);
  }
  if (error instanceof Error) {
    if (looksLikeProductCopy(error.message)) return error.message;
    if (RAW_MARKERS.test(error.message || '')) return NETWORK_COPY;
    return fallback;
  }
  return fallback;
}

/** 二维码/配对码轮询专用：判定 HTTP 错误是否应视为「二维码已过期」。 */
export function isQrExpiredError(error: unknown): boolean {
  return error instanceof ApiError && [401, 404, 410].includes(error.status);
}

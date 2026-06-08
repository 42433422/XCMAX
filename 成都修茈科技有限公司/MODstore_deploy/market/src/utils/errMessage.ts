/** 统一从 catch / API 错误对象取可读字符串，供 strict 模式下使用 */
export function errMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  if (e && typeof e === 'object' && 'message' in e) {
    const m = (e as { message?: unknown }).message
    if (typeof m === 'string') return m
  }
  return String(e)
}

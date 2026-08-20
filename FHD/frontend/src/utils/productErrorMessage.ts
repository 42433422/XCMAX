/**
 * 将 HTTP/SDK 原始错误转为用户可读文案（对齐 Android AppViewModel.productErrorMessage）。
 */
export function productErrorMessage(raw: unknown, fallback: string): string {
  const msg = String(raw instanceof Error ? raw.message : (raw ?? '')).trim()
  const lower = msg.toLowerCase()
  if (!msg) return fallback
  if (lower.includes('401') || msg.includes('未授权') || msg.includes('未登录')) {
    return '登录已过期，请重新登录或重新扫码绑定'
  }
  if (lower.includes('403') || msg.includes('拒绝') || msg.includes('无权限')) {
    return '当前账号没有权限，请切换管理员账号或重新绑定后台'
  }
  if (
    lower.includes('failed to connect') ||
    lower.includes('timeout') ||
    lower.includes('timedout') ||
    lower.includes('network') ||
    lower.includes('econnrefused') ||
    msg.includes('连接')
  ) {
    return '连接不到电脑执行端，已尝试通过服务器中继，请稍后重试'
  }
  if (lower.includes('firebase') || lower.includes('fcm')) {
    return '消息提醒未开启，不影响登录和员工同步'
  }
  if (lower.includes('pairing') || msg.includes('配对') || msg.includes('二维码')) {
    return '配对码已过期或无效，请在电脑端刷新二维码后重试'
  }
  if (msg.length > 80) return fallback
  return msg
}

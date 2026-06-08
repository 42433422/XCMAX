/**
 * 启发式：根据模型目录拉取错误与 fetch_source 推断 warn / danger。
 * 不表示各厂商真实余额，仅辅助 UI（黄/红）。
 */

export interface LlmKeyRow {
  provider?: string
  has_platform_key?: boolean
  has_user_override?: boolean
}

/**
 * resolve_api_key 语义：BYOK（可解密成功）或服务端 platform env 任一存在即运行时可用。
 * 与 /api/llm/catalog 拉目录一致；不因磁贴文案改名。
 */
export function hasAnyLlmKey(row: LlmKeyRow | null | undefined): boolean {
  if (!row) return false
  if (row.has_user_override) return true
  if (row.has_platform_key) return true
  return false
}

/**
 * 钱包磁贴「点亮」语义：仍以 BYOK 为主；仅小米允许仅凭服务端平台密钥视为磁贴「已配置」
 * （与钱包页文案一致）；其它厂商仅用平台密钥时磁贴 dim，避免误判为「我个人的密钥」已就位。
 */
export function walletTileKeyConfigured(
  provider: string,
  row: LlmKeyRow | null | undefined,
): boolean {
  if (!row) return false
  if (row.has_user_override) return true
  if (row.has_platform_key && provider === 'xiaomi') return true
  return false
}

/** danger 磁贴 tooltip 追加：额度/账单类错误的简短提示（启发式）。 */
export function catalogIssueCreditHint(error: string | null | undefined): string | null {
  const e = (error && String(error).toLowerCase()) || ''
  if (!e.trim()) return null
  if (
    e.includes('402') ||
    e.includes('balance') ||
    e.includes('quota') ||
    e.includes('billing') ||
    (e.includes('insufficient') && !e.includes('401'))
  ) {
    return '若提示与额度或账单相关，可能为厂商侧余额、配额或账单未结清（并非密钥格式错误）。'
  }
  return null
}

const DANGER_SUBSTR = [
  '401',
  '403',
  '402',
  'invalid',
  'authentication',
  'incorrect api key',
  'invalid api key',
  'wrong api key',
  'unauthorized',
  'forbidden',
  'insufficient',
  'quota',
  'exhausted',
  'billing',
  'payment',
  'permission denied',
  'not authorized',
  'no_api_key',
  '解密失败',
]

const EXPIRED_SUBSTR = [
  'expired',
  'expire',
  'expires',
  'invalid token',
  'token expired',
  'key expired',
  'api key expired',
  'credential expired',
  'access token expired',
  '已过期',
  '过期',
  '失效',
  '已失效',
]

const WARN_SUBSTR = [
  '429',
  'rate limit',
  'throttl',
  'resource_exhausted',
  'overloaded',
  'timeout',
  'timed out',
  'connect',
  '502',
  '503',
  '504',
  '500',
  'network',
  'unreachable',
  'temporar',
]

export type LlmCatalogIssue = 'warn' | 'danger' | 'expired' | null

export function classifyLlmCatalogIssue(
  error: string | null | undefined,
  fetchSource: string | null | undefined,
): LlmCatalogIssue {
  const e = (error && String(error).toLowerCase()) || ''
  const src = fetchSource ? String(fetchSource) : ''

  for (const p of EXPIRED_SUBSTR) {
    if (e.includes(p)) return 'expired'
  }

  if (src === 'static_fallback_merged') return 'warn'
  if (src === 'fallback_after_error') return 'warn'

  for (const p of DANGER_SUBSTR) {
    if (e.includes(p)) return 'danger'
  }

  for (const p of WARN_SUBSTR) {
    if (e.includes(p)) return 'warn'
  }

  if (e.trim()) return null

  return null
}

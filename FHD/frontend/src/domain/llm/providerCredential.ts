import type { LlmProviderStatus } from './types'

/** 与后端计费/解密一致：平台密钥可用；BYOK 需 Fernet 主密钥已配置 */
export function providerRowHasUsableKey(
  row: LlmProviderStatus | undefined | null,
  fernetConfigured: boolean,
): boolean {
  if (!row) return false
  if (row.has_platform_key) return true
  if (row.has_user_override && fernetConfigured) return true
  return false
}

export function buildProviderStatusMap(
  rows: LlmProviderStatus[] | undefined | null,
): Record<string, LlmProviderStatus> {
  const m: Record<string, LlmProviderStatus> = {}
  for (const r of rows || []) {
    const id = String(r.provider ?? '').trim()
    if (id) m[id] = r
  }
  return m
}

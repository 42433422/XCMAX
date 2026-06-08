/**
 * 与 modstore_server/llm_api.py `llm_status` 返回对齐：
 *   { providers: LlmProviderStatus[], fernet_configured: boolean }
 *
 * 字段源自 llm_key_resolver.credential_status：
 *   - has_platform_key：服务端返回；钱包磁贴与 BYOK 一并视为已配置（平台环境变量密钥）
 *   - has_user_override：用户 BYOK 已上报
 */
export interface LlmProviderStatus {
  provider: string
  label?: string
  has_platform_key?: boolean
  has_user_override?: boolean
  masked_key?: string
  /** 旧字段；磁贴「已配置」：BYOK 或平台环境变量密钥 */
  configured?: boolean
  healthy?: boolean
}

export interface LlmStatusResponse {
  providers: LlmProviderStatus[]
  fernet_configured: boolean
}

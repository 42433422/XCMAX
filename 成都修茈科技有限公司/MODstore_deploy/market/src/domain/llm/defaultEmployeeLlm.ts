import type { LlmProviderStatus, LlmStatusResponse } from './types'
import { providerRowHasUsableKey } from './providerCredential'

/** 无可用密钥或非登录场景时的静态默认（与 createEmpty 一致：运行时由账户密钥解析） */
export const STATIC_DEFAULT_EMPLOYEE_LLM = {
  provider: 'auto',
  model_name: 'auto',
} as const

/** 工作台「自动」：运行时按账户默认与可用密钥解析（与 resolve_llm_provider_model_auto 一致） */
export const AUTO_EMPLOYEE_LLM_SENTINEL = 'auto' as const

/** 目录未返回 models 时的保守默认（与 employeePackClientExport 思路对齐） */
const DEFAULT_MODEL_FOR_PROVIDER: Record<string, string> = {
  openai: 'gpt-4o-mini',
  deepseek: 'deepseek-chat',
  anthropic: 'claude-3-5-sonnet-20241022',
  google: 'gemini-2.0-flash',
  siliconflow: 'Qwen/Qwen2.5-7B-Instruct',
  dashscope: 'qwen-turbo',
  moonshot: 'moonshot-v1-8k',
  xiaomi: 'mimo-v2-flash',
  minimax: 'abab6.5s-chat',
  doubao: 'doubao-pro-32k',
  groq: 'llama-3.3-70b-versatile',
  together: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
  openrouter: 'openai/gpt-4o-mini',
  wenxin: 'ernie-4.0-8k',
  hunyuan: 'hunyuan-turbo',
  zhipu: 'glm-4-flash',
}

function catalogFirstModel(
  catalog: { providers?: Array<{ provider: string; models?: string[] }> } | null | undefined,
  provider: string,
): string | null {
  const block = catalog?.providers?.find((p) => p.provider === provider)
  const models = block?.models
  if (Array.isArray(models) && models.length) {
    const m0 = String(models[0] ?? '').trim()
    return m0 || null
  }
  return null
}

function fallbackModelName(provider: string): string {
  return DEFAULT_MODEL_FOR_PROVIDER[provider] || (provider === 'deepseek' ? 'deepseek-chat' : 'gpt-4o-mini')
}

/**
 * 新建员工 manifest：优先使用当前账号下「平台密钥或可用 BYOK」的第一个厂商（顺序与 /api/llm/status 中 providers 一致），
 * 模型 id 优先取目录该厂商的首个模型，否则用保守默认。
 */
export function resolveDefaultEmployeeLlmFromStatusAndCatalog(
  status: LlmStatusResponse | null | undefined,
  catalog: { providers?: Array<{ provider: string; models?: string[] }> } | null | undefined,
): { provider: string; model_name: string } {
  const rows = status?.providers
  if (!Array.isArray(rows) || !rows.length) {
    return { ...STATIC_DEFAULT_EMPLOYEE_LLM }
  }
  const fernetOk = Boolean(status?.fernet_configured)
  let picked: LlmProviderStatus | undefined
  for (const row of rows) {
    if (providerRowHasUsableKey(row, fernetOk)) {
      picked = row
      break
    }
  }
  if (!picked?.provider) {
    return { ...STATIC_DEFAULT_EMPLOYEE_LLM }
  }
  const provider = String(picked.provider).trim()
  const fromCat = catalogFirstModel(catalog, provider)
  const model_name = fromCat || fallbackModelName(provider)
  return { provider, model_name }
}

import { api } from './core'

/** Butler 四轴参数（0-100，从 MBTI 派生） */
export type ButlerFourAxes = {
  warmth: number
  verbosity: number
  proactiveness: number
  structuredness: number
}

/** Butler profile 视图（UI 可见，不含 MBTI 原始分数） */
export type ButlerProfileView = {
  user_id: string | number
  identity_primary: string
  identity_composite: string
  four_axes: ButlerFourAxes
  mbti_type: string
  mbti_confidence: number
  interaction_count: number
  last_inferred_at: string | null
}

export type ButlerProfileApiResult = {
  success?: boolean
  message?: string
  profile?: ButlerProfileView
  inference?: {
    mbti_type: string
    identity_changed: boolean
    confidence: number
    reasons: string[]
  }
}

export type InteractionPayload = {
  userId?: string | number
  userMessage: string
  assistantMessage: string
  interrupted?: boolean
  corrected?: boolean
}

export type InferPayload = {
  userId?: string | number
  conversations?: Array<{
    user_message: string
    assistant_message: string
    interrupted?: boolean
    corrected?: boolean
  }>
  mod_hints?: string[]
}

/** 与对话流同源：允许 ``web_normal_<session>`` 等字符串 id，禁止再强转丢会话键。 */
function resolveUserId(userId?: string | number): string {
  if (userId === undefined || userId === null) return '1'
  if (typeof userId === 'number') {
    if (!Number.isFinite(userId) || userId <= 0) return '1'
    return String(Math.trunc(userId))
  }
  const text = String(userId).trim()
  return text || '1'
}

export const butlerProfileApi = {
  get(userId?: string | number) {
    return api.get<ButlerProfileApiResult>('/api/butler/profile', {
      user_id: resolveUserId(userId),
    })
  },

  infer(payload: InferPayload = {}) {
    return api.post<ButlerProfileApiResult>('/api/butler/profile/infer', {
      user_id: resolveUserId(payload.userId),
      conversations: payload.conversations || [],
      mod_hints: payload.mod_hints || [],
    })
  },

  recordInteraction(payload: InteractionPayload) {
    return api.post<ButlerProfileApiResult>('/api/butler/profile/interaction', {
      user_id: resolveUserId(payload.userId),
      user_message: payload.userMessage,
      assistant_message: payload.assistantMessage,
      interrupted: payload.interrupted || false,
      corrected: payload.corrected || false,
    })
  },
}

export default butlerProfileApi

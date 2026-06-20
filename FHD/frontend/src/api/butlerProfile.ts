import { api } from './core';

/** Butler 四轴参数（0-100，从 MBTI 派生） */
export type ButlerFourAxes = {
  warmth: number;
  verbosity: number;
  proactiveness: number;
  structuredness: number;
};

/** Butler profile 视图（UI 可见，不含 MBTI 原始分数） */
export type ButlerProfileView = {
  user_id: number;
  identity_primary: string;
  identity_composite: string;
  four_axes: ButlerFourAxes;
  mbti_type: string;
  mbti_confidence: number;
  interaction_count: number;
  last_inferred_at: string | null;
};

export type ButlerProfileApiResult = {
  success?: boolean;
  message?: string;
  profile?: ButlerProfileView;
  inference?: {
    mbti_type: string;
    identity_changed: boolean;
    confidence: number;
    reasons: string[];
  };
};

export type InteractionPayload = {
  userId?: number;
  userMessage: string;
  assistantMessage: string;
  interrupted?: boolean;
  corrected?: boolean;
};

export type InferPayload = {
  userId?: number;
  conversations?: Array<{
    user_message: string;
    assistant_message: string;
    interrupted?: boolean;
    corrected?: boolean;
  }>;
  mod_hints?: string[];
};

function resolveUserId(userId?: number): number {
  return Number(userId || 1) || 1;
}

export const butlerProfileApi = {
  get(userId?: number) {
    return api.get<ButlerProfileApiResult>('/api/butler/profile', {
      user_id: resolveUserId(userId),
    });
  },

  infer(payload: InferPayload = {}) {
    return api.post<ButlerProfileApiResult>('/api/butler/profile/infer', {
      user_id: resolveUserId(payload.userId),
      conversations: payload.conversations || [],
      mod_hints: payload.mod_hints || [],
    });
  },

  recordInteraction(payload: InteractionPayload) {
    return api.post<ButlerProfileApiResult>('/api/butler/profile/interaction', {
      user_id: resolveUserId(payload.userId),
      user_message: payload.userMessage,
      assistant_message: payload.assistantMessage,
      interrupted: payload.interrupted || false,
      corrected: payload.corrected || false,
    });
  },
};

export default butlerProfileApi;

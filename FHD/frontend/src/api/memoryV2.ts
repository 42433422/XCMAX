import { api } from './core';

export type MemoryV2Type = 'preference' | 'entity' | 'episodic';
export type MemoryV2Status = 'pending' | 'active' | 'rejected' | 'deleted';

export type MemoryV2Record = {
  memory_id: string;
  memory_type: MemoryV2Type;
  key: string;
  value: unknown;
  status: MemoryV2Status;
  confidence?: number;
  source?: string;
  evidence?: Array<Record<string, unknown>>;
  created_at?: string;
  updated_at?: string;
  confirmed_at?: string;
  rejected_at?: string;
  deleted_at?: string;
  correction_count?: number;
  [key: string]: unknown;
};

export type MemoryV2Summary = {
  total: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
};

export type MemoryV2ListParams = {
  userId?: string;
  status?: MemoryV2Status;
  memoryType?: MemoryV2Type;
};

export type MemoryV2CandidatePayload = {
  userId?: string;
  memoryType?: MemoryV2Type;
  key: string;
  value: unknown;
  confidence?: number;
  source?: string;
  evidence?: Array<Record<string, unknown>>;
};

export type MemoryV2CorrectionPayload = {
  userId?: string;
  key?: string;
  value?: unknown;
  reason?: string;
};

export type MemoryV2ApiResult = {
  success?: boolean;
  message?: string;
  user_id?: string;
  memories?: MemoryV2Record[];
  summary?: MemoryV2Summary;
  planner_context?: string;
  candidate?: MemoryV2Record;
  memory?: MemoryV2Record;
};

function userParam(userId?: string) {
  return String(userId || 'default').trim() || 'default';
}

function deletePath(memoryId: string, userId?: string, reason?: string) {
  const params = new URLSearchParams({ user_id: userParam(userId) });
  const trimmedReason = String(reason || '').trim();
  if (trimmedReason) params.set('reason', trimmedReason);
  return `/api/memory/v2/${encodeURIComponent(memoryId)}?${params.toString()}`;
}

export const memoryV2Api = {
  list(params: MemoryV2ListParams = {}) {
    return api.get<MemoryV2ApiResult>('/api/memory/v2', {
      user_id: userParam(params.userId),
      status: params.status,
      memory_type: params.memoryType,
    });
  },

  summary(userId?: string) {
    return api.get<MemoryV2ApiResult>('/api/memory/v2/summary', {
      user_id: userParam(userId),
    });
  },

  createCandidate(payload: MemoryV2CandidatePayload) {
    return api.post<MemoryV2ApiResult>('/api/memory/v2/candidates', {
      user_id: userParam(payload.userId),
      memory_type: payload.memoryType || 'preference',
      key: payload.key,
      value: payload.value,
      confidence: payload.confidence,
      source: payload.source,
      evidence: payload.evidence,
    });
  },

  confirm(memoryId: string, userId?: string, correction?: Record<string, unknown>) {
    return api.post<MemoryV2ApiResult>(`/api/memory/v2/${encodeURIComponent(memoryId)}/confirm`, {
      user_id: userParam(userId),
      ...(correction ? { correction } : {}),
    });
  },

  reject(memoryId: string, userId?: string, reason?: string) {
    return api.post<MemoryV2ApiResult>(`/api/memory/v2/${encodeURIComponent(memoryId)}/reject`, {
      user_id: userParam(userId),
      reason: reason || '',
    });
  },

  correct(memoryId: string, payload: MemoryV2CorrectionPayload) {
    return api.patch<MemoryV2ApiResult>(`/api/memory/v2/${encodeURIComponent(memoryId)}`, {
      user_id: userParam(payload.userId),
      key: payload.key,
      value: payload.value,
      reason: payload.reason || '',
    });
  },

  remove(memoryId: string, userId?: string, reason?: string) {
    return api.delete<MemoryV2ApiResult>(deletePath(memoryId, userId, reason));
  },
};

export default memoryV2Api;

import { get, post } from '@/api';

export type ContractLifecycleBlock = {
  status?: string;
  esign_ref?: string;
  esign_provider?: string;
  esign_task?: { task_id?: string; sign_url?: string; provider?: string };
  updated_at?: string;
  history?: Array<Record<string, unknown>>;
};

export type ContractLifecycleStatus = {
  market_user_id: number;
  stage?: string;
  username?: string;
  erp_customer_name?: string;
  contract_lifecycle: ContractLifecycleBlock;
  sign_url?: string;
  party_a_default?: string;
};

export async function fetchContractLifecycleStatus(
  marketUserId: number,
  username = '',
): Promise<ContractLifecycleStatus> {
  const res = (await get('/api/contract-lifecycle/status', {
    market_user_id: marketUserId,
    username,
  })) as { success?: boolean; data?: ContractLifecycleStatus; error?: string };
  if (res?.success === false || !res?.data) {
    throw new Error(res?.error || '加载合同签章状态失败');
  }
  return res.data;
}

export async function startContractEsign(payload: {
  market_user_id: number;
  username?: string;
  party_a?: string;
  party_b?: string;
}): Promise<Record<string, unknown>> {
  const res = (await post('/api/contract-lifecycle/esign/start', payload)) as {
    success?: boolean;
    data?: { pipeline?: Record<string, unknown> };
    error?: string;
  };
  if (res?.success === false) {
    throw new Error(res?.error || '发起电子签失败');
  }
  return res?.data?.pipeline || {};
}

export async function transitionContractLifecycle(payload: {
  market_user_id: number;
  status: string;
  username?: string;
  note?: string;
}): Promise<Record<string, unknown>> {
  const res = (await post('/api/contract-lifecycle/transition', payload)) as {
    success?: boolean;
    data?: { pipeline?: Record<string, unknown> };
    error?: string;
  };
  if (res?.success === false) {
    throw new Error(res?.error || '更新合同状态失败');
  }
  return res?.data?.pipeline || {};
}

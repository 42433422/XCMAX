import api from '@/api/core';

export type UnifiedLedgerEntry = {
  source_type?: string;
  source_id?: string | number;
  track?: string;
  amount_cents?: number;
  status?: string;
  invoice_no?: string;
  payment_ref?: string;
  occurred_at?: string;
  label?: string;
  [key: string]: unknown;
};

export type UnifiedLedgerResult = {
  items: UnifiedLedgerEntry[];
};

export async function getUnifiedLedger(params: {
  market_user_id?: number;
  limit?: number;
  track?: string;
}): Promise<UnifiedLedgerResult> {
  const res = await api.get<{
    ok?: boolean;
    items?: UnifiedLedgerEntry[];
  }>('/api/finance/unified-ledger', params);
  return { items: Array.isArray(res?.items) ? res.items : [] };
}

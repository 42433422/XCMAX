export type UnifiedLedgerEntry = {
  id?: string | number
  amount?: number
  label?: string
  [key: string]: unknown
}

export async function getUnifiedLedger(_params?: {
  market_user_id?: number
  limit?: number
}): Promise<{ items: UnifiedLedgerEntry[] }> {
  return { items: [] }
}

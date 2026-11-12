import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord } from '@/utils/typeGuards'

function nestedData(data: ChatPlannerPayload): Record<string, unknown> {
  return asRecord(asRecord(data.data).data)
}

export function readPlannerBusinessResult(data: ChatPlannerPayload): Record<string, unknown> | undefined {
  const inner = nestedData(data)
  const envelope = asRecord(data.data)
  const businessResult = asRecord(
    data.businessResult || data.business_result || envelope.businessResult || envelope.business_result || inner.businessResult || inner.business_result,
  )
  return Object.keys(businessResult).length ? businessResult : undefined
}

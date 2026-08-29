import { get, post } from './http'
import { requestStreamResponse } from './shared'

export type CustomerDeliveryArtifact = {
  kind: 'module' | 'employee'
  id: string
}

export type CustomerDeliveryTicket = {
  id: number
  ticket_no?: string
  title?: string
  status?: string
  created_at?: string
  updated_at?: string
  custom_delivery?: {
    kind?: 'module' | 'employee' | 'bundle'
    title?: string
    requirements?: string
    acceptance_criteria?: string
    stage?: string
    stage_label?: string
    gate_ok?: boolean
    gate_message?: string
    acceptance_status?: string
    pricing_mode?: 'initial_included' | 'post_delivery_addon' | 'legacy'
    pricing_label?: string
    commerce_ready?: boolean
    commerce_blockers?: string[]
    artifacts?: CustomerDeliveryArtifact[]
    install_receipts?: Array<{ kind?: string; id?: string; version?: string; installed_at?: string }>
    crm?: {
      quote?: { status?: string; quote_no?: string; amount?: number; currency?: string }
      payment?: {
        status?: string
        reference?: string
        amount_paid?: number
        checkout_type?: string
        checkout_path?: string
      }
    }
    delivery_terms?: Record<string, unknown>
  }
}

export type CustomerDeliveryCreateInput = {
  kind: 'module' | 'employee' | 'bundle'
  title: string
  requirements: string
  acceptance_criteria: string
  suggested_id?: string
}

export type DeliveryDownload = {
  blob: Blob
  filename: string
  receiptToken: string
}

export type CustomerDeliveryCheckout = {
  ok: boolean
  order_id: string
  type?: string
  redirect_url?: string
  qr_code?: string
  checkout_path?: string
  total_amount?: string
}

function filenameFromDisposition(value: string | null, fallback: string): string {
  if (!value) return fallback
  const match = value.match(/filename="?([^";]+)"?/i)
  return match?.[1] || fallback
}

export const delivery = {
  customerDeliveryList: (limit = 50) => get<{ items?: CustomerDeliveryTicket[] }>('/api/customer-service/custom-deliveries', { limit }),
  customerDeliveryCreate: (body: CustomerDeliveryCreateInput) =>
    post<CustomerDeliveryTicket>('/api/customer-service/custom-deliveries', body),
  customerDeliveryDecision: (ticketId: number, action: 'accept' | 'rework', note = '') =>
    post<CustomerDeliveryTicket>(`/api/customer-service/custom-deliveries/${encodeURIComponent(String(ticketId))}/decision`, {
      action,
      note,
    }),
  customerDeliveryCheckout: (ticketId: number, payChannel: 'alipay' | 'wechat' = 'alipay') =>
    post<CustomerDeliveryCheckout>(
      `/api/customer-service/custom-deliveries/${encodeURIComponent(String(ticketId))}/payment-checkout`,
      { pay_channel: payChannel },
    ),
  async customerDeliveryDownload(ticketId: number, artifact: CustomerDeliveryArtifact): Promise<DeliveryDownload> {
    const path = `/api/customer-service/custom-deliveries/${encodeURIComponent(String(ticketId))}/artifacts/${encodeURIComponent(artifact.kind)}/download`
    const response = await requestStreamResponse(path, { method: 'GET' })
    const receiptToken = response.headers.get('X-Delivery-Receipt-Token') || ''
    if (!receiptToken) throw new Error('下载响应缺少安装回执令牌，请重试')
    return {
      blob: await response.blob(),
      filename: filenameFromDisposition(
        response.headers.get('Content-Disposition'),
        `${artifact.id}.${artifact.kind === 'employee' ? 'xcemp' : 'zip'}`,
      ),
      receiptToken,
    }
  },
  customerDeliveryInstalled: (
    ticketId: number,
    body: {
      artifact_kind: 'module' | 'employee'
      artifact_id: string
      installed_version?: string
      host?: string
      receipt_token: string
    },
  ) => post<CustomerDeliveryTicket>(`/api/customer-service/custom-deliveries/${encodeURIComponent(String(ticketId))}/installed`, body),
}

// 开发者门户域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const developerEndpoints = {
  // 开发者门户：Personal Access Token
  developerListTokens: () => req('/api/developer/tokens'),
  developerCreateToken: (name: string, scopes: string[] = [], expiresDays: number | null = null) =>
    req('/api/developer/tokens', {
      method: 'POST',
      body: JSON.stringify({ name, scopes, expires_days: expiresDays }),
    }),
  developerRevokeToken: (tokenId: string | number) =>
    req(`/api/developer/tokens/${tokenId}`, { method: 'DELETE' }),

  developerExportKeyBundle: (payload: {
    recipient_public_key_spki_b64: string
    current_password: string
    token_ids: number[]
    rotate_source_tokens?: boolean
  }) =>
    req('/api/developer/key-export/bundle', {
      method: 'POST',
      body: JSON.stringify({
        recipient_public_key_spki_b64: payload.recipient_public_key_spki_b64,
        current_password: payload.current_password,
        token_ids: payload.token_ids,
        rotate_source_tokens: payload.rotate_source_tokens !== false,
      }),
    }),
  developerListKeyExportAudit: (limit = 50) =>
    req(`/api/developer/key-export/audit?limit=${encodeURIComponent(String(limit))}`),

  // 开发者门户：Webhook 订阅
  developerWebhookEventCatalog: () => req('/api/developer/webhooks/event-catalog'),
  developerListWebhooks: () => req('/api/developer/webhooks'),
  developerCreateWebhook: (payload: {
    name: string
    target_url: string
    secret?: string
    enabled_events?: string[]
    description?: string
    is_active?: boolean
  }) => req('/api/developer/webhooks', { method: 'POST', body: JSON.stringify(payload) }),
  developerUpdateWebhook: (
    id: string | number,
    payload: {
      name?: string
      target_url?: string
      secret?: string
      enabled_events?: string[]
      description?: string
      is_active?: boolean
    },
  ) => req(`/api/developer/webhooks/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  developerDeleteWebhook: (id: string | number) =>
    req(`/api/developer/webhooks/${id}`, { method: 'DELETE' }),
  developerListWebhookDeliveries: (
    id: string | number,
    opts: { limit?: number; offset?: number; status?: string } = {},
  ) => {
    const p = new URLSearchParams()
    if (opts.limit) p.set('limit', String(opts.limit))
    if (opts.offset) p.set('offset', String(opts.offset))
    if (opts.status) p.set('status', opts.status)
    const qs = p.toString()
    return req(`/api/developer/webhooks/${id}/deliveries${qs ? `?${qs}` : ''}`)
  },
  developerRetryWebhookDelivery: (deliveryId: string | number) =>
    req(`/api/developer/webhooks/deliveries/${deliveryId}/retry`, { method: 'POST' }),
  developerTestWebhook: (id: string | number) =>
    req(`/api/developer/webhooks/${id}/test`, { method: 'POST' }),
}

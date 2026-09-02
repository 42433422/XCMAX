// 客服域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const customerServiceEndpoints = {
  customerServiceChat: (payload: { message: string; session_id?: number | null; context?: Record<string, unknown> }) =>
    req('/api/customer-service/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
      timeoutMs: 30_000,
    }),
  customerServiceSessions: () => req('/api/customer-service/sessions', { timeoutMs: 15_000 }),
  customerServiceSessionDetail: (id: number | string) =>
    req(`/api/customer-service/sessions/${encodeURIComponent(String(id))}`, { timeoutMs: 15_000 }),
  customerServiceTickets: (status = '') =>
    req(`/api/customer-service/tickets${status ? `?status=${encodeURIComponent(status)}` : ''}`, {
      timeoutMs: 15_000,
    }),
  customerServiceTicketDetail: (id: number | string) =>
    req(`/api/customer-service/tickets/${encodeURIComponent(String(id))}`, { timeoutMs: 15_000 }),
  customerServiceActions: (ticketId?: number | string) =>
    req(
      `/api/customer-service/actions${ticketId ? `?ticket_id=${encodeURIComponent(String(ticketId))}` : ''}`,
      { timeoutMs: 15_000 },
    ),
  customerServiceStandards: () => req('/api/customer-service/standards', { timeoutMs: 15_000 }),
  customerServiceCreateStandard: (payload: unknown) =>
    req('/api/customer-service/standards', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateStandard: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/standards/${encodeURIComponent(String(id))}`, {
      method: 'PUT',
      body: JSON.stringify(payload || {}),
    }),
  customerServiceIntegrations: () => req('/api/customer-service/integrations'),
  customerServiceCreateIntegration: (payload: unknown) =>
    req('/api/customer-service/integrations', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateIntegration: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/integrations/${encodeURIComponent(String(id))}`, {
      method: 'PUT',
      body: JSON.stringify(payload || {}),
    }),
}

import { requestJson } from '../infrastructure/http/client'
import type { AnalyticsDashboard } from '../domain/analytics/types'

export function dashboard(): Promise<AnalyticsDashboard> {
  return requestJson('/api/analytics/dashboard')
}

import { api } from '@/api/core'

export interface PriceListItem {
  model_number: string
  name: string
  spec: string
  unit: string
  unit_price: string
}

export interface GeneratePriceListParams {
  customer_name: string
  products: PriceListItem[]
  printer_name?: string
}

export interface GeneratePriceListResponse {
  success: boolean
  filename?: string
  filepath?: string
  message?: string
  error?: string
}

/**
 * 生成并打印价格表
 */
export async function generate(params: GeneratePriceListParams): Promise<GeneratePriceListResponse> {
  return api.post('/api/price-list/generate', params)
}

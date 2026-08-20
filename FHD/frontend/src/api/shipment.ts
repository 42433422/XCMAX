import { api } from './core'
import type { ApiResponse } from '@/types/api'
import { resolveErpApiPath } from '@/utils/erpDomainPaths'

/** 出货记录行（出货管理 AI 员工打印后拉取用） */
export interface ShipmentRecordRow {
  id?: number
  purchase_unit?: string
  model_number?: string
  product_name?: string
  quantity_tins?: number
  status?: string
  created_at?: string | null
  printed_at?: string | null
}

/** 用于发货预览补全的产品元信息（与 /api/products/list 单行对齐） */
export interface ShipmentProductMeta {
  name?: string
  product_name?: string
  price?: number
  unit_price?: number
  tin_spec?: number
  specification?: number
  spec?: number
}

export interface OrderNumberResult {
  order_number?: string
  next_number?: string
}

const ORDER_NUMBER_CANDIDATES = [
  '/api/shipment/orders/next_number?suffix=A',
  '/orders/next_number?suffix=A',
  '/api/orders/next_number?suffix=A',
]

export const shipmentApi = {
  /** 发货预览补全：按型号查询产品元信息（保持宿主 /api/products/list 路径，与原有裸 fetch 行为一致） */
  getProductMetaForPreview(params: { model: string; unitName?: string }): Promise<ApiResponse<unknown[]>> {
    const query: Record<string, string | number> = {
      keyword: params.model,
      model_number: params.model,
      page: 1,
      per_page: 20,
    }
    if (params.unitName) {
      query.unit = params.unitName
    }
    return api.get<ApiResponse<unknown[]>>('/api/products/list', query)
  },

  /** 依次尝试候选端点，返回第一个合法订单号；全部失败返回空串 */
  async fetchNextOrderNumber(): Promise<string> {
    for (const url of ORDER_NUMBER_CANDIDATES) {
      try {
        const data = await api.get<ApiResponse<OrderNumberResult> & { order_number?: string }>(url)
        const orderNo = String(
          data?.data?.order_number || (data as { order_number?: string })?.order_number || data?.data?.next_number || '',
        ).trim()
        if (orderNo && data?.success !== false) {
          return orderNo
        }
      } catch {
        // 单端点失败继续尝试下一个候选
      }
    }
    return ''
  },

  /** 打印完成后拉取出货记录 */
  getShipmentRecordsForUnit(purchaseUnit: string): Promise<ApiResponse<ShipmentRecordRow[]>> {
    const q = encodeURIComponent(String(purchaseUnit || '').trim())
    return api.get<ApiResponse<ShipmentRecordRow[]>>(resolveErpApiPath(`/api/shipment/shipment-records/records?unit=${q}`))
  },
}

export default shipmentApi

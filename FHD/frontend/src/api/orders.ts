import { api, ApiError } from './core';
import type { ApiResponse } from '@/types/api';
import type { Order } from '@/types/order';
import { resolveErpApiPath } from '@/utils/erpDomainPaths';
import { asRecord } from '@/utils/typeGuards'

const erp = (path: string) => resolveErpApiPath(path);

export const ordersApi = {
  getOrders(params: Record<string, unknown> = {}): Promise<ApiResponse<Order[]>> {
    return api.get<ApiResponse<Order[]>>(erp('/api/orders'), params);
  },

  getOrder(orderNumber: string): Promise<ApiResponse<Order>> {
    return api.get<ApiResponse<Order>>(erp(`/api/orders/${encodeURIComponent(orderNumber)}`));
  },

  getLatestOrders(): Promise<ApiResponse<Order[]>> {
    return api.get<ApiResponse<Order[]>>(erp('/api/orders/latest'));
  },

  searchOrders(query: string): Promise<ApiResponse<Order[]>> {
    return api.get<ApiResponse<Order[]>>(erp('/api/orders/search'), { q: query || '' });
  },

  deleteOrder(orderNumber: string): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(erp(`/api/shipment/orders/${encodeURIComponent(orderNumber)}`));
  },

  clearAllOrders(): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(erp('/api/orders/clear-all'));
  },

  async getShipmentRecordUnits(): Promise<ApiResponse<unknown[]>> {
    try {
      return await api.get<ApiResponse<unknown[]>>(erp('/api/shipment/shipment-records/units'));
    } catch (e: unknown) {
      const st = e instanceof ApiError ? e.status : Number(asRecord(e).status)
      if (st === 404) {
        return api.get<ApiResponse<unknown[]>>(erp('/api/purchase_units'));
      }
      throw e;
    }
  },

  getShipmentRecords(purchaseUnit: string): Promise<ApiResponse<unknown[]>> {
    return api.get<ApiResponse<unknown[]>>(erp('/api/shipment/shipment-records/records'), {
      unit_name: purchaseUnit,
    });
  },

  createShipmentRecord(payload: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>(erp('/api/shipment/shipment-records/record'), payload);
  },

  updateShipmentRecord(payload: unknown): Promise<ApiResponse<unknown>> {
    return api.patch<ApiResponse<unknown>>(erp('/api/shipment/shipment-records/record'), payload);
  },

  deleteShipmentRecord(payload: Record<string, unknown>): Promise<ApiResponse<unknown>> {
    return api.delete<ApiResponse<unknown>>(erp('/api/shipment/shipment-records/record'), payload);
  },

  exportShipmentRecords(purchaseUnit: string, templateId?: string, statusFilter?: string): Promise<Response> {
    return api.download(erp('/api/shipment/shipment-records/export'), {
      unit: purchaseUnit,
      template_id: templateId || '',
      status: statusFilter || ''
    });
  }
};

export default ordersApi;

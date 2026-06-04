import { api } from './index';
import type { ApiResponse } from '@/types/api';
import type { Customer, CustomerCreateDTO, CustomerUpdateDTO } from '@/types/customer';
import { getPersonnelModApiBase } from '@/constants/personnelModApi';

const MOD_BASE = getPersonnelModApiBase();

export const customersApi = {
  getCustomers(params: Record<string, any> = {}): Promise<ApiResponse<Customer[]>> {
    return api.get<ApiResponse<Customer[]>>(`${MOD_BASE}/customers/list`, params);
  },

  getCustomer(id: number | string): Promise<ApiResponse<Customer>> {
    return api.get<ApiResponse<Customer>>(`${MOD_BASE}/customers/${id}`);
  },

  createCustomer(data: CustomerCreateDTO): Promise<ApiResponse<Customer>> {
    return api.post<ApiResponse<Customer>>(`${MOD_BASE}/customers`, data);
  },

  updateCustomer(id: number | string, data: CustomerUpdateDTO): Promise<ApiResponse<Customer>> {
    return api.put<ApiResponse<Customer>>(`${MOD_BASE}/customers/${id}`, data);
  },

  deleteCustomer(id: number | string): Promise<ApiResponse<void>> {
    return api.delete<ApiResponse<void>>(`${MOD_BASE}/customers/${id}`);
  },

  batchDeleteCustomers(customerIds: (number | string)[]): Promise<ApiResponse<void>> {
    return api.post<ApiResponse<void>>(`${MOD_BASE}/customers/batch-delete`, { ids: customerIds });
  },

  exportCustomersXlsx(templateId?: string): Promise<Response> {
    const params: Record<string, any> = {};
    if (templateId) {
      params.template_id = templateId;
    }
    return api.download(`${MOD_BASE}/customers/export`, params);
  },

  importCustomersExcel(formData: FormData): Promise<ApiResponse<any>> {
    return api.post<ApiResponse<any>>(`${MOD_BASE}/customers/import`, formData);
  }
};

export default customersApi;

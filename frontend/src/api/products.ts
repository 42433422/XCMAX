import { api } from './index';
import type { ApiResponse } from '@/types/api';
import type { Product, ProductCreateDTO, ProductUpdateDTO, ProductQueryParams } from '@/types/product';
import { getPersonnelModApiBase } from '@/constants/personnelModApi';

const MOD_BASE = getPersonnelModApiBase();

export const productsApi = {
  getProducts(params: ProductQueryParams = {}): Promise<ApiResponse<Product[]>> {
    return api.get<ApiResponse<Product[]>>(`${MOD_BASE}/products/list`, params);
  },

  syncRemoteYuangonEmployees(): Promise<ApiResponse<{
    employees: number;
    departments: number;
    source_file: string;
    ssh_target: string;
    remote_root: string;
  }>> {
    return api.post<ApiResponse<{
      employees: number;
      departments: number;
      source_file: string;
      ssh_target: string;
      remote_root: string;
    }>>(`${MOD_BASE}/employees/sync-remote-yuangon`, {});
  },

  async getProductUnits(): Promise<{ success: boolean; data: string[]; count: number }> {
    const resp = await api.get(`${MOD_BASE}/customers/list`, { page: 1, per_page: 1000 });
    const list = resp?.data || [];
    return {
      success: true,
      data: (Array.isArray(list) ? list.map((c: any) => c.customer_name).filter(Boolean) : []),
      count: Array.isArray(list) ? list.length : 0
    };
  },

  getProduct(id: number | string): Promise<ApiResponse<Product>> {
    return api.get<ApiResponse<Product>>(`${MOD_BASE}/products/${id}`);
  },

  createProduct(data: ProductCreateDTO): Promise<ApiResponse<Product>> {
    return api.post<ApiResponse<Product>>(`${MOD_BASE}/products/add`, data);
  },

  updateProduct(id: number | string, data: ProductUpdateDTO): Promise<ApiResponse<Product>> {
    return api.post<ApiResponse<Product>>(`${MOD_BASE}/products/update`, { id, ...data });
  },

  deleteProduct(id: number | string, data: Record<string, any> = {}): Promise<ApiResponse<void>> {
    return api.post<ApiResponse<void>>(`${MOD_BASE}/products/delete`, { id, ...data });
  },

  batchDeleteProducts(productIds: (number | string)[]): Promise<ApiResponse<void>> {
    return api.post<ApiResponse<void>>(`${MOD_BASE}/products/batch-delete`, { ids: productIds });
  },

  exportUnitProductsXlsx(params: Record<string, any> = {}): Promise<Response> {
    return api.download(`${MOD_BASE}/products/export.xlsx`, params);
  },

  exportUnitProductsDocx(params: Record<string, any> = {}): Promise<Response> {
    return api.download(`${MOD_BASE}/products/export.docx`, params);
  },

  searchProducts(query: string, unit?: string): Promise<ApiResponse<Product[]>> {
    const params: Record<string, any> = { page: 1, per_page: 20 };
    const q = String(query || '').trim();
    if (q) params.keyword = q;
    if (unit) params.unit = unit;
    return api.get<ApiResponse<Product[]>>(`${MOD_BASE}/products/list`, params);
  },

  getProductNames(params: Record<string, any> = {}): Promise<ApiResponse<any[]>> {
    return api.get<ApiResponse<any[]>>(`${MOD_BASE}/products/product_names`, params);
  },

  searchProductNames(keyword: string): Promise<ApiResponse<any[]>> {
    return api.get<ApiResponse<any[]>>(`${MOD_BASE}/products/product_names/search`, { keyword });
  },

  batchAddProducts(products: ProductCreateDTO[]): Promise<ApiResponse<Product[]>> {
    return api.post<ApiResponse<Product[]>>(`${MOD_BASE}/products/batch`, { products });
  }
};

export default productsApi;

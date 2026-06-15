import { api } from './core';
import type { ApiResponse } from '@/types/api';

export interface Industry {
  id: number;
  name: string;
  code: string;
  description?: string;
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

export const systemApi = {
  getIndustries(): Promise<ApiResponse<Industry[]>> {
    return api.get<ApiResponse<Industry[]>>('/api/system/industries');
  },

  getCurrentIndustry(): Promise<ApiResponse<Industry>> {
    return api.get<ApiResponse<Industry>>('/api/system/industry');
  },

  setIndustry(industryId: number | string): Promise<ApiResponse<Industry>> {
    return api.post<ApiResponse<Industry>>('/api/system/industry', { industry_id: industryId });
  },

  getIndustryDetail(industryId: number | string): Promise<ApiResponse<Industry>> {
    return api.get<ApiResponse<Industry>>(`/api/system/industry/${industryId}`);
  },

  getSystemConfig(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/system/config');
  },

  getHostProfile(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/system/host-profile');
  },

  getIndustryPresets(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/system/industry-presets');
  },

  getWorkflowEmployeeCatalog(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/system/workflow-employee-catalog');
  },

  getEmployeeRegistryRules(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/system/employee-registry-rules');
  },
};

export default systemApi;

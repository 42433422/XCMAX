import { api } from './core';
import type { ApiResponse } from '@/types/api';

export const ocrApi = {
  recognizeText(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/ocr/recognize', data);
  },

  extractStructured(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/ocr/extract', data);
  },

  analyzeText(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/ocr/analyze', data);
  },

  recognizeAndExtract(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/ocr/recognize-and-extract', data);
  }
};

export default ocrApi;

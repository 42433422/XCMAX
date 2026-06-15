import { api } from './core';
import type { ApiResponse } from '@/types/api';

export interface Printer {
  id: number;
  name: string;
  model?: string;
  is_default: boolean;
  status: 'online' | 'offline' | 'error';
  [key: string]: unknown;
}

export const printApi = {
  getPrinters(): Promise<ApiResponse<Printer[]>> {
    return api.get<ApiResponse<Printer[]>>('/api/printers');
  },

  getDefaultPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/default');
  },

  printDocument(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/print/document', data);
  },

  printLabel(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/print/label', data);
  },

  listLabels(): Promise<ApiResponse<unknown[]>> {
    return api.get<ApiResponse<unknown[]>>('/api/print/list_labels');
  },

  printSingleLabel(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/print/single_label', data);
  },

  printByFilename(filename: string): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>(`/api/print/${encodeURIComponent(filename)}`, {});
  },

  validatePrinters(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/print/validate');
  },

  getDocumentPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/document-printer');
  },

  getLabelPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/label-printer');
  },

  getPrinterSelection(): Promise<ApiResponse<{ document_printer?: string; label_printer?: string }>> {
    return api.get<ApiResponse<{ document_printer?: string; label_printer?: string }>>('/api/print/printer-selection');
  },

  savePrinterSelection(data: { document_printer?: string; label_printer?: string }): Promise<ApiResponse<unknown>> {
    return api.put<ApiResponse<unknown>>('/api/print/printer-selection', data);
  }
};

export default printApi;

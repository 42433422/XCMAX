import { api } from './core';
import type { ApiResponse } from '@/types/api';
import { resolveErpApiPath } from '@/utils/erpDomainPaths';

export interface Printer {
  id: number;
  name: string;
  model?: string;
  is_default: boolean;
  status: 'online' | 'offline' | 'error';
  [key: string]: unknown;
}

export interface PrintLabelPayload {
  file_path: string;
  copies?: number;
}

export interface PrintDocumentPayload {
  file_path: string;
}

export interface MarkShipmentPrintedPayload {
  file_path: string;
  order_id?: number;
}

export interface PrintOperationResult {
  success?: boolean;
  message?: string;
  updated?: boolean;
}

export const printApi = {
  getPrinters(): Promise<ApiResponse<Printer[]>> {
    return api.get<ApiResponse<Printer[]>>('/api/printers');
  },

  getDefaultPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/default');
  },

  printDocument(data: PrintDocumentPayload): Promise<ApiResponse<PrintOperationResult>> {
    return api.post<ApiResponse<PrintOperationResult>>(resolveErpApiPath('/api/print/document'), data);
  },

  printLabel(data: PrintLabelPayload): Promise<ApiResponse<PrintOperationResult>> {
    return api.post<ApiResponse<PrintOperationResult>>(resolveErpApiPath('/api/print/label'), data);
  },

  markShipmentPrinted(data: MarkShipmentPrintedPayload): Promise<ApiResponse<PrintOperationResult> & { updated?: boolean }> {
    return api.post<ApiResponse<PrintOperationResult> & { updated?: boolean }>(resolveErpApiPath('/api/shipment/print'), data);
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

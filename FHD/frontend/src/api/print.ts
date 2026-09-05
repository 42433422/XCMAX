import { api } from './core'
import type { ApiResponse } from '@/types/api'
import { resolveErpApiPath } from '@/utils/erpDomainPaths'

export interface Printer {
  id: number
  name: string
  model?: string
  is_default: boolean
  status: 'online' | 'offline' | 'error'
  [key: string]: unknown
}

export interface PrintLabelPayload {
  file_path: string
  copies?: number
}

export interface PrintDocumentPayload {
  file_path: string
}

export interface MarkShipmentPrintedPayload {
  file_path: string
  order_id?: number
}

export interface PrintOperationResult {
  success?: boolean
  message?: string
  updated?: boolean
}

export interface LabelJob {
  id: string
  status: 'generated' | 'generation_failed' | 'submitting' | 'submitted' | 'failed' | 'outcome_unknown'
  message: string
  product_id: number
  product_name: string
  template_id: string
  template_name: string
  copies: number
  paper_width_mm: number
  paper_height_mm: number
  printer?: string
}
export interface LabelJobResponse { success: boolean; job: LabelJob; message?: string }
export interface LabelConfirmation extends LabelJobResponse { confirm_token: string; confirm_prompt: string }

export const printApi = {
  getLabelProducts(params: { keyword: string; page: number; per_page: number }): Promise<ApiResponse<{ id: number; name: string; model_number?: string; specification?: string }[]>> {
    return api.get('/api/print/label-jobs/products', params)
  },
  generateLabelJob(data: { product_id: number; template_id: string; copies: number; paper_width_mm: number; paper_height_mm: number }): Promise<LabelJobResponse> {
    return api.post('/api/print/label-jobs', data)
  },
  getLabelJob(id: string): Promise<LabelJobResponse> {
    return api.get(`/api/print/label-jobs/${encodeURIComponent(id)}`)
  },
  downloadLabelJob(id: string): Promise<Response> {
    return api.download(`/api/print/label-jobs/${encodeURIComponent(id)}/file`)
  },
  confirmLabelJob(id: string): Promise<LabelConfirmation> {
    return api.post(`/api/print/label-jobs/${encodeURIComponent(id)}/confirmation`)
  },
  submitLabelJob(id: string, confirmToken: string): Promise<LabelJobResponse> {
    return api.post(`/api/print/label-jobs/${encodeURIComponent(id)}/submit`, { confirm_token: confirmToken })
  },
  getPrinters(): Promise<ApiResponse<Printer[]>> {
    return api.get<ApiResponse<Printer[]>>('/api/printers')
  },

  getDefaultPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/default')
  },

  printDocument(data: PrintDocumentPayload): Promise<ApiResponse<PrintOperationResult>> {
    return api.post<ApiResponse<PrintOperationResult>>(resolveErpApiPath('/api/print/document'), data)
  },

  printLabel(data: PrintLabelPayload): Promise<ApiResponse<PrintOperationResult>> {
    return api.post<ApiResponse<PrintOperationResult>>(resolveErpApiPath('/api/print/label'), data)
  },

  markShipmentPrinted(data: MarkShipmentPrintedPayload): Promise<ApiResponse<PrintOperationResult> & { updated?: boolean }> {
    return api.post<ApiResponse<PrintOperationResult> & { updated?: boolean }>(resolveErpApiPath('/api/shipment/print'), data)
  },

  listLabels(): Promise<ApiResponse<unknown[]>> {
    return api.get<ApiResponse<unknown[]>>('/api/print/list_labels')
  },

  printSingleLabel(data: unknown): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>('/api/print/single_label', data)
  },

  printByFilename(filename: string): Promise<ApiResponse<unknown>> {
    return api.post<ApiResponse<unknown>>(`/api/print/${encodeURIComponent(filename)}`, {})
  },

  validatePrinters(): Promise<ApiResponse<unknown>> {
    return api.get<ApiResponse<unknown>>('/api/print/validate')
  },

  getDocumentPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/document-printer')
  },

  getLabelPrinter(): Promise<ApiResponse<Printer>> {
    return api.get<ApiResponse<Printer>>('/api/print/label-printer')
  },

  getPrinterSelection(): Promise<ApiResponse<{ document_printer?: string; label_printer?: string }>> {
    return api.get<ApiResponse<{ document_printer?: string; label_printer?: string }>>('/api/print/printer-selection')
  },

  savePrinterSelection(data: { document_printer?: string; label_printer?: string }): Promise<ApiResponse<unknown>> {
    return api.put<ApiResponse<unknown>>('/api/print/printer-selection', data)
  },
}

export default printApi

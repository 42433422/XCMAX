import api from './core';

export type ManualInductMissing = {
  purchase_units: string[];
  product_models: string[];
  customer_names: string[];
  material_codes: string[];
};

export const manualInductApi = {
  preview(payload: {
    target_scope: string;
    purchase_unit?: string;
    rows: Record<string, unknown>[];
  }) {
    return api.post<{
      success: boolean;
      message?: string;
      missing?: ManualInductMissing;
      row_count?: number;
      target_scope?: string;
    }>('/api/excel/manual-induct/preview', payload);
  },

  commit(payload: {
    target_scope: string;
    purchase_unit?: string;
    rows: Record<string, unknown>[];
    create_missing: Partial<Record<keyof ManualInductMissing, string[]>>;
  }) {
    return api.post<{ success: boolean; message?: string; summary?: Record<string, unknown> }>(
      '/api/excel/manual-induct/commit',
      payload
    );
  },

  /** 上传并解析全表行（表头默认第 1 行），与「业务对接」同源 openpyxl 逻辑 */
  extractUpload(file: File, sheetName: string) {
    const fd = new FormData();
    fd.append('excel_file', file);
    if (sheetName) {
      fd.append('sheet_name', sheetName);
    }
    return api.post<{
      success?: boolean;
      rows?: Record<string, unknown>[];
      total_rows?: number;
      message?: string;
    }>('/api/excel/data/extract/upload', fd);
  },
};

export default manualInductApi;

import type { JsonObject, JsonValue } from './json';

export type ExcelCellValue = JsonValue;
export type ExcelRow = Record<string, ExcelCellValue>;
export type ExcelGridRow = ExcelCellValue[];

export interface ExcelFieldInfo {
  name?: string;
  label?: string;
  type?: string;
  [key: string]: unknown;
}

export interface ExcelStyleCache {
  styles?: Record<string, JsonObject>;
  cell_style_refs?: Record<string, string>;
}

export interface ExcelTableSlice {
  table_index?: number;
  header_row?: number;
  fields?: ExcelFieldInfo[];
  sample_rows?: ExcelRow[];
}

export interface ExcelSheetDetail {
  sheet_index?: number;
  sheet_name?: string;
  fields?: ExcelFieldInfo[];
  sample_rows?: ExcelRow[];
  grid_preview?: { rows?: ExcelGridRow[] };
  style_cache?: ExcelStyleCache;
  tables?: ExcelTableSlice[];
}

export interface ExcelPreviewData {
  sheet_name?: string;
  sheet_names?: string[];
  sample_rows?: ExcelRow[];
  grid_preview?: { rows?: ExcelGridRow[] };
  all_sheets?: ExcelSheetDetail[];
  tables?: ExcelTableSlice[];
  grid_style_cache?: ExcelStyleCache;
}

export interface ExcelAnalysisResult {
  fields?: string[];
  sheets?: ExcelSheetDetail[];
  preview_data?: ExcelPreviewData;
}

export interface ExcelExtractGridResponse {
  success?: boolean;
  fields?: ExcelFieldInfo[];
  sheets?: ExcelSheetDetail[];
  preview_data?: ExcelPreviewData;
  message?: string;
}

export interface ExcelTemplateDto {
  id?: string | number;
  name?: string;
  template_name?: string;
  filename?: string;
  category?: string;
  template_type?: string;
  file_path?: string;
  path?: string;
  is_active?: boolean;
  preview_capable?: boolean;
  source?: string;
  exists?: boolean;
  [key: string]: unknown;
}

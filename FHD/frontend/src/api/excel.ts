import { api } from './core';
import type { ApiResponse } from '@/types/api';
import type { ExcelTemplateDto } from '@/types/excel';
import type { StringMap } from '@/types/json';

export interface ExcelTemplate {
  id: string;
  name: string;
  category: 'label_print' | 'excel' | string;
  template_type: string;
  file_path: string;
  is_active: boolean;
  preview_capable: boolean;
  source: 'db' | 'file' | string;
  exists?: boolean;
  filename?: string;
  template_name?: string;
  [key: string]: unknown;
}

function normalizeTemplateDto(tpl: ExcelTemplateDto = {}): ExcelTemplate {
  const templateType = String(tpl.template_type || '');
  const inferCategory =
    /(标签|label|print|打印)/i.test(templateType) ? 'label_print' : 'excel';
  const filePath = String(tpl.file_path || tpl.path || '');
  return {
    ...tpl,
    id: String(tpl.id ?? ''),
    name: String(tpl.name || tpl.template_name || tpl.filename || '未命名模板'),
    category: String(tpl.category || inferCategory),
    template_type: tpl.template_type || '',
    file_path: filePath,
    is_active: Boolean(tpl.is_active ?? true),
    preview_capable: Boolean(tpl.preview_capable ?? (tpl.exists && filePath)),
    source: String(tpl.source || 'db')
  };
}

export const excelApi = {
  async getTemplates(params: StringMap = {}): Promise<ApiResponse<{ templates: ExcelTemplate[] }>> {
    const res = await api.get<ApiResponse<{ templates: ExcelTemplateDto[] }>>('/api/excel/templates', params);
    const raw = res.data as { templates?: ExcelTemplateDto[] } | undefined;
    const templates = Array.isArray(raw?.templates) ? raw.templates : [];
    return {
      ...res,
      data: {
        templates: templates.map(normalizeTemplateDto)
      }
    };
  },

  saveTemplate(data: StringMap): Promise<ApiResponse<ExcelTemplate>> {
    return api.post<ApiResponse<ExcelTemplate>>('/api/excel/template/save', data);
  },

  decomposeTemplate(data: StringMap): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>('/api/excel/template/decompose', data);
  },

  uploadExcel(formData: FormData): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>('/api/excel/upload', formData);
  },

  extractData(data: StringMap): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>('/api/excel/data/extract', data);
  },

  generateExcel(data: StringMap): Promise<ApiResponse<StringMap>> {
    return api.post<ApiResponse<StringMap>>('/api/excel/data/generate', data);
  },

  normalizeTemplateDto
};

export function normalizeTemplateDtoList(items: ExcelTemplateDto[] = []): ExcelTemplate[] {
  return (Array.isArray(items) ? items : []).map(normalizeTemplateDto);
}

export default excelApi;

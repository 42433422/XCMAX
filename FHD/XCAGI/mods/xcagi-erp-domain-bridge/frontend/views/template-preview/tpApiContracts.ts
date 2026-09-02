import type { TplRecord, TplPreviewData } from './tpTemplateMeta'

/**
 * 模板 API 宽松响应契约：后端历史字段较杂，
 * 仅约束前端实际读取的键，未列举键以 unknown 兜底。
 */
export interface TplApiResponse {
  success?: boolean
  message?: string
  [key: string]: unknown
}

/** GET /api/templates 列表返回 */
export interface TplListResponse extends TplApiResponse {
  templates?: TplRecord[]
}

/** GET /api/templates/:id 详情返回 */
export interface TplDetailResponse extends TplApiResponse {
  template?: TplRecord
}

/** POST /api/excel/template/decompose 返回（按真实模板文件分解词条） */
export interface TplDecomposeResponse extends TplApiResponse {
  decomposition?: {
    editable_entries?: unknown[]
    sample_rows?: Record<string, unknown>[]
    [key: string]: unknown
  } | null
}

/** POST /api/templates/extract-grid 返回（Excel 网格提取工具） */
export interface ExtractGridResponse extends TplApiResponse {
  template_name?: string
  fields?: TplRecord['fields']
  preview_data?: TplPreviewData
  [key: string]: unknown
}

/**
 * templatePreviewSanitize.js 的类型声明（原为无类型 JS 模块；供 TS 拆分文件类型引用，无运行时影响）。
 */
export function stripSampleRowsKeepTemplateShape(sampleRows: unknown, fallbackFields: unknown): Record<string, string>[]
export function stripGridPreviewData(gridPreview: unknown, sampleRows: unknown): Record<string, unknown> | null

// 兼容 façade：「全量读取」员工包工具已按职责域拆分（员工ID/响应信封/全量JSON/下载产出/结果汇总），
// 本文件保留原导出面，内部逻辑与原单体行为完全一致。
export {
  GENERATE_EMPLOYEE_IDS,
  isGenerateEmployeeId,
  TABULAR_READ_EMPLOYEE_IDS,
  JSON_REPORT_EMPLOYEE_ID,
  resolveReadEmployeeForExtension,
  isEmployeeExecuteFileExt,
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  suggestEmployeeForUploadedFile,
  readEmployeeDisplayName,
} from './tabular-read/employeeIds'
export type { EmployeeExecuteDiagnostics } from './tabular-read/envelope'
export { normalizeEmployeeExecuteEnvelope, extractDirectPythonPayload } from './tabular-read/envelope'
export { extractDocumentFullJsonText, extractPresentationFullJsonText } from './tabular-read/fullJson'
export {
  extractWordReadStats,
  extractEmployeeExecuteDiagnostics,
  extractEmployeeReadTextForLlm,
  formatEmployeeReadResultSummary,
} from './tabular-read/resultSummary'
export {
  pickDocumentFullJsonDownload,
  pickPresentationFullJsonDownload,
  pickQuantitativeReportDownload,
  parseEmployeeOutputDownloads,
} from './tabular-read/downloads'
export type { EmployeeOutputDownload } from './tabular-read/downloads'

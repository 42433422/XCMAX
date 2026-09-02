// 员工运行时域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { requestBlob } from '../../infrastructure/http/client'
import { req } from './shared'

export const employeeEndpoints = {
  listEmployees: () => req('/api/employees/'),
  getEmployeeStatus: (employeeId: string) => req(`/api/employees/${encodeURIComponent(employeeId)}/status`),
  getEmployeeManifest: async (employeeId: string) => {
    try {
      return await req(`/api/employees/${encodeURIComponent(employeeId)}/manifest`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e || '')
      if (msg.includes('404') || msg.includes('不存在') || msg.includes('Not Found')) {
        return { pack_id: employeeId, name: employeeId, version: '0.0.0', manifest: {} }
      }
      throw e
    }
  },
  /** 管理员：排查员工 manifest 404 — 目录路径、packages.json、Mod 库与可选 pack_id 探测 */
  employeeCatalogManifestDiagnostics: (packId?: string) => {
    const q = packId ? `?pack_id=${encodeURIComponent(packId)}` : ''
    return req(`/api/employees/catalog-manifest-diagnostics${q}`)
  },
  executeEmployeeTask: (employeeId: string, task: string, inputData: unknown) =>
    req(`/api/employees/${employeeId}/execute`, { method: 'POST', body: JSON.stringify({ task, input_data: inputData }) }),
  /** multipart：原始表格给员工包执行（不走知识抽取）；与 Nginx / MODSTORE_EMPLOYEE_FILE_MAX_BYTES 上限一致。 */
  employeeExecuteFile: (
    employeeId: string,
    file: File,
    opts?: {
      task?: string
      inputData?: Record<string, unknown>
      timeoutMs?: number
      template?: File
    },
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.template) form.append('template_file', opts.template)
    form.append('task', opts?.task ?? '')
    form.append('input_data_json', JSON.stringify(opts?.inputData ?? {}))
    return req(`/api/employees/${encodeURIComponent(employeeId)}/execute-file`, {
      method: 'POST',
      body: form,
      timeoutMs: opts?.timeoutMs,
    })
  },
  /** 下载 execute-file 持久化后的产出（需登录，与 employeeExecuteFile 配套）。 */
  employeeOutputDownload: (jobId: string, filename: string) =>
    requestBlob(
      `/api/employees/downloads/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`,
      { method: 'GET' },
    ),
}

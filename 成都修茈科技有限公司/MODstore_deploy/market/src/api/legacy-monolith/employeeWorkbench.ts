// 员工上架 / 工作台域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { authHeaders, req } from './shared'

export const employeeWorkbenchEndpoints = {
  /** 员工上架：LLM 生成 1-5 级测试任务 → 执行 → 量化打分 → 五维审核 */
  employeeBenchTest: (employeeId: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-bench-test', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, provider: provider || null, model: model || null }),
    }),

  /** 员工上架：bench 通过后写入 catalog_store + catalog_items */
  employeePublish: (employeeId: string, opts?: { price?: number; industry?: string; release_channel?: string }) =>
    req('/api/workbench/employee-publish', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, ...(opts || {}) }),
    }),

  /**
   * 保存当前编辑器 manifest 到服务器库（持久化）并通过 vibe-coding 注册 ESkill。
   * 返回保存的 pack_id、已注册 eskill 数量和更新后的 manifest（含 eskill_id）。
   */
  employeeSaveManifest: (
    manifest: unknown,
    employeeId?: string,
    opts?: { provider?: string; model?: string; registerSkills?: boolean },
  ) =>
    req('/api/workbench/employee-save', {
      method: 'POST',
      body: JSON.stringify({
        manifest,
        employee_id: employeeId || null,
        provider: opts?.provider || null,
        model: opts?.model || null,
        register_skills: opts?.registerSkills !== false,
      }),
    }),

  /**
   * 根据当前 manifest 生成完整 .xcemp（含 blueprints.py + employee.py）并下载。
   * 不落盘，直接返回 zip 流。
   * `standalone: true` 时额外打入 zipapp（__main__.py、standalone/），可本机 `python *.xcemp validate`。
   */
  employeeExportZip: async (
    manifest: unknown,
    employeeId?: string,
    opts?: { standalone?: boolean },
  ): Promise<Blob> => {
    const headers = authHeaders() || {}
    headers['Content-Type'] = 'application/json'
    const res = await fetch('/api/workbench/employee-export', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        manifest,
        employee_id: employeeId || null,
        standalone: opts?.standalone === true,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err?.detail || err?.error || `HTTP ${res.status}`))
    }
    return res.blob()
  },

  /**
   * 员工同步测试：bench → 发布到 catalog → 推送到宿主 fhd-sandbox-runtime /api/mod-store/install
   * 成功后员工出现在宿主「一键托管」面板
   */
  employeeSyncTest: (employeeId: string, fhdBaseUrl?: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-sync-test', {
      method: 'POST',
      body: JSON.stringify({
        employee_id: employeeId,
        fhd_base_url: fhdBaseUrl || null,
        provider: provider || null,
        model: model || null,
      }),
    }),
}

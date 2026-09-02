// workflow_employees 员工名片管理：编辑弹窗、从目录/市场挑选、预填跳转（原单体实现原样迁移）。
import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Router } from 'vue-router'
import { api } from '@/api'
import { filterOutPlannedDutyEmployees } from '@/utils/workbenchEmployeeFilter'
import { asLooseRecord, type LooseRecord } from '../../types'
import { EMP_ID_RE, PREFILL_KEY, type EmployeePickRow, type ModAuthoringData, type WorkflowEmployeeViewRow } from './types'
import type { Flash } from './core'

export interface EmployeeModalDeps {
  modData: Ref<ModAuthoringData | null>
  modId: ComputedRef<string>
  router: Router
  flash: Flash
  reload: () => Promise<void>
  manifestSaveWarnings: Ref<string[]>
  workflowEmployeesRows: ComputedRef<WorkflowEmployeeViewRow[]>
}

export function createEmployeeModal(deps: EmployeeModalDeps) {
  const { modData, modId, router, flash, reload, manifestSaveWarnings, workflowEmployeesRows } = deps

  const empModalOpen = ref(false)
  const empModalMode = ref('add')
  const empEditIndex = ref(-1)
  const empDraft = ref({ id: '', label: '', panel_title: '', panel_summary: '' })
  const empScaffoldRouter = ref(false)
  const empModalSaving = ref(false)
  const empModalError = ref('')
  const empModalMergeHint = ref('')
  const empScaffoldDone = ref(false)

  const empPickOpen = ref(false)
  const empPickRows = ref<EmployeePickRow[]>([])
  const empPickLoading = ref(false)
  const empPickError = ref('')
  const empPickSaving = ref(false)

  function slugWorkflowEmpId(raw: string): string {
    let x = String(raw || '')
      .trim()
      .toLowerCase()
      .replace(/\./g, '_')
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
    if (!x || !/^[a-z]/.test(x)) {
      x = `emp${Date.now().toString(36)}`
    }
    x = x.slice(0, 64)
    if (!EMP_ID_RE.test(x)) {
      x = `e${Date.now().toString(36)}`.slice(0, 64)
    }
    return x
  }

  function allocateWorkflowEmployeeId(taken: Set<string>, preferredRaw: string): string {
    const base = slugWorkflowEmpId(preferredRaw)
    if (!taken.has(base)) return base
    for (let i = 2; i < 200; i++) {
      const suf = `x${i}`
      const maxBase = Math.max(1, 64 - suf.length)
      const candidate = `${base.slice(0, maxBase)}${suf}`
      if (!taken.has(candidate) && EMP_ID_RE.test(candidate)) return candidate
    }
    return slugWorkflowEmpId(`emp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`)
  }

  async function openEmployeePickModal() {
    empPickOpen.value = true
    empPickError.value = ''
    empPickRows.value = []
    await loadEmpPickList()
  }

  function closeEmployeePickModal() {
    empPickOpen.value = false
    empPickError.value = ''
    empPickLoading.value = false
  }

  async function loadEmpPickList() {
    empPickLoading.value = true
    empPickError.value = ''
    try {
      const [sqlRows, v1Rows, catalogRes] = await Promise.all([
        api.listEmployees().catch(() => []),
        api.listV1Packages('employee_pack', '', 120, 0).catch(() => ({ packages: [] })),
        api.catalog('', 'employee_pack', 120, 0).catch(() => ({ items: [] })),
      ])
      const merged = new Map<string, EmployeePickRow>()
      for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
        const ex = e as { id?: string; name?: string; version?: string; description?: string }
        const id = String(ex?.id || '').trim()
        if (!id) continue
        merged.set(id, {
          pickKey: id,
          id,
          name: String(ex?.name || id).trim() || id,
          version: String(ex?.version || '').trim(),
          description: typeof ex?.description === 'string' ? ex.description : '',
          sourceLabel: '执行器目录',
        })
      }
      for (const p of v1Rows?.packages || []) {
        const pkg = p as { id?: string; name?: string; version?: string; description?: string }
        const id = String(pkg?.id || '').trim()
        if (!id || merged.has(id)) continue
        merged.set(id, {
          pickKey: id,
          id,
          name: String(pkg?.name || id).trim() || id,
          version: String(pkg?.version || '').trim(),
          description: typeof pkg?.description === 'string' ? pkg.description : '',
          sourceLabel: '本地包目录',
        })
      }
      for (const it of catalogRes?.items || []) {
        const row = it as { pkg_id?: string; name?: string; version?: string; description?: string }
        const pkgId = String(row?.pkg_id || '').trim()
        if (!pkgId || merged.has(pkgId)) continue
        merged.set(pkgId, {
          pickKey: `catalog:${pkgId}`,
          id: pkgId,
          name: String(row?.name || pkgId).trim() || pkgId,
          version: String(row?.version || '').trim(),
          description: typeof row?.description === 'string' ? row.description : '',
          sourceLabel: 'AI 市场',
          catalogPkgId: pkgId,
        })
      }
      empPickRows.value = filterOutPlannedDutyEmployees([...merged.values()]).sort((a, b) =>
        String(a.name).localeCompare(String(b.name), 'zh-CN'),
      )
    } catch (e: unknown) {
      empPickError.value = e instanceof Error ? e.message : String(e)
      empPickRows.value = []
    } finally {
      empPickLoading.value = false
    }
  }

  function goMyEmployees() {
    closeEmployeePickModal()
    router.push({ name: 'workbench-unified', query: { focus: 'employee' } })
  }

  async function confirmPickEmployee(row: { id: string; name: string; description: string; sourceLabel: string; catalogPkgId?: string }) {
    if (empPickSaving.value) return
    empPickSaving.value = true
    empPickError.value = ''
    try {
      const wf = getWorkflowEmployeesArray()
      const taken = new Set<string>()
      for (const x of wf) {
        const id = String(x?.id || '').trim()
        if (id) taken.add(id)
      }
      const internalId = allocateWorkflowEmployeeId(taken, row.id)
      const label = String(row.name || '').trim() || row.id
      const panel_title = String(row.name || '').trim() || row.id
      const panel_summary =
        typeof row.description === 'string' && row.description.trim()
          ? row.description.trim().slice(0, 8000)
          : `来自${row.sourceLabel}的员工包「${row.id}」。`
      const entry: Record<string, string> = {
        id: internalId,
        label,
        panel_title,
        panel_summary,
      }
      const catalogPkgId = String(row.catalogPkgId || row.id || '').trim()
      if (catalogPkgId && (row.sourceLabel === 'AI 市场' || row.catalogPkgId)) {
        entry.catalog_pkg_id = catalogPkgId
      }
      wf.push(entry)
      await persistWorkflowEmployees(wf)
      closeEmployeePickModal()
    } catch (e: unknown) {
      empPickError.value = e instanceof Error ? e.message : String(e)
    } finally {
      empPickSaving.value = false
    }
  }

  function goEmployeePrefill(
    row: Pick<WorkflowEmployeeViewRow, 'index'> & Partial<Pick<WorkflowEmployeeViewRow, 'bodyFull' | 'id' | 'raw' | 'title'>>,
  ) {
    const mid = modId.value
    const wi = row.index
    const desc = row.bodyFull
      ? `声明摘要：${row.bodyFull}\n来源 Mod：${mid}（workflow_employees[${wi}]）。已带入员工制作页预填；也可在本页点「一键登记」写入 /v1/packages，或完成向导后手动登记。`
      : `来自 Mod「${mid}」的 workflow_employees[${wi}]（ID：${row.id || '—'}）。已带入员工制作页预填；也可点「一键登记」或完成向导后登记。`
    try {
      sessionStorage.setItem(
        PREFILL_KEY,
        JSON.stringify({
          modId: mid,
          workflowIndex: wi,
          workflowEmployee: row.raw && typeof row.raw === 'object' ? row.raw : {},
          name: String(row.title || '员工').slice(0, 200),
          description: desc.slice(0, 4000),
        }),
      )
    } catch {
      /* ignore */
    }
    router.push({ name: 'workbench-employee' })
  }

  function getWorkflowEmployeesArray() {
    const raw = modData.value?.manifest?.workflow_employees
    if (!Array.isArray(raw)) return []
    return raw.map(asLooseRecord).map((item) => ({ ...item }))
  }

  function openEmployeeModal(mode: 'add' | 'edit', index = -1) {
    empModalMode.value = mode
    empModalError.value = ''
    empModalMergeHint.value = ''
    empScaffoldDone.value = false
    empScaffoldRouter.value = false
    if (mode === 'add') {
      empEditIndex.value = -1
      empDraft.value = { id: '', label: '', panel_title: '', panel_summary: '' }
    } else {
      empEditIndex.value = index
      const row = workflowEmployeesRows.value.find((r) => r.index === index)
      const o = row?.raw || {}
      empDraft.value = {
        id: typeof o.id === 'string' ? o.id : '',
        label: typeof o.label === 'string' ? o.label : '',
        panel_title: typeof o.panel_title === 'string' ? o.panel_title : '',
        panel_summary: typeof o.panel_summary === 'string' ? o.panel_summary : '',
      }
    }
    empModalOpen.value = true
  }

  function closeEmployeeModal() {
    empModalOpen.value = false
    empModalError.value = ''
    empModalMergeHint.value = ''
    empScaffoldDone.value = false
  }

  async function persistWorkflowEmployees(nextList: LooseRecord[]) {
    const parsed = JSON.parse(JSON.stringify(modData.value?.manifest || {}))
    parsed.workflow_employees = nextList
    await api.putModManifest(modId.value, parsed)
    manifestSaveWarnings.value = []
    flash('员工名片已保存')
    await reload()
  }

  function copyMergeHint() {
    if (!empModalMergeHint.value) return
    navigator.clipboard?.writeText(empModalMergeHint.value).then(
      () => flash('已复制到剪贴板', true),
      () => flash('复制失败', false),
    )
  }

  async function submitEmployeeModal() {
    empModalError.value = ''
    empModalMergeHint.value = ''
    const id = empDraft.value.id.trim()
    const label = empDraft.value.label.trim()
    const panel_title = empDraft.value.panel_title.trim()
    const panel_summary = empDraft.value.panel_summary.trim()
    if (!label) {
      empModalError.value = '请填写显示名（label）'
      return
    }
    if (empModalMode.value === 'add' && !id) {
      empModalError.value = '请填写内部 ID（id）'
      return
    }
    if (empModalMode.value === 'add' && !EMP_ID_RE.test(id)) {
      empModalError.value = '内部 ID 须小写字母开头，仅含小写字母、数字、下划线、连字符（1–64 字符）'
      return
    }
    const wf = getWorkflowEmployeesArray()
    if (empModalMode.value === 'add') {
      if (wf.some((x) => String(x.id || '').trim() === id)) {
        empModalError.value = '该内部 ID 已存在'
        return
      }
    }
    empModalSaving.value = true
    try {
      if (empModalMode.value === 'add' && empScaffoldRouter.value) {
        const res = await api.scaffoldWorkflowEmployee(modId.value, {
          id,
          label,
          panel_title,
          panel_summary,
          template: 'skeleton_router',
          force_auto_merge: false,
        })
        await reload()
        if (res.merge_hint) {
          empModalMergeHint.value = String(res.merge_hint)
          empScaffoldDone.value = true
          flash(
            res.merged_blueprint
              ? '已添加员工；已尝试合并 blueprints。请查看下方合并说明，可复制给开发者。'
              : '已添加员工与占位文件；请按下方说明手动合并 blueprints。',
            true,
          )
        } else {
          flash('已添加员工并生成占位路由', true)
          closeEmployeeModal()
        }
        return
      }
      const entry = { id, label, panel_title, panel_summary }
      if (empModalMode.value === 'add') {
        wf.push(entry)
      } else {
        const idx = empEditIndex.value
        if (idx < 0 || idx >= wf.length) {
          empModalError.value = '索引无效'
          return
        }
        const prev = wf[idx] || {}
        wf[idx] = { ...prev, ...entry, id: typeof prev.id === 'string' && prev.id ? prev.id : id }
      }
      await persistWorkflowEmployees(wf)
      closeEmployeeModal()
    } catch (e) {
      empModalError.value = (e as Error)?.message || String(e)
    } finally {
      empModalSaving.value = false
    }
  }

  async function confirmDeleteEmployee(index: number) {
    const wf = getWorkflowEmployeesArray()
    if (index < 0 || index >= wf.length) return
    const row = wf[index]
    const name = (row && row.label) || row?.id || `第 ${index + 1} 条`
    if (!window.confirm(`确定从 manifest 中删除员工「${name}」？（不会删除已生成的 Python 文件）`)) return
    wf.splice(index, 1)
    empModalSaving.value = true
    try {
      await persistWorkflowEmployees(wf)
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      empModalSaving.value = false
    }
  }

  return {
    empModalOpen,
    empModalMode,
    empEditIndex,
    empDraft,
    empScaffoldRouter,
    empModalSaving,
    empModalError,
    empModalMergeHint,
    empScaffoldDone,
    empPickOpen,
    empPickRows,
    empPickLoading,
    empPickError,
    empPickSaving,
    openEmployeePickModal,
    closeEmployeePickModal,
    goMyEmployees,
    confirmPickEmployee,
    goEmployeePrefill,
    getWorkflowEmployeesArray,
    openEmployeeModal,
    closeEmployeeModal,
    persistWorkflowEmployees,
    copyMergeHint,
    submitEmployeeModal,
    confirmDeleteEmployee,
  }
}

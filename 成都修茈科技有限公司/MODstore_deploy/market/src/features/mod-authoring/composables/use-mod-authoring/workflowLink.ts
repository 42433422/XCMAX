// 工作流关联与员工闭环：链接工作流、画布对齐重试、一键登记（原单体实现原样迁移）。
import { reactive, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Router } from 'vue-router'
import { api } from '@/api'
import { asLooseRecord, type LooseRecord } from '../../types'
import type { ModAuthoringData, WorkflowEmployeeViewRow } from './types'
import type { Flash } from './core'

export interface WorkflowLinkDeps {
  modData: Ref<ModAuthoringData | null>
  modId: ComputedRef<string>
  router: Router
  flash: Flash
  reload: () => Promise<void>
  manifestSaveWarnings: Ref<string[]>
}

export function createWorkflowLink(deps: WorkflowLinkDeps) {
  const { modData, modId, router, flash, reload, manifestSaveWarnings } = deps

  const linkableWorkflows = ref<Array<{ id: number; name?: string }>>([])
  const linkPick = reactive<Record<number, number>>({})
  const linkWorkflowBusy = ref(false)
  /** workflow_employees 行 index，一键登记 API 进行中 */
  const registerCatalogBusy = ref(-1)
  /** 重试「画布 employee 对齐」 */
  const patchWorkflowBusy = ref(false)
  const closureBusy = ref(false)

  function openWorkflowSandboxDecompose(row: Pick<WorkflowEmployeeViewRow, 'linkedWorkflowId'>) {
    const wid = row.linkedWorkflowId
    if (!wid) {
      flash('当前员工条目未声明 workflow_id，请先在 manifest 中关联 MODstore 工作流', false)
      return
    }
    router.push({ name: 'workbench-workflow', query: { edit: String(wid), tab: 'sandbox' } })
  }

  async function loadLinkableWorkflows() {
    try {
      linkableWorkflows.value = (await api.listWorkflows()) || []
    } catch {
      linkableWorkflows.value = []
    }
  }

  async function applyWorkflowLinkToRow(row: { index: number }) {
    const wid = Number(linkPick[row.index])
    if (!modId.value || !Number.isFinite(wid) || wid <= 0) {
      flash('请在下拉框中选择一个工作流', false)
      return
    }
    linkWorkflowBusy.value = true
    try {
      const res = await api.modWorkflowLink(modId.value, {
        workflow_id: wid,
        workflow_index: row.index,
      })
      const mw = Array.isArray(res?.manifest_warnings) ? res.manifest_warnings : []
      if (mw.length) manifestSaveWarnings.value = mw
      flash('已写入 workflow_id，可点「拆解与沙盒测试」', true)
      await reload()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      linkWorkflowBusy.value = false
    }
  }

  async function runWorkflowEmployeeClosure() {
    if (!localStorage.getItem('modstore_token')) {
      flash('请先登录后再执行员工闭环', false)
      return
    }
    if (!modId.value) return
    closureBusy.value = true
    try {
      const res = await api.runWorkflowEmployeeClosure(modId.value, {
        register_missing: true,
        patch_canvas: true,
        industry: String(asLooseRecord(asLooseRecord(modData.value?.manifest).industry).id || '通用'),
      })
      const reg = res?.pack_register
      const regErrs = Array.isArray(reg?.errors) ? reg.errors.length : 0
      if (res?.ok) {
        flash('员工闭环完成：登记与画布已对齐', true)
      } else {
        const gaps = Array.isArray(res?.readiness_after?.gaps) ? res.readiness_after.gaps[0] : ''
        flash(
          regErrs
            ? `闭环已执行，登记有 ${regErrs} 项失败；${gaps || '请查看下方各行'}`
            : `闭环已执行，仍有缺口：${gaps || '请查看下方说明'}`,
          false,
        )
      }
      await reload()
    } catch (e: unknown) {
      const status = (e as { status?: number })?.status
      const msg = (e as Error)?.message || String(e)
      if (status === 404) {
        flash('员工闭环接口未就绪，请刷新页面或联系管理员升级服务区', false)
        return
      }
      flash(msg, false)
    } finally {
      closureBusy.value = false
    }
  }

  async function patchWorkflowEmployeeNodesRetry() {
    if (!localStorage.getItem('modstore_token')) {
      flash('请先登录后再重试图布对齐', false)
      return
    }
    if (!modId.value) return
    patchWorkflowBusy.value = true
    try {
      const res = await api.patchModWorkflowEmployeeNodes(modId.value)
      const patches: LooseRecord[] = Array.isArray(res?.graph_patch?.patches)
        ? (res.graph_patch.patches as unknown[]).map(asLooseRecord)
        : []
      const errs = patches.filter((patch) => typeof patch.error === 'string' && patch.error)
      const skips = patches.filter((patch) => typeof patch.skipped === 'string')
      if (errs.length) {
        flash(`修图部分失败：${errs.map((item) => String(item.error)).join('；')}`, false)
      } else if (res?.employee_readiness?.ok) {
        flash('画布已对齐，员工可用性检查通过', true)
      } else {
        const g = Array.isArray(res?.employee_readiness?.gaps) ? res.employee_readiness.gaps[0] : ''
        const s0 = skips.length ? String(skips[0].skipped || '') : ''
        let msg = '已执行对齐，请查看下方各行说明'
        if (g) msg = `已执行对齐，仍有缺口：${g}`
        if (s0) msg = g ? `${msg}（${s0}）` : `已执行对齐：${s0}`
        flash(msg, false)
      }
      await reload()
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : String(e), false)
    } finally {
      patchWorkflowBusy.value = false
    }
  }

  async function registerWorkflowEmployeeCatalog(row: { index: number }) {
    if (!localStorage.getItem('modstore_token')) {
      flash('请先登录工作台后再一键登记', false)
      return
    }
    registerCatalogBusy.value = row.index
    try {
      const res = await api.registerWorkflowEmployeeCatalog(modId.value, row.index)
      const pkg = res?.package
      const pid = pkg?.id || ''
      const ver = pkg?.version || ''
      const readyRow = Array.isArray(res?.employee_readiness?.employees)
        ? (res.employee_readiness.employees as unknown[]).map(asLooseRecord).find((item) => Number(item.index) === row.index)
        : null
      const nextGap = Array.isArray(readyRow?.gaps) && readyRow.gaps.length ? `；下一步：${readyRow.gaps[0]}` : ''
      flash((pid && ver ? `已登记到本地仓库：${pid} @ ${ver}` : '已登记到本地仓库（/v1/packages）') + nextGap, true)
      await reload()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      registerCatalogBusy.value = -1
    }
  }

  return {
    linkableWorkflows,
    linkPick,
    linkWorkflowBusy,
    registerCatalogBusy,
    patchWorkflowBusy,
    closureBusy,
    openWorkflowSandboxDecompose,
    loadLinkableWorkflows,
    applyWorkflowLinkToRow,
    runWorkflowEmployeeClosure,
    patchWorkflowEmployeeNodesRetry,
    registerWorkflowEmployeeCatalog,
  }
}

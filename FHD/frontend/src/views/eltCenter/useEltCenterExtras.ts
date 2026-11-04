/**
 * 数据对接中心附加动作（拆分自 views/EltCenterView.vue，行为保持一致）：
 * 既有任务的个人模板 / 发货单版式保存、关联客户及产品预演。
 */
import type { ComputedRef } from 'vue'
import type { Router } from 'vue-router'
import { eltApi } from '@/api/elt'
import { tabForRunStatus } from '@/utils/eltRunView'
import type { EltCenterState } from './eltCenterState'
import { createTargetLabel } from './eltCenterShared'

export interface EltCenterExtrasDeps {
  state: EltCenterState
  router: Pick<Router, 'replace'>
  shipmentTemplateCandidate: ComputedRef<Record<string, unknown> | null>
  linkedCustomerProductPreview: ComputedRef<Record<string, unknown> | null>
  schedulePoll: () => void
  syncDraft: () => void
  loadRows: () => Promise<void>
}

export function createEltCenterExtras({
  state,
  router,
  shipmentTemplateCandidate,
  linkedCustomerProductPreview,
  schedulePoll,
  syncDraft,
  loadRows,
}: EltCenterExtrasDeps) {
  const {
    busy,
    pageError,
    runs,
    currentRun,
    targetType,
    templates,
    runRows,
    rowPage,
    rowTotal,
    rowActionFilter,
    shipmentTemplateMessage,
    customerProductPreviewMessage,
    activeTab,
  } = state

  const targetLabel = createTargetLabel(state.capabilities)

  async function saveCurrentAsTemplate() {
    if (busy.value || !currentRun.value) return
    const name = window.prompt('模板名称', `${targetLabel(currentRun.value.target_type)}-${new Date().toLocaleDateString()}`)
    if (!name?.trim()) return
    const isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    try {
      await eltApi.createTemplate({
        name: name.trim(),
        target_type: currentRun.value.target_type,
        draft: currentRun.value.draft,
        source_features: currentRun.value.source_features,
      })
      if (!isCurrent()) return
      const savedTemplates = await eltApi.templates()
      if (isCurrent()) templates.value = savedTemplates
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '模板保存失败'
    } finally {
      finishBusy()
    }
  }

  async function saveCurrentAsShipmentTemplate() {
    if (busy.value || !currentRun.value || currentRun.value.target_type !== 'shipment_records') return
    const run = currentRun.value
    const isCurrent = state.captureReadContext()
    const requestedName = window.prompt('发货单版式名称（可选；留空将按识别到的客户命名）', '')
    if (requestedName === null) return
    const name = requestedName.trim()
    const finishBusy = state.beginBusy()
    shipmentTemplateMessage.value = ''
    try {
      const result = await eltApi.saveShipmentTemplate(
        run.id,
        name,
        String(shipmentTemplateCandidate.value?.source_region_id || ''),
      )
      if (!isCurrent()) return
      const latest = await eltApi.run(run.id)
      if (!isCurrent()) return
      shipmentTemplateMessage.value = result.name ? `已保存“${result.name}”。${result.message}` : result.message
      currentRun.value = latest
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '发货单版式保存失败'
    } finally {
      finishBusy()
    }
  }

  async function previewCustomerProductsFromShipment() {
    if (busy.value || !currentRun.value || currentRun.value.target_type !== 'shipment_records') return
    let isCurrent = state.captureReadContext()
    const sourceRun = currentRun.value
    const linkedRunId = String(linkedCustomerProductPreview.value?.run_id || '').trim()
    if (linkedRunId) {
      const finishBusy = state.beginBusy()
      pageError.value = ''
      try {
        const customerProductRun = await eltApi.run(linkedRunId)
        if (!isCurrent()) return
        currentRun.value = customerProductRun
        targetType.value = 'customer_products'
        rowPage.value = 1
        rowActionFilter.value = ''
        runRows.value = []
        rowTotal.value = 0
        if (!runs.value.some((run) => run.id === customerProductRun.id)) {
          runs.value = [customerProductRun, ...runs.value]
        }
        customerProductPreviewMessage.value = '这是同一上传文件自动建立的客户及产品导入任务；尚未执行，不会写入客户库或产品库。'
        syncDraft()
        activeTab.value = tabForRunStatus(customerProductRun.status)
        isCurrent = state.captureReadContext()
        if (customerProductRun.status === 'preview_ready') await loadRows()
        if (!isCurrent()) return
        await router.replace({
          path: '/business-docking',
          query: { run_id: customerProductRun.id },
        })
        if (isCurrent()) schedulePoll()
      } catch (error) {
        if (isCurrent()) pageError.value = error instanceof Error ? error.message : '读取关联客户及产品任务失败'
      } finally {
        finishBusy()
      }
      return
    }
    if (!sourceRun.upload_id) {
      pageError.value = '原始上传文件不可用，无法创建客户及产品导入。请重新上传该工作簿。'
      return
    }
    const finishBusy = state.beginBusy()
    pageError.value = ''
    shipmentTemplateMessage.value = ''
    customerProductPreviewMessage.value = ''
    try {
      const customerProductRun = await eltApi.preview({
        upload_id: sourceRun.upload_id,
        target_type: 'customer_products',
      })
      if (!isCurrent()) return
      currentRun.value = customerProductRun
      targetType.value = 'customer_products'
      rowPage.value = 1
      rowActionFilter.value = ''
      runRows.value = []
      rowTotal.value = 0
      const retainedRuns = runs.value.some((run) => run.id === sourceRun.id) ? runs.value : [sourceRun, ...runs.value]
      runs.value = [customerProductRun, ...retainedRuns.filter((run) => run.id !== customerProductRun.id)]
      customerProductPreviewMessage.value = '已从同一上传文件创建客户及产品导入任务；请核对后点击“写入数据库”。'
      syncDraft()
      activeTab.value = 'preview'
      isCurrent = state.captureReadContext()
      await router.replace({
        path: '/business-docking',
        query: { run_id: customerProductRun.id },
      })
      if (!isCurrent()) return
      if (customerProductRun.status === 'preview_ready') await loadRows()
      if (isCurrent()) schedulePoll()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '创建客户及产品导入失败'
    } finally {
      finishBusy()
    }
  }

  return {
    saveCurrentAsTemplate,
    saveCurrentAsShipmentTemplate,
    previewCustomerProductsFromShipment,
  }
}

export type EltCenterExtras = ReturnType<typeof createEltCenterExtras>

/**
 * 数据对接中心附加动作（拆分自 views/EtlCenterView.vue，行为保持一致）：
 * Webhook 配置、个人模板 / 发货单版式保存、客户及产品导入创建。
 */
import type { ComputedRef } from 'vue'
import type { Router } from 'vue-router'
import { etlApi } from '@/api/etl'
import { tabForRunStatus } from '@/utils/etlRunView'
import type { EtlCenterState } from './etlCenterState'
import { createTargetLabel } from './etlCenterShared'

export interface EtlCenterExtrasDeps {
  state: EtlCenterState
  router: Pick<Router, 'replace'>
  shipmentTemplateCandidate: ComputedRef<Record<string, unknown> | null>
  linkedCustomerProductPreview: ComputedRef<Record<string, unknown> | null>
  schedulePoll: () => void
  syncDraft: () => void
  loadRows: () => Promise<void>
}

export function createEtlCenterExtras({
  state,
  router,
  shipmentTemplateCandidate,
  linkedCustomerProductPreview,
  schedulePoll,
  syncDraft,
  loadRows,
}: EtlCenterExtrasDeps) {
  const {
    busy,
    pageError,
    runs,
    currentRun,
    targetType,
    templates,
    targetConfigs,
    targetConfigId,
    runRows,
    rowPage,
    rowTotal,
    rowActionFilter,
    showWebhookForm,
    webhookDraft,
    webhookTestMessage,
    shipmentTemplateMessage,
    customerProductPreviewMessage,
    activeTab,
  } = state

  const targetLabel = createTargetLabel(state.capabilities)

  async function saveWebhook() {
    if (busy.value) return
    const isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    try {
      const headers = JSON.parse(webhookDraft.headersJson || '{}')
      if (!headers || Array.isArray(headers) || typeof headers !== 'object') {
        throw new Error('普通请求头必须是 JSON 对象')
      }
      const config = await etlApi.createTargetConfig({
        name: webhookDraft.name,
        endpoint_url: webhookDraft.endpoint_url,
        headers,
        secret: webhookDraft.secret,
      })
      if (!isCurrent()) return
      const configs = await etlApi.targetConfigs()
      if (!isCurrent()) return
      targetConfigs.value = configs
      targetConfigId.value = config.id
      showWebhookForm.value = false
      webhookDraft.name = ''
      webhookDraft.endpoint_url = ''
      webhookDraft.headersJson = '{}'
      webhookDraft.secret = ''
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : 'Webhook 配置保存失败'
    } finally {
      finishBusy()
    }
  }

  async function testWebhook() {
    const configId = targetConfigId.value
    if (busy.value || !configId) return
    const ownsContext = state.captureReadContext()
    const isCurrent = () => ownsContext() && configId === targetConfigId.value
    const finishBusy = state.beginBusy()
    webhookTestMessage.value = ''
    try {
      await etlApi.testTarget(configId)
      if (isCurrent()) webhookTestMessage.value = '连接测试成功'
    } catch (error) {
      if (isCurrent()) webhookTestMessage.value = error instanceof Error ? error.message : '连接测试失败'
    } finally {
      finishBusy()
    }
  }

  async function saveCurrentAsTemplate() {
    if (busy.value || !currentRun.value) return
    const name = window.prompt('模板名称', `${targetLabel(currentRun.value.target_type)}-${new Date().toLocaleDateString()}`)
    if (!name?.trim()) return
    const isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    try {
      await etlApi.createTemplate({
        name: name.trim(),
        target_type: currentRun.value.target_type,
        draft: currentRun.value.draft,
        source_features: currentRun.value.source_features,
      })
      if (!isCurrent()) return
      const savedTemplates = await etlApi.templates()
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
      const result = await etlApi.saveShipmentTemplate(
        run.id,
        name,
        String(shipmentTemplateCandidate.value?.source_region_id || ''),
      )
      if (!isCurrent()) return
      const latest = await etlApi.run(run.id)
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
        const customerProductRun = await etlApi.run(linkedRunId)
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
      const customerProductRun = await etlApi.preview({
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
    saveWebhook,
    testWebhook,
    saveCurrentAsTemplate,
    saveCurrentAsShipmentTemplate,
    previewCustomerProductsFromShipment,
  }
}

export type EtlCenterExtras = ReturnType<typeof createEtlCenterExtras>

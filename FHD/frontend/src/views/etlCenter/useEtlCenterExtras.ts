/**
 * 数据对接中心附加动作（拆分自 views/EtlCenterView.vue，行为保持一致）：
 * Webhook 配置、个人模板 / 发货单版式保存、客户及产品导入创建。
 */
import type { ComputedRef } from 'vue'
import type { Router } from 'vue-router'
import { etlApi, type EtlRun } from '@/api/etl'
import { tabForRunStatus } from '@/utils/etlRunView'
import type { EtlCenterState } from './etlCenterState'
import { createTargetLabel } from './etlCenterShared'

export interface EtlCenterExtrasDeps {
  state: EtlCenterState
  router: Pick<Router, 'replace'>
  shipmentTemplateCandidate: ComputedRef<Record<string, unknown> | null>
  linkedCustomerProductPreview: ComputedRef<Record<string, unknown> | null>
  schedulePoll: () => void
  tryAutoWrite: (run: EtlRun) => Promise<void>
  markAutoWrite: (runId: string) => void
  syncDraft: () => void
  loadRows: () => Promise<void>
}

export function createEtlCenterExtras({
  state,
  router,
  shipmentTemplateCandidate,
  linkedCustomerProductPreview,
  schedulePoll,
  tryAutoWrite,
  markAutoWrite,
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
    autoWriteEnabled,
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
    busy.value = true
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
      targetConfigs.value = await etlApi.targetConfigs()
      targetConfigId.value = config.id
      showWebhookForm.value = false
      webhookDraft.name = ''
      webhookDraft.endpoint_url = ''
      webhookDraft.headersJson = '{}'
      webhookDraft.secret = ''
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : 'Webhook 配置保存失败'
    } finally {
      busy.value = false
    }
  }

  async function testWebhook() {
    if (!targetConfigId.value) return
    busy.value = true
    webhookTestMessage.value = ''
    try {
      await etlApi.testTarget(targetConfigId.value)
      webhookTestMessage.value = '连接测试成功'
    } catch (error) {
      webhookTestMessage.value = error instanceof Error ? error.message : '连接测试失败'
    } finally {
      busy.value = false
    }
  }

  async function saveCurrentAsTemplate() {
    if (!currentRun.value) return
    const name = window.prompt('模板名称', `${targetLabel(currentRun.value.target_type)}-${new Date().toLocaleDateString()}`)
    if (!name?.trim()) return
    busy.value = true
    try {
      await etlApi.createTemplate({
        name: name.trim(),
        target_type: currentRun.value.target_type,
        draft: currentRun.value.draft,
        source_features: currentRun.value.source_features,
      })
      templates.value = await etlApi.templates()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '模板保存失败'
    } finally {
      busy.value = false
    }
  }

  async function saveCurrentAsShipmentTemplate() {
    if (!currentRun.value || currentRun.value.target_type !== 'shipment_records') return
    const requestedName = window.prompt('发货单版式名称（可选；留空将按识别到的客户命名）', '')
    if (requestedName === null) return
    const name = requestedName.trim()
    busy.value = true
    shipmentTemplateMessage.value = ''
    try {
      const result = await etlApi.saveShipmentTemplate(
        currentRun.value.id,
        name,
        String(shipmentTemplateCandidate.value?.source_region_id || ''),
      )
      shipmentTemplateMessage.value = result.name ? `已保存“${result.name}”。${result.message}` : result.message
      currentRun.value = await etlApi.run(currentRun.value.id)
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '发货单版式保存失败'
    } finally {
      busy.value = false
    }
  }

  async function previewCustomerProductsFromShipment() {
    if (!currentRun.value || currentRun.value.target_type !== 'shipment_records') return
    const sourceRun = currentRun.value
    const linkedRunId = String(linkedCustomerProductPreview.value?.run_id || '').trim()
    if (linkedRunId) {
      busy.value = true
      pageError.value = ''
      try {
        const customerProductRun = await etlApi.run(linkedRunId)
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
        if (customerProductRun.status === 'preview_ready') await loadRows()
        await router.replace({
          path: '/business-docking',
          query: { run_id: customerProductRun.id },
        })
        schedulePoll()
      } catch (error) {
        pageError.value = error instanceof Error ? error.message : '读取关联客户及产品任务失败'
      } finally {
        busy.value = false
      }
      return
    }
    if (!sourceRun.upload_id) {
      pageError.value = '原始上传文件不可用，无法创建客户及产品导入。请重新上传该工作簿。'
      return
    }
    busy.value = true
    pageError.value = ''
    shipmentTemplateMessage.value = ''
    customerProductPreviewMessage.value = ''
    try {
      const customerProductRun = await etlApi.preview({
        upload_id: sourceRun.upload_id,
        target_type: 'customer_products',
      })
      currentRun.value = customerProductRun
      targetType.value = 'customer_products'
      rowPage.value = 1
      rowActionFilter.value = ''
      runRows.value = []
      rowTotal.value = 0
      const retainedRuns = runs.value.some((run) => run.id === sourceRun.id) ? runs.value : [sourceRun, ...runs.value]
      runs.value = [customerProductRun, ...retainedRuns.filter((run) => run.id !== customerProductRun.id)]
      customerProductPreviewMessage.value = '已从同一上传文件创建客户及产品导入任务；请核对后点击“写入数据库”。'
      if (autoWriteEnabled.value) markAutoWrite(customerProductRun.id)
      syncDraft()
      activeTab.value = 'preview'
      await router.replace({
        path: '/business-docking',
        query: { run_id: customerProductRun.id },
      })
      if (customerProductRun.status === 'preview_ready' && autoWriteEnabled.value) {
        await tryAutoWrite(customerProductRun)
      } else {
        schedulePoll()
      }
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '创建客户及产品导入失败'
    } finally {
      busy.value = false
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

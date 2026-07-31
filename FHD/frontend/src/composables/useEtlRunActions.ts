import type { Ref } from 'vue'
import type { Router } from 'vue-router'
import { etlApi, type EtlRun, type EtlTargetConfig, type EtlTemplate } from '@/api/etl'
import { tabForRunStatus, type EtlRunTab } from '@/utils/etlRunView'

interface EtlRunActionsOptions {
  currentRun: Ref<EtlRun | null>
  runs: Ref<EtlRun[]>
  templates: Ref<EtlTemplate[]>
  targetConfigs: Ref<EtlTargetConfig[]>
  targetType: Ref<string>
  targetConfigId: Ref<string>
  activeTab: Ref<EtlRunTab>
  rowPage: Ref<number>
  rowActionFilter: Ref<string>
  runRows: Ref<unknown[]>
  rowTotal: Ref<number>
  busy: Ref<boolean>
  pageError: Ref<string>
  personalTemplateName: Ref<string>
  shipmentTemplateName: Ref<string>
  shipmentTemplateMessage: Ref<string>
  customerProductPreviewMessage: Ref<string>
  showWebhookForm: Ref<boolean>
  webhookDraft: { name: string; endpoint_url: string; headersJson: string; secret: string }
  webhookTestMessage: Ref<string>
  shipmentTemplateCandidate: Readonly<Ref<Record<string, unknown> | null>>
  linkedCustomerProductPreview: Readonly<Ref<Record<string, unknown> | null>>
  workbookRootRunId: Readonly<Ref<string>>
  router: Router
  syncDraft: () => void
  schedulePoll: () => void
  loadRows: () => Promise<void>
}

export function useEtlRunActions(options: EtlRunActionsOptions) {
  const {
    currentRun,
    runs,
    templates,
    targetConfigs,
    targetType,
    targetConfigId,
    activeTab,
    rowPage,
    rowActionFilter,
    runRows,
    rowTotal,
    busy,
    pageError,
    personalTemplateName,
    shipmentTemplateName,
    shipmentTemplateMessage,
    customerProductPreviewMessage,
    showWebhookForm,
    webhookDraft,
    webhookTestMessage,
    shipmentTemplateCandidate,
    linkedCustomerProductPreview,
    workbookRootRunId,
    router,
    syncDraft,
    schedulePoll,
    loadRows,
  } = options

  async function saveCurrentAsTemplate() {
    if (!currentRun.value) return
    const name = personalTemplateName.value.trim()
    if (!name) {
      pageError.value = '请输入个人模板名称'
      return
    }
    busy.value = true
    try {
      await etlApi.createTemplate({
        name,
        target_type: currentRun.value.target_type,
        draft: currentRun.value.draft,
        source_features: currentRun.value.source_features,
      })
      templates.value = await etlApi.templates()
      personalTemplateName.value = ''
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '模板保存失败'
    } finally {
      busy.value = false
    }
  }

  async function saveCurrentAsShipmentTemplate() {
    if (!currentRun.value || currentRun.value.target_type !== 'shipment_records') return
    const name = shipmentTemplateName.value.trim()
    busy.value = true
    shipmentTemplateMessage.value = ''
    try {
      const result = await etlApi.saveShipmentTemplate(
        currentRun.value.id,
        name,
        String(shipmentTemplateCandidate.value?.source_region_id || ''),
      )
      shipmentTemplateMessage.value = result.name
        ? `已保存“${result.name}”。${result.message}`
        : result.message
      shipmentTemplateName.value = ''
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
        customerProductPreviewMessage.value = '这是同一上传文件自动建立的客户及产品预演；尚未执行，不会写入客户库或产品库。'
        syncDraft()
        activeTab.value = tabForRunStatus(customerProductRun.status)
        if (customerProductRun.status === 'preview_ready') await loadRows()
        await router.replace({ path: '/business-docking', query: { run_id: customerProductRun.id } })
        schedulePoll()
      } catch (error) {
        pageError.value = error instanceof Error ? error.message : '读取关联客户及产品预演失败'
      } finally {
        busy.value = false
      }
      return
    }
    if (!sourceRun.upload_id) {
      pageError.value = '原始上传文件不可用，无法创建客户及产品预演。请重新上传该工作簿。'
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
      const retainedRuns = runs.value.some((run) => run.id === sourceRun.id)
        ? runs.value
        : [sourceRun, ...runs.value]
      runs.value = [customerProductRun, ...retainedRuns.filter((run) => run.id !== customerProductRun.id)]
      customerProductPreviewMessage.value = '已从同一上传文件创建客户及产品预演；请先核对附表规划与行级结果，点击“确认执行”前不会写入客户库或产品库。'
      syncDraft()
      activeTab.value = 'preview'
      await router.replace({ path: '/business-docking', query: { run_id: customerProductRun.id } })
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '创建客户及产品预演失败'
    } finally {
      busy.value = false
    }
  }

  async function refreshRuns() {
    runs.value = await etlApi.runs()
    if (currentRun.value) {
      const latest = runs.value.find((item) => item.id === currentRun.value?.id)
      if (latest) currentRun.value = latest
    }
  }

  async function selectRun(run: EtlRun) {
    customerProductPreviewMessage.value = ''
    currentRun.value = await etlApi.run(run.id)
    syncDraft()
    activeTab.value = 'history'
    await router.replace({ path: '/business-docking', query: { run_id: run.id } })
    schedulePoll()
  }

  async function openDocumentRoute(route: Record<string, unknown>) {
    const runId = String(route.run_id || '').trim()
    if (!runId) return
    pageError.value = ''
    try {
      currentRun.value = await etlApi.run(runId)
      syncDraft()
      activeTab.value = currentRun.value.status === 'preview_ready' ? 'preview' : 'history'
      if (currentRun.value.status === 'preview_ready') await loadRows()
      await router.replace({ path: '/business-docking', query: { run_id: runId } })
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '读取单据预演失败'
    }
  }

  async function openWorkbookRoot() {
    if (workbookRootRunId.value) await openDocumentRoute({ run_id: workbookRootRunId.value })
  }

  async function retryRun() {
    if (!currentRun.value) return
    busy.value = true
    try {
      currentRun.value = await etlApi.retry(currentRun.value.id)
      activeTab.value = 'upload'
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '重试失败'
    } finally {
      busy.value = false
    }
  }

  async function reanalyzeDocumentWithLlm() {
    if (!currentRun.value) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.reanalyzeLlm(currentRun.value.id)
      activeTab.value = 'upload'
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : 'LLM 重新识别失败'
    } finally {
      busy.value = false
    }
  }

  async function rollbackRun() {
    if (!currentRun.value || !window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
    busy.value = true
    try {
      currentRun.value = await etlApi.rollback(currentRun.value.id)
      await refreshRuns()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '撤销失败'
    } finally {
      busy.value = false
    }
  }

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
      Object.assign(webhookDraft, { name: '', endpoint_url: '', headersJson: '{}', secret: '' })
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

  return {
    saveCurrentAsTemplate,
    saveCurrentAsShipmentTemplate,
    previewCustomerProductsFromShipment,
    refreshRuns,
    selectRun,
    openDocumentRoute,
    openWorkbookRoot,
    retryRun,
    reanalyzeDocumentWithLlm,
    rollbackRun,
    saveWebhook,
    testWebhook,
  }
}

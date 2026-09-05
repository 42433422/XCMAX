/**
 * 数据对接中心运行生命周期（拆分自 views/EtlCenterView.vue，行为保持一致）：
 * 引导加载、轮询、自动写入、逐行/批量动作、历史选择、重试与撤销。
 */
import type { ComputedRef } from 'vue'
import type { Router } from 'vue-router'
import { etlApi, type EtlRun, type EtlRunRow } from '@/api/etl'
import { tabForRunStatus } from '@/utils/etlRunView'
import type { EtlCenterState } from './etlCenterState'
import { createEtlProductInvalidation } from '@/utils/etlProductInvalidation'

export interface EtlCenterRunsDeps {
  state: EtlCenterState
  route: { query: Record<string, unknown> }
  router: Pick<Router, 'replace'>
  canExecute: ComputedRef<boolean>
  canRollback: ComputedRef<boolean>
  shipmentTemplateCandidates: ComputedRef<Array<Record<string, unknown>>>
  bulkNewRows: ComputedRef<EtlRunRow[]>
}

export function createEtlCenterRuns({ state, route, router, canExecute, canRollback, shipmentTemplateCandidates, bulkNewRows }: EtlCenterRunsDeps) {
  const productChanges = createEtlProductInvalidation()
  const readRun = (id: string) => productChanges.read(() => etlApi.run(id))
  const readRuns = () => productChanges.readMany(() => etlApi.runs())
  const {
    activeTab,
    busy,
    pageError,
    runs,
    currentRun,
    targetType,
    runRows,
    rowPage,
    rowTotal,
    rowActionFilter,
    autoWriteEnabled,
    pendingAutoWriteIds,
    validRowsOnly,
    editableMappings,
    mappingUiTransform,
    mappingUiTransformJson,
    allowedUpdateFields,
    ocrConfirmed,
    hasOcrRows,
    selectedShipmentTemplateRegionId,
    customerProductPreviewMessage,
    pollTimer,
    autoWriteInFlight,
  } = state

  function markAutoWrite(runId: string) {
    pendingAutoWriteIds.value = new Set([...pendingAutoWriteIds.value, runId])
  }

  async function tryAutoWrite(run: EtlRun) {
    if (!autoWriteEnabled.value) return
    if (!pendingAutoWriteIds.value.has(run.id)) return
    if (run.status !== 'preview_ready') return
    if (autoWriteInFlight.has(run.id)) return
    autoWriteInFlight.add(run.id)
    const nextPending = new Set(pendingAutoWriteIds.value)
    nextPending.delete(run.id)
    pendingAutoWriteIds.value = nextPending
    const writable = (run.summary.new || 0) + (run.summary.update || 0)
    if (writable <= 0) {
      autoWriteInFlight.delete(run.id)
      currentRun.value = run
      syncDraft()
      activeTab.value = 'preview'
      await loadRows()
      pageError.value = '解析完成，但没有可写入行（全部跳过或错误）。请核对后手动写入。'
      return
    }
    busy.value = true
    pageError.value = ''
    try {
      const onlyValid = (run.summary.error || 0) > 0
      validRowsOnly.value = onlyValid
      currentRun.value = await productChanges.mutate(run, () => etlApi.execute(run.id, onlyValid))
      activeTab.value = 'history'
      await refreshRuns()
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '自动写入失败'
      currentRun.value = await readRun(run.id).catch(() => run)
      syncDraft()
      activeTab.value = 'preview'
      if (currentRun.value?.status === 'preview_ready') await loadRows()
    } finally {
      autoWriteInFlight.delete(run.id)
      busy.value = false
    }
  }

  async function bootstrap() {
    busy.value = true
    pageError.value = ''
    try {
      const [caps, templateRows, history, configs] = await Promise.all([
        etlApi.capabilities(),
        etlApi.templates(),
        readRuns(),
        etlApi.targetConfigs(),
      ])
      state.capabilities.value = caps
      state.templates.value = templateRows
      runs.value = history
      state.targetConfigs.value = configs
      if (targetType.value !== 'auto' && !caps.targets.some((item) => item.type === targetType.value)) {
        targetType.value = 'auto'
      }
      const requestedRun = String(route.query.run_id || '')
      if (requestedRun) {
        currentRun.value = await readRun(requestedRun)
        syncDraft()
        activeTab.value = tabForRunStatus(currentRun.value.status)
        if (currentRun.value.status === 'preview_ready') await loadRows()
        schedulePoll()
      }
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '数据对接中心加载失败'
    } finally {
      busy.value = false
    }
  }

  function schedulePoll() {
    if (pollTimer.value) clearTimeout(pollTimer.value)
    if (!currentRun.value || !['queued', 'previewing', 'executing'].includes(currentRun.value.status)) return
    pollTimer.value = setTimeout(async () => {
      if (!currentRun.value) return
      try {
        currentRun.value = await readRun(currentRun.value.id)
        syncDraft()
        if (currentRun.value.status === 'preview_ready') {
          if (autoWriteEnabled.value && pendingAutoWriteIds.value.has(currentRun.value.id)) {
            await tryAutoWrite(currentRun.value)
          } else {
            activeTab.value = 'preview'
            await loadRows()
            await refreshRuns()
          }
        } else if (currentRun.value.status === 'completed') {
          activeTab.value = 'history'
          await refreshRuns()
        }
      } catch (error) {
        pageError.value = error instanceof Error ? error.message : '读取运行进度失败'
      }
      schedulePoll()
    }, 1200)
  }

  function syncDraft() {
    if (!currentRun.value) return
    const candidateIds = shipmentTemplateCandidates.value.map((candidate) => String(candidate.source_region_id || '').trim()).filter(Boolean)
    if (!candidateIds.includes(selectedShipmentTemplateRegionId.value)) {
      selectedShipmentTemplateRegionId.value = candidateIds[0] || ''
    }
    editableMappings.value = (currentRun.value.draft.field_mappings || []).map((item) => ({
      ...item,
      transforms: [...(item.transforms || [])],
    }))
    for (const [index, mapping] of editableMappings.value.entries()) {
      const firstOp = String(mapping.transforms?.[0]?.op || '')
      mappingUiTransform[String(index)] = ['', 'trim', 'number', 'date'].includes(firstOp) ? firstOp : 'custom'
      mappingUiTransformJson[String(index)] = JSON.stringify(mapping.transforms || [])
    }
    allowedUpdateFields.value = [...(currentRun.value.draft.allowed_update_fields || [])]
    ocrConfirmed.value = Boolean(currentRun.value.draft.ocr_confirmed)
  }

  async function loadRows() {
    if (!currentRun.value || currentRun.value.total_rows === 0) {
      runRows.value = []
      rowTotal.value = 0
      return
    }
    const result = await etlApi.rows(currentRun.value.id, rowPage.value, 50, rowActionFilter.value)
    runRows.value = result.items
    rowTotal.value = result.total
    hasOcrRows.value = result.items.some((row) => row.provenance.ocr === true)
  }

  async function setRowActionFilter(action: string) {
    if (action === rowActionFilter.value) return
    rowActionFilter.value = action
    rowPage.value = 1
    await loadRows()
  }

  function onRowActionFilterChange(event: Event) {
    void setRowActionFilter((event.target as HTMLSelectElement).value)
  }

  async function overrideRow(row: EtlRunRow, event: Event) {
    if (!currentRun.value) return
    const action = (event.target as HTMLSelectElement).value
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
        row_overrides: { [String(row.id)]: action },
      })
      await loadRows()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '逐行动作保存失败'
    } finally {
      busy.value = false
    }
  }

  async function bulkOverride(action: 'new' | 'skip') {
    if (!currentRun.value) return
    const candidates = action === 'new' ? bulkNewRows.value : runRows.value.filter((row) => row.validation_issues.length === 0)
    if (!candidates.length) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
        row_overrides: Object.fromEntries(candidates.map((row) => [String(row.id), action])),
      })
      await loadRows()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '批量动作保存失败'
    } finally {
      busy.value = false
    }
  }

  async function executeCurrentRun() {
    if (!currentRun.value || !canExecute.value) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await productChanges.mutate(currentRun.value, () => etlApi.execute(currentRun.value!.id, validRowsOnly.value))
      activeTab.value = 'history'
      await refreshRuns()
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '执行失败'
      if (currentRun.value) currentRun.value = await readRun(currentRun.value.id).catch(() => currentRun.value)
    } finally {
      busy.value = false
    }
  }

  async function refreshRuns() {
    runs.value = await readRuns()
    if (currentRun.value) {
      const latest = runs.value.find((item) => item.id === currentRun.value?.id)
      if (latest) currentRun.value = latest
    }
  }

  async function selectRun(run: EtlRun) {
    pageError.value = ''
    customerProductPreviewMessage.value = ''
    currentRun.value = await readRun(run.id)
    syncDraft()
    activeTab.value = 'history'
    await router.replace({ path: '/business-docking', query: { run_id: run.id } })
    schedulePoll()
  }

  async function retryRun() {
    if (!currentRun.value) return
    busy.value = true
    pageError.value = ''
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

  async function rollbackRun() {
    if (!currentRun.value) return
    if (!canRollback.value) {
      pageError.value = '当前账号没有撤销权限，请联系管理员授权后重试。'
      return
    }
    if (!window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await productChanges.mutate(currentRun.value, () => etlApi.rollback(currentRun.value!.id))
      await refreshRuns()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '撤销失败'
    } finally {
      busy.value = false
    }
  }

  return {
    markAutoWrite,
    tryAutoWrite,
    bootstrap,
    schedulePoll,
    syncDraft,
    loadRows,
    setRowActionFilter,
    onRowActionFilterChange,
    overrideRow,
    bulkOverride,
    executeCurrentRun,
    refreshRuns,
    selectRun,
    retryRun,
    rollbackRun,
  }
}

export type EtlCenterRuns = ReturnType<typeof createEtlCenterRuns>

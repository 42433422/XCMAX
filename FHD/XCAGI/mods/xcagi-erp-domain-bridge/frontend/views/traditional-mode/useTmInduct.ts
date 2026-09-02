import { ref, computed } from 'vue'
import api from '@/api/core'
import manualInductApi from '@/api/manualInduct'
import type { TmExcelPanel } from './useTmExcelPanel'

const INDUCT_SCOPE_OPTIONS = [
  { key: 'products', label: '产品目录表' },
  { key: 'customers', label: '客户管理' },
  { key: 'materials', label: '原材料仓库' },
  { key: 'shipmentRecords', label: '出货记录' },
  { key: 'orders', label: '出货明细（发货单）' }
] as const

const MISSING_LABELS: Record<string, string> = {
  purchase_units: '客户',
  product_models: '产品型号（产品库）',
  customer_names: '客户名称',
  material_codes: '原材料编码'
}

interface TmInductDeps {
  excel: TmExcelPanel
  showToast: (message: string, type?: 'success' | 'error') => void
}

/** manualInduct preview 接口返回（沿用 @/api/manualInduct 声明） */
type TmInductPreviewResponse = Awaited<ReturnType<typeof manualInductApi.preview>>

/** 手动归纳：全表行解析 → 主数据校验 → 缺失确认 → 入库 */
export function useTmInduct(deps: TmInductDeps) {
  const { excelPanel, runTraditionalGridExtract } = deps.excel

  const inductScopeOptions = INDUCT_SCOPE_OPTIONS
  const inductPurchaseUnit = ref('')
  const inductPurchaseUnitOptions = ref<string[]>([])
  const inductTargetScope = ref('products')
  const inductRows = ref<Record<string, unknown>[]>([])
  const inductRowsLoading = ref(false)
  const inductRowsError = ref('')
  const inductRowsLoadedKey = ref('')
  const inductPreviewLoading = ref(false)
  const inductCommitLoading = ref(false)
  const inductLastPreview = ref<TmInductPreviewResponse | null>(null)
  const inductMissingModal = ref(false)
  const inductCreateSelected = ref<Record<string, boolean>>({})

  let traditionalSheetChangeBusy = false

  function inductSelKey(cat: string, item: string) {
    return `${cat}::${item}`
  }

  const inductModalMissingList = computed(() => {
    const prev = inductLastPreview.value as { missing?: Record<string, string[]> } | null
    const m = prev?.missing
    if (!m) return []
    const out: { key: string; label: string; items: string[] }[] = []
    for (const key of Object.keys(m)) {
      const items = Array.isArray(m[key]) ? m[key].filter(Boolean) : []
      if (!items.length) continue
      out.push({ key, label: MISSING_LABELS[key] || key, items })
    }
    return out
  })

  const inductPreviewHasMissing = computed(() => inductModalMissingList.value.length > 0)

  const inductPreviewMessage = computed(() => {
    const p = inductLastPreview.value
    if (!p) return ''
    if (!p.success) return String(p.message || '校验失败')
    if (!inductPreviewHasMissing.value) return '校验通过：未发现缺失主数据，可直接确认入库。'
    const parts = inductModalMissingList.value.map((g) => `${g.label} ${g.items.length} 项`)
    return `校验完成：待确认 ${parts.join('；')}`
  })

  function resetInductState() {
    inductPurchaseUnit.value = ''
    inductTargetScope.value = 'products'
    inductRows.value = []
    inductRowsLoading.value = false
    inductRowsError.value = ''
    inductRowsLoadedKey.value = ''
    inductPreviewLoading.value = false
    inductCommitLoading.value = false
    inductLastPreview.value = null
    inductMissingModal.value = false
    inductCreateSelected.value = {}
  }

  /** 保存成功后作废行缓存（不弹窗、不重置用户已选项以外的状态） */
  function invalidateInductRows() {
    inductRowsLoadedKey.value = ''
    inductLastPreview.value = null
  }

  async function loadInductPurchaseUnits() {
    try {
      const res = (await api.get('/api/orders/purchase-units')) as { success?: boolean; data?: unknown }
      const raw = res?.data
      const list = Array.isArray(raw) ? raw : []
      const names: string[] = []
      for (const x of list) {
        if (typeof x === 'string' && x.trim()) names.push(x.trim())
        else if (x && typeof x === 'object' && (x as { unit_name?: string }).unit_name) {
          const n = String((x as { unit_name?: string }).unit_name || '').trim()
          if (n) names.push(n)
        }
      }
      inductPurchaseUnitOptions.value = [...new Set(names)].sort((a, b) => a.localeCompare(b, 'zh-CN'))
    } catch {
      inductPurchaseUnitOptions.value = []
    }
  }

  function inductRowsCacheKey() {
    return `${excelPanel.filePath}|${excelPanel.selectedSheetName || ''}|${excelPanel.sourceFingerprint || ''}`
  }

  async function ensureInductRowsLoaded() {
    if (!excelPanel.visible || !excelPanel.filePath) return
    const key = inductRowsCacheKey()
    if (inductRowsLoadedKey.value === key && inductRows.value.length) return
    inductRowsLoading.value = true
    inductRowsError.value = ''
    try {
      const f = await deps.excel.getTraditionalExcelFile(
        excelPanel.filePath,
        excelPanel.fileName,
        excelPanel.sourceFingerprint || deps.excel.buildFileFingerprint({
          name: excelPanel.fileName,
          is_dir: false,
          size: 0,
          modified_time: '',
          type: ''
        })
      )
      const sheet = excelPanel.selectedSheetName || ''
      const res = (await manualInductApi.extractUpload(f, sheet)) as {
        success?: boolean
        rows?: unknown
        message?: string
      }
      if (res && res.success === false) {
        throw new Error(res.message || '解析 Excel 行失败')
      }
      const rows = Array.isArray(res.rows) ? res.rows : []
      inductRows.value = rows
      inductRowsLoadedKey.value = key
    } catch (e) {
      inductRows.value = []
      inductRowsLoadedKey.value = ''
      inductRowsError.value = e instanceof Error ? e.message : String(e)
      deps.showToast(inductRowsError.value, 'error')
    } finally {
      inductRowsLoading.value = false
    }
  }

  async function reloadInductRows() {
    inductRowsLoadedKey.value = ''
    await ensureInductRowsLoaded()
  }

  function initInductCreateSelections() {
    const next: Record<string, boolean> = {}
    for (const grp of inductModalMissingList.value) {
      for (const item of grp.items) {
        next[inductSelKey(grp.key, item)] = true
      }
    }
    inductCreateSelected.value = next
  }

  async function runInductPreview() {
    if (!inductRows.value.length) {
      deps.showToast('请先等待行数据加载完成', 'error')
      return
    }
    if (
      (inductTargetScope.value === 'shipmentRecords' || inductTargetScope.value === 'orders') &&
      !String(inductPurchaseUnit.value || '').trim()
    ) {
      deps.showToast('当前目标库需要选择客户', 'error')
      return
    }
    inductPreviewLoading.value = true
    inductLastPreview.value = null
    try {
      const res = await manualInductApi.preview({
        target_scope: inductTargetScope.value,
        purchase_unit: inductPurchaseUnit.value.trim() || undefined,
        rows: inductRows.value
      })
      inductLastPreview.value = res
      if (!res?.success) {
        deps.showToast(res?.message || '校验失败', 'error')
        return
      }
      if (inductPreviewHasMissing.value) {
        deps.showToast('校验完成：存在缺失主数据，点击「确认入库」可勾选是否新增', 'error')
      } else {
        deps.showToast('校验通过', 'success')
      }
    } catch (e) {
      deps.showToast(e instanceof Error ? (e.message || '校验失败') : String(e), 'error')
    } finally {
      inductPreviewLoading.value = false
    }
  }

  function buildCreateMissingPayload(): Record<string, string[]> {
    const out: Record<string, string[]> = {
      purchase_units: [],
      product_models: [],
      customer_names: [],
      material_codes: []
    }
    for (const grp of inductModalMissingList.value) {
      const key = grp.key
      if (!(key in out)) continue
      const acc: string[] = []
      for (const item of grp.items) {
        const sel = inductCreateSelected.value[inductSelKey(key, item)]
        if (sel !== false) acc.push(item)
      }
      out[key] = acc
    }
    return out
  }

  async function submitInductCommit(createMissing: Record<string, string[]>) {
    inductCommitLoading.value = true
    try {
      const res = await manualInductApi.commit({
        target_scope: inductTargetScope.value,
        purchase_unit: inductPurchaseUnit.value.trim() || undefined,
        rows: inductRows.value,
        create_missing: createMissing
      })
      if (!res?.success) {
        deps.showToast(res?.message || '入库失败', 'error')
        return
      }
      deps.showToast(res?.message || '入库成功', 'success')
      inductMissingModal.value = false
      inductLastPreview.value = null
      await loadInductPurchaseUnits()
    } catch (e) {
      deps.showToast(e instanceof Error ? (e.message || '入库失败') : String(e), 'error')
    } finally {
      inductCommitLoading.value = false
    }
  }

  function closeInductMissingModal() {
    if (inductCommitLoading.value) return
    inductMissingModal.value = false
  }

  async function confirmInductCommitFromModal() {
    const cm = buildCreateMissingPayload()
    await submitInductCommit(cm)
  }

  async function onInductCommitClick() {
    if (!inductLastPreview.value?.success) {
      deps.showToast('请先完成校验', 'error')
      return
    }
    if (
      (inductTargetScope.value === 'shipmentRecords' || inductTargetScope.value === 'orders') &&
      !String(inductPurchaseUnit.value || '').trim()
    ) {
      deps.showToast('请选择客户', 'error')
      return
    }
    if (inductPreviewHasMissing.value) {
      initInductCreateSelections()
      inductMissingModal.value = true
      return
    }
    await submitInductCommit({
      purchase_units: [],
      product_models: [],
      customer_names: [],
      material_codes: []
    })
  }

  async function setExcelMainTab(tab: 'edit' | 'induct') {
    /** 离开「手动归纳」时作废进行中的 extract-grid，避免旧请求晚到或 loading 一直为 true */
    if (tab === 'edit' && excelPanel.mainTab === 'induct') {
      deps.excel.invalidateExtract()
    }
    excelPanel.mainTab = tab
    if (tab === 'induct') {
      void loadInductPurchaseUnits()
      if (excelPanel.extractLoadedPath !== excelPanel.filePath || !excelPanel.extractResult) {
        await runTraditionalGridExtract('')
      }
      await ensureInductRowsLoaded()
    }
  }

  async function onTraditionalExtractSheetChange() {
    if (traditionalSheetChangeBusy || !excelPanel.visible || !excelPanel.filePath) return
    const sheet = excelPanel.selectedSheetName
    if (!sheet) return
    traditionalSheetChangeBusy = true
    try {
      await runTraditionalGridExtract(sheet)
      inductRowsLoadedKey.value = ''
      inductLastPreview.value = null
      if (excelPanel.mainTab === 'induct') {
        await ensureInductRowsLoaded()
      }
    } finally {
      traditionalSheetChangeBusy = false
    }
  }

  return {
    inductScopeOptions,
    inductPurchaseUnit,
    inductPurchaseUnitOptions,
    inductTargetScope,
    inductRows,
    inductRowsLoading,
    inductRowsError,
    inductRowsLoadedKey,
    inductPreviewLoading,
    inductCommitLoading,
    inductLastPreview,
    inductMissingModal,
    inductCreateSelected,
    inductSelKey,
    inductModalMissingList,
    inductPreviewHasMissing,
    inductPreviewMessage,
    resetInductState,
    invalidateInductRows,
    loadInductPurchaseUnits,
    ensureInductRowsLoaded,
    reloadInductRows,
    runInductPreview,
    onInductCommitClick,
    closeInductMissingModal,
    confirmInductCommitFromModal,
    setExcelMainTab,
    onTraditionalExtractSheetChange,
  }
}

export type TmInduct = ReturnType<typeof useTmInduct>

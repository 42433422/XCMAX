import { ref, reactive, onMounted, onActivated, onDeactivated, onBeforeUnmount, computed, type Ref } from 'vue'
import { createLatestBusinessRead, requireBusinessSuccess } from '@/utils/businessPageLifecycle'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'
import { api, get, post } from '@/api'
import { appAlert, appConfirm } from '@/utils/appDialog'

// 实体类型（字段以 MaterialsView 模板与表单赋值实际访问项为准）
interface Material {
  id: number
  code: string
  name: string
  category: string
  spec: string
  unit: string
  quantity: number
  price: number
  supplier: string
  min_stock: number
}

interface Warehouse {
  id: number
  code: string
  name: string
  type: string
  address: string
  manager: string
  status: string
}

interface Location {
  id: number
  warehouse_id: number | null
  code: string
  name: string
  max_capacity: number | null
  current_capacity: number
  status: string
}

interface Transaction {
  id: number
  transaction_date: string
  transaction_type: string
  product_name?: string
  warehouse_name?: string
  quantity: number
  operator?: string
  remark?: string
}

interface Supplier {
  id: number
  code: string
  name: string
  contact_person: string
  contact_phone: string
  rating: number
}

interface MaterialForm {
  id: number | null
  code: string
  name: string
  category: string
  spec: string
  unit: string
  quantity: number
  price: number
  supplier: string
  min_stock: number
}

interface WarehouseForm {
  id: number | null
  code: string
  name: string
  type: string
  address: string
  manager: string
}

interface LocationForm {
  id: number | null
  warehouse_id?: number | null
  code: string
  name: string
  max_capacity: number | null
}

interface InoutForm {
  product_id: number | string
  warehouse_id: number | string
  quantity: number
  batch_no: string
  remark: string
}

interface SupplierForm {
  id: number | null
  code: string
  name: string
  contact_person: string
  contact_phone: string
  rating: number
}

interface ApiListResponse<T> {
  success: boolean
  message?: string
  data?: T[]
  categories?: string[]
  total?: number
}

interface ApiWriteResponse {
  success: boolean
  message?: string
}

// 拆分自 MaterialsView.vue script（原第 342–628 行）；逻辑逐字迁移，行为不变。
export function useMaterials() {
  const industryStore = useIndustryStore()
  const modsStore = useModsStore()
  const { modsForUi } = storeToRefs(modsStore)

  const materialsPageTitle = computed(() =>
    resolveCoreNavLabel(
      'materials',
      String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID),
      modsForUi.value,
    ) || '排班资源',
  )

  const resourceTabLabel = computed(() => {
    const id = String(industryStore.currentIndustryId || '')
    if (id === '涂料') return '原材料'
    if (id === '电商') return '商品'
    if (id === '考勤') return '资源明细'
    return '库存'
  })

  const warehouseTabLabel = computed(() =>
    String(industryStore.currentIndustryId) === '考勤' ? '场所库位' : '仓库库位',
  )

  const inoutTabLabel = computed(() =>
    String(industryStore.currentIndustryId) === '考勤' ? '调拨' : '出入库',
  )

  const supplierTabLabel = computed(() =>
    String(industryStore.currentIndustryId) === '考勤' ? '协作方' : '供应商',
  )

  const resourceModalNoun = computed(() => {
    const id = String(industryStore.currentIndustryId || '')
    if (id === '涂料') return '原材料'
    if (id === '考勤') return '排班资源'
    return '物料'
  })

  const activeTab = ref('materials')
  const materials = ref<Material[]>([])
  const warehouses = ref<Warehouse[]>([])
  const locations = ref<Location[]>([])
  const transactions = ref<Transaction[]>([])
  const suppliers = ref<Supplier[]>([])
  const categories = ref<string[]>([])
  const searchQuery = ref('')
  const selectedCategory = ref('')
  const saving = ref(false)
  type ListName = 'materials' | 'warehouses' | 'locations' | 'transactions' | 'suppliers'
  const listLoading = reactive<Record<ListName, boolean>>({ materials: false, warehouses: false, locations: false, transactions: false, suppliers: false })
  const listErrors = reactive<Record<ListName, string>>({ materials: '', warehouses: '', locations: '', transactions: '', suppliers: '' })
  const reads = { materials: createLatestBusinessRead(), warehouses: createLatestBusinessRead(), locations: createLatestBusinessRead(), transactions: createLatestBusinessRead(), suppliers: createLatestBusinessRead() }
  let searchTimer: ReturnType<typeof setTimeout> | undefined
  let materialQueryKey: string | null = null
  const materialPagination = reactive({ page: 1, pageSize: 50, total: 0 })
  const transactionPagination = reactive({ page: 1, pageSize: 50, total: 0 })

  const showMaterialModal = ref(false)
  const isEditMaterial = ref(false)
  const materialForm = ref<MaterialForm>({ id: null, code: '', name: '', category: '', spec: '', unit: '个', quantity: 0, price: 0, supplier: '', min_stock: 0 })

  const showWarehouseModalFlag = ref(false)
  const isEditWarehouse = ref(false)
  const warehouseForm = ref<WarehouseForm>({ id: null, code: '', name: '', type: '', address: '', manager: '' })
  const selectedWarehouse = ref<Warehouse | null>(null)

  const showLocationModalFlag = ref(false)
  const isEditLocation = ref(false)
  const locationForm = ref<LocationForm>({ id: null, warehouse_id: null, code: '', name: '', max_capacity: null })

  const showInModalFlag = ref(false)
  const showOutModalFlag = ref(false)
  const inoutForm = ref<InoutForm>({ product_id: '', warehouse_id: '', quantity: 1, batch_no: '', remark: '' })

  const showSupplierModalFlag = ref(false)
  const isEditSupplier = ref(false)
  const supplierForm = ref<SupplierForm>({ id: null, code: '', name: '', contact_person: '', contact_phone: '', rating: 3 })

  async function readList<T>(name: ListName, target: Ref<T[]>, url: string, params: Record<string, unknown> = {}, onData?: (response: ApiListResponse<T>) => void) {
    const read = reads[name].begin()
    listLoading[name] = true
    listErrors[name] = ''
    try {
      const response = await get<ApiListResponse<T>>(url, params, { signal: read.signal, timeoutMs: 8000, retry: false })
      if (!read.isCurrent()) return
      requireBusinessSuccess(response, '读取失败，请重试')
      target.value = Array.isArray(response.data) ? response.data : []
      onData?.(response)
    } catch (error) {
      if (!read.isCurrent()) return
      const status = Number((error as { status?: number })?.status || 0)
      if (status === 401 || status === 403) {
        target.value = []
        listErrors[name] = '无权限读取数据'
      } else {
        listErrors[name] = error instanceof Error ? error.message : '读取失败，请重试'
      }
    } finally {
      if (read.isCurrent()) listLoading[name] = false
      read.finish()
    }
  }

  const loadMaterials = async (requestedPage = 1) => {
    if (searchTimer !== undefined) clearTimeout(searchTimer)
    searchTimer = undefined
    const keyword = searchQuery.value.trim()
    const category = selectedCategory.value
    const key = JSON.stringify([keyword, category])
    if (key !== materialQueryKey) {
      materials.value = []
      materialQueryKey = key
      materialPagination.total = 0
      requestedPage = 1
    }
    if (materialPagination.page !== requestedPage) materials.value = []
    materialPagination.page = requestedPage
    await readList('materials', materials, '/api/materials', {
      page: materialPagination.page, per_page: materialPagination.pageSize,
      ...(keyword ? { search: keyword } : {}),
      ...(category ? { category } : {}),
    }, response => {
      if (response.categories) categories.value = response.categories
      materialPagination.total = Number(response.total ?? response.data?.length ?? 0)
    })
  }

  const scheduleMaterialsSearch = () => {
    if (searchTimer !== undefined) clearTimeout(searchTimer)
    reads.materials.cancel()
    materials.value = []
    listErrors.materials = ''
    listLoading.materials = true
    searchTimer = setTimeout(() => { void loadMaterials() }, 280)
  }

  const loadWarehouses = () => readList('warehouses', warehouses, '/api/inventory/warehouses')
  const loadLocations = (warehouseId: number | string) => readList('locations', locations, '/api/inventory/locations', { warehouse_id: warehouseId })
  const loadTransactions = async (requestedPage = 1) => {
    if (transactionPagination.page !== requestedPage) transactions.value = []
    transactionPagination.page = requestedPage
    await readList('transactions', transactions, '/api/inventory/transactions', { page: requestedPage, per_page: transactionPagination.pageSize }, response => {
      transactionPagination.total = Number(response.total ?? response.data?.length ?? 0)
    })
  }
  const loadSuppliers = () => readList('suppliers', suppliers, '/api/purchase/suppliers')

  const showAddModal = () => {
    isEditMaterial.value = false
    materialForm.value = { id: null, code: '', name: '', category: '', spec: '', unit: '个', quantity: 0, price: 0, supplier: '', min_stock: 0 }
    showMaterialModal.value = true
  }

  const editMaterial = (item: Material) => {
    isEditMaterial.value = true
    materialForm.value = { ...item }
    showMaterialModal.value = true
  }

  const saveMaterial = async () => {
    if (saving.value) return
    if (!materialForm.value.name) { await appAlert('请输入名称'); return }
    saving.value = true
    try {
      const res = isEditMaterial.value
        ? await api.put<ApiWriteResponse>(`/api/materials/${materialForm.value.id}`, materialForm.value)
        : await post<ApiWriteResponse>('/api/materials', materialForm.value)
      if (res.success) { showMaterialModal.value = false; await loadMaterials() }
      else await appAlert(res.message || '保存失败')
    } catch (e) { await appAlert('保存失败') } finally { saving.value = false }
  }

  const deleteMaterial = async (item: Material) => {
    if (saving.value) return
    saving.value = true
    try {
      if (!(await appConfirm('确认删除？', { danger: true }))) return
      const res = await api.delete<ApiWriteResponse>(`/api/materials/${item.id}`)
      if (res.success) await loadMaterials()
      else await appAlert(res.message || '删除失败')
    } catch (e) { await appAlert('删除失败') } finally { saving.value = false }
  }

  const showWarehouseModal = () => {
    isEditWarehouse.value = false
    warehouseForm.value = { id: null, code: '', name: '', type: '', address: '', manager: '' }
    showWarehouseModalFlag.value = true
  }

  const editWarehouse = (w: Warehouse) => {
    isEditWarehouse.value = true
    warehouseForm.value = { ...w }
    showWarehouseModalFlag.value = true
  }

  const saveWarehouse = async () => {
    if (saving.value) return
    if (!warehouseForm.value.code || !warehouseForm.value.name) { await appAlert('请填写必填项'); return }
    saving.value = true
    try {
      const res = isEditWarehouse.value
        ? await api.put<ApiWriteResponse>(`/api/inventory/warehouses/${warehouseForm.value.id}`, warehouseForm.value)
        : await post<ApiWriteResponse>('/api/inventory/warehouses', warehouseForm.value)
      if (res.success) { showWarehouseModalFlag.value = false; await loadWarehouses() }
      else await appAlert(res.message || '保存失败')
    } catch (e) { await appAlert('保存失败') } finally { saving.value = false }
  }

  const manageLocations = (w: Warehouse) => {
    if (selectedWarehouse.value?.id !== w.id) locations.value = []
    selectedWarehouse.value = w
    void loadLocations(w.id)
  }

  const showLocationModal = () => {
    isEditLocation.value = false
    locationForm.value = { id: null, warehouse_id: selectedWarehouse.value?.id, code: '', name: '', max_capacity: null }
    showLocationModalFlag.value = true
  }

  const editLocation = (loc: Location) => {
    isEditLocation.value = true
    locationForm.value = { ...loc }
    showLocationModalFlag.value = true
  }

  const saveLocation = async () => {
    if (saving.value) return
    if (!locationForm.value.code) { await appAlert('请输入编码'); return }
    saving.value = true
    try {
      const res = isEditLocation.value
        ? await api.put<ApiWriteResponse>(`/api/inventory/locations/${locationForm.value.id}`, locationForm.value)
        : await post<ApiWriteResponse>('/api/inventory/locations', locationForm.value)
      if (res.success) { showLocationModalFlag.value = false; if (selectedWarehouse.value) await loadLocations(selectedWarehouse.value.id) }
      else await appAlert(res.message || '保存失败')
    } catch (e) { await appAlert('保存失败') } finally { saving.value = false }
  }

  const showInModal = () => {
    inoutForm.value = { product_id: '', warehouse_id: '', quantity: 1, batch_no: '', remark: '' }
    showInModalFlag.value = true
  }

  const showOutModal = () => {
    inoutForm.value = { product_id: '', warehouse_id: '', quantity: 1, batch_no: '', remark: '' }
    showOutModalFlag.value = true
  }

  const doIn = async () => {
    if (saving.value) return
    if (!inoutForm.value.product_id || !inoutForm.value.warehouse_id || (!Number.isFinite(inoutForm.value.quantity) || inoutForm.value.quantity <= 0)) {
      await appAlert('请填写必填项'); return
    }
    saving.value = true
    try {
      const res = await post<ApiWriteResponse>('/api/inventory/in', inoutForm.value)
      if (res.success) { showInModalFlag.value = false; await Promise.all([loadTransactions(), loadMaterials(), ...(selectedWarehouse.value ? [loadLocations(selectedWarehouse.value.id)] : [])]); await appAlert('入库成功') }
      else await appAlert(res.message || '入库失败')
    } catch (e) { await appAlert('入库失败') } finally { saving.value = false }
  }

  const doOut = async () => {
    if (saving.value) return
    if (!inoutForm.value.product_id || !inoutForm.value.warehouse_id || (!Number.isFinite(inoutForm.value.quantity) || inoutForm.value.quantity <= 0)) {
      await appAlert('请填写必填项'); return
    }
    saving.value = true
    try {
      const res = await post<ApiWriteResponse>('/api/inventory/out', inoutForm.value)
      if (res.success) { showOutModalFlag.value = false; await Promise.all([loadTransactions(), loadMaterials(), ...(selectedWarehouse.value ? [loadLocations(selectedWarehouse.value.id)] : [])]); await appAlert('出库成功') }
      else await appAlert(res.message || '出库失败')
    } catch (e) { await appAlert('出库失败') } finally { saving.value = false }
  }

  const showSupplierModal = () => {
    isEditSupplier.value = false
    supplierForm.value = { id: null, code: '', name: '', contact_person: '', contact_phone: '', rating: 3 }
    showSupplierModalFlag.value = true
  }

  const editSupplier = (s: Supplier) => {
    isEditSupplier.value = true
    supplierForm.value = { ...s }
    showSupplierModalFlag.value = true
  }

  const saveSupplier = async () => {
    if (saving.value) return
    if (!supplierForm.value.code || !supplierForm.value.name) { await appAlert('请填写必填项'); return }
    saving.value = true
    try {
      const res = isEditSupplier.value
        ? await api.put<ApiWriteResponse>(`/api/purchase/suppliers/${supplierForm.value.id}`, supplierForm.value)
        : await post<ApiWriteResponse>('/api/purchase/suppliers', supplierForm.value)
      if (res.success) { showSupplierModalFlag.value = false; await loadSuppliers() }
      else await appAlert(res.message || '保存失败')
    } catch (e) { await appAlert('保存失败') } finally { saving.value = false }
  }

  const exportData = async () => {
    try {
      const { materialsApi } = await import('@/api')
      const params: Record<string, unknown> = {}
      if (searchQuery.value) params.search = searchQuery.value
      if (selectedCategory.value) params.category = selectedCategory.value
      const resp = await materialsApi.exportMaterialsXlsx(params)
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      const ind = String(industryStore.currentIndustryId || '')
      a.download =
        ind === '考勤' ? '排班资源导出.xlsx' : ind === '涂料' ? '原材料导出.xlsx' : '库存导出.xlsx'
      a.click()
      setTimeout(() => URL.revokeObjectURL(objectUrl), 10000)
    } catch (e) {
      const message = e && typeof e === 'object' ? String((e as { message?: unknown }).message || '') : ''
      await appAlert('导出失败：' + (message || '请重试'))
    }
  }

  let active = false
  function activate() {
    if (active) return
    active = true
    void loadMaterials()
    void loadWarehouses()
    void loadTransactions()
    if (activeTab.value === 'supplier') void loadSuppliers()
    if (selectedWarehouse.value) void loadLocations(selectedWarehouse.value.id)
  }
  function deactivate() {
    active = false
    if (searchTimer !== undefined) clearTimeout(searchTimer)
    searchTimer = undefined
    for (const name of Object.keys(reads) as ListName[]) {
      reads[name].cancel()
      listLoading[name] = false
    }
  }
  onMounted(activate)
  onActivated(activate)
  onDeactivated(deactivate)
  onBeforeUnmount(deactivate)

  return {
    materialsPageTitle,
    resourceTabLabel,
    warehouseTabLabel,
    inoutTabLabel,
    supplierTabLabel,
    resourceModalNoun,
    activeTab,
    materials,
    warehouses,
    locations,
    transactions,
    suppliers,
    categories,
    searchQuery,
    selectedCategory,
    showMaterialModal,
    isEditMaterial,
    materialForm,
    showWarehouseModalFlag,
    isEditWarehouse,
    warehouseForm,
    selectedWarehouse,
    showLocationModalFlag,
    isEditLocation,
    locationForm,
    showInModalFlag,
    showOutModalFlag,
    inoutForm,
    showSupplierModalFlag,
    isEditSupplier,
    supplierForm,
    loadMaterials,
    scheduleMaterialsSearch,
    loadWarehouses,
    loadLocations,
    loadTransactions,
    listLoading,
    listErrors,
    materialPagination,
    transactionPagination,
    saving,
    loadSuppliers,
    showAddModal,
    editMaterial,
    saveMaterial,
    deleteMaterial,
    showWarehouseModal,
    editWarehouse,
    saveWarehouse,
    manageLocations,
    showLocationModal,
    editLocation,
    saveLocation,
    showInModal,
    showOutModal,
    doIn,
    doOut,
    showSupplierModal,
    editSupplier,
    saveSupplier,
    exportData,
  }
}

import { ref, reactive, onMounted, onUnmounted, onActivated, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/index'
import { templatePreviewApi } from '@/api/templatePreview'
import { getTemplateScopeKey, isExportTemplate, type TplRecord } from '../template-preview/tpTemplateMeta'
import { productsApi } from '@/api/products'
import type { Product } from '@/types/product'
import { downloadBlob } from '@/utils'
import { appAlert } from '@/utils/appDialog'
import { pushErpPage } from '@/utils/erpPagePaths'

// AI 填单事件（xcagi:ai-fill-order / window.__VUE_FILL_ORDER__）载荷
interface AIProductPayload {
  nameId?: string | number
  name?: string
  model?: string
  quantityBox?: number
  specification?: number
  quantityKg?: number
  unitPrice?: number
  amount?: number
}

interface AIFillOrderPayload {
  purchaseUnit?: string
  contactPerson?: string
  date?: string
  autoPrint?: boolean
  products?: AIProductPayload[]
}

interface PurchaseUnit {
  unit_name: string
  contact_person?: string
}

interface OrderProductRow {
  id: number
  nameId: string | number
  name: string
  model: string
  quantityBox: number
  specification: number
  quantityKg: number
  unitPrice: number
  amount: number
}

interface ShipmentResult {
  success: boolean
  doc_name?: string
  message?: string
}

declare global {
  interface Window {
    __VUE_FILL_ORDER__?: (data: AIFillOrderPayload | null) => void
  }
}

export function useCreateOrder() {
  const router = useRouter()

  function goOrdersList() {
    pushErpPage(router, '/orders')
  }

  function goTemplatePreview() {
    pushErpPage(router, { path: '/template-preview', query: { scope: 'orders' } })
  }

  function handleAIFillOrder(data: AIFillOrderPayload | null) {
    if (!data) return

    if (data.purchaseUnit) {
      const matchedUnit = purchaseUnits.value.find(u => u.unit_name === data.purchaseUnit)
      if (matchedUnit) {
        form.purchaseUnit = data.purchaseUnit
        form.contactPerson = data.contactPerson || matchedUnit.contact_person || ''
      } else {
        form.purchaseUnit = data.purchaseUnit
        form.contactPerson = data.contactPerson || ''
      }
    }

    if (data.contactPerson && !form.contactPerson) {
      form.contactPerson = data.contactPerson
    }

    if (data.date) {
      form.purchaseDate = data.date
      generateOrderNumber()
    }

    if (data.autoPrint !== undefined) {
      form.autoPrint = data.autoPrint
    }

    if (data.products && Array.isArray(data.products) && data.products.length > 0) {
      products.value = []
      data.products.forEach((p: AIProductPayload) => {
        const nameId = p.nameId || ''
        const matchedProduct = nameId ? allProducts.value.find(ap => ap.id == nameId) : null

        products.value.push({
          id: ++productIdCounter,
          nameId: nameId,
          name: p.name || matchedProduct?.name || '',
          model: p.model || '',
          quantityBox: p.quantityBox || 1,
          specification: p.specification || matchedProduct?.specification || 0,
          quantityKg: p.quantityKg || 0,
          unitPrice: p.unitPrice || matchedProduct?.price || 0,
          amount: p.amount || 0
        })

        const idx = products.value.length - 1
        if (products.value[idx].specification && !p.quantityKg) {
          calculateKg(idx)
        }
        if (products.value[idx].unitPrice && !p.amount) {
          calculateAmount(idx)
        }
      })
    }

    showStatus('AI 数据已自动填充', 'success')
  }

  function setupAIEventListener() {
    window.addEventListener('xcagi:ai-fill-order', (event: Event) => {
      handleAIFillOrder((event as CustomEvent).detail)
    })

    window.__VUE_FILL_ORDER__ = handleAIFillOrder
  }

  function refreshOptions() {
    loadTemplates()
    loadPurchaseUnits()
    loadAllProducts()
  }
  onActivated(refreshOptions)
  onMounted(() => {
    refreshOptions()
    generateOrderNumber()
    setupAIEventListener()
  })

  onUnmounted(() => {
    window.removeEventListener('xcagi:ai-fill-order', handleAIFillOrder as EventListener)
    if (window.__VUE_FILL_ORDER__ === handleAIFillOrder) {
      delete window.__VUE_FILL_ORDER__
    }
  })

  const templates = ref<TplRecord[]>([])
  const purchaseUnits = ref<PurchaseUnit[]>([])
  const allProducts = ref<Product[]>([])
  const products = ref<OrderProductRow[]>([])
  let productIdCounter = 0

  const status = reactive({
    message: '',
    type: ''
  })

  const form = reactive({
    templateName: '',
    purchaseUnit: '',
    contactPerson: '',
    purchaseDate: new Date().toISOString().split('T')[0],
    orderNumber: '',
    autoPrint: false
  })

  const result = ref<ShipmentResult | null>(null)
  const showProductSelector = ref(false)
  const productSearchQuery = ref('')
  const searchingProducts = ref(false)

  const filteredProductsForSelection = computed(() => {
    if (!productSearchQuery.value) return allProducts.value
    const q = productSearchQuery.value.toLowerCase()
    return allProducts.value.filter(p =>
      (p.name && p.name.toLowerCase().includes(q)) ||
      (p.model_number && p.model_number.toLowerCase().includes(q))
    )
  })

  function showStatus(message: string, type: string) {
    status.message = message
    status.type = type
    setTimeout(() => {
      status.message = ''
      status.type = ''
    }, 5000)
  }

  async function loadTemplates() {
    try {
      const data = await templatePreviewApi.listTemplates() as { success: boolean; templates: TplRecord[] }
      if (data.success) {
        templates.value = data.templates.filter(t => isExportTemplate(t) && t.category === 'excel' && getTemplateScopeKey(t) === 'orders')
        if (!templates.value.some(t => t.id === form.templateName)) {
          form.templateName = templates.value[0]?.id || ''
        }
      }
    } catch (error) {
      console.error('加载模板失败:', error)
    }
  }

  async function loadPurchaseUnits() {
    try {
      const data = await api.get<{ success: boolean; data: PurchaseUnit[] }>('/api/purchase_units')
      if (data.success) {
        purchaseUnits.value = data.data
      }
    } catch (error) {
      console.error('加载购买单位失败:', error)
    }
  }

  function onPurchaseUnitChange() {
    form.contactPerson = purchaseUnits.value.find(unit => unit.unit_name === form.purchaseUnit)?.contact_person || ''
  }

  async function loadAllProducts() {
    try {
      const rows: Product[] = []
      for (let page = 1; ; page++) {
        const data = await productsApi.getProducts({ page, per_page: 1000 })
        if (!data.success) throw new Error(data.message || '产品列表不可用')
        rows.push(...(data.data || []))
        if (!data.data?.length || rows.length >= (data.total ?? rows.length)) break
      }
      allProducts.value = rows
    } catch (error) {
      console.error('加载产品名称列表失败:', error)
    }
  }

  async function generateOrderNumber() {
    try {
      const data = await api.get<{ success: boolean; data: { order_number: string } }>('/api/orders/next_number', { suffix: 'A' })
      if (data.success) {
        form.orderNumber = data.data.order_number
      }
    } catch (error) {
      console.error('获取订单编号失败:', error)
    }
  }

  function onDateChange() {
    generateOrderNumber()
  }

  function addProductRow() {
    products.value.push({
      id: ++productIdCounter,
      nameId: '',
      name: '',
      model: '',
      quantityBox: 1,
      specification: 0,
      quantityKg: 0,
      unitPrice: 0,
      amount: 0
    })
  }

  function removeProductRow(index: number) {
    products.value.splice(index, 1)
  }

  function calculateKg(index: number) {
    const product = products.value[index]
    product.quantityKg = (product.quantityBox || 0) * (product.specification || 0)
    calculateAmount(index)
  }

  function calculateAmount(index: number) {
    const product = products.value[index]
    product.amount = (product.quantityKg || 0) * (product.unitPrice || 0)
  }

  function onProductNameSelect(product: OrderProductRow, index: number) {
    const selected = allProducts.value.find(p => p.id == product.nameId)
    if (selected) {
      product.name = selected.name || ''
      if (selected.model_number) {
        product.model = selected.model_number
      }
      if (selected.specification) {
        product.specification = Number.parseFloat(String(selected.specification)) || 0
        calculateKg(index)
      }
      if (selected.price) {
        product.unitPrice = selected.price
        calculateAmount(index)
      }
    }
  }

  function searchProductsForSelection() {
    searchingProducts.value = true
    setTimeout(() => {
      searchingProducts.value = false
    }, 300)
  }

  function selectProductForAdd(product: Product) {
    addProductRow()
    const newProduct = products.value[products.value.length - 1]
    newProduct.nameId = product.id
    onProductNameSelect(newProduct, products.value.length - 1)
    showProductSelector.value = false
  }

  async function generateShipment() {
    if (!templates.value.length) {
      await appAlert('暂无可用发货单模板：请先点「模板编辑」上传或创建贵司出货单模板，保存后回到本页点「刷新模板列表」再生成。')
      return
    }
    if (!form.templateName) {
      await appAlert('请选择发货单模板')
      return
    }
    if (!form.purchaseUnit) {
      await appAlert('请选择购买单位')
      return
    }
    if (!form.purchaseDate) {
      await appAlert('请选择日期')
      return
    }
    if (products.value.length === 0) {
      await appAlert('请至少添加一个产品')
      return
    }

    showStatus('正在生成发货单...', 'processing')

    try {
      const data = await api.post<ShipmentResult>('/api/shipment/generate', {
        unit_name: form.purchaseUnit,
        date: form.purchaseDate,
        order_number: form.orderNumber,
        template_id: form.templateName,
        products: products.value.map(product => ({
          name: product.name,
          model_number: product.model,
          quantity_tins: product.quantityBox,
          tin_spec: product.specification,
          quantity_kg: product.quantityKg,
          unit_price: product.unitPrice,
          amount: product.amount
        }))
      })
      if (data.success) {
        showStatus('发货单生成成功！', 'success')
        result.value = data
      } else {
        showStatus('生成失败: ' + data.message, 'error')
      }
    } catch (error) {
      showStatus('生成失败: ' + (error as Error).message, 'error')
    }
  }

  async function downloadShipment() {
    const filename = result.value?.doc_name
    if (!filename) return
    try {
      const response = await api.download(`/api/shipment/download/${encodeURIComponent(filename)}`)
      downloadBlob(await response.blob(), filename)
    } catch (error) {
      showStatus('下载失败: ' + (error as Error).message, 'error')
    }
  }

  function resetForm() {
    form.templateName = ''
    form.purchaseUnit = ''
    form.contactPerson = ''
    form.orderNumber = ''
    form.autoPrint = false
    products.value = []
    result.value = null
    form.purchaseDate = new Date().toISOString().split('T')[0]
    generateOrderNumber()
  }

  onMounted(() => {
    loadTemplates()
    loadPurchaseUnits()
    loadAllProducts()
    generateOrderNumber()
  })

  return {
    goOrdersList,
    goTemplatePreview,
    templates,
    purchaseUnits,
    allProducts,
    products,
    status,
    form,
    result,
    showProductSelector,
    productSearchQuery,
    searchingProducts,
    filteredProductsForSelection,
    onPurchaseUnitChange,
    onDateChange,
    loadTemplates,
    addProductRow,
    removeProductRow,
    calculateKg,
    calculateAmount,
    onProductNameSelect,
    searchProductsForSelection,
    selectProductForAdd,
    generateShipment, downloadShipment,
    resetForm,
  }
}

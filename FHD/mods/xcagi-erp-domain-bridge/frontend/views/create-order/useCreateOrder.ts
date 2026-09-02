import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/index'
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

// 模板下拉项（/templates?action=api，模板仅访问 name）
interface TemplateOption {
  name: string
}

// 购买单位（/api/purchase_units）
interface PurchaseUnit {
  unit_name: string
  contact_person?: string
}

// 产品名称库（/api/product_names）
interface ProductName {
  id: number
  name: string
  model_number?: string
  specification?: number
  price?: number
  purchase_unit_name?: string
}

// 订单产品编辑行（本地状态）
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

// /documents 生成结果（模板访问 output_filename）
interface ShipmentResult {
  success: boolean
  output_filename?: string
  message?: string
}

// 发货单可编辑数据结构（提交给 /documents 的 editable_data）
interface ShipmentHeaderCell {
  purchase_unit: string
  contact_person: string
  purchase_date: string
  order_number: string
}

type ShipmentRowCells = Record<number, string | number>

interface ShipmentEditableData {
  header_row: Record<number, ShipmentHeaderCell>
  product_rows: ShipmentRowCells[]
  price_row: Record<number, string | number>
}

declare global {
  interface Window {
    __VUE_FILL_ORDER__?: (data: AIFillOrderPayload | null) => void
  }
}

// 拆分自 CreateOrderView.vue script（原第 179–563 行）；逻辑逐字迁移，行为不变。
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

  onMounted(() => {
    loadTemplates()
    loadPurchaseUnits()
    loadAllProducts()
    generateOrderNumber()
    setupAIEventListener()
  })

  onUnmounted(() => {
    window.removeEventListener('xcagi:ai-fill-order', handleAIFillOrder as EventListener)
    if (window.__VUE_FILL_ORDER__ === handleAIFillOrder) {
      delete window.__VUE_FILL_ORDER__
    }
  })

  const templates = ref<TemplateOption[]>([])
  const purchaseUnits = ref<PurchaseUnit[]>([])
  const allProducts = ref<ProductName[]>([])
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
      const response = await fetch('/templates?action=api', {
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
      const data: { success: boolean; templates: TemplateOption[] } = await response.json()
      if (data.success) {
        templates.value = data.templates
        if (data.templates.length > 0 && !form.templateName) {
          form.templateName = data.templates[0].name
        }
      }
    } catch (error) {
      console.error('加载模板失败:', error)
    }
  }

  function onTemplateChange() {
    console.log('已选择模板:', form.templateName)
  }

  async function loadPurchaseUnits() {
    try {
      const response = await fetch('/api/purchase_units')
      const data: { success: boolean; data: PurchaseUnit[] } = await response.json()
      if (data.success) {
        purchaseUnits.value = data.data
      }
    } catch (error) {
      console.error('加载购买单位失败:', error)
    }
  }

  async function onPurchaseUnitChange() {
    if (form.purchaseUnit) {
      try {
        const response = await fetch(`/api/purchase_units/by_name/${encodeURIComponent(form.purchaseUnit)}`)
        const data: { success: boolean; data: PurchaseUnit } = await response.json()
        if (data.success) {
          form.contactPerson = data.data.contact_person || ''
        }
      } catch (error) {
        console.error('获取购买单位信息失败:', error)
      }
    }
  }

  async function loadAllProducts() {
    try {
      const response = await fetch('/api/product_names')
      const data: { success: boolean; data: ProductName[] } = await response.json()
      if (data.success) {
        allProducts.value = data.data
      }
    } catch (error) {
      console.error('加载产品名称列表失败:', error)
    }
  }

  async function generateOrderNumber() {
    try {
      const response = await fetch('/orders/next_number?suffix=A')
      const data: { success: boolean; data: { order_number: string } } = await response.json()
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
        product.specification = selected.specification
        calculateKg(index)
      }
      if (selected.price) {
        product.unitPrice = selected.price
        calculateAmount(index)
      }
    }
  }

  function onProductModelChange(_product: OrderProductRow, _index: number) {
    // Auto-fill name when model changes
  }

  function searchProductsForSelection() {
    searchingProducts.value = true
    setTimeout(() => {
      searchingProducts.value = false
    }, 300)
  }

  function selectProductForAdd(product: ProductName) {
    addProductRow()
    const newProduct = products.value[products.value.length - 1]
    newProduct.nameId = product.id
    newProduct.name = product.name || ''
    newProduct.model = product.model_number || ''
    if (product.specification) {
      newProduct.specification = product.specification
      calculateKg(products.value.length - 1)
    }
    if (product.price) {
      newProduct.unitPrice = product.price
      calculateAmount(products.value.length - 1)
    }
    showProductSelector.value = false
  }

  async function generateShipment() {
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

    const editableData: ShipmentEditableData = {
      header_row: {},
      product_rows: [],
      price_row: {}
    }

    const dateStr = form.purchaseDate.replace(/(\d{4})-(\d{2})-(\d{2})/, '$1年$2月$3日')
    editableData.header_row[1] = {
      purchase_unit: form.purchaseUnit,
      contact_person: form.contactPerson,
      purchase_date: dateStr,
      order_number: form.orderNumber
    }

    products.value.forEach((product, index) => {
      const rowNum = index + 4
      const productData: ShipmentRowCells = {}
      productData[1] = product.model || ''
      productData[4] = product.name || ''
      productData[5] = product.quantityBox || ''
      productData[6] = product.specification || ''
      productData[7] = product.quantityKg || ''
      productData[8] = product.unitPrice || ''
      productData[9] = product.amount || ''
      editableData.product_rows.push(productData)
    })

    try {
      const response = await fetch('/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_name: form.templateName,
          editable_data: editableData,
          // 统一策略：仅使用编号模式，禁用其他模式分支
          number_mode: true,
          custom_mode: false
        })
      })

      const data: ShipmentResult = await response.json()
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
    onTemplateChange,
    onPurchaseUnitChange,
    onDateChange,
    loadTemplates,
    addProductRow,
    removeProductRow,
    calculateKg,
    calculateAmount,
    onProductNameSelect,
    onProductModelChange,
    searchProductsForSelection,
    selectProductForAdd,
    generateShipment,
    resetForm,
  }
}

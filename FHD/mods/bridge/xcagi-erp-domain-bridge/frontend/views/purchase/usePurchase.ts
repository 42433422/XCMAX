import { ref, onMounted, onActivated, type Ref } from 'vue'
import { get, post, productsApi } from '@/api'
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog'

interface OrderItem {
  id?: number
  received_quantity?: number
  order_item_id?: number
  remaining_quantity?: number
  product_id: number | string
  quantity: number
  unit_price: number
  amount: number
}

interface PurchaseOrder {
  id: number
  order_no: string
  supplier_id: number | string
  supplier_name: string
  order_date: string
  delivery_date: string
  remark: string
  items: OrderItem[]
  total_amount: number
  status: string
}

interface InboundRecord {
  id: number
  inbound_no: string
  supplier_name: string
  inbound_date: string
  total_amount: number
  status: string
}

interface Supplier {
  id: number
  code: string
  name: string
  contact_person: string
  contact_phone: string
  contact_email: string
  address: string
  rating: number
  status: string
  remark: string
}

interface Product {
  id: number
  name: string
  price: number
}

type OrderForm = Omit<PurchaseOrder, 'id' | 'order_no' | 'supplier_name' | 'status'> & { id: number | null }

type SupplierForm = Omit<Supplier, 'id' | 'status'> & { id: number | null }

interface ApiListResponse<T> {
  success: boolean
  message?: string
  data?: T[]
}

interface ApiWriteResponse {
  success: boolean
  message?: string
  data?: { id?: number }
}

export function usePurchase() {
    const activeTab = ref('orders')
    const orders = ref<PurchaseOrder[]>([])
    const inbounds = ref<InboundRecord[]>([])
    const suppliers = ref<Supplier[]>([])
    const products = ref<Product[]>([])
    const filterStatus = ref('')
    const selectedSupplier = ref('')
    const showOrderModalFlag = ref(false)
    const showSupplierModalFlag = ref(false)
    const isEditOrder = ref(false)
    const isEditSupplier = ref(false)
    const receiving = ref(false)
    const orderSaving = ref(false)
    const supplierSaving = ref(false)
    const approvingOrderId = ref<number | null>(null)
    const orderLoading = ref(false)
    const orderListError = ref('')
    let orderReadSequence = 0
    const warehouses = ref<{ id: number; name: string }[]>([])
    const receiveWarehouse = ref<number | ''>('')

    const orderForm = ref<OrderForm>({
      id: null,
      supplier_id: '',
      order_date: new Date().toISOString().split('T')[0],
      delivery_date: '',
      remark: '',
      items: [],
      total_amount: 0
    })

    const supplierForm = ref<SupplierForm>({
      id: null,
      code: '',
      name: '',
      contact_person: '',
      contact_phone: '',
      contact_email: '',
      address: '',
      rating: 3,
      remark: ''
    })

    const loadList = async <T,>(url: string, target: Ref<T[]>, params = {}, request?: () => Promise<ApiListResponse<T>>) => {
      try {
        const res = await (request ? request() : get<ApiListResponse<T>>(url, params))
        if (res.success) target.value = res.data || []
      } catch (e) {
        console.error(`加载 ${url} 失败`, e)
      }
    }
    const loadOrders = async () => {
      const sequence = ++orderReadSequence
      const params = { ...(filterStatus.value ? { status: filterStatus.value } : {}), ...(selectedSupplier.value ? { supplier_id: selectedSupplier.value } : {}) }
      orderLoading.value = true
      orderListError.value = ''
      try {
        const response = await get<ApiListResponse<PurchaseOrder>>('/api/purchase/orders', params)
        if (sequence !== orderReadSequence) return
        if (!response.success) throw new Error(response.message || '采购订单读取失败')
        orders.value = Array.isArray(response.data) ? response.data : []
      } catch (e) {
        if (sequence !== orderReadSequence) return
        orders.value = []
        orderListError.value = e instanceof Error ? e.message : '采购订单读取失败'
      } finally {
        if (sequence === orderReadSequence) orderLoading.value = false
      }
    }
    const loadInbounds = () => loadList('/api/purchase/inbounds', inbounds)
    const loadSuppliers = () => loadList('/api/purchase/suppliers', suppliers)

    const loadProducts = () => loadList('产品', products, {}, () => productsApi.getProducts({ page: 1, per_page: 1000 }))

    const getStatusText = (status: string) => {
      const map: Record<string, string> = {
        draft: '草稿',
        approved: '已审核',
        partial: '部分入库',
        completed: '已完成',
        cancelled: '已取消'
      }
      return map[status] || status
    }

    const showOrderModal = () => {
      receiving.value = false
      isEditOrder.value = false
      orderForm.value = {
        id: null,
        supplier_id: '',
        order_date: new Date().toISOString().split('T')[0],
        delivery_date: '',
        remark: '',
        items: [],
        total_amount: 0
      }
      showOrderModalFlag.value = true
    }

    const editOrder = (order: PurchaseOrder) => {
      receiving.value = false
      isEditOrder.value = true
      orderForm.value = {
        id: order.id,
        supplier_id: order.supplier_id,
        order_date: order.order_date,
        delivery_date: order.delivery_date || '',
        remark: order.remark || '',
        items: order.items || [],
        total_amount: order.total_amount
      }
      showOrderModalFlag.value = true
    }

    const receiveOrder = async (order: PurchaseOrder) => {
      if (!['approved', 'partial'].includes(order.status)) return
      const res = await get<ApiListResponse<{ id: number; name: string }>>('/api/inventory/warehouses')
      if (!res.success) { await appAlert(res.message || '加载仓库失败'); return }
      warehouses.value = res.data || []
      receiveWarehouse.value = ''
      editOrder(order)
      receiving.value = true
      orderForm.value.items = order.items.map(item => ({ ...item, order_item_id: item.id, remaining_quantity: item.quantity - (item.received_quantity || 0), quantity: item.quantity - (item.received_quantity || 0) })).filter(item => item.quantity > 0)
      orderForm.value.items.forEach((_, idx) => calcItemAmount(idx))
    }
    const createWarehouse = async () => {
      const name = (await appPrompt('收货仓库名称'))?.trim()
      if (!name) return
      const res = await post<ApiWriteResponse>('/api/inventory/warehouses', { name, code: `WH-${crypto.randomUUID()}` })
      if (!res.success || !res.data?.id) { await appAlert(res.message || '创建仓库失败'); return }
      warehouses.value.push({ id: res.data.id, name }); receiveWarehouse.value = res.data.id
    }

    const addOrderItem = () => {
      orderForm.value.items.push({
        product_id: '',
        quantity: 1,
        unit_price: 0,
        amount: 0
      })
    }

    const removeOrderItem = (idx: number) => {
      orderForm.value.items.splice(idx, 1)
      calcTotalAmount()
    }

    const selectProduct = (idx: number) => {
      const product = products.value.find(p => p.id === orderForm.value.items[idx].product_id)
      if (product) {
        orderForm.value.items[idx].unit_price = product.price || 0
        calcItemAmount(idx)
      }
    }

    const calcItemAmount = (idx: number) => {
      const item = orderForm.value.items[idx]
      item.amount = (item.quantity || 0) * (item.unit_price || 0)
      calcTotalAmount()
    }

    const calcTotalAmount = () => {
      orderForm.value.total_amount = orderForm.value.items.reduce((sum: number, item: OrderItem) => {
        return sum + (item.amount || 0)
      }, 0)
    }

    const saveOrder = async () => {
      if (orderSaving.value) return
      if (receiving.value && (!receiveWarehouse.value || orderForm.value.items.some(item => !(item.quantity > 0) || item.quantity > (item.remaining_quantity || 0)))) {
        await appAlert('请选择收货仓库，数量不得超过订单待收数量'); return
      }
      if (!orderForm.value.supplier_id) {
        await appAlert('请选择供应商')
        return
      }
      if (orderForm.value.items.length === 0) {
        await appAlert('请添加订单明细')
        return
      }
      const missing = orderForm.value.items.findIndex((item: OrderItem) => !item.product_id)
      if (missing >= 0) {
        await appAlert(`第 ${missing + 1} 行明细未选择产品`)
        return
      }
      const invalidQuantity = orderForm.value.items.findIndex(item =>
        !Number.isFinite(Number(item.quantity)) || Number(item.quantity) <= 0 ||
        !Number.isFinite(Number(item.unit_price)) || Number(item.unit_price) < 0
      )
      if (invalidQuantity >= 0) { await appAlert(`第 ${invalidQuantity + 1} 行数量或单价无效`); return }
      orderSaving.value = true
      try {
        const res = receiving.value
          ? await post<ApiWriteResponse>('/api/purchase/inbounds', { order_id: orderForm.value.id, supplier_id: orderForm.value.supplier_id, warehouse_id: receiveWarehouse.value, items: orderForm.value.items, remark: orderForm.value.remark })
          : isEditOrder.value
          ? await post<ApiWriteResponse>(`/api/purchase/orders/${orderForm.value.id}`, orderForm.value)
          : await post<ApiWriteResponse>('/api/purchase/orders', orderForm.value)
        if (res.success) {
          await loadOrders()
          if (receiving.value) { await loadInbounds(); activeTab.value = 'inbounds' }
          showOrderModalFlag.value = false
          await appAlert(orderListError.value ? '已保存，但采购订单重新读取失败，请刷新确认。' : '保存成功')
        } else {
          await appAlert('保存失败: ' + (res.message || '服务端未确认'))
        }
      } catch (e) {
        await appAlert(`保存结果需要核对：${e instanceof Error ? e.message : '请求失败'}`)
      } finally {
        orderSaving.value = false
      }
    }

    const approveOrder = async (order: PurchaseOrder) => {
      if (approvingOrderId.value !== null) return
      approvingOrderId.value = order.id
      try {
        if (!(await appConfirm('确认审核该订单？'))) return
        const res = await post<ApiWriteResponse>(`/api/purchase/orders/${order.id}/approve`)
        if (res.success) {
          await loadOrders()
          await appAlert(orderListError.value ? '已审核，但订单列表刷新失败，请核对。' : '审核成功')
        } else {
          await appAlert('审核失败: ' + (res.message || '服务端未确认'))
        }
      } catch (e) {
        await appAlert(`审核结果需要核对：${e instanceof Error ? e.message : '请求失败'}`)
      } finally {
        approvingOrderId.value = null
      }
    }

    const showSupplierModal = () => {
      isEditSupplier.value = false
      supplierForm.value = {
        id: null,
        code: '',
        name: '',
        contact_person: '',
        contact_phone: '',
        contact_email: '',
        address: '',
        rating: 3,
        remark: ''
      }
      showSupplierModalFlag.value = true
    }

    const editSupplier = (supplier: Supplier) => {
      isEditSupplier.value = true
      supplierForm.value = { ...supplier }
      showSupplierModalFlag.value = true
    }

    const saveSupplier = async () => {
      if (supplierSaving.value) return
      if (!supplierForm.value.code || !supplierForm.value.name) {
        await appAlert('请填写必填项')
        return
      }
      supplierSaving.value = true
      try {
        const res = isEditSupplier.value
          ? await post<ApiWriteResponse>(`/api/purchase/suppliers/${supplierForm.value.id}`, supplierForm.value)
          : await post<ApiWriteResponse>('/api/purchase/suppliers', supplierForm.value)
        if (res.success) {
          await loadSuppliers()
          showSupplierModalFlag.value = false
          await appAlert('保存成功')
        } else {
          await appAlert('保存失败: ' + (res.message || '服务端未确认'))
        }
      } catch (e) {
        await appAlert(`供应商保存结果需要核对：${e instanceof Error ? e.message : '请求失败'}`)
      } finally {
        supplierSaving.value = false
      }
    }

    const refreshPurchaseView = () => {
      loadOrders()
      loadInbounds()
      loadSuppliers()
      loadProducts()
    }
    let activatedOnce = false
    onMounted(refreshPurchaseView)
    // App 以 keep-alive 缓存路由页：再次进入时重新拉取，避免显示离开前的旧列表。
    onActivated(() => {
      if (activatedOnce) refreshPurchaseView()
      activatedOnce = true
    })

    return {
      activeTab,
      orders,
      orderLoading,
      orderListError,
      orderSaving,
      supplierSaving,
      approvingOrderId,
      inbounds,
      suppliers,
      products,
      filterStatus,
      selectedSupplier,
      showOrderModalFlag,
      showSupplierModalFlag,
      isEditOrder,
      isEditSupplier,
      orderForm,
      supplierForm,
      loadOrders,
      getStatusText,
      showOrderModal,
      editOrder,
      viewOrder: editOrder,
      addOrderItem,
      removeOrderItem,
      selectProduct,
      calcItemAmount,
      saveOrder,
      approveOrder,
      receiving, warehouses, receiveWarehouse, receiveOrder, createWarehouse,
      showSupplierModal,
      editSupplier,
      saveSupplier
    }
}

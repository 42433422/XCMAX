import { ref, onMounted } from 'vue'
import { get, post } from '@/api'
import { appAlert, appConfirm } from '@/utils/appDialog'

// 拆分自 PurchaseView.vue script（原第 262–540 行）；逻辑逐字迁移，行为不变。
export function usePurchase() {
    const activeTab = ref('orders')
    const orders = ref<any[]>([])
    const inbounds = ref<any[]>([])
    const suppliers = ref<any[]>([])
    const products = ref<any[]>([])
    const filterStatus = ref('')
    const selectedSupplier = ref('')
    const showOrderModalFlag = ref(false)
    const showSupplierModalFlag = ref(false)
    const isEditOrder = ref(false)
    const isEditSupplier = ref(false)

    const orderForm = ref<Record<string, any>>({
      id: null,
      supplier_id: '',
      order_date: new Date().toISOString().split('T')[0],
      delivery_date: '',
      remark: '',
      items: [],
      total_amount: 0
    })

    const supplierForm = ref<Record<string, any>>({
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

    const loadOrders = async () => {
      try {
        const params: Record<string, unknown> = {}
        if (filterStatus.value) params.status = filterStatus.value
        if (selectedSupplier.value) params.supplier_id = selectedSupplier.value
        const res: any = await get('/api/purchase/orders', params)
        if (res.success) {
          orders.value = res.data || []
        }
      } catch (e) {
        console.error('加载订单失败', e)
      }
    }

    const loadInbounds = async () => {
      try {
        const res: any = await get('/api/purchase/inbounds')
        if (res.success) {
          inbounds.value = res.data || []
        }
      } catch (e) {
        console.error('加载入库记录失败', e)
      }
    }

    const loadSuppliers = async () => {
      try {
        const res: any = await get('/api/purchase/suppliers')
        if (res.success) {
          suppliers.value = res.data || []
        }
      } catch (e) {
        console.error('加载供应商失败', e)
      }
    }

    const loadProducts = async () => {
      try {
        const res: any = await get('/api/products')
        if (res.success) {
          products.value = res.data || []
        }
      } catch (e) {
        console.error('加载产品失败', e)
      }
    }

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

    const editOrder = (order: any) => {
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

    const viewOrder = (order: any) => {
      isEditOrder.value = true
      orderForm.value = { ...order }
      showOrderModalFlag.value = true
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
      orderForm.value.total_amount = orderForm.value.items.reduce((sum: number, item: any) => {
        return sum + (item.amount || 0)
      }, 0)
    }

    const saveOrder = async () => {
      if (!orderForm.value.supplier_id) {
        await appAlert('请选择供应商')
        return
      }
      if (orderForm.value.items.length === 0) {
        await appAlert('请添加订单明细')
        return
      }
      try {
        const res: any = isEditOrder.value
          ? await post(`/api/purchase/orders/${orderForm.value.id}`, orderForm.value)
          : await post('/api/purchase/orders', orderForm.value)
        if (res.success) {
          await appAlert('保存成功')
          showOrderModalFlag.value = false
          loadOrders()
        } else {
          await appAlert('保存失败: ' + res.message)
        }
      } catch (e) {
        await appAlert('保存失败')
      }
    }

    const approveOrder = async (order: any) => {
      if (!(await appConfirm('确认审核该订单？'))) return
      try {
        const res: any = await post(`/api/purchase/orders/${order.id}/approve`)
        if (res.success) {
          await appAlert('审核成功')
          loadOrders()
        } else {
          await appAlert('审核失败: ' + res.message)
        }
      } catch (e) {
        await appAlert('审核失败')
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

    const editSupplier = (supplier: any) => {
      isEditSupplier.value = true
      supplierForm.value = { ...supplier }
      showSupplierModalFlag.value = true
    }

    const saveSupplier = async () => {
      if (!supplierForm.value.code || !supplierForm.value.name) {
        await appAlert('请填写必填项')
        return
      }
      try {
        const res: any = isEditSupplier.value
          ? await post(`/api/purchase/suppliers/${supplierForm.value.id}`, supplierForm.value)
          : await post('/api/purchase/suppliers', supplierForm.value)
        if (res.success) {
          await appAlert('保存成功')
          showSupplierModalFlag.value = false
          loadSuppliers()
        } else {
          await appAlert('保存失败: ' + res.message)
        }
      } catch (e) {
        await appAlert('保存失败')
      }
    }

    onMounted(() => {
      loadOrders()
      loadInbounds()
      loadSuppliers()
      loadProducts()
    })

    return {
      activeTab,
      orders,
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
      viewOrder,
      addOrderItem,
      removeOrderItem,
      selectProduct,
      calcItemAmount,
      saveOrder,
      approveOrder,
      showSupplierModal,
      editSupplier,
      saveSupplier
    }
}

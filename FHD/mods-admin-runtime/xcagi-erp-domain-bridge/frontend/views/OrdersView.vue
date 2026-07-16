<template>
  <div class="page-view" id="view-orders">
    <div class="page-content">
      <div class="page-header">
        <h2>{{ ordersTitle }}</h2>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-secondary" data-testid="orders-export" @click="exportOrders" :disabled="store.loading">导出</button>
          <button class="btn btn-primary" @click="goCreateOrder">+ 新建订单</button>
          <button class="btn btn-danger" @click="handleClearAll" :disabled="store.loading">清空全部</button>
        </div>
      </div>
      <div class="search-box">
        <input v-model.trim="searchQuery" type="text" placeholder="搜索客户名/单号..." @input="doSearch">
      </div>
      <div class="card">
        <DataTable
          :columns="columns"
          :data="store.orders"
          :loading="store.loading"
          :selectable="false"
          row-key="id"
          empty-text="暂无出货记录"
        >
          <template #cell-order_number="{ value }">
            {{ value || '-' }}
          </template>
          <template #cell-customer_name="{ row }">
            {{ row.customer_name || row.purchase_unit || '-' }}
          </template>
          <template #cell-date="{ value }">
            {{ value || '-' }}
          </template>
          <template #cell-total_amount="{ value }">
            {{ formatAmount(value) }}
          </template>
          <template #cell-status="{ value }">
            <span class="badge badge-success">{{ value || '已完成' }}</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn btn-secondary btn-sm"
              data-testid="order-edit"
              @click="openEdit(row)"
              :disabled="store.loading || !row.id"
            >
              编辑
            </button>
            <button
              class="btn btn-danger btn-sm"
              @click="handleDelete(row.id || row.order_number)"
              :disabled="store.loading || !(row.id || row.order_number)"
            >
              删除
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <div v-if="editingOrder" class="modal active" data-testid="order-edit-modal">
      <div class="modal-content">
        <div class="modal-header">编辑出货单</div>
        <div class="modal-body">
          <div class="form-group">
            <label for="order-purchase-unit">购买单位</label>
            <input id="order-purchase-unit" v-model.trim="editForm.purchase_unit" type="text">
          </div>
          <div class="form-group">
            <label for="order-product-name">产品名称</label>
            <input id="order-product-name" v-model.trim="editForm.product_name" type="text">
          </div>
          <div class="form-group">
            <label for="order-quantity-kg">数量（KG）</label>
            <input id="order-quantity-kg" v-model.number="editForm.quantity_kg" type="number" min="0" step="0.01">
          </div>
          <div class="form-group">
            <label for="order-status">状态</label>
            <select id="order-status" v-model="editForm.status">
              <option value="pending">待处理</option>
              <option value="printed">已打印</option>
              <option value="completed">已完成</option>
              <option value="cancelled">已取消</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeEdit">取消</button>
          <button class="btn btn-primary" data-testid="order-edit-save" @click="saveEdit" :disabled="store.loading">保存</button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      v-model="showClearConfirm"
      title="清空全部"
      message="确定要清空所有出货记录吗？此操作不可恢复！"
      confirm-text="清空"
      confirm-class="btn-danger"
      @confirm="confirmClearAll"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useOrdersStore } from '@/stores/orders';
import { pushErpPage } from '@/utils/erpPagePaths';
import { storeToRefs } from 'pinia';
import DataTable from '@/components/DataTable.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog';
import { useIndustryFieldSchema } from '@/composables/useIndustryFieldSchema';
import ordersApi from '@/api/orders';

const router = useRouter();
const store = useOrdersStore();
const { orders } = storeToRefs(store);

// 行业感知：订单标题与「客户」列随行业变（发货单/考勤单、客户/部门），取代硬编码
const ordersSchema = useIndustryFieldSchema('orders');
const customerSchema = useIndustryFieldSchema('customers');
const ordersTitle = computed(() => `${ordersSchema.label.value || '出货单'}记录`);

function goCreateOrder() {
  pushErpPage(router, '/orders/create');
}

const searchQuery = ref('');
const showClearConfirm = ref(false);
const editingOrder = ref(null);
const editForm = ref({ purchase_unit: '', product_name: '', quantity_kg: 0, status: 'pending' });

const columns = computed(() => [
  { key: 'order_number', label: '单号' },
  { key: 'customer_name', label: customerSchema.entity.value || '客户' },
  { key: 'date', label: '日期' },
  { key: 'total_amount', label: '金额' },
  { key: 'status', label: '状态' }
]);

function formatAmount(value) {
  const n = Number(value || 0);
  if (Number.isNaN(n)) return '¥0';
  return `¥${n.toFixed(2)}`;
}

async function loadOrders() {
  await store.fetchOrders({ limit: 200 });
}

async function doSearch() {
  if (!searchQuery.value) {
    await loadOrders();
    return;
  }
  await store.searchOrders(searchQuery.value);
}

async function handleDelete(orderNumber) {
  if (!orderNumber) return;
  if (!(await appConfirm(`确定要删除订单 ${orderNumber} 吗？`, { danger: true }))) return;
  await store.deleteOrder(orderNumber);
}

function openEdit(order) {
  editingOrder.value = order;
  editForm.value = {
    purchase_unit: order.purchase_unit || order.customer_name || '',
    product_name: order.product_name || '',
    quantity_kg: Number(order.quantity_kg || 0),
    status: order.status || 'pending',
  };
}

function closeEdit() {
  editingOrder.value = null;
}

async function saveEdit() {
  const orderId = editingOrder.value?.id;
  if (!orderId || !editForm.value.purchase_unit || !editForm.value.product_name) {
    await appAlert('请填写购买单位和产品名称');
    return;
  }
  const result = await store.updateOrder(String(orderId), { ...editForm.value });
  if (!result.success) {
    await appAlert(result.message || '更新失败');
    return;
  }
  closeEdit();
}

async function exportOrders() {
  try {
    const response = await ordersApi.exportOrders({ q: searchQuery.value || '' });
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `出货单_${new Date().toISOString().slice(0, 10)}.xlsx`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
  } catch (error) {
    await appAlert(`导出失败：${error instanceof Error ? error.message : '请重试'}`);
  }
}

async function handleClearAll() {
  const key = await appPrompt('请输入密钥确认清空:', '', { title: '密钥验证' });
  if (key !== '61408693') {
    await appAlert('密钥错误');
    return;
  }
  showClearConfirm.value = true;
}

async function confirmClearAll() {
  await store.clearAllOrders();
}

onMounted(() => {
  loadOrders();
});
</script>

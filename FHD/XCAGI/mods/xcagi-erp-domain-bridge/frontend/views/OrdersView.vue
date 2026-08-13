<template>
  <div class="page-view" id="view-orders">
    <div class="page-content">
      <div class="page-header">
        <h2>出货单记录</h2>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-primary" @click="goCreateOrder">+ 新建订单</button>
          <button class="btn btn-danger" @click="handleClearAll" :disabled="store.loading">清空全部</button>
        </div>
      </div>
      <div class="search-box">
        <input v-model.trim="searchQuery" type="text" placeholder="搜索客户名/单号..." @input="doSearch">
      </div>
      <section v-if="tutorialSalesEvidence" class="tutorial-business-proof" data-tutorial-id="tutorial-order-proof">
        <strong>教学销售订单 · 服务端核验</strong>
        <span>客户B · A 产品</span>
        <span>订单 {{ tutorialCount('sales_order_count') }} 张 · 明细 {{ tutorialCount('sales_order_item_count') }} 条</span>
        <span>数量 10 · 单价 ¥100 · 金额 ¥{{ tutorialCount('order_total') }}</span>
      </section>
      <div class="card" data-tutorial-id="orders-table">
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
import { computed, ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useOrdersStore } from '@/stores/orders';
import { pushErpPage } from '@/utils/erpPagePaths';
import { storeToRefs } from 'pinia';
import DataTable from '@/components/DataTable.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog';
import { useTutorialV2Store } from '@/stores/tutorialV2';

const router = useRouter();
const store = useOrdersStore();
const { orders } = storeToRefs(store);
const tutorialStore = useTutorialV2Store();
const tutorialSalesEvidence = computed(() => tutorialStore.courses
  .find((course) => course.id === 'sales-to-cash')
  ?.run?.steps.find((step) => step.id === 'approve-sales-request')
  ?.evidence || null);

function tutorialCount(key) {
  return tutorialSalesEvidence.value?.counts?.[key] ?? 0;
}

function goCreateOrder() {
  pushErpPage(router, '/orders/create');
}

const searchQuery = ref('');
const showClearConfirm = ref(false);

const columns = [
  { key: 'order_number', label: '单号' },
  { key: 'customer_name', label: '客户' },
  { key: 'date', label: '日期' },
  { key: 'total_amount', label: '金额' },
  { key: 'status', label: '状态' }
];

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
  void tutorialStore.loadCourses().catch(() => undefined);
});
</script>

<style scoped>
.tutorial-business-proof { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-bottom: 14px; padding: 12px 14px; border: 1px solid #e7c46a; border-radius: 10px; background: #fff8df; color: #6f5314; }
.tutorial-business-proof strong { color: #744707; }
</style>

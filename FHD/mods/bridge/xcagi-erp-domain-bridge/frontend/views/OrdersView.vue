<template>
  <div class="page-view" id="view-orders">
    <div class="page-content">
      <div class="page-header">
        <h2>出货单记录</h2>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-primary" @click="goCreateOrder">+ 新建订单</button>
          <button class="btn btn-danger" @click="handleClearAll" :disabled="!canClearAll" title="清空当前业务空间内全部出货记录，不限于当前筛选结果">清空全部出货记录</button>
        </div>
      </div>
      <div class="search-box erp-filters">
        <input v-model.trim="searchQuery" type="text" placeholder="搜索客户名/单号..." @input="scheduleSearch">
      </div>
      <section v-if="tutorialSalesEvidence" class="tutorial-business-proof" data-tutorial-id="tutorial-order-proof">
        <strong>教学销售订单 · 服务端核验</strong>
        <span>客户B · A 产品</span>
        <span>订单 {{ tutorialCount('sales_order_count') }} 张 · 明细 {{ tutorialCount('sales_order_item_count') }} 条</span>
        <span>数量 10 · 单价 ¥100 · 金额 ¥{{ tutorialCount('order_total') }}</span>
      </section>
      <div class="card erp-list" data-tutorial-id="orders-table">
        <DataTable
          :columns="columns"
          :data="store.orders"
          :loading="store.loading"
          :error="store.error || ''"
          :selectable="false"
          row-key="order_number"
          empty-text="暂无出货记录"
          @retry="doSearch"
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
      message="确定要清空当前业务空间内全部出货记录吗？包括筛选外的记录，此操作不可恢复！"
      confirm-text="清空"
      confirm-class="btn-danger"
      @confirm="confirmClearAll"
    />
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onActivated, onDeactivated, onBeforeUnmount, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useOrdersStore } from '@/stores/orders';
import { pushErpPage } from '@/utils/erpPagePaths';
import { useRecordFocusQuery } from '@/composables/useRecordFocusQuery';
import DataTable from '@/components/DataTable.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';
import { appConfirm } from '@/utils/appDialog';
import { useTutorialV2Store } from '@/stores/tutorialV2';

const router = useRouter();
const store = useOrdersStore();
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
const { keyword: routeKeyword } = useRecordFocusQuery();
const showClearConfirm = ref(false);
const canClearAll = computed(() => !store.loading && !store.error && store.orders.length > 0);

const columns = [
  { key: 'order_number', label: '单号', sortable: true, minWidth: 145 },
  { key: 'customer_name', label: '客户', sortable: true, minWidth: 160 },
  { key: 'date', label: '日期', sortable: true, minWidth: 110 },
  { key: 'total_amount', label: '金额', sortable: true, minWidth: 110, align: 'right' },
  { key: 'status', label: '状态', minWidth: 100 }
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
  if (!searchQuery.value) return loadOrders();
  return store.searchOrders(searchQuery.value);
}

let searchTimer = null;
function cancelSearch() {
  if (searchTimer !== null) clearTimeout(searchTimer);
  searchTimer = null;
}
function scheduleSearch() {
  cancelSearch();
  searchTimer = setTimeout(() => { void doSearch(); }, 280);
}

async function handleDelete(orderNumber) {
  if (!orderNumber) return;
  if (!(await appConfirm(`确定要删除订单 ${orderNumber} 吗？`, { danger: true }))) return;
  const result = await store.deleteOrder(orderNumber);
  if (result.success) await doSearch();
}

async function handleClearAll() {
  if (!canClearAll.value) return;
  showClearConfirm.value = true;
}

async function confirmClearAll() {
  if (!canClearAll.value) return;
  const result = await store.clearAllOrders();
  if (result.success) await loadOrders();
}

let firstActivation = true;
onActivated(() => {
  if (firstActivation) { firstActivation = false; return; }
  void doSearch();
});
onDeactivated(cancelSearch);
onBeforeUnmount(cancelSearch);

watch(routeKeyword, (keyword) => {
  searchQuery.value = String(keyword || '').trim();
  void doSearch();
});

onMounted(() => {
  searchQuery.value = String(routeKeyword.value || '').trim();
  if (searchQuery.value) {
    void doSearch();
  } else {
    loadOrders();
  }
  void tutorialStore.loadCourses().catch(() => undefined);
});
</script>

<style scoped>
.tutorial-business-proof { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-bottom: 14px; padding: 12px 14px; border: 1px solid #e7c46a; border-radius: 10px; background: #fff8df; color: #6f5314; }
.tutorial-business-proof strong { color: #744707; }
</style>
<style scoped src="./erp-list-surfaces.css"></style>

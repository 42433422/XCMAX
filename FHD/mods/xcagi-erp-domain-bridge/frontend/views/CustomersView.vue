<template>
  <div class="page-view" id="view-customers">
    <div class="page-content">
      <div class="page-header customers-page-header">
        <div class="customers-header-main">
          <h2>{{ pageNavTitle }}</h2>
          <p class="muted customers-header-desc">
            购买单位与「{{ productsNavLabel }}」「{{ shipmentNavLabel }}」同源；可选单位筛选客户列表。
            <span v-if="pageNavTitle !== '客户管理'" class="customers-header-note">（当前行业显示为「{{ pageNavTitle }}」，数据实体为购买单位/客户）</span>
          </p>
          <div class="customers-unit-filter">
            <label class="customers-unit-label" for="customers-purchase-unit">购买单位</label>
            <select
              id="customers-purchase-unit"
              v-model="selectedPurchaseUnit"
              class="customers-unit-select"
              title="与产品页、出货记录页单位下拉一致"
            >
              <option value="">全部购买单位</option>
              <option
                v-for="(unit, idx) in purchaseUnitOptions"
                :key="unitOptionKey(unit, idx)"
                :value="unitOptionValue(unit)"
              >
                {{ unitOptionLabel(unit) }}
              </option>
            </select>
          </div>
        </div>
        <div class="header-actions customers-header-actions">
          <select
            v-model="selectedTemplateId"
            class="template-select"
            :disabled="loadingTemplateOptions || templateOptions.length === 0"
            title="客户管理导出模板"
          >
            <option value="" disabled>{{ loadingTemplateOptions ? '加载模板中...' : '请选择导出模板' }}</option>
            <option v-for="tpl in templateOptions" :key="tpl.id" :value="tpl.id">
              {{ tpl.name }}
            </option>
          </select>
          <button class="btn btn-icon" @click="triggerImport" title="上传Excel更新购买单位">
            <i class="fa fa-upload" aria-hidden="true"></i>
          </button>
          <input
            ref="importFileInput"
            type="file"
            accept=".xlsx"
            style="display:none"
            @change="handleImport"
          >
          <button
            class="btn btn-icon"
            @click="exportCustomers"
            title="导出购买单位Excel"
            :disabled="!selectedTemplateId"
          >
            <svg class="excel-icon-svg" viewBox="0 0 24 24" width="22" height="22">
              <rect width="24" height="24" rx="3" fill="#217346"/>
              <path stroke="#fff" stroke-width="2.2" stroke-linecap="round" fill="none" d="M7 7l10 10M17 7L7 17"/>
            </svg>
          </button>
          <button class="btn btn-primary" data-tutorial-id="customer-create" @click="openAddModal">+ 新建客户</button>
          <button v-if="selectedIds.length > 0" class="btn btn-danger" @click="handleBatchDelete">批量删除 ({{ selectedIds.length }})</button>
        </div>
      </div>
      <div class="stat-cards">
        <div class="stat-card">
          <div class="number">{{ totalCustomers }}</div>
          <div class="label">客户总数</div>
        </div>
      </div>
      <div class="card">
        <DataTable
          :columns="columns"
          :data="customers"
          :loading="loading"
          :selectable="true"
          :selected-ids="selectedIds"
          :has-more="hasMore"
          row-key="id"
          empty-text="暂无客户数据"
          @update:selected-ids="selectedIds = $event"
          @load-more="loadMoreCustomers"
        >
          <template #cell-customer_name="{ row }: any">
            {{ row.customer_name || row.unit_name || row.name || '-' }}
          </template>
          <template #cell-contact_person="{ value }">
            {{ value || '-' }}
          </template>
          <template #cell-contact_phone="{ value }">
            {{ value || '-' }}
          </template>
          <template #cell-address="{ value }">
            {{ value || '-' }}
          </template>
          <template #actions="{ row }">
            <button
              class="btn btn-primary"
              style="padding: 6px 10px; font-size: 12px; margin-right: 5px;"
              @click="openEditModal(row)"
            >
              编辑
            </button>
            <button
              class="btn btn-danger"
              style="padding: 6px 10px; font-size: 12px;"
              @click="handleDelete(row)"
            >
              删除
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <ConfirmDialog
      v-model="showDeleteConfirm"
      title="确认删除"
      :message="`确定删除客户 &quot;${itemToDelete?.customer_name || itemToDelete?.unit_name || ''}&quot; 吗？`"
      confirm-text="删除"
      confirm-class="btn-danger"
      @confirm="confirmDelete"
    />

    <ConfirmDialog
      v-model="showBatchDeleteConfirm"
      title="批量删除"
      :message="`确定要删除选中的 ${selectedIds.length} 个客户吗？`"
      confirm-text="批量删除"
      confirm-class="btn-danger"
      @confirm="confirmBatchDelete"
    />

    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal-content">
        <div class="modal-header">
          <h3>新建客户</h3>
          <button class="btn btn-icon" @click="closeAddModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>客户名称 *</label>
            <input data-tutorial-id="customer-name" type="text" v-model="addForm.customer_name" placeholder="请输入客户名称" />
          </div>
          <div class="form-group">
            <label>联系人</label>
            <input type="text" v-model="addForm.contact_person" placeholder="请输入联系人" />
          </div>
          <div class="form-group">
            <label>电话</label>
            <input type="text" v-model="addForm.contact_phone" placeholder="请输入联系电话" />
          </div>
          <div class="form-group">
            <label>地址</label>
            <input type="text" v-model="addForm.address" placeholder="请输入地址" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeAddModal">取消</button>
          <button class="btn btn-primary" data-tutorial-id="customer-save" @click="saveAdd" :disabled="loading">创建</button>
        </div>
      </div>
    </div>

    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content">
        <div class="modal-header">
          <h3>编辑客户</h3>
          <button class="btn btn-icon" @click="closeEditModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>客户名称</label>
            <input type="text" v-model="editForm.customer_name" placeholder="请输入客户名称" />
          </div>
          <div class="form-group">
            <label>联系人</label>
            <input type="text" v-model="editForm.contact_person" placeholder="请输入联系人" />
          </div>
          <div class="form-group">
            <label>电话</label>
            <input type="text" v-model="editForm.contact_phone" placeholder="请输入联系电话" />
          </div>
          <div class="form-group">
            <label>地址</label>
            <input type="text" v-model="editForm.address" placeholder="请输入地址" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeEditModal">取消</button>
          <button class="btn btn-primary" @click="saveEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./customers/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装（DataTable/ConfirmDialog 组件在此导入）。
import DataTable from '@/components/DataTable.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';
import { useCustomers } from './customers/useCustomers'

const {
  pageNavTitle, productsNavLabel, shipmentNavLabel,
  customers, purchaseUnitOptions, selectedPurchaseUnit, loading, selectedIds,
  totalCustomers, hasMore, importFileInput,
  showEditModal, showDeleteConfirm, showBatchDeleteConfirm, showAddModal,
  addForm, itemToDelete, templateOptions, selectedTemplateId, loadingTemplateOptions,
  editForm, columns,
  unitOptionValue, unitOptionLabel, unitOptionKey,
  loadMoreCustomers, handleDelete, confirmDelete, handleBatchDelete, confirmBatchDelete,
  openEditModal, closeEditModal, openAddModal, closeAddModal,
  saveAdd, saveEdit, exportCustomers, triggerImport, handleImport,
} = useCustomers()
</script>

<style scoped src="./customers/customers.css"></style>

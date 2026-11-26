<template>
  <div class="page-view" id="view-materials">
    <div class="page-content">
      <div class="page-header">
        <h2>{{ materialsPageTitle }}</h2>
        <div>
          <button class="btn btn-secondary" @click="exportData" style="margin-right:10px;">导出</button>
          <button class="btn btn-primary" @click="showAddModal">+ 添加</button>
        </div>
      </div>

      <div class="tabs">
        <button :class="{active: activeTab === 'materials'}" @click="activeTab = 'materials'">{{ resourceTabLabel }}</button>
        <button :class="{active: activeTab === 'warehouse'}" @click="activeTab = 'warehouse'">{{ warehouseTabLabel }}</button>
        <button :class="{active: activeTab === 'inout'}" @click="activeTab = 'inout'">{{ inoutTabLabel }}</button>
        <button :class="{active: activeTab === 'supplier'}" @click="activeTab = 'supplier'; loadSuppliers()">{{ supplierTabLabel }}</button>
      </div>

      <div v-if="activeTab === 'materials'" class="card">
        <div class="search-box">
          <input v-model="searchQuery" type="text" placeholder="搜索..." @input="scheduleMaterialsSearch">
          <select v-model="selectedCategory" @change="loadMaterials()">
            <option value="">全部分类</option>
            <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
          </select>
        </div>
        <DataTable :columns="materialColumns" :data="materials" :loading="listLoading.materials" :error="listErrors.materials" :server-pagination="materialPagination" :has-more="false" @page-change="loadMaterials" @retry="loadMaterials(materialPagination.page)">
          <template #cell-quantity="{ row }: any">
            <span :class="{ 'text-red': row.quantity < (row.min_stock || 0) }">{{ row.quantity }} {{ row.unit || '' }}</span>
          </template>
          <template #cell-price="{ value }">{{ value == null ? '-' : '¥' + Number(value).toFixed(2) }}</template>
          <template #actions="{ row }: any">
            <button class="btn btn-sm btn-secondary" :disabled="saving || listLoading.materials || !!listErrors.materials" @click="editMaterial(row)">编辑</button>
            <button class="btn btn-sm btn-danger" :disabled="saving || listLoading.materials || !!listErrors.materials" @click="deleteMaterial(row)">删除</button>
          </template>
        </DataTable>
      </div>

      <div v-if="activeTab === 'warehouse'" class="card">
        <div class="page-header" style="padding:0;border:none;">
          <h4>仓库列表</h4>
          <button class="btn btn-primary btn-sm" @click="showWarehouseModal">+ 添加仓库</button>
        </div>
        <DataTable :columns="warehouseColumns" :data="warehouses" :loading="listLoading.warehouses" :error="listErrors.warehouses" :has-more="false" empty-text="暂无仓库" @retry="loadWarehouses">
          <template #cell-status="{ value }">{{ value === 'active' ? '正常' : '禁用' }}</template>
          <template #actions="{ row }: any">
            <button class="btn btn-sm btn-secondary" :disabled="saving || listLoading.warehouses || !!listErrors.warehouses" @click="editWarehouse(row)">编辑</button>
            <button class="btn btn-sm btn-secondary" :disabled="saving || listLoading.warehouses || !!listErrors.warehouses" @click="manageLocations(row)">库位</button>
          </template>
        </DataTable>

        <div v-if="selectedWarehouse" style="margin-top:30px;">
          <h4>库位管理 - {{ selectedWarehouse.name }}</h4>
          <button class="btn btn-sm btn-primary" @click="showLocationModal" style="margin-bottom:10px;">+ 添加库位</button>
          <DataTable :columns="locationColumns" :data="locations" :loading="listLoading.locations" :error="listErrors.locations" :has-more="false" empty-text="暂无库位" @retry="selectedWarehouse && loadLocations(selectedWarehouse.id)">
            <template #cell-status="{ value }">{{ value === 'active' ? '正常' : '禁用' }}</template>
            <template #actions="{ row }: any">
              <button class="btn btn-sm btn-secondary" :disabled="saving || listLoading.locations || !!listErrors.locations" @click="editLocation(row)">编辑</button>
            </template>
          </DataTable>
        </div>
      </div>

      <div v-if="activeTab === 'inout'" class="card">
        <div class="page-header" style="padding:0;border:none;">
          <h4>出入库记录</h4>
          <div>
            <button class="btn btn-sm btn-primary" @click="showInModal">入库</button>
            <button class="btn btn-sm btn-warning" @click="showOutModal" style="margin-left:5px;">出库</button>
          </div>
        </div>
        <DataTable :columns="transactionColumns" :data="transactions" :loading="listLoading.transactions" :error="listErrors.transactions" :server-pagination="transactionPagination" :has-more="false" empty-text="暂无记录" @page-change="loadTransactions" @retry="loadTransactions(transactionPagination.page)">
          <template #cell-transaction_type="{ value }">
            <span :class="value === 'in' ? 'text-green' : 'text-red'">{{ value === 'in' ? '入库' : value === 'out' ? '出库' : value }}</span>
          </template>
        </DataTable>
      </div>

      <div v-if="activeTab === 'supplier'" class="card">
        <div class="page-header" style="padding:0;border:none;">
          <h4>供应商列表</h4>
          <button class="btn btn-primary btn-sm" @click="showSupplierModal">+ 添加供应商</button>
        </div>
        <DataTable :columns="supplierColumns" :data="suppliers" :loading="listLoading.suppliers" :error="listErrors.suppliers" :has-more="false" empty-text="暂无供应商" @retry="loadSuppliers">
          <template #cell-rating="{ value }">{{ '★'.repeat(Math.max(0, Math.min(5, Number(value) || 0))) }}</template>
          <template #actions="{ row }: any">
            <button class="btn btn-sm btn-secondary" :disabled="saving || listLoading.suppliers || !!listErrors.suppliers" @click="editSupplier(row)">编辑</button>
          </template>
        </DataTable>
      </div>
    </div>

    <div v-if="showMaterialModal" class="modal active">
      <div class="modal-content">
        <div class="modal-header">{{ isEditMaterial ? '编辑' : '添加' }}{{ resourceModalNoun }}</div>
        <div class="modal-body">
          <div class="form-group"><label>编码</label><input v-model="materialForm.code" type="text"></div>
          <div class="form-group"><label>名称 *</label><input v-model="materialForm.name" type="text"></div>
          <div class="form-group"><label>分类</label><input v-model="materialForm.category" type="text"></div>
          <div class="form-group"><label>规格</label><input v-model="materialForm.spec" type="text"></div>
          <div class="form-group"><label>单位</label><input v-model="materialForm.unit" type="text"></div>
          <div class="form-group"><label>库存</label><input v-model.number="materialForm.quantity" type="number"></div>
          <div class="form-group"><label>单价</label><input v-model.number="materialForm.price" type="number" step="0.01"></div>
          <div class="form-group"><label>供应商</label><input v-model="materialForm.supplier" type="text"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showMaterialModal = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveMaterial">保存</button>
        </div>
      </div>
    </div>

    <div v-if="showWarehouseModalFlag" class="modal active">
      <div class="modal-content">
        <div class="modal-header">{{ isEditWarehouse ? '编辑' : '添加' }}仓库</div>
        <div class="modal-body">
          <div class="form-group"><label>编码 *</label><input v-model="warehouseForm.code" type="text"></div>
          <div class="form-group"><label>名称 *</label><input v-model="warehouseForm.name" type="text"></div>
          <div class="form-group"><label>类型</label>
            <select v-model="warehouseForm.type">
              <option value="">请选择</option>
              <option value="原材料">原材料仓</option>
              <option value="成品">成品仓</option>
              <option value="半成品">半成品仓</option>
              <option value="其他">其他</option>
            </select>
          </div>
          <div class="form-group"><label>地址</label><input v-model="warehouseForm.address" type="text"></div>
          <div class="form-group"><label>负责人</label><input v-model="warehouseForm.manager" type="text"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showWarehouseModalFlag = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveWarehouse">保存</button>
        </div>
      </div>
    </div>

    <div v-if="showLocationModalFlag" class="modal active">
      <div class="modal-content">
        <div class="modal-header">{{ isEditLocation ? '编辑' : '添加' }}库位</div>
        <div class="modal-body">
          <div class="form-group"><label>编码 *</label><input v-model="locationForm.code" type="text"></div>
          <div class="form-group"><label>名称</label><input v-model="locationForm.name" type="text"></div>
          <div class="form-group"><label>最大容量</label><input v-model.number="locationForm.max_capacity" type="number"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showLocationModalFlag = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveLocation">保存</button>
        </div>
      </div>
    </div>

    <div v-if="showInModalFlag" class="modal active">
      <div class="modal-content">
        <div class="modal-header">入库</div>
        <div class="modal-body">
          <div class="form-group"><label>产品 *</label>
            <select v-model="inoutForm.product_id">
              <option value="">选择产品</option>
              <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>仓库 *</label>
            <select v-model="inoutForm.warehouse_id">
              <option value="">选择仓库</option>
              <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>数量 *</label><input v-model.number="inoutForm.quantity" type="number" min="1"></div>
          <div class="form-group"><label>批次</label><input v-model="inoutForm.batch_no" type="text"></div>
          <div class="form-group"><label>备注</label><input v-model="inoutForm.remark" type="text"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showInModalFlag = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="doIn">确认入库</button>
        </div>
      </div>
    </div>

    <div v-if="showOutModalFlag" class="modal active">
      <div class="modal-content">
        <div class="modal-header">出库</div>
        <div class="modal-body">
          <div class="form-group"><label>产品 *</label>
            <select v-model="inoutForm.product_id">
              <option value="">选择产品</option>
              <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>仓库 *</label>
            <select v-model="inoutForm.warehouse_id">
              <option value="">选择仓库</option>
              <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>数量 *</label><input v-model.number="inoutForm.quantity" type="number" min="1"></div>
          <div class="form-group"><label>备注</label><input v-model="inoutForm.remark" type="text"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showOutModalFlag = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="doOut">确认出库</button>
        </div>
      </div>
    </div>

    <div v-if="showSupplierModalFlag" class="modal active">
      <div class="modal-content">
        <div class="modal-header">{{ isEditSupplier ? '编辑' : '添加' }}供应商</div>
        <div class="modal-body">
          <div class="form-group"><label>编码 *</label><input v-model="supplierForm.code" type="text"></div>
          <div class="form-group"><label>名称 *</label><input v-model="supplierForm.name" type="text"></div>
          <div class="form-group"><label>联系人</label><input v-model="supplierForm.contact_person" type="text"></div>
          <div class="form-group"><label>电话</label><input v-model="supplierForm.contact_phone" type="text"></div>
          <div class="form-group"><label>评级</label>
            <select v-model="supplierForm.rating">
              <option :value="1">★</option>
              <option :value="2">★★</option>
              <option :value="3">★★★</option>
              <option :value="4">★★★★</option>
              <option :value="5">★★★★★</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showSupplierModalFlag = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveSupplier">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./materials/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import { useMaterials } from './materials/useMaterials'
import DataTable from '@/components/DataTable.vue'

const col = (key: string, label: string, minWidth = 100) => ({ key, label, minWidth, sortable: true })
const materialColumns = [col('code', '编码'), col('name', '名称', 150), col('category', '分类'), col('quantity', '库存'), col('price', '单价'), col('supplier', '供应商', 130)]
const warehouseColumns = [col('code', '编码'), col('name', '名称', 150), col('type', '类型'), col('address', '地址', 160), col('status', '状态')]
const locationColumns = [col('code', '编码'), col('name', '名称', 150), col('max_capacity', '容量'), col('current_capacity', '当前用量'), col('status', '状态')]
const transactionColumns = [col('transaction_date', '时间', 160), col('transaction_type', '类型'), col('product_name', '产品', 150), col('warehouse_name', '仓库'), col('quantity', '数量'), col('operator', '操作人'), col('remark', '备注', 150)]
const supplierColumns = [col('code', '编码'), col('name', '名称', 150), col('contact_person', '联系人'), col('contact_phone', '电话', 130), col('rating', '评级')]

const {
  materialsPageTitle, resourceTabLabel, warehouseTabLabel, inoutTabLabel, supplierTabLabel,
  resourceModalNoun, activeTab, materials, warehouses, locations, transactions, suppliers,
  categories, searchQuery, selectedCategory,
  showMaterialModal, isEditMaterial, materialForm,
  showWarehouseModalFlag, isEditWarehouse, warehouseForm, selectedWarehouse,
  showLocationModalFlag, isEditLocation, locationForm,
  showInModalFlag, showOutModalFlag, inoutForm,
  showSupplierModalFlag, isEditSupplier, supplierForm,
  loadMaterials, scheduleMaterialsSearch, loadWarehouses, loadLocations, loadTransactions, loadSuppliers,
  listLoading, listErrors, materialPagination, transactionPagination, saving, showAddModal, editMaterial, saveMaterial, deleteMaterial,
  showWarehouseModal, editWarehouse, saveWarehouse, manageLocations,
  showLocationModal, editLocation, saveLocation,
  showInModal, showOutModal, doIn, doOut,
  showSupplierModal, editSupplier, saveSupplier, exportData,
} = useMaterials()
</script>

<style scoped src="./materials/materials.css"></style>

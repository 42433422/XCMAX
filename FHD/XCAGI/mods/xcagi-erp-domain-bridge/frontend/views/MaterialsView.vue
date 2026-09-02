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
          <input v-model="searchQuery" type="text" placeholder="搜索..." @input="loadMaterials">
          <select v-model="selectedCategory">
            <option value="">全部分类</option>
            <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
          </select>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>分类</th>
              <th>库存</th>
              <th>单价</th>
              <th>供应商</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in materials" :key="item.id">
              <td>{{ item.code || '-' }}</td>
              <td>{{ item.name }}</td>
              <td>{{ item.category || '-' }}</td>
              <td :class="{'text-red': item.quantity < (item.min_stock || 0)}">{{ item.quantity }} {{ item.unit || '' }}</td>
              <td>{{ item.price ? '¥' + item.price.toFixed(2) : '-' }}</td>
              <td>{{ item.supplier || '-' }}</td>
              <td>
                <button class="btn btn-sm btn-secondary" @click="editMaterial(item)">编辑</button>
                <button class="btn btn-sm btn-danger" @click="deleteMaterial(item)">删除</button>
              </td>
            </tr>
            <tr v-if="materials.length === 0">
              <td colspan="7" class="text-center">暂无数据</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="activeTab === 'warehouse'" class="card">
        <div class="page-header" style="padding:0;border:none;">
          <h4>仓库列表</h4>
          <button class="btn btn-primary btn-sm" @click="showWarehouseModal">+ 添加仓库</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>类型</th>
              <th>地址</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="w in warehouses" :key="w.id">
              <td>{{ w.code }}</td>
              <td>{{ w.name }}</td>
              <td>{{ w.type || '-' }}</td>
              <td>{{ w.address || '-' }}</td>
              <td>{{ w.status === 'active' ? '正常' : '禁用' }}</td>
              <td>
                <button class="btn btn-sm btn-secondary" @click="editWarehouse(w)">编辑</button>
                <button class="btn btn-sm btn-secondary" @click="manageLocations(w)">库位</button>
              </td>
            </tr>
            <tr v-if="warehouses.length === 0">
              <td colspan="6" class="text-center">暂无仓库</td>
            </tr>
          </tbody>
        </table>

        <div v-if="selectedWarehouse" style="margin-top:30px;">
          <h4>库位管理 - {{ selectedWarehouse.name }}</h4>
          <button class="btn btn-sm btn-primary" @click="showLocationModal" style="margin-bottom:10px;">+ 添加库位</button>
          <table class="data-table">
            <thead>
              <tr>
                <th>编码</th>
                <th>名称</th>
                <th>容量</th>
                <th>当前用量</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="loc in locations" :key="loc.id">
                <td>{{ loc.code }}</td>
                <td>{{ loc.name }}</td>
                <td>{{ loc.max_capacity || '-' }}</td>
                <td>{{ loc.current_capacity || 0 }}</td>
                <td>{{ loc.status === 'active' ? '正常' : '禁用' }}</td>
                <td>
                  <button class="btn btn-sm btn-secondary" @click="editLocation(loc)">编辑</button>
                </td>
              </tr>
              <tr v-if="locations.length === 0">
                <td colspan="6" class="text-center">暂无库位</td>
              </tr>
            </tbody>
          </table>
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
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>产品</th>
              <th>仓库</th>
              <th>数量</th>
              <th>操作人</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in transactions" :key="t.id">
              <td>{{ t.transaction_date }}</td>
              <td>
                <span :class="t.transaction_type === 'in' ? 'text-green' : 'text-red'">
                  {{ t.transaction_type === 'in' ? '入库' : '出库' }}
                </span>
              </td>
              <td>{{ t.product_name || '-' }}</td>
              <td>{{ t.warehouse_name || '-' }}</td>
              <td>{{ t.quantity }}</td>
              <td>{{ t.operator || '-' }}</td>
              <td>{{ t.remark || '-' }}</td>
            </tr>
            <tr v-if="transactions.length === 0">
              <td colspan="7" class="text-center">暂无记录</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="activeTab === 'supplier'" class="card">
        <div class="page-header" style="padding:0;border:none;">
          <h4>供应商列表</h4>
          <button class="btn btn-primary btn-sm" @click="showSupplierModal">+ 添加供应商</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>联系人</th>
              <th>电话</th>
              <th>评级</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in suppliers" :key="s.id">
              <td>{{ s.code }}</td>
              <td>{{ s.name }}</td>
              <td>{{ s.contact_person || '-' }}</td>
              <td>{{ s.contact_phone || '-' }}</td>
              <td>{{ '★'.repeat(s.rating || 3) }}</td>
              <td>
                <button class="btn btn-sm btn-secondary" @click="editSupplier(s)">编辑</button>
              </td>
            </tr>
            <tr v-if="suppliers.length === 0">
              <td colspan="6" class="text-center">暂无供应商</td>
            </tr>
          </tbody>
        </table>
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
          <button class="btn btn-primary" @click="saveMaterial">保存</button>
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
          <button class="btn btn-primary" @click="saveWarehouse">保存</button>
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
          <button class="btn btn-primary" @click="saveLocation">保存</button>
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
          <button class="btn btn-primary" @click="doIn">确认入库</button>
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
          <button class="btn btn-primary" @click="doOut">确认出库</button>
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
          <button class="btn btn-primary" @click="saveSupplier">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./materials/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import { useMaterials } from './materials/useMaterials'

const {
  materialsPageTitle, resourceTabLabel, warehouseTabLabel, inoutTabLabel, supplierTabLabel,
  resourceModalNoun, activeTab, materials, warehouses, locations, transactions, suppliers,
  categories, searchQuery, selectedCategory,
  showMaterialModal, isEditMaterial, materialForm,
  showWarehouseModalFlag, isEditWarehouse, warehouseForm, selectedWarehouse,
  showLocationModalFlag, isEditLocation, locationForm,
  showInModalFlag, showOutModalFlag, inoutForm,
  showSupplierModalFlag, isEditSupplier, supplierForm,
  loadMaterials, loadSuppliers, showAddModal, editMaterial, saveMaterial, deleteMaterial,
  showWarehouseModal, editWarehouse, saveWarehouse, manageLocations,
  showLocationModal, editLocation, saveLocation,
  showInModal, showOutModal, doIn, doOut,
  showSupplierModal, editSupplier, saveSupplier, exportData,
} = useMaterials()
</script>

<style scoped src="./materials/materials.css"></style>

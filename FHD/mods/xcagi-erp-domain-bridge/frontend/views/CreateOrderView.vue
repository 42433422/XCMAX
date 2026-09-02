<template>
  <div class="page-view" id="view-create-order">
    <div class="page-content">
      <div class="page-header">
        <h2>新建发货单</h2>
        <button class="btn btn-secondary" @click="goOrdersList">返回列表</button>
      </div>

      <div v-if="status.message" :class="['status', status.type]" style="display: block; margin-bottom: 20px;">
        {{ status.message }}
      </div>

      <div class="card">
        <h3>选择发货单模板</h3>
        <div class="form-row">
          <div class="form-col">
            <label>发货单模板</label>
            <select v-model="form.templateName" @change="onTemplateChange">
              <option value="">-- 请选择模板 --</option>
              <option v-for="t in templates" :key="t.name" :value="t.name">{{ t.name }}</option>
            </select>
          </div>
          <div class="form-col" style="flex: 0;">
            <label>&nbsp;</label>
            <button class="btn" @click="loadTemplates">刷新模板列表</button>
          </div>
        </div>
      </div>

      <div class="card header-section">
        <h3>基础信息</h3>
        <div class="form-row">
          <div class="form-col">
            <label>购买单位 *</label>
            <div style="display: flex; gap: 10px;">
              <select v-model="form.purchaseUnit" @change="onPurchaseUnitChange" style="flex: 1;">
                <option value="">-- 选择购买单位 --</option>
                <option v-for="u in purchaseUnits" :key="u.unit_name" :value="u.unit_name">
                  {{ u.unit_name }}{{ u.contact_person ? ` (${u.contact_person})` : '' }}
                </option>
              </select>
              <a href="/purchase-units" class="btn btn-secondary" style="white-space: nowrap; text-decoration: none; display: inline-flex; align-items: center;">+ 新建</a>
            </div>
          </div>
          <div class="form-col">
            <label>联系人</label>
            <input type="text" v-model="form.contactPerson" placeholder="联系人姓名">
          </div>
        </div>
        <div class="form-row">
          <div class="form-col">
            <label>日期 *</label>
            <input type="date" v-model="form.purchaseDate" @change="onDateChange">
          </div>
          <div class="form-col">
            <label>订单编号</label>
            <input type="text" v-model="form.orderNumber" placeholder="订单编号" readonly style="background-color: #f0f0f0;">
          </div>
        </div>
      </div>

      <div class="card">
        <h3>产品信息</h3>
        <div style="margin-bottom: 15px;">
          <button class="btn btn-success" @click="addProductRow"><i class="fa fa-plus" aria-hidden="true"></i> 添加产品</button>
          <button class="btn" @click="showProductSelector = true"><i class="fa fa-search" aria-hidden="true"></i> 选择产品名称</button>
          <a href="/product-names" class="btn btn-secondary" style="text-decoration: none;"><i class="fa fa-cubes" aria-hidden="true"></i> 管理产品库</a>
        </div>

        <div v-if="products.length === 0" class="empty-products">
          暂无产品，请点击"添加产品"或"选择产品名称"添加产品
        </div>

        <div v-for="(product, index) in products" :key="product.id" class="product-row">
          <div class="product-cell">
            <label>产品型号 *</label>
            <input type="text" v-model="product.model" placeholder="产品型号" @input="onProductModelChange(product, index)">
          </div>
          <div class="product-cell">
            <label>产品名称 *</label>
            <select v-model="product.nameId" @change="onProductNameSelect(product, index)">
              <option value="">-- 请选择产品 --</option>
              <option v-for="p in allProducts" :key="p.id" :value="p.id">
                {{ p.name }}{{ p.model_number ? ` (${p.model_number})` : '' }}
              </option>
            </select>
            <input type="hidden" v-model="product.name">
          </div>
          <div class="product-cell">
            <label>数量/件</label>
            <input type="number" v-model.number="product.quantityBox" min="0" step="1" @input="calculateKg(index)">
          </div>
          <div class="product-cell">
            <label>规格/KG</label>
            <input type="number" v-model.number="product.specification" min="0" step="0.01" @input="calculateKg(index)">
          </div>
          <div class="product-cell">
            <label>数量/KG</label>
            <input type="number" v-model.number="product.quantityKg" min="0" step="0.01" @input="calculateAmount(index)">
          </div>
          <div class="product-cell">
            <label>单价/元</label>
            <input type="number" v-model.number="product.unitPrice" min="0" step="0.01" @input="calculateAmount(index)">
          </div>
          <div class="product-cell">
            <label>金额/元</label>
            <input type="number" v-model.number="product.amount" readonly style="background-color: #f0f0f0;">
          </div>
          <div class="product-cell">
            <label>&nbsp;</label>
            <button class="btn btn-danger" @click="removeProductRow(index)" style="padding: 8px 15px;">删除</button>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>操作</h3>
        <div style="text-align: center;">
          <button class="btn btn-success" @click="generateShipment" style="padding: 15px 40px; font-size: 18px;">
            <i class="fa fa-rocket" aria-hidden="true"></i> 生成发货单
          </button>
          <button class="btn btn-secondary" @click="resetForm" style="padding: 15px 40px; font-size: 18px;">
            <i class="fa fa-refresh" aria-hidden="true"></i> 重置
          </button>
          <button class="btn" @click="goTemplatePreview" style="padding: 15px 40px; font-size: 18px;">
            <i class="fa fa-edit" aria-hidden="true"></i> 模板编辑
          </button>
        </div>
      </div>

      <div v-if="result" class="card" style="margin-top: 20px;">
        <h3><i class="fa fa-check-circle-o" aria-hidden="true"></i> 生成结果</h3>
        <div style="text-align: center; padding: 20px;">
          <p style="margin-bottom: 15px;">文件名: {{ result.output_filename }}</p>
          <a :href="`/download/${result.output_filename}`" class="btn btn-success" download style="padding: 15px 30px; font-size: 16px;">
            <i class="fa fa-download" aria-hidden="true"></i> 下载发货单
          </a>
          <button class="btn" @click="resetForm" style="padding: 15px 30px; font-size: 16px;">
            <i class="fa fa-plus-square-o" aria-hidden="true"></i> 新建发货单
          </button>
        </div>
      </div>
    </div>

    <div v-if="showProductSelector" class="modal-overlay" @click.self="showProductSelector = false">
      <div class="modal-content" style="width: 80%; max-width: 800px;">
        <div class="modal-header">
          <h3>选择产品</h3>
          <button class="close-btn" @click="showProductSelector = false">&times;</button>
        </div>
        <div class="modal-body">
          <div style="margin-bottom: 15px;">
            <input type="text" v-model="productSearchQuery" placeholder="搜索产品名称或型号..." style="width: 70%;">
            <button class="btn" @click="searchProductsForSelection">搜索</button>
          </div>
          <div style="max-height: 400px; overflow-y: auto;">
            <div v-if="searchingProducts" class="loading">加载中...</div>
            <div v-else-if="filteredProductsForSelection.length === 0" class="no-products">未找到产品</div>
            <div
              v-else
              v-for="product in filteredProductsForSelection"
              :key="product.id"
              class="product-item"
              @click="selectProductForAdd(product)"
            >
              <div style="font-weight: 600; font-size: 16px;">{{ product.name || '' }}</div>
              <div style="margin-top: 5px; color: #666; font-size: 14px;">
                {{ product.model_number ? `型号: ${product.model_number}` : '' }}
                {{ product.purchase_unit_name ? ` | 单位: ${product.purchase_unit_name}` : '' }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./create-order/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import { useCreateOrder } from './create-order/useCreateOrder'

const {
  status, form, templates, purchaseUnits, allProducts, products,
  result, showProductSelector, productSearchQuery, searchingProducts,
  filteredProductsForSelection,
  goOrdersList, goTemplatePreview, loadTemplates,
  onTemplateChange, onPurchaseUnitChange, onDateChange,
  addProductRow, removeProductRow, calculateKg, calculateAmount,
  onProductNameSelect, onProductModelChange,
  searchProductsForSelection, selectProductForAdd,
  generateShipment, resetForm,
} = useCreateOrder()
</script>

<style scoped src="./create-order/create-order.css"></style>

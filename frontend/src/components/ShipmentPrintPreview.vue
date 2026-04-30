<template>
  <div v-if="show" class="modal-overlay" @click.self="close">
    <div class="modal-content shipment-preview">
      <div class="modal-header">
        <h3><i class="fa fa-file-text-o" aria-hidden="true"></i> 发货单预览</h3>
        <button type="button" class="modal-close" @click="close">&times;</button>
      </div>
      <div class="modal-body">
        <div class="shipment-grid">
          <div class="grid-row grid-header">
            <div class="grid-cell cell-info">
              <div class="info-item">
                <span class="label">客户：</span>
                <input type="text" v-model="localData.customer_name" class="editable-input" />
              </div>
              <div class="info-item">
                <span class="label">日期：</span>
                <input type="text" v-model="localData.date" class="editable-input" />
              </div>
              <div class="info-item">
                <span class="label">单号：</span>
                <input type="text" v-model="localData.order_number" class="editable-input" />
              </div>
            </div>
          </div>

          <div class="grid-row grid-products">
            <table class="product-table">
              <thead>
                <tr>
                  <th class="col-index">#</th>
                  <th class="col-product">产品</th>
                  <th class="col-spec">规格</th>
                  <th class="col-quantity">数量</th>
                  <th class="col-unit">单位</th>
                  <th class="col-price">单价</th>
                  <th class="col-amount">金额</th>
                  <th class="col-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(product, idx) in localData.products" :key="idx">
                  <td class="col-index">{{ idx + 1 }}</td>
                  <td class="col-product">
                    <input type="text" v-model="product.name" class="editable-input table-input" />
                  </td>
                  <td class="col-spec">
                    <input type="text" v-model="product.spec" class="editable-input table-input" />
                  </td>
                  <td class="col-quantity">
                    <input type="number" v-model.number="product.quantity" class="editable-input table-input" @input="recalculate" />
                  </td>
                  <td class="col-unit">
                    <select v-model="product.unit" class="editable-select">
                      <option value="KG">KG</option>
                      <option value="桶">桶</option>
                      <option value="件">件</option>
                    </select>
                  </td>
                  <td class="col-price">
                    <input type="number" v-model.number="product.unit_price" class="editable-input table-input" step="0.01" @input="recalculate" />
                  </td>
                  <td class="col-amount">{{ calculateAmount(product) }}元</td>
                  <td class="col-actions">
                    <button type="button" class="btn-icon btn-delete" @click="removeProduct(idx)" title="删除">
                      <i class="fa fa-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="grid-row grid-add">
            <button type="button" class="btn btn-secondary btn-sm" @click="addProduct">
              <i class="fa fa-plus"></i> 添加产品
            </button>
          </div>

          <div class="grid-row grid-summary">
            <div class="summary-info">
              <div class="summary-item">
                <span class="label">总数量：</span>
                <input type="number" v-model.number="localData.total_quantity" class="editable-input summary-input" readonly /> {{ localData.unit || 'KG' }}
              </div>
              <div class="summary-item total-amount">
                <span class="label">合计金额：</span>
                <span class="value">¥{{ localData.total_amount.toFixed(2) }}元</span>
              </div>
            </div>
          </div>

          <div class="grid-row grid-notes">
            <div class="notes-section">
              <span class="label">备注：</span>
              <textarea v-model="localData.notes" class="editable-textarea" rows="2" placeholder="请输入备注信息..."></textarea>
            </div>
          </div>

          <div class="grid-row grid-signatures">
            <div class="signature-item">
              <span class="role">核準：</span>
              <input type="text" v-model="localData.signatures.approver" class="editable-input sig-input" />
            </div>
            <div class="signature-item">
              <span class="role">會計：</span>
              <input type="text" v-model="localData.signatures.accountant" class="editable-input sig-input" />
            </div>
            <div class="signature-item">
              <span class="role">經辨：</span>
              <input type="text" v-model="localData.signatures.manager" class="editable-input sig-input" />
            </div>
            <div class="signature-item">
              <span class="role">倉庫：</span>
              <input type="text" v-model="localData.signatures.warehouse" class="editable-input sig-input" />
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-primary" @click="handlePrint" :disabled="loading">
          <i class="fa fa-print" aria-hidden="true"></i> 打印
        </button>
        <button type="button" class="btn btn-success" @click="handleDownload">
          <i class="fa fa-download" aria-hidden="true"></i> 下载
        </button>
        <button type="button" class="btn btn-secondary" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ShipmentPrintPreview',
  props: {
    show: {
      type: Boolean,
      default: false
    },
    shipmentData: {
      type: Object,
      default: null
    }
  },
  emits: ['close', 'print', 'download', 'update'],
  data() {
    return {
      loading: false,
      localData: {
        customer_name: '',
        date: '',
        order_number: '',
        products: [],
        total_quantity: 0,
        total_amount: 0,
        unit: 'KG',
        notes: '',
        signatures: {
          approver: '黄种霜',
          accountant: '胡小玲',
          manager: '姚胜华',
          warehouse: '廖振卷'
        }
      }
    }
  },
  watch: {
    shipmentData: {
      handler(newData) {
        if (newData) {
          this.localData = {
            ...this.localData,
            ...newData,
            signatures: {
              ...this.localData.signatures,
              ...(newData.signatures || {})
            }
          }
          this.recalculate()
        }
      },
      immediate: true,
      deep: true
    },
    localData: {
      handler() {
        this.$emit('update', this.localData)
      },
      deep: true
    }
  },
  methods: {
    close() {
      this.$emit('close')
    },

    calculateAmount(product) {
      const qty = Number(product.quantity) || 0
      const price = Number(product.unit_price) || 0
      return (qty * price).toFixed(2)
    },

    recalculate() {
      let totalQty = 0
      let totalAmt = 0
      this.localData.products.forEach(p => {
        const qty = Number(p.quantity) || 0
        const price = Number(p.unit_price) || 0
        totalQty += qty
        totalAmt += qty * price
      })
      this.localData.total_quantity = totalQty
      this.localData.total_amount = totalAmt
    },

    addProduct() {
      this.localData.products.push({
        name: '',
        spec: '',
        quantity: 1,
        unit: 'KG',
        unit_price: 0
      })
    },

    removeProduct(index) {
      this.localData.products.splice(index, 1)
      this.recalculate()
    },

    async handlePrint() {
      this.loading = true
      try {
        this.$emit('print', this.localData)
      } finally {
        this.loading = false
      }
    },

    handleDownload() {
      this.$emit('download', this.localData)
    }
  }
}
</script>

<style scoped>
.shipment-preview {
  max-width: 900px;
  width: 95vw;
}

.shipment-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.grid-row {
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 12px;
}

.grid-header {
  background: #f8f9fa;
}

.cell-info {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.info-item .label {
  font-weight: 600;
  color: #495057;
  white-space: nowrap;
}

.editable-input {
  border: 1px solid #ced4da;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 13px;
  background: #fff;
  transition: border-color 0.15s;
}

.editable-input:focus {
  outline: none;
  border-color: #86b7fe;
  box-shadow: 0 0 0 2px rgba(13, 110, 253, 0.15);
}

.table-input {
  width: 100%;
  min-width: 60px;
}

.editable-select {
  border: 1px solid #ced4da;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 13px;
  background: #fff;
}

.editable-textarea {
  width: 100%;
  border: 1px solid #ced4da;
  border-radius: 4px;
  padding: 8px;
  font-size: 13px;
  resize: vertical;
  font-family: inherit;
}

.editable-textarea:focus {
  outline: none;
  border-color: #86b7fe;
  box-shadow: 0 0 0 2px rgba(13, 110, 253, 0.15);
}

.grid-products {
  padding: 0;
  overflow-x: auto;
}

.product-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.product-table th,
.product-table td {
  border: 1px solid #dee2e6;
  padding: 8px;
  text-align: center;
}

.product-table th {
  background: #f1f3f5;
  font-weight: 600;
  color: #495057;
}

.col-index {
  width: 40px;
}

.col-product {
  min-width: 150px;
}

.col-spec {
  width: 100px;
}

.col-quantity {
  width: 80px;
}

.col-unit {
  width: 70px;
}

.col-price {
  width: 90px;
}

.col-amount {
  width: 90px;
  font-weight: 600;
  color: #198754;
}

.col-actions {
  width: 50px;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  color: #6c757d;
  transition: all 0.15s;
}

.btn-icon:hover {
  background: #f8f9fa;
  color: #dc3545;
}

.grid-add {
  display: flex;
  justify-content: flex-start;
}

.grid-summary {
  background: #e9ecef;
}

.summary-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-item .label {
  font-weight: 600;
  color: #495057;
}

.summary-input {
  width: 80px;
  text-align: right;
}

.total-amount .value {
  font-size: 18px;
  font-weight: 700;
  color: #198754;
}

.grid-notes {
  background: #f8f9fa;
}

.notes-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.notes-section .label {
  font-weight: 600;
  color: #495057;
}

.grid-signatures {
  display: flex;
  justify-content: space-around;
  flex-wrap: wrap;
  gap: 12px;
}

.signature-item {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.signature-item .role {
  font-size: 12px;
  color: #6c757d;
}

.sig-input {
  width: 80px;
  text-align: center;
}

.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>

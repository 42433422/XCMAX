<template>
  <div v-if="show" class="modal-overlay" @click.self="close">
    <div class="modal-content sales-contract-preview">
      <div class="modal-header">
        <h3><i class="fa fa-file-text-o" aria-hidden="true"></i> 销售合同预览</h3>
        <button type="button" class="modal-close" @click="close">&times;</button>
      </div>
      <div class="modal-body">
        <div class="contract-info">
          <div class="info-row">
            <span class="label">客户：</span>
            <span class="value">{{ previewData.customer_name }}</span>
          </div>
          <div class="info-row">
            <span class="label">日期：</span>
            <span class="value">{{ previewData.contract_date }}</span>
          </div>
        </div>

        <table class="contract-table">
          <thead>
            <tr>
              <th>编号</th>
              <th>品名</th>
              <th>规格</th>
              <th>单位</th>
              <th>数量</th>
              <th>单价</th>
              <th>金额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(product, idx) in previewData.products" :key="idx">
              <td>{{ product.model_number }}</td>
              <td>{{ product.name }}</td>
              <td>{{ product.spec }}</td>
              <td>{{ product.unit }}</td>
              <td>{{ product.quantity }}</td>
              <td>{{ product.unit_price }}元/KG</td>
              <td>{{ product.amount }}元</td>
            </tr>
          </tbody>
        </table>

        <div class="contract-summary">
          <div class="summary-row">
            <span>总重量：{{ previewData.total_quantity }} KG</span>
            <span>合计金额：{{ previewData.total_amount }}元</span>
          </div>
          <div class="notes">
            <p>注：以上价格均为实价，无折扣！</p>
            <p>注：160KG桶需退回，如未退回一个按80元计算 应退桶({{ previewData.return_buckets_expected }})个，实退桶({{ previewData.return_buckets_actual }})个.</p>
          </div>
        </div>

        <div class="contract-signatures">
          <div class="signature-item">
            <span class="role">核準：</span>
            <span class="name">黄种霜</span>
          </div>
          <div class="signature-item">
            <span class="role">會計：</span>
            <span class="name">胡小玲</span>
          </div>
          <div class="signature-item">
            <span class="role">經辨：</span>
            <span class="name">姚胜华</span>
          </div>
          <div class="signature-item">
            <span class="role">倉庫：</span>
            <span class="name">廖振卷</span>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <p class="muted sales-contract-preview-footer-link">
          <a href="#" @click.prevent="goSalesContractTemplateLibrary">去模板库（销售合同 Word / Excel）</a>
        </p>
        <button type="button" class="btn btn-primary" @click="handlePrint">
          <i class="fa fa-print" aria-hidden="true"></i> 打印
        </button>
        <button type="button" class="btn btn-secondary" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<script>
import { salesContractApi } from '../api/salesContract'
import { appAlert } from '@/utils/appDialog'

export default {
  name: 'SalesContractPreview',
  props: {
    show: {
      type: Boolean,
      default: false
    },
    contractData: {
      type: Object,
      default: null
    }
  },
  emits: ['close'],
  data() {
    return {
      previewData: {
        customer_name: '深圳市百木鼎家具有限公司',
        contract_date: '2026年04月11日',
        products: [
          {
            model_number: '306B',
            name: 'PU亮光硬化剂',
            spec: '10KG×1',
            unit: '桶',
            quantity: '10 KG',
            unit_price: '39.2',
            amount: '392'
          }
        ],
        total_quantity: 10,
        total_amount: 392,
        return_buckets_expected: 1,
        return_buckets_actual: 0
      }
    }
  },
  watch: {
    contractData: {
      handler(newData) {
        if (newData) {
          this.previewData = { ...this.previewData, ...newData }
        }
      },
      immediate: true
    }
  },
  methods: {
    close() {
      this.$emit('close')
    },
    goSalesContractTemplateLibrary() {
      try {
        this.$router.push({ path: '/template-preview', query: { scope: 'salesContract' } })
      } catch {
        /* ignore */
      }
      this.close()
    },
    async handlePrint() {
      try {
        const result = await salesContractApi.print({
          filename: this.contractData?.filename || ''
        })
        if (result?.success) {
          await appAlert('打印任务已发送')
        } else {
          await appAlert('打印失败：' + (result?.error || '未知错误'))
        }
      } catch (err) {
        await appAlert('打印失败：' + err.message)
      }
    }
  }
}
</script>

<style scoped>
.sales-contract-preview {
  max-width: 800px;
  width: 90vw;
}

.contract-info {
  margin-bottom: 16px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
}

.info-row {
  display: flex;
  gap: 12px;
  margin-bottom: 6px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-row .label {
  font-weight: 600;
  color: #495057;
}

.info-row .value {
  color: #212529;
}

.contract-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
  font-size: 13px;
}

.contract-table th,
.contract-table td {
  border: 1px solid #dee2e6;
  padding: 8px;
  text-align: center;
}

.contract-table th {
  background: #f1f3f5;
  font-weight: 600;
  color: #495057;
}

.contract-summary {
  margin-bottom: 16px;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  background: #e9ecef;
  border-radius: 6px;
  margin-bottom: 10px;
  font-weight: 600;
}

.notes {
  font-size: 12px;
  color: #6c757d;
}

.notes p {
  margin: 4px 0;
}

.contract-signatures {
  display: flex;
  justify-content: space-around;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 6px;
}

.signature-item {
  text-align: center;
}

.signature-item .role {
  display: block;
  font-size: 12px;
  color: #6c757d;
}

.signature-item .name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #212529;
}

.sales-contract-preview-footer-link {
  width: 100%;
  text-align: left;
  font-size: 12px;
  margin: 0 0 10px;
}

.sales-contract-preview-footer-link a {
  color: #0d6efd;
  text-decoration: none;
}

.sales-contract-preview-footer-link a:hover {
  text-decoration: underline;
}
</style>
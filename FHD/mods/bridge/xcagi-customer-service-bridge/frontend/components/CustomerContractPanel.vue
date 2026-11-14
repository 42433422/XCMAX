<template>
  <section v-if="showContractBlock" class="cs-block cs-block-biz">
    <h4 class="cs-block-title">合同签约</h4>
    <p class="cs-block-desc">{{ description }}</p>
    <div class="cs-contract-grid">
      <label class="cs-field"><span>甲方名称 *</span><input v-model="contractForm.party_a_name" class="cs-input"></label>
      <label class="cs-field"><span>信用代码</span><input v-model="contractForm.party_a_credit_code" class="cs-input"></label>
      <label class="cs-field"><span>合同金额 *</span><input v-model="contractForm.total_amount_number" class="cs-input" placeholder="10000.00"></label>
      <label class="cs-field cs-field-wide">
        <span>关联市场订单号</span>
        <input
          v-model="contractForm.expected_out_trade_no"
          class="cs-input"
          placeholder="客户在修茈市场支付后的 out_trade_no，用于自动核对到款"
        >
      </label>
      <label class="cs-field"><span>签署日期</span><input v-model="contractForm.sign_date" type="date" class="cs-input"></label>
      <label class="cs-field cs-field-wide"><span>主要功能/模块</span><textarea v-model="contractForm.main_function_list" rows="2" class="cs-input" /></label>
    </div>
    <div class="cs-block-actions">
      <a class="btn btn-xs" :href="contractSamplePdfUrl" target="_blank" rel="noopener">乙方预填样例</a>
      <button type="button" class="btn btn-xs" :disabled="contractForm.savingFields" @click="$emit('save-fields')">
        {{ contractForm.savingFields ? '保存中…' : '保存合同字段' }}
      </button>
      <button type="button" class="btn btn-xs btn-accent" :disabled="contractForm.loading" @click="$emit('generate')">
        {{ contractForm.loading ? '生成中…' : '生成合同' }}
      </button>
      <a v-if="contractForm.downloadUrl" class="btn btn-xs btn-accent" :href="contractForm.downloadUrl" download>下载</a>
    </div>
    <p v-if="contractForm.filename" class="cs-contract-file">已生成：{{ contractForm.filename }}</p>
    <ContractEsignPanel
      v-if="showEsignPanel && selectedUserId"
      class="cs-esign-panel-wrap"
      :market-user-id="selectedUserId"
      :username="username"
      :party-a="partyA"
      :compact="true"
      @updated="(p) => $emit('apply-pipeline', p)"
    />
  </section>
</template>

<script setup lang="ts">
import ContractEsignPanel from '@/components/contract/ContractEsignPanel.vue'

export type ContractFormState = {
  party_a_name: string
  party_a_credit_code: string
  total_amount_number: string
  expected_out_trade_no: string
  sign_date: string
  main_function_list: string
  loading: boolean
  savingFields: boolean
  filename: string
  downloadUrl: string
}

defineProps<{
  showContractBlock: boolean
  description: string
  contractForm: ContractFormState
  contractSamplePdfUrl: string
  showEsignPanel: boolean
  selectedUserId: number | null
  username: string
  partyA: string
}>()

defineEmits<{
  (e: 'save-fields'): void
  (e: 'generate'): void
  (e: 'apply-pipeline', p: Record<string, unknown>): void
}>()
</script>

<style scoped>
.cs-block {
  background: #f8fafc; border: 1px solid #e8ecf2; border-radius: 10px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.cs-block-biz { background: #fff; }
.cs-block-title { margin: 0; font-size: 13px; font-weight: 600; color: #334155; }
.cs-block-desc { margin: 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.cs-block-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.cs-contract-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
@media (max-width: 640px) { .cs-contract-grid { grid-template-columns: 1fr; } }
.cs-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #64748b; }
.cs-field-wide { grid-column: 1 / -1; }
.cs-contract-file { font-size: 12px; color: #16a34a; margin: 0; }
.cs-input {
  width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px;
  font-size: 13px; box-sizing: border-box; background: #fff;
}
.cs-esign-panel-wrap { margin-top: 12px; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: #4a6cf7; border-color: #4a6cf7; color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
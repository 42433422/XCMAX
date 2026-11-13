<template>
  <section v-if="showDeliveryBlock" class="cs-block cs-block-biz cs-block-delivery">
    <h4 class="cs-block-title">项目交付</h4>
    <p class="cs-block-desc">{{ description }}</p>
    <div class="cs-delivery-grid">
      <label class="cs-field">
        <span>客户期望交付时间</span>
        <input v-model="deliveryForm.expected_delivery_at" type="date" class="cs-input">
      </label>
      <label class="cs-field">
        <span>制作进度</span>
        <span class="cs-delivery-pct">{{ deliveryForm.progress_percent }}%</span>
      </label>
    </div>
    <div class="cs-delivery-progress-track">
      <div class="cs-delivery-progress-fill" :style="{ width: `${deliveryForm.progress_percent}%` }" />
    </div>
    <ul class="cs-milestone-list">
      <li v-for="m in deliveryForm.milestones" :key="m.id" class="cs-milestone-item">
        <label>
          <input v-model="m.done" type="checkbox" @change="$emit('milestone-toggle')">
          <span>{{ m.label }}</span>
          <span class="muted">（{{ m.weight }}%）</span>
        </label>
      </li>
    </ul>
    <div class="cs-block-actions">
      <button
        type="button"
        class="btn btn-xs btn-accent"
        :disabled="deliveryForm.saving"
        @click="$emit('save-plan', currentStageId === 'signed')"
      >
        {{ deliveryForm.saving ? '保存中…' : (currentStageId === 'signed' ? '保存并进入交付中' : '保存进度') }}
      </button>
      <p v-if="clientDesktopOs" class="cs-stage-done-hint muted">
        交付包：{{ clientDesktopOs === 'mac' ? 'macOS' : 'Windows' }} 电脑端
        <span v-if="clientNeedMobile"> + Android 手机端</span>
        <span v-if="softwareDeliverySentAt">
          · 已于 {{ formatPassivePollTime(softwareDeliverySentAt) }} 推送
        </span>
      </p>
      <button
        type="button"
        class="btn btn-xs btn-accent"
        :disabled="deliveryForm.checkingPayment"
        @click="$emit('check-payment', false)"
      >
        {{ deliveryForm.checkingPayment ? '检查中…' : '检查到款并出账' }}
      </button>
      <button
        type="button"
        class="btn btn-xs"
        :disabled="deliveryForm.checkingPayment"
        @click="$emit('check-payment', true)"
      >
        强制确认到款
      </button>
      <button
        v-if="currentStageId === 'delivering'"
        type="button"
        class="btn btn-xs"
        :disabled="signoffLoading"
        @click="$emit('request-signoff')"
      >
        {{ signoffLoading ? '处理中…' : '发起客户签收' }}
      </button>
      <button
        v-if="deliverySignoff?.status === 'pending'"
        type="button"
        class="btn btn-xs btn-accent"
        :disabled="signoffLoading"
        @click="$emit('confirm-signoff')"
      >
        确认签收并完成交付
      </button>
      <button
        v-if="currentStageId === 'delivering' && deliveryForm.progress_percent >= 100 && !deliverySignoff"
        type="button"
        class="btn btn-xs"
        :disabled="stageSaving"
        @click="$emit('mark-delivered')"
      >
        标记为已交付
      </button>
    </div>
    <p v-if="paymentStatus" class="cs-stage-done-hint">
      到款状态：{{ paymentStatusLabel }}
      <span v-if="paymentOutTradeNo"> · 订单 {{ paymentOutTradeNo }}</span>
      <span v-if="paymentVerification"> · {{ paymentVerificationLabel }}</span>
      <span v-if="invoiceNo"> · 账单 {{ invoiceNo }}</span>
    </p>
  </section>
</template>

<script setup lang="ts">
import { formatPassivePollTime } from '../composables/useCustomerServiceFormat'

export type DeliveryMilestone = { id: string; label: string; weight: number; done: boolean }
export type DeliveryFormState = {
  expected_delivery_at: string
  milestones: DeliveryMilestone[]
  progress_percent: number
  saving: boolean
  checkingPayment: boolean
}

defineProps<{
  showDeliveryBlock: boolean
  description: string
  currentStageId: string
  deliveryForm: DeliveryFormState
  clientDesktopOs: string
  clientNeedMobile: boolean
  softwareDeliverySentAt: string
  deliverySignoff: { status?: string } | null
  stageSaving: boolean
  signoffLoading: boolean
  paymentStatus: string
  paymentStatusLabel: string
  paymentOutTradeNo: string
  paymentVerification: string
  paymentVerificationLabel: string
  invoiceNo: string
}>()

defineEmits<{
  (e: 'milestone-toggle'): void
  (e: 'save-plan', startDelivering: boolean): void
  (e: 'check-payment', force: boolean): void
  (e: 'request-signoff'): void
  (e: 'confirm-signoff'): void
  (e: 'mark-delivered'): void
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
.cs-block-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.cs-delivery-grid { display: grid; grid-template-columns: 1fr 120px; gap: 8px 12px; }
@media (max-width: 640px) { .cs-delivery-grid { grid-template-columns: 1fr; } }
.cs-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #64748b; }
.cs-delivery-pct { font-size: 18px; font-weight: 700; color: #4a6cf7; }
.cs-delivery-progress-track { height: 8px; background: #eef2f7; border-radius: 4px; overflow: hidden; }
.cs-delivery-progress-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #4a6cf7); border-radius: 4px; transition: width 0.3s; }
.cs-milestone-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.cs-milestone-item label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #334155; }
.cs-milestone-item .muted { margin-left: auto; font-size: 11px; }
.cs-stage-done-hint { margin: 0; font-size: 12px; color: #16a34a; }
.cs-input { width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; font-size: 13px; box-sizing: border-box; background: #fff; }
.muted { color: #94a3b8; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: #4a6cf7; border-color: #4a6cf7; color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
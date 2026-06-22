<template>
  <div class="recharge-page">
    <div class="recharge-container">
      <h1 class="recharge-title">钱包充值</h1>
      <p class="recharge-subtitle">当前余额: ¥{{ balance.toFixed(2) }}</p>

      <div class="amount-section">
        <label class="section-label">选择充值金额</label>
        <div class="amount-grid">
          <button
            v-for="amt in presetAmounts"
            :key="amt"
            class="amount-btn"
            :class="{ active: selectedAmount === amt }"
            @click="selectedAmount = amt; customAmount = ''"
          >
            ¥{{ amt }}
          </button>
          <div class="custom-amount">
            <input
              v-model="customAmount"
              type="number"
              placeholder="自定义金额"
              class="custom-input"
              @focus="selectedAmount = 0"
            />
          </div>
        </div>
      </div>

      <div class="pay-method">
        <label class="section-label">支付方式</label>
        <div class="method-card active">
          <img src="https://img.alicdn.com/tfs/TB1Zv8_lxSYBuNjSspjXXX73VXa-200-200.png" alt="支付宝" class="alipay-icon" />
          <span>支付宝</span>
        </div>
      </div>

      <div class="amount-display">
        <span class="label">支付金额</span>
        <span class="value">¥{{ finalAmount.toFixed(2) }}</span>
      </div>

      <button
        class="btn btn-primary btn-block"
        :disabled="!finalAmount || finalAmount <= 0 || loading"
        @click="handleRecharge"
      >
        <span v-if="loading">正在创建订单...</span>
        <span v-else>立即支付</span>
      </button>

      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

      <!-- 二维码支付 -->
      <div v-if="qrCode" class="qr-section">
        <p class="qr-hint">请使用支付宝扫码支付</p>
        <img :src="qrImageUrl" alt="支付二维码" class="qr-img" />
        <p class="qr-waiting">支付完成后自动到账...</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { confirmDanger } from '../composables/useDangerConfirm'

const router = useRouter()
const balance = ref(0)
const selectedAmount = ref(50)
const customAmount = ref('')
const loading = ref(false)
const errorMsg = ref('')
const qrCode = ref('')
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)

const presetAmounts = [10, 50, 100, 200, 500, 1000]

const finalAmount = computed(() => {
  if (selectedAmount.value > 0) return selectedAmount.value
  const custom = parseFloat(customAmount.value)
  return isNaN(custom) ? 0 : custom
})

const qrImageUrl = computed(() => {
  if (!qrCode.value) return ''
  return `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data=${encodeURIComponent(qrCode.value)}`
})

onMounted(async () => {
  try {
    const res = await api.balance()
    balance.value = res.balance || 0
  } catch (e) {
    console.error('获取余额失败:', e)
  }
})

onBeforeUnmount(() => {
  if (pollingTimer.value) clearInterval(pollingTimer.value)
})

async function handleRecharge() {
  if (!finalAmount.value || finalAmount.value <= 0) {
    errorMsg.value = '请选择或输入充值金额'
    return
  }

  const ok = import.meta.env.MODE === 'test' ? true : await confirmDanger({
    title: '确认充值',
    message: `即将充值 ¥${finalAmount.value.toFixed(2)}，是否继续支付？`,
    confirmLabel: '继续',
  })
  if (!ok && import.meta.env.MODE !== 'test') return

  loading.value = true
  errorMsg.value = ''
  qrCode.value = ''

  try {
    const res = await api.paymentCheckout({
      wallet_recharge: true,
      total_amount: finalAmount.value,
      subject: '钱包充值',
    })

    if (!res.ok) {
      errorMsg.value = res.message || '创建订单失败'
      return
    }

    if (res.type === 'page' || res.type === 'wap') {
      window.location.href = res.redirect_url ?? ''
    } else if (res.type === 'precreate' || res.type === 'wechat_native') {
      qrCode.value = res.qr_code ?? ''
      startPolling(String(res.order_id ?? ''))
    }
  } catch (e) {
    errorMsg.value = '充值失败: ' + ((e as Error)?.message || String(e))
  } finally {
    loading.value = false
  }
}

function startPolling(orderId: string) {
  pollingTimer.value = setInterval(async () => {
    try {
      const res = await api.paymentQuery(orderId, { reconcile: true })
      if (res.status === 'paid') {
        if (pollingTimer.value) clearInterval(pollingTimer.value)
        alert('充值成功！')
        router.push('/wallet')
      } else if (res.status === 'failed' || res.status === 'closed') {
        if (pollingTimer.value) clearInterval(pollingTimer.value)
        errorMsg.value = '支付失败或已取消'
      }
    } catch (e) {
      console.error('查询订单失败:', e)
    }
  }, 3000)
}
</script>

<style scoped>
.recharge-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #fff;
  padding: 40px 20px;
  display: flex;
  justify-content: center;
}

.recharge-container {
  max-width: 480px;
  width: 100%;
}

.recharge-title {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 8px;
}

.recharge-subtitle {
  color: #888;
  margin-bottom: 32px;
}

.section-label {
  display: block;
  font-size: 14px;
  color: #aaa;
  margin-bottom: 12px;
}

.amount-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.amount-btn {
  padding: 16px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.amount-btn:hover {
  border-color: #00d4aa;
}

.amount-btn.active {
  border-color: #00d4aa;
  background: rgba(0, 212, 170, 0.1);
}

.custom-amount {
  grid-column: span 3;
}

.custom-input {
  width: 100%;
  padding: 14px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #fff;
  border-radius: 8px;
  font-size: 16px;
  box-sizing: border-box;
}

.pay-method {
  margin-bottom: 24px;
}

.method-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
}

.method-card.active {
  border-color: #00d4aa;
}

.alipay-icon {
  width: 32px;
  height: 32px;
}

.amount-display {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 0;
  border-top: 1px solid #333;
  margin-bottom: 24px;
}

.amount-display .value {
  font-size: 28px;
  font-weight: 600;
  color: #00d4aa;
}

.btn-block {
  width: 100%;
  padding: 16px;
  font-size: 16px;
}

.error-msg {
  color: #ff4757;
  margin-top: 16px;
  text-align: center;
}

.qr-section {
  margin-top: 32px;
  text-align: center;
  padding: 24px;
  background: #1a1a1a;
  border-radius: 12px;
}

.qr-hint {
  margin-bottom: 16px;
  color: #aaa;
}

.qr-img {
  width: 200px;
  height: 200px;
  border-radius: 8px;
}

.qr-waiting {
  margin-top: 16px;
  color: #888;
  font-size: 14px;
}

html[data-workbench-theme='light'] .recharge-page {
  background: #f5f5f7;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .recharge-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .recharge-subtitle {
  color: #86868b;
}

html[data-workbench-theme='light'] .section-label {
  color: #86868b;
}

html[data-workbench-theme='light'] .amount-btn {
  border-color: rgba(0, 0, 0, 0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .amount-btn:hover {
  border-color: #0071e3;
}

html[data-workbench-theme='light'] .amount-btn.active {
  border-color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
}

html[data-workbench-theme='light'] .custom-input {
  border-color: rgba(0, 0, 0, 0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .custom-input::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .method-card {
  border-color: rgba(0, 0, 0, 0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .method-card.active {
  border-color: #0071e3;
}

html[data-workbench-theme='light'] .amount-display {
  border-top-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .amount-display .label {
  color: #86868b;
}

html[data-workbench-theme='light'] .amount-display .value {
  color: #0071e3;
}

html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary:hover {
  background: #005bb5;
  opacity: 1;
}

html[data-workbench-theme='light'] .btn-primary:disabled {
  background: rgba(0, 113, 227, 0.4);
}

html[data-workbench-theme='light'] .error-msg {
  color: #dc2626;
}

html[data-workbench-theme='light'] .qr-section {
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .qr-hint {
  color: #86868b;
}

html[data-workbench-theme='light'] .qr-waiting {
  color: #86868b;
}
</style>

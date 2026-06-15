<template>
  <div>
    <h1 class="page-title">钱包</h1>

    <div class="balance-card">
      <div class="balance-label">当前余额</div>
      <div class="balance-value">¥{{ balance !== null ? balance.toFixed(2) : '--' }}</div>
    </div>

    <div class="card recharge-card">
      <h3 class="card-title">支付宝充值</h3>
      <p class="recharge-intro">输入金额后跳转支付宝完成付款，到账后余额与交易记录会自动更新。</p>
      <div v-if="payErr" class="flash flash-err">{{ payErr }}</div>
      <div v-if="payHint" class="flash flash-ok">{{ payHint }}</div>
      <div class="recharge-form">
        <input
          class="input"
          type="number"
          v-model.number="payAmount"
          placeholder="金额（元）"
          min="0.01"
          step="0.01"
        />
        <input class="input" v-model="payNote" placeholder="备注（可选）" />
        <button class="btn btn-primary-solid" type="button" :disabled="paying" @click="startAlipayRecharge">
          {{ paying ? '正在拉起支付…' : '支付宝充值' }}
        </button>
      </div>
      <p class="recharge-hint">
        若按钮无反应，请确认服务端已配置支付宝密钥与
        <code>ALIPAY_NOTIFY_URL</code>。套餐购买请前往
        <router-link to="/plans" class="inline-link">套餐页</router-link>。
      </p>
    </div>

    <div class="card">
      <h3 class="card-title">交易记录</h3>
      <div v-if="txLoading" class="loading">加载中...</div>
      <table v-else-if="transactions.length" class="tx-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>金额</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in transactions" :key="t.id">
            <td>{{ formatDate(t.created_at) }}</td>
            <td>{{ txnTypeLabel(t.type) }}</td>
            <td :class="t.amount > 0 ? 'amount-pos' : 'amount-neg'">
              {{ t.amount > 0 ? '+' : '' }}¥{{ t.amount.toFixed(2) }}
            </td>
            <td>{{ t.description }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">暂无交易记录</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useWalletStore } from '../stores/wallet'

const router = useRouter()
const walletStore = useWalletStore()
const { balance } = storeToRefs(walletStore)
const transactions = ref<any[]>([])
const txLoading = ref(true)
const payAmount = ref<number | null>(null)
const payNote = ref('')
const paying = ref(false)
const payErr = ref('')
const payHint = ref('')

onMounted(async () => {
  await Promise.all([walletStore.refreshBalance(), loadTransactions()])
})

function txnTypeLabel(type: string): string {
  const m: Record<string, string> = {
    recharge: '管理员充值',
    alipay_wallet: '支付宝充值',
    alipay_recharge: '支付宝入账',
    plan_purchase: '套餐购买',
    purchase: '购买',
  }
  return m[type] || type || '—'
}

async function loadTransactions() {
  txLoading.value = true
  try {
    const res = await api.transactions()
    transactions.value = res.transactions
  } catch {
    transactions.value = []
  } finally {
    txLoading.value = false
  }
}

async function startAlipayRecharge() {
  if (!localStorage.getItem('modstore_token')) {
    await router.push({ name: 'login', query: { redirect: '/wallet' } })
    return
  }
  const amt = Number(payAmount.value)
  if (!amt || amt <= 0) {
    payErr.value = '请输入大于 0 的金额'
    return
  }
  paying.value = true
  payErr.value = ''
  payHint.value = ''
  try {
    const res = await api.paymentCheckout({
      wallet_recharge: true,
      total_amount: amt,
      subject: payNote.value.trim() || 'XC AGI 钱包充值',
    })
    if (!res.ok) {
      payErr.value = res.message || '下单失败'
      return
    }
    if (res.type === 'page' || res.type === 'wap') {
      if (res.redirect_url) {
        window.location.href = res.redirect_url
        return
      }
      payErr.value = '未返回支付跳转地址'
      return
    }
    if (res.type === 'precreate' && res.order_id) {
      await router.push({ name: 'checkout', params: { orderId: res.order_id } })
      return
    }
    payErr.value = '未知的支付类型'
  } catch (e: any) {
    payErr.value = e?.message || String(e)
  } finally {
    paying.value = false
  }
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #ffffff; }
.balance-card { background: #111111; border: 0.5px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.balance-label { font-size: 14px; color: rgba(255,255,255,0.5); }
.balance-value { font-size: 36px; font-weight: 700; margin-top: 4px; color: #ffffff; }
.recharge-intro { font-size: 13px; color: rgba(255,255,255,0.45); margin: 0 0 12px; line-height: 1.5; }
.recharge-card .recharge-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.recharge-form .input { flex: 1; min-width: 120px; }
.recharge-hint { font-size: 12px; color: rgba(255,255,255,0.3); margin-top: 10px; line-height: 1.5; }
.recharge-hint code { font-size: 11px; color: rgba(255,255,255,0.45); }
.inline-link { color: #ffffff; font-weight: 500; text-decoration: underline; text-underline-offset: 2px; }
.tx-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.tx-table th { text-align: left; padding: 8px 12px; border-bottom: 0.5px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.4); font-weight: 600; }
.tx-table td { padding: 8px 12px; border-bottom: 0.5px solid rgba(255,255,255,0.06); }
.amount-pos { color: #4ade80; font-weight: 600; }
.amount-neg { color: #ff6b6b; font-weight: 600; }
.loading { text-align: center; padding: 20px; color: rgba(255,255,255,0.4); }
.empty-state { text-align: center; padding: 20px; color: rgba(255,255,255,0.4); }
</style>

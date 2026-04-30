<template>
  <div>
    <h1 class="page-title">钱包</h1>

    <div class="balance-card">
      <div class="balance-label">当前余额</div>
      <div class="balance-value">¥{{ balance !== null ? balance.toFixed(2) : '--' }}</div>
    </div>

    <div class="card recharge-card">
      <h3 class="card-title">充值</h3>
      <div v-if="rechargeErr" class="flash flash-err">{{ rechargeErr }}</div>
      <div v-if="rechargeOk" class="flash flash-ok">{{ rechargeOk }}</div>
      <div class="recharge-form">
        <input class="input" type="number" v-model.number="rechargeAmount" placeholder="充值金额" min="1" step="0.01" />
        <input class="input" v-model="rechargeDesc" placeholder="备注（可选）" />
        <button class="btn btn-primary-solid" @click="doRecharge" :disabled="recharging">
          {{ recharging ? '充值中...' : '充值' }}
        </button>
      </div>
      <p class="recharge-hint">需要管理员配置 MODSTORE_ADMIN_RECHARGE_TOKEN 才能充值</p>
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
            <td>{{ t.type === 'recharge' ? '充值' : '购买' }}</td>
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

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const balance = ref(null)
const transactions = ref([])
const txLoading = ref(true)
const rechargeAmount = ref(null)
const rechargeDesc = ref('')
const recharging = ref(false)
const rechargeErr = ref('')
const rechargeOk = ref('')

onMounted(async () => {
  await Promise.all([loadBalance(), loadTransactions()])
})

async function loadBalance() {
  try {
    const res = await api.balance()
    balance.value = res.balance
  } catch {
    balance.value = null
  }
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

async function doRecharge() {
  if (!rechargeAmount.value || rechargeAmount.value <= 0) {
    rechargeErr.value = '请输入有效金额'
    return
  }
  recharging.value = true
  rechargeErr.value = ''
  rechargeOk.value = ''
  try {
    const res = await api.recharge(rechargeAmount.value, rechargeDesc.value)
    rechargeOk.value = '充值成功'
    balance.value = res.new_balance
    rechargeAmount.value = null
    rechargeDesc.value = ''
    await loadTransactions()
  } catch (e) {
    rechargeErr.value = e.message
  } finally {
    recharging.value = false
  }
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.balance-card { background: linear-gradient(135deg, #4361ee, #3a56d4); color: #fff; border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.balance-label { font-size: 14px; opacity: 0.8; }
.balance-value { font-size: 36px; font-weight: 700; margin-top: 4px; }
.recharge-card .recharge-form { display: flex; gap: 8px; flex-wrap: wrap; }
.recharge-form .input { flex: 1; min-width: 120px; }
.recharge-hint { font-size: 12px; color: #999; margin-top: 8px; }
.tx-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.tx-table th { text-align: left; padding: 8px 12px; border-bottom: 2px solid #e0e0e0; color: #666; font-weight: 600; }
.tx-table td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }
.amount-pos { color: #2d6a4f; font-weight: 600; }
.amount-neg { color: #e74c3c; font-weight: 600; }
.loading { text-align: center; padding: 20px; color: #999; }
.empty-state { text-align: center; padding: 20px; color: #999; }
</style>

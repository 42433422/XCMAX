import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api'

export const useWalletStore = defineStore('wallet', () => {
  const balance = ref<number | null>(null)
  /** 会员累计参考线（元），来自 /api/wallet/balance */
  const membershipReferenceYuan = ref<number | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<number | null>(null)

  function setMembershipReferenceYuan(v: unknown): void {
    const n = Number(v)
    membershipReferenceYuan.value = Number.isFinite(n) && n >= 0 ? Math.floor(n) : null
  }

  async function refreshBalance(retryCount = 2): Promise<number | null> {
    loading.value = true
    error.value = null

    for (let attempt = 0; attempt <= retryCount; attempt++) {
      try {
        const res = await api.balance()
        if (res && typeof res.balance === 'number') {
          balance.value = res.balance
          setMembershipReferenceYuan(res?.membership_reference_yuan)
          lastUpdated.value = Date.now()
          console.log(`[Wallet] 余额刷新成功: ¥${res.balance.toFixed(2)}`)
          return balance.value
        } else {
          throw new Error('Invalid API response format')
        }
      } catch (err) {
        console.warn(`[Wallet] 余额刷新失败 (尝试 ${attempt + 1}/${retryCount + 1}):`, err)
        if (attempt < retryCount) {
          await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)))
        } else {
          error.value = err instanceof Error ? err.message : String(err)
          console.error('[Wallet] 所有重试失败，余额设为 null')
        }
      }
    }

    balance.value = null
    membershipReferenceYuan.value = null
    return null
  }

  function setBalance(value: unknown): void {
    const n = Number(value)
    balance.value = Number.isFinite(n) ? n : null
    if (balance.value !== null) {
      lastUpdated.value = Date.now()
    }
  }

  function clear(): void {
    balance.value = null
    membershipReferenceYuan.value = null
    error.value = null
    lastUpdated.value = null
  }

  return {
    balance,
    membershipReferenceYuan,
    loading,
    error,
    lastUpdated,
    refreshBalance,
    setBalance,
    setMembershipReferenceYuan,
    clear
  }
})

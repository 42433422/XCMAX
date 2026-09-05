import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api'
import { useAuthStore } from './auth'

export const useWalletStore = defineStore('wallet', () => {
  const auth = useAuthStore()
  let readVersion = 0
  const balance = ref<number | null>(null)
  /** 会员累计参考线（元），来自 /api/wallet/balance */
  const membershipReferenceYuan = ref<number | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<number | null>(null)

  function setMembershipReferenceYuan(v: unknown): void {
    const n = Number(v)
    membershipReferenceYuan.value = v !== null && v !== undefined && String(v).trim() !== '' && Number.isFinite(n) && n >= 0 ? Math.floor(n) : null
  }

  function markBalanceStale(message: string): void {
    error.value = message
  }

  async function refreshBalance(retryCount = 2): Promise<number | null> {
    const version = ++readVersion
    loading.value = true
    error.value = null
    try {
      for (let attempt = 0; attempt <= retryCount; attempt++) {
        try {
          const res = await api.balance()
          if (version !== readVersion) return null
          const raw = res?.balance
          if (raw === null || raw === undefined || String(raw).trim() === '' || !Number.isFinite(Number(raw))) {
            throw new Error('余额暂时无法读取')
          }
          setBalance(raw)
          setMembershipReferenceYuan(res.membership_reference_yuan)
          return balance.value
        } catch {
          if (version !== readVersion) return null
          if (attempt < retryCount) {
            await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
            if (version !== readVersion) return null
          } else {
            markBalanceStale('余额加载失败，请重试。')
          }
        }
      }
      // A failed refresh says nothing about the amount; keep the last confirmed snapshot.
      return null
    } finally {
      if (version === readVersion) loading.value = false
    }
  }

  function setBalance(value: unknown): void {
    const n = Number(value)
    balance.value = value !== null && value !== undefined && String(value).trim() !== '' && Number.isFinite(n) ? n : null
    if (balance.value !== null) {
      error.value = null
      lastUpdated.value = Date.now()
    }
  }

  function clear(): void {
    readVersion++
    loading.value = false
    balance.value = null
    membershipReferenceYuan.value = null
    error.value = null
    lastUpdated.value = null
  }

  watch(() => auth.user?.id, () => clear(), { flush: 'sync' })

  return {
    balance,
    membershipReferenceYuan,
    loading,
    error,
    lastUpdated,
    refreshBalance,
    markBalanceStale,
    setBalance,
    setMembershipReferenceYuan,
    clear,
  }
})

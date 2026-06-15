import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api'

export const useWalletStore = defineStore('wallet', () => {
  const balance = ref<number | null>(null)
  const loading = ref(false)

  async function refreshBalance(): Promise<number | null> {
    loading.value = true
    try {
      const res = (await api.balance()) as { balance?: number | string }
      const n = Number(res?.balance ?? 0)
      balance.value = Number.isFinite(n) ? n : null
      return balance.value
    } catch {
      balance.value = null
      return null
    } finally {
      loading.value = false
    }
  }

  function setBalance(value: unknown): void {
    const n = Number(value)
    balance.value = Number.isFinite(n) ? n : null
  }

  function clear(): void {
    balance.value = null
  }

  return { balance, loading, refreshBalance, setBalance, clear }
})

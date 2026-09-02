// 拆分自 App.vue：自助补额弹窗状态与动作（逻辑逐字迁移，行为不变）。
import { ref } from 'vue'
import { api } from '../api'
import { useI18n } from '../i18n'
import { useWalletStore } from '../stores/wallet'

export function useSelfCredit() {
  const { t } = useI18n()
  const walletStore = useWalletStore()
  const selfCreditOpen = ref(false)
  const selfCreditAmount = ref('')
  const selfCreditNote = ref('')
  const selfCreditErr = ref('')
  const selfCreditBusy = ref(false)

  function openSelfCreditModal() {
    selfCreditErr.value = ''
    selfCreditAmount.value = ''
    selfCreditNote.value = ''
    selfCreditOpen.value = true
  }

  function closeSelfCreditModal() {
    if (selfCreditBusy.value) return
    selfCreditOpen.value = false
  }

  async function submitSelfCredit() {
    const n = Number(selfCreditAmount.value)
    if (!Number.isFinite(n) || n <= 0) {
      selfCreditErr.value = t('nav.adminSelfCreditAmountInvalid')
      return
    }
    selfCreditBusy.value = true
    selfCreditErr.value = ''
    try {
      await api.walletAdminSelfCredit(n, selfCreditNote.value.trim())
      await walletStore.refreshBalance()
      selfCreditOpen.value = false
    } catch (e) {
      selfCreditErr.value = (e as Error)?.message || String(e)
    } finally {
      selfCreditBusy.value = false
    }
  }

  return {
    selfCreditOpen,
    selfCreditAmount,
    selfCreditNote,
    selfCreditErr,
    selfCreditBusy,
    openSelfCreditModal,
    closeSelfCreditModal,
    submitSelfCredit,
  }
}

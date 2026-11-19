import { ref, computed, watch, onBeforeUnmount, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { User } from '@/api/auth'
import { butlerProfileApi, type ButlerProfileView } from '@/api/butlerProfile'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

export function useSettingsMemory(localUser: Ref<User | null>) {
  const { t } = useI18n()

  const persyProfile = ref<ButlerProfileView | null>(null)
  const persyLoading = ref(false)
  const persyInferring = ref(false)
  const persyLastReason = ref('')
  const persyError = ref('')
  let profileRequest = 0

  const persyUserId = computed(() => {
    void productReadAccountEpoch.value
    const accountId = Number(localUser.value?.id)
    return Number.isSafeInteger(accountId) && accountId > 0 ? String(accountId) : '1'
  })

  const persyFoldMeta = computed(() => {
    if (!persyProfile.value) return t('settings.persyUninitialized')
    const identity = persyProfile.value.identity_composite || persyProfile.value.identity_primary || t('settings.persyUninitialized')
    const interactions = persyProfile.value.interaction_count || 0
    return t('settings.persyFoldMeta', { identity, count: interactions })
  })

  async function loadPersyProfile() {
    const request = ++profileRequest
    const account = productReadAccountEpoch.value
    persyLoading.value = true
    persyError.value = ''
    try {
      const result = await butlerProfileApi.get(persyUserId.value)
      if (request !== profileRequest || account !== productReadAccountEpoch.value) return
      if (result.success === false) throw new Error(result.message || t('settings.persyLoadFailed'))
      persyProfile.value = result.profile || null
    } catch {
      if (request === profileRequest && account === productReadAccountEpoch.value) persyError.value = t('settings.persyReadRetry')
    } finally {
      if (request === profileRequest) persyLoading.value = false
    }
  }

  async function runPersyInfer() {
    if (persyInferring.value) return
    const account = productReadAccountEpoch.value
    const userId = persyUserId.value
    persyInferring.value = true
    persyLastReason.value = ''
    try {
      const result = await butlerProfileApi.infer({ userId: persyUserId.value })
      if (account !== productReadAccountEpoch.value || userId !== persyUserId.value) return
      if (result.success === false) throw new Error(result.message || t('settings.persyInferFailed'))
      if (result.profile) { persyProfile.value = result.profile; persyError.value = '' }
      if (result.inference?.reasons?.length) {
        persyLastReason.value = result.inference.reasons[result.inference.reasons.length - 1]
      }
    } catch (e: unknown) {
      if (account === productReadAccountEpoch.value && userId === persyUserId.value) persyLastReason.value = e instanceof Error ? e.message : t('settings.persyInferFailed')
    } finally {
      if (account === productReadAccountEpoch.value && userId === persyUserId.value) persyInferring.value = false
    }
  }

  watch([persyUserId, productReadAccountEpoch], () => {
    profileRequest++
    persyProfile.value = null
    persyError.value = ''
    persyLastReason.value = ''
    persyInferring.value = false
    void loadPersyProfile()
  }, { flush: 'sync' })
  onBeforeUnmount(() => { profileRequest++ })

  return { persyProfile, persyLoading, persyInferring, persyLastReason, persyError, persyUserId, persyFoldMeta, loadPersyProfile, runPersyInfer }
}

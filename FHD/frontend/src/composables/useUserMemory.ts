import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { memoryV2Api, type MemoryV2ApiResult, type MemoryV2Record, type MemoryV2Status, type MemoryV2Type } from '@/api/memoryV2'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useModsStore } from '@/stores/mods'
import { appAlert, appConfirm } from '@/utils/appDialog'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import { errorMessage } from './settings/utils'

function editableValue(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2) ?? ''
  } catch {
    return String(value ?? '')
  }
}

function parseInput(value: string): unknown {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (!/^(\{|\[|"|-?\d+(\.\d+)?$|true$|false$|null$)/i.test(trimmed)) return value
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

export function useUserMemory() {
  const { t, locale } = useI18n()
  const account = useAccountProfileStore()
  const mods = useModsStore()
  const memoryV2UserId = computed(() =>
    account.workspaceReady && Number.isSafeInteger(account.localUserId) && Number(account.localUserId) > 0
      ? String(account.localUserId) : '',
  )
  const scopeKey = computed(() =>
    JSON.stringify([getAuthSessionEpoch(), productReadScopeKey(mods.activeModId), memoryV2UserId.value]),
  )

  const memoryV2TypeOptions = computed<Array<{ value: MemoryV2Type; label: string }>>(() => [
    { value: 'preference', label: t('settings.memoryTypePreference') },
    { value: 'entity', label: t('settings.memoryTypeEntity') },
    { value: 'episodic', label: t('settings.memoryTypeEpisodic') },
  ])
  const memoryV2StatusFilters = computed<Array<{ value: 'all' | MemoryV2Status; label: string }>>(() => [
    { value: 'all', label: t('settings.memoryStatusAll') },
    { value: 'pending', label: t('settings.memoryStatusPending') },
    { value: 'active', label: t('settings.memoryStatusActive') },
    { value: 'rejected', label: t('settings.memoryStatusRejected') },
    { value: 'deleted', label: t('settings.memoryStatusDeleted') },
  ])
  const memoryV2Records = ref<MemoryV2Record[]>([])
  const memoryV2Loading = ref(false)
  const memoryV2Creating = ref(false)
  const memoryV2BusyId = ref('')
  const memoryV2Error = ref('')
  const memoryV2Saved = ref(false)
  const mutatingMemory = computed(() => Boolean(memoryV2BusyId.value || memoryV2Creating.value))
  const memoryV2StatusFilter = ref<'all' | MemoryV2Status>('all')
  const memoryV2TypeFilter = ref<'all' | MemoryV2Type>('all')
  const initialDraft = { memoryType: 'preference' as MemoryV2Type, key: '', value: '' }
  const memoryV2Draft = reactive({ ...initialDraft })
  const memoryV2Edit = reactive({ memoryId: '', key: '', value: '' })
  let generation = 0
  let read = 0

  function memoryV2TypeLabel(type: unknown) {
    return memoryV2TypeOptions.value.find(item => item.value === type)?.label || String(type || t('settings.memoryUnknown'))
  }

  function memoryV2StatusLabel(status: unknown) {
    return memoryV2StatusFilters.value.find(item => item.value === status)?.label || String(status || t('settings.memoryUnknown'))
  }

  function memoryV2DisplayValue(value: unknown) {
    const display = editableValue(value)
    return display.length > 160 ? `${display.slice(0, 160)}…` : display
  }

  function memoryV2Time(value: unknown) {
    const raw = String(value || '').trim()
    const parsed = Date.parse(raw)
    return Number.isNaN(parsed) ? raw : new Date(parsed).toLocaleString(locale.value, {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  }

  function canEditMemoryV2(record: MemoryV2Record) {
    return record.status === 'pending' || record.status === 'active'
  }

  async function loadMemoryV2() {
    const userId = memoryV2UserId.value
    if (!userId) return
    const request = ++read
    const owner = generation
    const scope = scopeKey.value
    const current = () => owner === generation && scope === scopeKey.value && request === read
    memoryV2Loading.value = true
    memoryV2Error.value = ''
    try {
      const result = await memoryV2Api.list({
        userId,
        status: memoryV2StatusFilter.value === 'all' ? undefined : memoryV2StatusFilter.value,
        memoryType: memoryV2TypeFilter.value === 'all' ? undefined : memoryV2TypeFilter.value,
      })
      if (!current()) return
      if (result.success === false) throw new Error(result.message || t('settings.memoryLoadFailed'))
      memoryV2Records.value = Array.isArray(result.memories) ? result.memories : []
    } catch (error) {
      if (!current()) return
      memoryV2Records.value = []
      memoryV2Error.value = errorMessage(error, t('settings.memoryLoadFailed'))
    } finally {
      if (current()) memoryV2Loading.value = false
    }
  }

  async function mutate(
    busyId: string,
    errorKey: string,
    action: (userId: string, current: () => boolean) => Promise<MemoryV2ApiResult>,
    onSuccess?: () => void,
  ) {
    const userId = memoryV2UserId.value
    if (!userId || mutatingMemory.value) return
    const owner = generation
    const scope = scopeKey.value
    const current = () => owner === generation && scope === scopeKey.value
    if (busyId) memoryV2BusyId.value = busyId
    else memoryV2Creating.value = true
    memoryV2Error.value = ''
    memoryV2Saved.value = false
    try {
      const result = await action(userId, current)
      if (!current()) return
      if (result.success !== true) throw new Error(result.message || t(errorKey))
      onSuccess?.()
      await loadMemoryV2()
    } catch (error) {
      if (current()) memoryV2Error.value = errorMessage(error, t(errorKey))
    } finally {
      if (current()) {
        memoryV2BusyId.value = ''
        memoryV2Creating.value = false
      }
    }
  }

  async function saveMemoryV2() {
    const { key, value, memoryType } = memoryV2Draft
    if (!key.trim() || !value.trim()) {
      memoryV2Saved.value = false
      await appAlert(t('settings.memoryFillKeyValue'))
      return
    }
    await mutate('', 'settings.memorySaveFailed', async (userId, current) => {
      const result = await memoryV2Api.createCandidate({
        userId, memoryType, key: key.trim(), value: parseInput(value), confidence: 1, source: 'settings_ui',
      })
      if (!current() || result.success !== true) return result
      const candidate = result.candidate
      if (candidate?.status === 'rejected') {
        return { success: false, message: t('settings.memorySaveRejected') }
      }
      const memoryId = typeof candidate?.memory_id === 'string' ? candidate.memory_id.trim() : ''
      if (memoryId && candidate?.status === 'active' && candidate.eligible_for_planner === true) return result
      if (!memoryId || candidate?.status !== 'pending') {
        return { success: false, message: t('settings.memorySaveUnverified') }
      }

      // The authority deduplicates this candidate on a later, explicit save.
      try {
        const confirmed = await memoryV2Api.confirm(memoryId, userId)
        const memory = confirmed.memory
        if (confirmed.success === true && memory?.memory_id === memoryId &&
          memory.status === 'active' && memory.eligible_for_planner === true) return confirmed
      } catch {
        // A timeout can occur after the confirmation committed.
      }
      return { success: false, message: t('settings.memorySaveUnconfirmed') }
    }, () => {
      memoryV2Draft.key = ''
      memoryV2Draft.value = ''
      memoryV2Saved.value = true
    })
  }

  function confirmMemoryV2(record: MemoryV2Record) {
    return mutate(record.memory_id, 'settings.memoryConfirmFailed', userId => memoryV2Api.confirm(record.memory_id, userId))
  }

  async function rejectMemoryV2(record: MemoryV2Record) {
    const owner = generation
    if (!await appConfirm(t('settings.memoryRejectConfirm', { key: record.key }), { danger: true }) || owner !== generation) return
    await mutate(record.memory_id, 'settings.memoryRejectFailed', userId => memoryV2Api.reject(record.memory_id, userId, 'settings_ui_rejected'))
  }

  function startMemoryV2Edit(record: MemoryV2Record) {
    Object.assign(memoryV2Edit, { memoryId: record.memory_id, key: String(record.key || ''), value: editableValue(record.value) })
  }

  function cancelMemoryV2Edit() {
    Object.assign(memoryV2Edit, { memoryId: '', key: '', value: '' })
  }

  async function saveMemoryV2Edit(record: MemoryV2Record) {
    const key = memoryV2Edit.key.trim()
    if (!key) {
      await appAlert(t('settings.memoryFillKey'))
      return
    }
    const value = parseInput(memoryV2Edit.value)
    await mutate(record.memory_id, 'settings.memoryReviseFailed', userId => memoryV2Api.correct(record.memory_id, {
      userId, key, value, reason: 'settings_ui_correction',
    }), cancelMemoryV2Edit)
  }

  async function deleteMemoryV2(record: MemoryV2Record) {
    const owner = generation
    if (!await appConfirm(t('settings.memoryDeleteConfirm', { key: record.key }), { danger: true }) || owner !== generation) return
    await mutate(record.memory_id, 'settings.memoryDeleteFailed', userId => memoryV2Api.remove(record.memory_id, userId, 'settings_ui_deleted'), () => {
      if (memoryV2Edit.memoryId === record.memory_id) cancelMemoryV2Edit()
    })
  }

  watch(scopeKey, () => {
    ++generation
    memoryV2Records.value = []
    memoryV2Loading.value = false
    memoryV2Error.value = ''
    memoryV2Saved.value = false
    memoryV2BusyId.value = ''
    memoryV2Creating.value = false
    Object.assign(memoryV2Draft, initialDraft)
    cancelMemoryV2Edit()
    const owner = generation
    void nextTick(() => {
      if (owner === generation) void loadMemoryV2()
    })
  }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(() => { ++generation })

  return {
    memoryV2UserId, memoryV2Records, memoryV2StatusFilters, memoryV2StatusFilter,
    memoryV2TypeOptions, memoryV2TypeFilter, memoryV2Loading, memoryV2Error, memoryV2Draft,
    memoryV2Creating, memoryV2Edit, memoryV2Saved, mutatingMemory, loadMemoryV2, saveMemoryV2,
    confirmMemoryV2, rejectMemoryV2, startMemoryV2Edit, cancelMemoryV2Edit, saveMemoryV2Edit,
    deleteMemoryV2, memoryV2TypeLabel, memoryV2StatusLabel, memoryV2Time, memoryV2DisplayValue, canEditMemoryV2,
  }
}

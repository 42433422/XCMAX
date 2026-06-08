import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import {
  applyButlerDownloadRetention,
  downloadsToButlerRecords,
  mergeButlerDownloadRecord,
  parseButlerDownloadStorage,
  serializeButlerDownloadStorage,
  storageKeyForUser,
  type ButlerDownloadRecord,
} from '../utils/butlerDownloadHistory'
import type { EmployeeOutputDownload } from '../utils/tabularReadEmployees'

export const useButlerDownloadHistoryStore = defineStore('butlerDownloadHistory', () => {
  const authStore = useAuthStore()
  const records = ref<ButlerDownloadRecord[]>([])
  const hydrated = ref(false)

  const isMember = computed(() => Boolean(authStore.membership?.is_member))

  const activeRecords = computed(() => records.value.filter((r) => !r.expired))
  const expiredRecords = computed(() => records.value.filter((r) => r.expired))

  function loadFromStorage() {
    const userId = authStore.user?.id
    const key = storageKeyForUser(userId)
    let raw: string | null = null
    try {
      raw = localStorage.getItem(key)
    } catch {
      raw = null
    }
    const parsed = parseButlerDownloadStorage(raw)
    records.value = applyButlerDownloadRetention(parsed, isMember.value)
    hydrated.value = true
  }

  function persist() {
    if (!hydrated.value) return
    const key = storageKeyForUser(authStore.user?.id)
    try {
      localStorage.setItem(key, serializeButlerDownloadStorage(records.value))
    } catch {
      /* ignore quota */
    }
  }

  function reapplyRetention() {
    records.value = applyButlerDownloadRetention(records.value, isMember.value)
    persist()
  }

  function recordDownloads(
    downloads: EmployeeOutputDownload[],
    opts?: { employeeId?: string },
  ) {
    if (!downloads?.length) return
    if (!hydrated.value) loadFromStorage()
    const base = downloadsToButlerRecords(downloads, { employeeId: opts?.employeeId })
    let next = records.value
    for (const row of base) {
      next = mergeButlerDownloadRecord(next, row, isMember.value)
    }
    records.value = next
    persist()
  }

  function recordSingle(jobId: string, filename: string, displayName: string, employeeId?: string) {
    recordDownloads([{ jobId, filename, label: displayName }], { employeeId })
  }

  watch(
    () => [authStore.user?.id, authStore.membership?.is_member] as const,
    () => {
      loadFromStorage()
    },
    { immediate: true },
  )

  watch(isMember, () => {
    if (!hydrated.value) return
    reapplyRetention()
  })

  return {
    records,
    isMember,
    activeRecords,
    expiredRecords,
    loadFromStorage,
    recordDownloads,
    recordSingle,
    reapplyRetention,
  }
})

// 快照：列表刷新、手动创建、恢复与 manifest 版本 bump（原单体实现原样迁移）。
import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { api } from '@/api'
import type { SnapshotRow } from './types'
import type { Flash } from './core'

export interface SnapshotsDeps {
  modId: ComputedRef<string>
  flash: Flash
  reload: () => Promise<void>
  manifestSaveWarnings: Ref<string[]>
}

export function createSnapshots(deps: SnapshotsDeps) {
  const { modId, flash, reload, manifestSaveWarnings } = deps

  const snapshotsRows = ref<SnapshotRow[]>([])
  const snapshotsLoadErr = ref('')
  const snapshotBusy = ref(false)
  const snapshotLabelDraft = ref('')

  function formatSnapTime(ts: unknown): string {
    const n = Number(ts)
    if (!Number.isFinite(n) || n <= 0) return '—'
    try {
      return new Date(n * 1000).toLocaleString()
    } catch {
      return String(ts)
    }
  }

  async function refreshSnapshots() {
    if (!modId.value) return
    snapshotsLoadErr.value = ''
    try {
      const res = await api.listModSnapshots(modId.value)
      const rows = Array.isArray(res) ? res : Array.isArray(res.snapshots) ? res.snapshots : []
      snapshotsRows.value = rows as SnapshotRow[]
    } catch (e: unknown) {
      snapshotsRows.value = []
      const status = (e as { status?: number })?.status
      const msg = (e as Error)?.message || String(e)
      // 旧版后端未注册 snapshots 路由时勿阻断制作页
      if (status === 404 && /not found/i.test(msg)) return
      snapshotsLoadErr.value = msg
    }
  }

  async function captureSnapshotManual() {
    if (!modId.value) return
    snapshotBusy.value = true
    try {
      await api.captureModSnapshot(modId.value, snapshotLabelDraft.value.trim())
      snapshotLabelDraft.value = ''
      flash('已创建快照', true)
      await refreshSnapshots()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      snapshotBusy.value = false
    }
  }

  async function restoreSnapshot(snapId: string) {
    if (!modId.value || !snapId) return
    if (!window.confirm('将用该快照覆盖当前 manifest.json，确定继续？')) return
    snapshotBusy.value = true
    try {
      await api.restoreModSnapshot(modId.value, snapId)
      flash('已从快照恢复 manifest', true)
      await reload()
      await refreshSnapshots()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      snapshotBusy.value = false
    }
  }

  async function bumpManifestPatch() {
    if (!modId.value) return
    snapshotBusy.value = true
    try {
      const res = await api.bumpModManifestPatchVersion(modId.value)
      const w = Array.isArray(res?.warnings) ? res.warnings : []
      if (w.length) manifestSaveWarnings.value = w
      flash(`manifest 版本已更新为 ${res?.manifest?.version || '新版本'}`, true)
      await reload()
      await refreshSnapshots()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      snapshotBusy.value = false
    }
  }

  return {
    snapshotsRows,
    snapshotsLoadErr,
    snapshotBusy,
    snapshotLabelDraft,
    formatSnapTime,
    refreshSnapshots,
    captureSnapshotManual,
    restoreSnapshot,
    bumpManifestPatch,
  }
}

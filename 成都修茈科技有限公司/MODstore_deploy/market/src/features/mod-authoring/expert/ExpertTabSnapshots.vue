<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const {
  snapshotsRows,
  snapshotsLoadErr,
  snapshotBusy,
  snapshotLabelDraft,
  formatSnapTime,
  refreshSnapshots,
  captureSnapshotManual,
  restoreSnapshot,
  bumpManifestPatch,
} = useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">版本</h2>
    <div class="snap-toolbar">
      <input
        v-model="snapshotLabelDraft"
        type="text"
        class="input snap-label-input"
        maxlength="240"
        placeholder="备注（可选）"
      />
      <button type="button" class="btn btn-primary" :disabled="snapshotBusy" @click="() => void captureSnapshotManual()">
        {{ snapshotBusy ? '…' : '快照' }}
      </button>
      <button type="button" class="btn" :disabled="snapshotBusy" @click="() => void refreshSnapshots()">刷新</button>
      <button type="button" class="btn" :disabled="snapshotBusy" @click="() => void bumpManifestPatch()">
        patch+1
      </button>
    </div>
    <p v-if="snapshotsLoadErr" class="flash flash-err">{{ snapshotsLoadErr }}</p>
    <ul v-if="snapshotsRows.length" class="snap-list">
      <li v-for="s in snapshotsRows" :key="s.snap_id" class="snap-li">
        <code class="mono">{{ s.snap_id }}</code>
        <span class="muted small">{{ formatSnapTime(s.created_at) }}</span>
        <span v-if="s.label" class="snap-label">{{ s.label }}</span>
        <button type="button" class="btn btn-sm btn-ghost" :disabled="snapshotBusy" @click="() => void restoreSnapshot(s.snap_id)">
          恢复
        </button>
      </li>
    </ul>
    <p v-else class="muted small">暂无快照</p>
  </section>
</template>

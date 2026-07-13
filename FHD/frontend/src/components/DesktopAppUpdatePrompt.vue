<template>
  <div v-if="badgeVisible" class="desktop-update-anchor">
    <button
      type="button"
      class="desktop-update-chip"
      :class="{
        'is-downloading': phase === 'downloading',
        'is-ready': phase === 'downloaded',
      }"
      :title="badgeLabel"
      @click="openModal"
    >
      <span class="desktop-update-chip__dot" aria-hidden="true" />
      <span>{{ badgeLabel }}</span>
    </button>
    <button
      type="button"
      class="desktop-update-dismiss"
      aria-label="稍后提醒"
      title="稍后提醒"
      @click.stop="dismiss"
    >
      ×
    </button>
  </div>

  <Modal v-model="modalOpen" title="软件更新" max-width="520px">
    <div class="desktop-update-modal">
      <p class="desktop-update-modal__lead">
        <template v-if="updateInfo?.version">
          新版本 <strong>{{ updateInfo.version }}</strong> 可用
        </template>
        <template v-else>有新版本可用</template>
        <span v-if="updateInfo?.buildSha" class="muted">
          · 构建 {{ updateInfo.buildSha.slice(0, 12) }}
        </span>
      </p>

      <div class="desktop-update-notes" aria-label="更新说明">
        <pre>{{ notesText }}</pre>
      </div>

      <div v-if="phase === 'downloading'" class="desktop-update-progress">
        <div class="desktop-update-progress__bar" :style="{ width: `${downloadPercent}%` }" />
        <span>正在下载 {{ Math.round(downloadPercent) }}%</span>
      </div>

      <p v-if="errorMessage" class="desktop-update-error">{{ errorMessage }}</p>
    </div>
    <template #footer>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="busy" @click="closeModal">
        稍后
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="busy || phase === 'downloading'"
        @click="primaryAction"
      >
        <template v-if="phase === 'downloaded'">更新并重新加载</template>
        <template v-else-if="phase === 'downloading'">下载中…</template>
        <template v-else>下载更新</template>
      </button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import Modal from '@/components/Modal.vue'
import { useDesktopAppUpdater } from '@/composables/useDesktopAppUpdater'

const {
  phase,
  updateInfo,
  downloadPercent,
  errorMessage,
  modalOpen,
  busy,
  badgeVisible,
  badgeLabel,
  notesText,
  openModal,
  closeModal,
  dismiss,
  primaryAction,
} = useDesktopAppUpdater()
</script>

<style scoped>
.desktop-update-anchor {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
}

.desktop-update-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 180px;
  padding: 3px 8px;
  border: 1px solid rgba(37, 99, 235, 0.35);
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.3;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.desktop-update-chip.is-downloading {
  border-color: rgba(217, 119, 6, 0.4);
  background: #fffbeb;
  color: #b45309;
}

.desktop-update-chip.is-ready {
  border-color: rgba(22, 163, 74, 0.4);
  background: #f0fdf4;
  color: #15803d;
}

.desktop-update-chip__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: 0 0 auto;
}

.desktop-update-dismiss {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}

.desktop-update-modal__lead {
  margin: 0 0 12px;
  font-size: 14px;
}

.desktop-update-notes {
  max-height: 280px;
  overflow: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px 14px;
}

.desktop-update-notes pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
}

.desktop-update-progress {
  margin-top: 12px;
  font-size: 12px;
  color: #64748b;
}

.desktop-update-progress__bar {
  height: 6px;
  margin-bottom: 6px;
  border-radius: 999px;
  background: #2563eb;
  transition: width 160ms ease;
}

.desktop-update-error {
  margin: 12px 0 0;
  color: #b91c1c;
  font-size: 13px;
}

.muted {
  color: #64748b;
  font-weight: 400;
}
</style>

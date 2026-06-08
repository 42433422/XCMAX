<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../../stores/butlerDownloadHistory'
import { useAgentStore } from '../../stores/agent'
import { api } from '../../api'
import type { DirectGeneratedFile } from '../../utils/directGeneratedFiles'
import { directFileKindLabel, directFileKind } from '../../utils/directAttachments'
import { BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT } from '../../utils/butlerDownloadHistory'

const trayStore = useButlerWorkbenchTrayStore()
const historyStore = useButlerDownloadHistoryStore()
const agentStore = useAgentStore()
const router = useRouter()

const { overflowAttachments, overflowGenerated, overflowCount } = storeToRefs(trayStore)
const { activeRecords, expiredRecords, isMember } = storeToRefs(historyStore)

const showOverflow = computed(() => overflowCount.value > 0)

async function downloadFromHistory(jobId: string, filename: string, expired: boolean) {
  if (expired) return
  try {
    const blob = await api.employeeOutputDownload(jobId, filename)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename.split(/[/\\]/).pop() || filename
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    /* toast optional */
  }
}

function onDownloadGenerated(f: DirectGeneratedFile) {
  const fn = trayStore.actions.downloadGenerated
  if (fn) void fn(f)
  else void downloadFromHistory(f.jobId, f.filename, false)
}

function onRemoveGenerated(id: string) {
  trayStore.actions.removeGenerated?.(id)
}

function onRemoveAttachment(id: string) {
  void trayStore.actions.removeAttachment?.(id)
}

function goPlans() {
  agentStore.closePanel()
  void router.push({ name: 'plans' })
}
</script>

<template>
  <section class="butler-files" aria-label="文件收纳与下载记录">
    <div v-if="showOverflow" class="butler-files__block">
      <h3 class="butler-files__title">
        收纳文件
        <span class="butler-files__count">{{ overflowCount }}</span>
      </h3>
      <p class="butler-files__hint">顶栏仅展示少量卡片，其余收纳在 AI 管家中。</p>
      <ul class="butler-files__list">
        <li
          v-for="f in overflowAttachments"
          :key="`att-${f.id}`"
          class="butler-files__item butler-files__item--attachment"
        >
          <span class="butler-files__kind">{{ directFileKindLabel(directFileKind(f.name)) }}</span>
          <span class="butler-files__name" :title="f.name">{{ f.name }}</span>
          <span class="butler-files__meta">{{ f.status }}</span>
          <button
            type="button"
            class="butler-files__btn butler-files__btn--ghost"
            aria-label="移除附件"
            @click="onRemoveAttachment(f.id)"
          >
            移除
          </button>
        </li>
        <li
          v-for="f in overflowGenerated"
          :key="f.id"
          class="butler-files__item butler-files__item--generated"
        >
          <span class="butler-files__kind">已生成</span>
          <button
            type="button"
            class="butler-files__name butler-files__name--link"
            :title="`${f.name}：点击下载`"
            @click="onDownloadGenerated(f)"
          >
            {{ f.name }}
          </button>
          <button
            type="button"
            class="butler-files__btn butler-files__btn--ghost"
            aria-label="移除"
            @click="onRemoveGenerated(f.id)"
          >
            移除
          </button>
        </li>
      </ul>
    </div>

    <div class="butler-files__block">
      <h3 class="butler-files__title">下载记录</h3>
      <p v-if="!isMember" class="butler-files__member-hint">
        普通用户仅保留最近 {{ BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT }} 条可下载记录；开通
        <button type="button" class="butler-files__link" @click="goPlans">会员</button>
        可长期保留全部记录。
      </p>
      <p v-else class="butler-files__member-hint butler-files__member-hint--ok">
        会员：下载记录将长期保留。
      </p>

      <ul v-if="activeRecords.length" class="butler-files__list">
        <li
          v-for="r in activeRecords"
          :key="r.id"
          class="butler-files__item butler-files__item--history"
        >
          <button
            type="button"
            class="butler-files__name butler-files__name--link"
            :title="r.displayName"
            @click="downloadFromHistory(r.jobId, r.filename, false)"
          >
            {{ r.displayName }}
          </button>
          <span class="butler-files__meta">{{ new Date(r.createdAt).toLocaleString() }}</span>
        </li>
      </ul>
      <p v-else class="butler-files__empty">暂无有效下载记录</p>

      <template v-if="expiredRecords.length">
        <h4 class="butler-files__subtitle">已过期</h4>
        <ul class="butler-files__list butler-files__list--expired">
          <li
            v-for="r in expiredRecords"
            :key="`exp-${r.id}`"
            class="butler-files__item butler-files__item--expired"
          >
            <span class="butler-files__name">{{ r.displayName }}</span>
            <span class="butler-files__meta">已过期</span>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>

<style scoped>
.butler-files {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 10px 12px 12px;
  max-height: min(38vh, 280px);
  overflow-y: auto;
  flex-shrink: 0;
}

.butler-files__block + .butler-files__block {
  margin-top: 12px;
}

.butler-files__title {
  margin: 0 0 4px;
  font-size: 0.78rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
  display: flex;
  align-items: center;
  gap: 6px;
}

.butler-files__count {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(129, 140, 248, 0.35);
  color: #e0e7ff;
}

.butler-files__subtitle {
  margin: 10px 0 4px;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.55);
}

.butler-files__hint,
.butler-files__member-hint,
.butler-files__empty {
  margin: 0 0 8px;
  font-size: 0.7rem;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.55);
}

.butler-files__member-hint--ok {
  color: rgba(134, 239, 172, 0.85);
}

.butler-files__link {
  padding: 0;
  border: none;
  background: none;
  color: #a5b4fc;
  text-decoration: underline;
  cursor: pointer;
  font: inherit;
}

.butler-files__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.butler-files__item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 6px 8px;
  align-items: center;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  font-size: 0.72rem;
}

.butler-files__item--history {
  grid-template-columns: 1fr auto;
}

.butler-files__item--expired {
  opacity: 0.55;
}

.butler-files__kind {
  font-size: 0.65rem;
  color: #a5b4fc;
  white-space: nowrap;
}

.butler-files__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(255, 255, 255, 0.9);
}

.butler-files__name--link {
  padding: 0;
  border: none;
  background: none;
  text-align: left;
  cursor: pointer;
  font: inherit;
  color: #c7d2fe;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.butler-files__meta {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.45);
  white-space: nowrap;
}

.butler-files__btn {
  font-size: 0.65rem;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: rgba(255, 255, 255, 0.75);
  cursor: pointer;
}

.butler-files__btn--ghost:hover {
  border-color: rgba(248, 113, 113, 0.45);
  color: #fca5a5;
}

:global(.butler-panel--light) .butler-files {
  border-top-color: rgba(15, 23, 42, 0.1);
}

:global(.butler-panel--light) .butler-files__title {
  color: #0f172a;
}

:global(.butler-panel--light) .butler-files__hint,
:global(.butler-panel--light) .butler-files__member-hint,
:global(.butler-panel--light) .butler-files__empty {
  color: #64748b;
}

:global(.butler-panel--light) .butler-files__item {
  background: rgba(15, 23, 42, 0.04);
}

:global(.butler-panel--light) .butler-files__name {
  color: #1e293b;
}

:global(.butler-panel--light) .butler-files__name--link {
  color: #4338ca;
}
</style>

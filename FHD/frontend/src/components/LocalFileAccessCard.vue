<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { appAlert, appConfirm } from '@/utils/appDialog'
import localFileAccessApi, {
  type FullDiskAccessStatus,
  type LocalFileGrant,
} from '@/api/localFileAccess'

const desktopAvailable = computed(() => Boolean(window.xcagiDesktop?.chooseDirectory))
const grants = ref<LocalFileGrant[]>([])
const fullDisk = ref<FullDiskAccessStatus>('unknown')
const loading = ref(false)
const busy = ref<number | null>(null)
const error = ref('')
let timer: number | undefined

const activeGrants = computed(() => grants.value.filter((grant) => grant.is_active))
const scanning = computed(() =>
  activeGrants.value.some((grant) => ['queued', 'scanning'].includes(String(grant.scan_status))),
)

const fullDiskLabel = computed(() => {
  if (fullDisk.value === 'granted') return '已开启'
  if (fullDisk.value === 'denied') return '未开启'
  if (fullDisk.value === 'not_required') return '当前系统无需该权限'
  return '未知（可尝试开启）'
})

function modeLabel(grant: LocalFileGrant): string {
  return grant.mode === 'full_disk' ? '整机模式' : '目录授权'
}

function statusLabel(grant: LocalFileGrant): string {
  const status = String(grant.scan_status || '')
  if (status === 'scanning' || status === 'queued') return '同步中'
  if (status === 'error') return '同步失败'
  if (status === 'revoked') return '已撤销'
  if (status === 'ready') return '已同步'
  return '待同步'
}

async function refresh(): Promise<void> {
  if (!desktopAvailable.value) return
  try {
    const data = await localFileAccessApi.status()
    grants.value = Array.isArray(data.grants) ? data.grants : []
    fullDisk.value = data.full_disk_access || 'unknown'
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '本机文件服务暂时不可用'
  }
  schedulePoll()
}

function schedulePoll(): void {
  if (timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
  if (!scanning.value) return
  timer = window.setTimeout(() => void refresh(), 2000)
}

async function authorizeFolder(): Promise<void> {
  if (!desktopAvailable.value || busy.value !== null) return
  try {
    const picked = await window.xcagiDesktop?.chooseDirectory?.()
    if (!picked || picked.canceled || !picked.paths?.length) return
    for (const path of picked.paths) {
      loading.value = true
      await localFileAccessApi.createGrant('folder', path)
    }
    await appAlert('已授权，AI 正在读取该文件夹并写入知识库')
  } catch (cause) {
    await appAlert(cause instanceof Error ? cause.message : '授权失败')
  } finally {
    loading.value = false
    await refresh()
  }
}

async function enableFullDisk(): Promise<void> {
  if (!desktopAvailable.value || busy.value !== null) return
  if (fullDisk.value === 'denied') {
    await window.xcagiDesktop?.openPrivacySettings?.()
    await appAlert('请在系统设置的「完全磁盘访问权限」中勾选本应用，然后回来重试')
    return
  }
  const confirmed = await appConfirm(
    '整机模式会读取主目录和外接卷中的文档（敏感目录与凭证文件自动跳过），确定开启吗？',
  )
  if (!confirmed) return
  try {
    loading.value = true
    await localFileAccessApi.createGrant('full_disk', '~')
    await appAlert('整机模式已开启，AI 正在建立知识库索引')
  } catch (cause) {
    await appAlert(cause instanceof Error ? cause.message : '开启失败')
  } finally {
    loading.value = false
    await refresh()
  }
}

async function syncGrant(grant: LocalFileGrant): Promise<void> {
  if (busy.value !== null) return
  busy.value = grant.id
  try {
    await localFileAccessApi.syncGrant(grant.id)
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '同步失败'
  } finally {
    busy.value = null
  }
}

async function revokeGrant(grant: LocalFileGrant): Promise<void> {
  if (busy.value !== null) return
  const confirmed = await appConfirm(`撤销后 AI 将不再读取「${grant.display_name || grant.root_path}」，并清除已入库内容。确定撤销吗？`)
  if (!confirmed) return
  busy.value = grant.id
  try {
    await localFileAccessApi.revokeGrant(grant.id)
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '撤销失败'
  } finally {
    busy.value = null
  }
}

onMounted(() => {
  void refresh()
})
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer)
})
</script>

<template>
  <section>
    <header class="local-file-header">
      <h2>本机文件（只读）</h2>
      <span class="local-file-badge" :data-on="activeGrants.length > 0">
        {{ activeGrants.length > 0 ? `已授权 ${activeGrants.length} 处` : '未授权' }}
      </span>
    </header>
    <p class="muted local-file-note">
      授权后 AI 只读取你选定的文件夹（或整机模式下的主目录/外接卷）中的文档，并持续写入知识库；
      不会修改、移动或删除原文件。敏感目录与凭证文件（.ssh、Keychains、浏览器 Cookie 等）始终跳过。
    </p>

    <p v-if="!desktopAvailable" class="muted">本机文件读取仅桌面端可用。</p>
    <p v-else-if="error" class="local-file-alert" role="alert">{{ error }}</p>

    <template v-if="desktopAvailable">
      <div class="local-file-actions">
        <button class="btn btn-primary" type="button" :disabled="loading || busy !== null" @click="authorizeFolder">
          选择文件夹授权
        </button>
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="loading || busy !== null || fullDisk === 'not_required'"
          @click="enableFullDisk"
        >
          {{ fullDisk === 'denied' ? '去系统设置开启整机权限' : '开启整机模式' }}
        </button>
        <span class="local-file-fda">完全磁盘访问：{{ fullDiskLabel }}</span>
      </div>

      <p v-if="loading" class="muted">正在处理…</p>
      <p v-else-if="!activeGrants.length" class="muted">还没有授权任何目录。</p>
      <ul v-else class="local-file-list">
        <li v-for="grant in activeGrants" :key="grant.id" class="local-file-item">
          <div class="local-file-item-main">
            <div class="local-file-item-title">
              <strong>{{ grant.display_name || grant.root_path }}</strong>
              <span class="local-file-mode">{{ modeLabel(grant) }}</span>
              <span class="local-file-status" :data-status="grant.scan_status">{{ statusLabel(grant) }}</span>
            </div>
            <div class="local-file-path" :title="grant.root_path">{{ grant.root_path }}</div>
            <div class="muted local-file-meta">
              已索引 {{ grant.indexed_count || 0 }} · 跳过 {{ grant.skipped_count || 0 }} ·
              失败 {{ grant.error_count || 0 }}
              <template v-if="grant.last_scan_at"> · 最后同步 {{ grant.last_scan_at }}</template>
            </div>
            <div v-if="grant.scan_error" class="local-file-alert">{{ grant.scan_error }}</div>
          </div>
          <div class="local-file-item-actions">
            <button class="btn btn-secondary btn-sm" type="button" :disabled="busy !== null" @click="syncGrant(grant)">
              {{ busy === grant.id ? '处理中…' : '立即同步' }}
            </button>
            <button class="btn btn-secondary btn-sm is-danger" type="button" :disabled="busy !== null" @click="revokeGrant(grant)">
              撤销
            </button>
          </div>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.local-file-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.local-file-header h2 { margin: 0; font-size: 15px; font-weight: 600; }
.local-file-badge { padding: 2px 10px; border-radius: 999px; background: #eef1f6; color: #5b6472; font-size: 12px; font-weight: 600; }
.local-file-badge[data-on='true'] { background: #e7f6ec; color: #157f3b; }
.local-file-note { margin: 0 0 12px; font-size: 13px; line-height: 1.6; }
.local-file-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.local-file-fda { color: #667085; font-size: 12px; }
.local-file-alert { margin: 8px 0; padding: 8px 12px; border-radius: 8px; background: #fdeceb; color: #b42318; font-size: 13px; }
.local-file-list { margin: 0; padding: 0; list-style: none; }
.local-file-item { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px 0; border-block-start: 1px solid var(--xc-color-border); }
.local-file-item-main { min-width: 0; flex: 1 1 320px; }
.local-file-item-title { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.local-file-mode { padding: 1px 8px; border-radius: 999px; background: #e8f1fd; color: #1a63bd; font-size: 12px; }
.local-file-status { padding: 1px 8px; border-radius: 999px; background: #eef1f6; color: #5b6472; font-size: 12px; }
.local-file-status[data-status='ready'] { background: #e7f6ec; color: #157f3b; }
.local-file-status[data-status='error'] { background: #fdeceb; color: #b42318; }
.local-file-status[data-status='scanning'], .local-file-status[data-status='queued'] { background: #fdf3e2; color: #a15c07; }
.local-file-path { margin: 6px 0 4px; color: #475467; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }
.local-file-meta { font-size: 12px; }
.local-file-item-actions { display: flex; gap: 8px; }
.local-file-item-actions .is-danger { color: #b42318; border-color: #f3c7c3; }
</style>

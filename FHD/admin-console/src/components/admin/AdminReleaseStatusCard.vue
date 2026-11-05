<template>
  <div class="admin-card admin-card--release">
    <div class="card-header">
      <i class="fa fa-cloud-upload card-icon" aria-hidden="true"></i>
      <h3>软件版本与更新包</h3>
      <span class="status-badge" :class="`badge-${status.kind}`">{{ status.text }}</span>
    </div>
    <dl class="card-info">
      <dt>管理端版本</dt><dd>{{ deployStatus?.admin_local?.version || localVersion || '—' }}</dd>
      <dt>管理端 Git</dt><dd class="mono small">{{ shortSha(deployStatus?.admin_local?.git_sha) }}</dd>
      <dt>update 站版本</dt><dd>{{ deployStatus?.update_hub?.version || '—' }}</dd>
      <dt>update 站 Git</dt><dd class="mono small">{{ shortSha(deployStatus?.update_hub?.git_sha) }}</dd>
      <dt>企业端</dt><dd>{{ enterpriseText }}</dd>
      <dt>本构建安装回执</dt>
      <dd>
        <template v-if="receiptSummary">
          {{ receiptSummary.installed_devices }} 台报告已安装
          <span v-if="receiptSummary.failed_devices"> · {{ receiptSummary.failed_devices }} 台异常</span>
        </template>
        <span v-else>{{ loading ? '检测中' : error && deployStatus ? '读取失败' : '未检测' }}</span>
      </dd>
    </dl>
    <p class="release-hint" :class="`is-${status.kind}`">{{ status.hint }}</p>
    <div v-if="receipts.length" class="install-receipts" aria-label="最近安装回执">
      <div v-for="receipt in receipts.slice(0, 6)" :key="receipt.id || `${receipt.installation_id}:${receipt.reported_at}`">
        <span :class="['receipt-dot', `is-${receipt.status || 'unknown'}`]"></span>
        <div>
          <strong>客户 #{{ receipt.user_id || '—' }} · {{ receipt.platform || 'unknown' }}</strong>
          <small>{{ shortSha(receipt.installation_id) }} · {{ receipt.installed_version || '版本未知' }} · {{ receiptTime(receipt.reported_at) }}</small>
          <small v-if="receipt.error" class="receipt-error">{{ receipt.error }}</small>
        </div>
        <b>{{ receipt.status === 'installed' ? '已安装' : receipt.status === 'rolled_back' ? '已回滚' : '失败' }}</b>
      </div>
    </div>
    <div class="card-actions">
      <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">
        {{ loading ? '检测中...' : '检测版本' }}
      </button>
      <button class="btn btn-primary btn-sm" @click="$emit('open-deploy')">推送更新安装包</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

defineProps({ localVersion: { type: String, default: '' } })
defineEmits(['open-deploy'])

const deployStatus = ref(null)
const loading = ref(false)
const error = ref('')
const receiptSummary = ref(null)
const receipts = ref([])

const enterpriseText = computed(() => {
  if (!deployStatus.value) return loading.value ? '检测中' : error.value ? '检测失败' : '未检测'
  const reachable = deployStatus.value.enterprise?.reachable
  return reachable === true ? '在线' : reachable === false ? '不可达' : '未知'
})

const status = computed(() => {
  if (loading.value) return { text: '检测中', kind: 'dim', hint: '正在检测软件版本和安装回执。' }
  if (error.value) return { text: '异常', kind: 'error', hint: error.value }
  if (deployStatus.value?.update_hub?.reachable === false) return { text: '未连通', kind: 'error', hint: 'update 站不可达，请检查连接配置。' }
  if (deployStatus.value && [undefined, null, '', 'local'].includes(deployStatus.value.update_hub?.git_sha)) return { text: '未知', kind: 'dim', hint: 'update 站构建身份未知，无法统计本构建安装回执。' }
  const flags = deployStatus.value?.flags || {}
  const version = deployStatus.value?.admin_local?.version || deployStatus.value?.update_hub?.version || ''
  const { failed_devices: failed, installed_devices: installed } = receiptSummary.value || {}
  if (failed) return { text: '有异常', kind: 'error', hint: `有 ${failed} 台客户端安装失败或已回滚，请查看回执后再重新推送。` }
  if (installed) return { text: `已安装 ${installed}`, kind: 'ok', hint: `已收到 ${installed} 台客户电脑的稳定启动回执，不再把进入 update 站当成完成安装。` }
  if (flags.needs_pack) return { text: '待推送', kind: 'warn', hint: `本地 ${version || '当前版本'} 尚未打包，推送时会先生成更新包。` }
  if (flags.needs_push) return { text: '待推送', kind: 'warn', hint: `本地 ${version || '当前版本'} 比 update 站新，需要推送更新安装包。` }
  if (flags.enterprise_pending) return { text: '已推送', kind: 'info', hint: `新版本 ${version} 仅已进入 update 中转站，尚未收到客户电脑安装回执。` }
  if (flags.up_to_date) return { text: '最新', kind: 'ok', hint: `管理端与 update 站已同步${version ? `（${version}）` : ''}。` }
  return { text: deployStatus.value ? '未知' : '待检测', kind: 'dim', hint: '点击检测版本，确认本地、update 站和企业端的软件版本。' }
})

function shortSha(value) {
  const text = String(value || '').trim()
  return text ? (text.length > 12 ? text.slice(0, 12) : text) : '—'
}

function receiptTime(value) {
  const date = new Date(String(value || ''))
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN', { hour12: false })
}

function emitStatus() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('xcagi:admin-deploy-updated', {
    detail: {
      text: status.value.text,
      version: deployStatus.value?.update_hub?.version || deployStatus.value?.admin_local?.version || '',
      flags: deployStatus.value?.flags || {},
    },
  }))
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  deployStatus.value = receiptSummary.value = null
  receipts.value = []
  try {
    const result = await xcmaxAdminApi.checkDeployUpdates('stable')
    const data = result?.data && typeof result.data === 'object' && !Array.isArray(result.data) ? result.data : null
    if (!data) throw new Error(result?.message || '版本检测失败')
    deployStatus.value = data
    const target = String(data.update_hub?.git_sha || '').trim()
    if (!target || target === 'local') return
    const report = await xcmaxAdminApi.listUpdateInstallReceipts(target)
    if (!Array.isArray(report?.items) || !['installed_devices', 'failed_devices'].every(
      key => Number.isInteger(report?.summary?.[key]) && report.summary[key] >= 0,
    )) {
      throw new Error('安装回执数据不完整')
    }
    receiptSummary.value = report.summary
    receipts.value = report.items
  } catch (cause) {
    error.value = `${deployStatus.value ? '安装回执读取失败' : '版本检测失败'}：${cause instanceof Error ? cause.message : String(cause || '未知错误')}`
  } finally {
    loading.value = false
    emitStatus()
  }
}

defineExpose({ refresh })
</script>

<style scoped>
.card-header { display: flex; align-items: center; gap: 10px; }
.card-header h3 { margin: 0; color: #172033; font-size: 15px; font-weight: 700; flex: 1; }
.card-icon { width: 22px; color: #1890ff; font-size: 18px; text-align: center; }
.card-info { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; margin: 0; font-size: 13px; }
.card-info dt { color: rgba(23, 32, 51, .55); font-weight: 600; white-space: nowrap; }
.card-info dd { margin: 0; color: #172033; word-break: break-all; }
.card-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.status-badge { display: inline-flex; padding: 2px 10px; border-radius: 20px; font-size: 11px; }
.badge-ok { background: #d1fae5; color: #047857; }
.badge-error { background: #fee2e2; color: #b91c1c; }
.badge-warn { background: #fef3c7; color: #b45309; }
.badge-info { background: #dbeafe; color: #1d4ed8; }
.badge-dim { background: #e2e8f0; color: #475569; }
.release-hint { margin: 0; padding: 9px 11px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; color: #475569; font-size: 12px; line-height: 1.5; }
.release-hint.is-ok { border-color: #bbf7d0; background: #ecfdf5; color: #047857; }
.release-hint.is-warn { border-color: #fde68a; background: #fffbeb; color: #b45309; }
.release-hint.is-info { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.release-hint.is-error { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.install-receipts { display: grid; gap: 7px; }
.install-receipts > div { display: grid; grid-template-columns: 9px minmax(0, 1fr) auto; gap: 8px; align-items: start; padding: 8px 9px; border: 1px solid rgba(24, 144, 255, .13); border-radius: 9px; background: rgba(239, 246, 255, .58); }
.install-receipts strong, .install-receipts small { display: block; }
.install-receipts strong { color: #172033; font-size: 12px; }
.install-receipts small { margin-top: 2px; color: #64748b; font-size: 10px; line-height: 1.4; word-break: break-all; }
.install-receipts b { color: #0f5fb8; font-size: 10px; white-space: nowrap; }
.receipt-dot { width: 8px; height: 8px; margin-top: 4px; border-radius: 50%; background: #94a3b8; }
.receipt-dot.is-installed { background: #16a34a; }
.receipt-dot.is-failed, .receipt-dot.is-rolled_back { background: #dc2626; }
.receipt-error { color: #b91c1c !important; }
</style>

<template>
  <div class="mobile-pairing">
    <p class="mobile-pairing__lead">
      {{ $t('settings.mobilePairingLead') }}
    </p>

    <div class="mobile-pairing__status" :class="`mobile-pairing__status--${connectionTone}`">
      <span class="mobile-pairing__status-dot" aria-hidden="true"></span>
      <span>{{ connectionStatusText }}</span>
    </div>

    <div class="mobile-pairing__panel">
      <div class="mobile-pairing__qr-wrap" aria-live="polite">
        <div v-if="loading" class="mobile-pairing__qr-state">
          <i class="fa fa-spinner fa-spin" aria-hidden="true"></i>
          <span>{{ $t('settings.mobilePairingGenerating') }}</span>
        </div>
        <img v-else-if="qrDataUrl" :src="qrDataUrl" :alt="$t('settings.mobilePairingQrAlt')" class="mobile-pairing__qr" />
        <div v-else class="mobile-pairing__qr-state mobile-pairing__qr-state--error">
          <span>{{ errorMessage || $t('settings.mobilePairingUnavailable') }}</span>
        </div>
      </div>

      <div class="mobile-pairing__meta">
        <!-- 大号设备码展示，优先使用服务器中继码。 -->
        <div v-if="pairingShortCode" class="mobile-pairing__code-block">
          <span class="mobile-pairing__code-label">{{ $t('settings.mobilePairingDeviceCode') }}</span>
          <span class="mobile-pairing__code-value">{{ pairingShortCode }}</span>
          <button
            type="button"
            class="mobile-pairing__copy-code"
            :class="{ 'mobile-pairing__copy-code--copied': copied }"
            :title="$t('settings.mobilePairingCopyCode')"
            @click="copyCode"
          >
            <i class="fa" :class="copied ? 'fa-check' : 'fa-copy'" aria-hidden="true"></i>
          </button>
          <Transition name="toast">
            <span v-if="copied" class="mobile-pairing__copy-toast">{{ $t('settings.mobilePairingCopied') }}</span>
          </Transition>
        </div>

        <!-- 倒计时 + 刷新（保留） -->
        <p v-if="countdown > 0" class="mobile-pairing__countdown">
          {{ $t('settings.mobilePairingExpiresIn', { seconds: countdown }) }}
        </p>
        <p v-else-if="!loading && qrDataUrl" class="mobile-pairing__countdown mobile-pairing__countdown--warn">
          {{ $t('settings.mobilePairingExpired') }}
        </p>
        <button type="button" class="mobile-pairing__refresh" :disabled="loading" @click="refreshQr">
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          {{ $t('settings.mobilePairingRefresh') }}
        </button>
      </div>
    </div>

    <ul class="mobile-pairing__tips">
      <li>{{ $t('settings.mobilePairingTipRelay') }}</li>
      <li>{{ $t('settings.mobilePairingTipScan') }}</li>
      <li>{{ $t('settings.mobilePairingTipLogin') }}</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import QRCode from 'qrcode'
import {
  applyDevProxyReachablePort,
  buildPairingQrText,
  fetchHostDiscoverHint,
  issueMobilePairing,
  loadDesktopPairingPayload,
  resolvePairingHost,
  resolveReachablePairingPort,
  type PairingPayload,
} from '@/api/mobilePairing'
import { apiFetch } from '@/utils/apiBase'

const { t } = useI18n()

const loading = ref(false)
const qrDataUrl = ref('')
const errorMessage = ref('')
const pairingHost = ref('')
const pairingPort = ref(0)
const pairingNonce = ref('')
const pairingShortCode = ref('') // v2: 6位配对码
const copied = ref(false) // 复制反馈状态
const expiresAt = ref(0)
const nowSec = ref(Math.floor(Date.now() / 1000))

let countdownTimer: ReturnType<typeof setInterval> | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const countdown = computed(() => Math.max(0, expiresAt.value - nowSec.value))

/**
 * 绑定/中继状态：与手机端「我的 → 服务」的 server_mode_label 用同一套词汇（服务器中继 / 已绑定），
 * 避免用户在电脑上只能看到出码，猜不到手机到底连没连上。
 */
const pairingStatusPaired = ref(false)
const pairingStatusMobileUsername = ref('')
const pairingStatusLastSyncAt = ref(0) // unix 秒
const pairingStatusLoaded = ref(false)
let statusPollTimer: ReturnType<typeof setInterval> | null = null

const STALE_SYNC_SEC = 5 * 60 // 超过 5 分钟没同步过，视为中继可能不通

const connectionTone = computed<'connected' | 'stale' | 'pending'>(() => {
  if (!pairingStatusPaired.value) return 'pending'
  if (!pairingStatusLastSyncAt.value) return 'stale'
  const age = nowSec.value - pairingStatusLastSyncAt.value
  return age <= STALE_SYNC_SEC ? 'connected' : 'stale'
})

const connectionStatusText = computed(() => {
  if (!pairingStatusLoaded.value) return '正在查询连接状态…'
  if (!pairingStatusPaired.value) return '尚未绑定手机，扫码或输入下方设备码即可连接'
  const who = pairingStatusMobileUsername.value ? `已连接：${pairingStatusMobileUsername.value} 的手机` : '已连接手机'
  return connectionTone.value === 'connected' ? `${who} · 服务器中继正常` : `${who} · 中继暂时不通，请检查网络`
})

async function refreshPairingStatus() {
  try {
    const res = await apiFetch('/api/desktop/mobile-pairing-status')
    if (!res.ok) return
    const data = (await res.json()) as {
      paired?: boolean
      mobileUsername?: string
      lastRelaySyncAt?: number
    }
    pairingStatusPaired.value = Boolean(data.paired)
    pairingStatusMobileUsername.value = String(data.mobileUsername || '')
    pairingStatusLastSyncAt.value = Number(data.lastRelaySyncAt || 0)
  } catch {
    // 状态查询失败不影响二维码本身的展示
  } finally {
    pairingStatusLoaded.value = true
  }
}

function pairingDisplayCode(payload: PairingPayload): string {
  const qrJson = payload.qr_json || {}
  const qrKind = String(qrJson.kind || '')
  if (qrKind === 'xcagi_relay_pairing') {
    return String(qrJson.code || qrJson.t || payload.shortCode || '').trim()
  }
  const relay = payload.relay || {}
  return String(relay.pairing_code || payload.shortCode || '').trim()
}

function clearTimers() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleAutoRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer)
  const ms = Math.max(5_000, (expiresAt.value - nowSec.value - 15) * 1000)
  refreshTimer = setTimeout(() => {
    void refreshQr()
  }, ms)
}

async function renderPayload(payload: PairingPayload) {
  pairingHost.value = payload.host
  pairingPort.value = payload.port
  pairingNonce.value = payload.nonce
  pairingShortCode.value = pairingDisplayCode(payload)
  expiresAt.value = Number(payload.exp || 0)
  qrDataUrl.value = await QRCode.toDataURL(buildPairingQrText(payload), {
    width: 220,
    margin: 1,
    errorCorrectionLevel: 'M',
  })
  errorMessage.value = ''
  scheduleAutoRefresh()
}

/** 复制配对码到剪贴板 */
async function copyCode() {
  try {
    await navigator.clipboard.writeText(pairingShortCode.value || pairingNonce.value)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = pairingShortCode.value || pairingNonce.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 1500)
}

async function refreshQr() {
  loading.value = true
  errorMessage.value = ''
  try {
    const desktopPayload = await loadDesktopPairingPayload()
    if (desktopPayload) {
      await renderPayload(desktopPayload)
      return
    }

    const hint = await fetchHostDiscoverHint()
    const port = resolveReachablePairingPort(Number(hint.api_port || 0))
    const host = resolvePairingHost()
    const payload = applyDevProxyReachablePort(await issueMobilePairing(host, port))
    await renderPayload(payload)
  } catch (error: unknown) {
    qrDataUrl.value = ''
    errorMessage.value = error instanceof Error ? error.message : t('settings.mobilePairingGenerateFailed')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  countdownTimer = setInterval(() => {
    nowSec.value = Math.floor(Date.now() / 1000)
  }, 1000)
  void refreshQr()
  void refreshPairingStatus()
  statusPollTimer = setInterval(() => {
    void refreshPairingStatus()
  }, 15_000)
})

onBeforeUnmount(() => {
  clearTimers()
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
})
</script>

<style scoped>
.mobile-pairing {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.mobile-pairing__lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #475569;
}

.mobile-pairing__status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}

.mobile-pairing__status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.mobile-pairing__status--connected {
  color: #047857;
  background: #d1fae5;
}
.mobile-pairing__status--connected .mobile-pairing__status-dot {
  background: #10b981;
}

.mobile-pairing__status--stale {
  color: #b45309;
  background: #fef3c7;
}
.mobile-pairing__status--stale .mobile-pairing__status-dot {
  background: #f59e0b;
}

.mobile-pairing__status--pending {
  color: #475569;
  background: #e2e8f0;
}
.mobile-pairing__status--pending .mobile-pairing__status-dot {
  background: #94a3b8;
}

.mobile-pairing__panel {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: center;
  padding: 16px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.mobile-pairing__qr-wrap {
  width: 220px;
  height: 220px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #dbeafe;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.mobile-pairing__qr {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.mobile-pairing__qr-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: #64748b;
}

.mobile-pairing__qr-state--error {
  color: #b91c1c;
}

.mobile-pairing__meta {
  flex: 1 1 220px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* v2: 配对码大号展示 */
.mobile-pairing__code-block {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  background: linear-gradient(135deg, #eff6ff, #f0f9ff);
  border: 1px solid #bfdbfe;
  position: relative;
}

.mobile-pairing__code-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.mobile-pairing__code-value {
  font-size: 32px;
  font-weight: 700;
  color: #1d4ed8;
  letter-spacing: 6px;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.mobile-pairing__copy-code {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #93c5fd;
  color: #3b82f6;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
  flex-shrink: 0;
}

.mobile-pairing__copy-code:hover,
.mobile-pairing__copy-code--copied {
  background: #3b82f6;
  color: #fff;
  border-color: #3b82f6;
}

/* 复制成功 toast */
.mobile-pairing__copy-toast {
  position: absolute;
  top: -10px;
  right: 0;
  padding: 4px 10px;
  border-radius: 6px;
  background: #1d4ed8;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  pointer-events: none;
  animation: toast-in 0.2s ease-out;
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.toast-enter-active {
  transition: all 0.2s ease-out;
}
.toast-leave-active {
  transition: all 0.15s ease-in;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.toast-leave-to {
  opacity: 0;
}

.mobile-pairing__endpoint,
.mobile-pairing__countdown {
  margin: 0;
  font-size: 13px;
  color: #334155;
}

.mobile-pairing__countdown--warn {
  color: #b45309;
}

.mobile-pairing__endpoint code,
.mobile-pairing__tips code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.mobile-pairing__refresh {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #fff;
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.mobile-pairing__refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.mobile-pairing__tips {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

@media (max-width: 720px) {
  .mobile-pairing__panel {
    flex-direction: column;
    align-items: stretch;
  }

  .mobile-pairing__qr-wrap {
    margin: 0 auto;
  }
}
</style>

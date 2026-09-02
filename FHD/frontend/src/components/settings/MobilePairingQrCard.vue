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

<style scoped src="./MobilePairingQrCard.css"></style>

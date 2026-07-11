<template>
  <div class="mobile-pairing">
    <p class="mobile-pairing__lead">
      <template v-if="allowManagement">
        选择手机用途后再扫码。两种二维码权限隔离，普通企业配对不会获得管理权限。
      </template>
      <template v-else>
        使用 XCAGI 企业端 App 扫描下方二维码，与本机安全连接。
      </template>
    </p>

    <div
      v-if="allowManagement"
      class="mobile-pairing__mode"
      role="tablist"
      aria-label="手机配对用途"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="pairingPurpose === 'enterprise'"
        :class="{ 'mobile-pairing__mode-button--active': pairingPurpose === 'enterprise' }"
        :disabled="loading"
        class="mobile-pairing__mode-button"
        @click="selectPurpose('enterprise')"
      >
        企业端手机
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="pairingPurpose === 'management'"
        :class="{ 'mobile-pairing__mode-button--active': pairingPurpose === 'management' }"
        :disabled="loading"
        class="mobile-pairing__mode-button"
        @click="selectPurpose('management')"
      >
        管理端手机
      </button>
    </div>
    <p
      v-if="allowManagement && pairingPurpose === 'management'"
      class="mobile-pairing__management-warning"
      role="alert"
    >
      此二维码可处理员工决策、验收、停止和改派，仅供管理者本人设备使用。
    </p>

    <div class="mobile-pairing__panel">
      <div class="mobile-pairing__qr-wrap" aria-live="polite">
        <div v-if="loading" class="mobile-pairing__qr-state">
          <i class="fa fa-spinner fa-spin" aria-hidden="true"></i>
          <span>正在生成二维码…</span>
        </div>
        <img
          v-else-if="qrDataUrl"
          :src="qrDataUrl"
          :alt="pairingPurpose === 'management' ? '管理端手机配对二维码' : '企业端手机配对二维码'"
          class="mobile-pairing__qr"
        >
        <div v-else class="mobile-pairing__qr-state mobile-pairing__qr-state--error">
          <span>{{ errorMessage || '无法生成二维码' }}</span>
        </div>
      </div>

      <div class="mobile-pairing__meta">
        <!-- 大号设备码展示，优先使用服务器中继码。 -->
        <div v-if="pairingShortCode" class="mobile-pairing__code-block">
          <span class="mobile-pairing__code-label">
            {{ pairingPurpose === 'management' ? '管理码' : '设备码' }}
          </span>
          <span class="mobile-pairing__code-value">{{ pairingShortCode }}</span>
          <button
            type="button"
            class="mobile-pairing__copy-code"
            :class="{ 'mobile-pairing__copy-code--copied': copied }"
            :title="'复制设备码'"
            @click="copyCode"
          >
            <i class="fa" :class="copied ? 'fa-check' : 'fa-copy'" aria-hidden="true"></i>
          </button>
          <Transition name="toast">
            <span v-if="copied" class="mobile-pairing__copy-toast">已复制</span>
          </Transition>
        </div>

        <!-- 倒计时 + 刷新（保留） -->
        <p v-if="countdown > 0" class="mobile-pairing__countdown">
          {{ countdown }} 秒后过期
        </p>
        <p v-else-if="!loading && qrDataUrl" class="mobile-pairing__countdown mobile-pairing__countdown--warn">
          二维码已过期，请刷新
        </p>
        <button
          type="button"
          class="mobile-pairing__refresh"
          :disabled="loading"
          @click="refreshQr"
        >
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          刷新二维码
        </button>
      </div>
    </div>

    <ul class="mobile-pairing__tips">
      <li v-if="pairingPurpose === 'enterprise' && allowManagement">企业端二维码只授予业务与超级员工使用权限，不含管理权限。</li>
      <li v-else-if="pairingPurpose === 'enterprise'">企业端二维码用于业务与超级员工协作。</li>
      <li v-else>管理端任务依赖本机真实台账，请保持手机与电脑处于同一可信局域网。</li>
      <li>扫描二维码或输入上方 6 位设备码即可连接。</li>
      <li>登录确认请使用 App 扫描登录页的「App 扫码登录」二维码（非本设备码）。</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import QRCode from 'qrcode';
import {
  applyDevProxyReachablePort,
  buildPairingQrText,
  fetchHostDiscoverHint,
  issueMobilePairing,
  loadDesktopPairingPayload,
  resolvePairingHost,
  resolveReachablePairingPort,
  type PairingPayload,
  type PairingPurpose,
} from '@/api/mobilePairing';

const props = withDefaults(defineProps<{
  allowManagement?: boolean;
}>(), {
  allowManagement: false,
});

const loading = ref(false);
const qrDataUrl = ref('');
const errorMessage = ref('');
const pairingHost = ref('');
const pairingPort = ref(0);
const pairingNonce = ref('');
const pairingShortCode = ref(''); // v2: 6位配对码
const copied = ref(false); // 复制反馈状态
const expiresAt = ref(0);
const nowSec = ref(Math.floor(Date.now() / 1000));
const pairingPurpose = ref<PairingPurpose>('enterprise');

let countdownTimer: ReturnType<typeof setInterval> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

const countdown = computed(() => Math.max(0, expiresAt.value - nowSec.value));

function pairingDisplayCode(payload: PairingPayload): string {
  const qrJson = payload.qr_json || {};
  const qrKind = String(qrJson.kind || '');
  if (qrKind === 'xcagi_relay_pairing') {
    return String(qrJson.code || qrJson.t || payload.shortCode || '').trim();
  }
  const relay = payload.relay || {};
  return String(relay.pairing_code || payload.shortCode || '').trim();
}

function clearTimers() {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
}

function scheduleAutoRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  const ms = Math.max(5_000, (expiresAt.value - nowSec.value - 15) * 1000);
  refreshTimer = setTimeout(() => {
    void refreshQr();
  }, ms);
}

function selectPurpose(purpose: PairingPurpose) {
  if (purpose === 'management' && !props.allowManagement) return;
  if (purpose === pairingPurpose.value || loading.value) return;
  pairingPurpose.value = purpose;
  qrDataUrl.value = '';
  pairingShortCode.value = '';
  expiresAt.value = 0;
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  void refreshQr();
}

async function renderPayload(payload: PairingPayload) {
  pairingHost.value = payload.host;
  pairingPort.value = payload.port;
  pairingNonce.value = payload.nonce;
  pairingShortCode.value = pairingDisplayCode(payload);
  expiresAt.value = Number(payload.exp || 0);
  qrDataUrl.value = await QRCode.toDataURL(buildPairingQrText(payload), {
    width: 220,
    margin: 1,
    errorCorrectionLevel: 'M',
  });
  errorMessage.value = '';
  scheduleAutoRefresh();
}

/** 复制配对码到剪贴板 */
async function copyCode() {
  try {
    await navigator.clipboard.writeText(pairingShortCode.value || pairingNonce.value);
  } catch {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = pairingShortCode.value || pairingNonce.value;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  copied.value = true;
  setTimeout(() => { copied.value = false; }, 1500);
}

async function refreshQr() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const desktopPayload = await loadDesktopPairingPayload(pairingPurpose.value);
    if (desktopPayload) {
      await renderPayload(desktopPayload);
      return;
    }

    const hint = await fetchHostDiscoverHint();
    const port = resolveReachablePairingPort(Number(hint.api_port || 0));
    const host = resolvePairingHost();
    const payload = applyDevProxyReachablePort(
      await issueMobilePairing(host, port, pairingPurpose.value),
    );
    await renderPayload(payload);
  } catch (error: unknown) {
    qrDataUrl.value = '';
    errorMessage.value = error instanceof Error ? error.message : '生成配对二维码失败';
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  countdownTimer = setInterval(() => {
    nowSec.value = Math.floor(Date.now() / 1000);
  }, 1000);
  void refreshQr();
});

onBeforeUnmount(() => {
  clearTimers();
});
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

.mobile-pairing__mode {
  display: inline-flex;
  align-self: flex-start;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: #e2e8f0;
}

.mobile-pairing__mode-button {
  padding: 8px 14px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.mobile-pairing__mode-button--active {
  background: #fff;
  color: #1d4ed8;
  box-shadow: 0 1px 3px rgb(15 23 42 / 12%);
}

.mobile-pairing__mode-button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.mobile-pairing__management-warning {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid #fdba74;
  border-radius: 10px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.5;
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
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.toast-enter-active { transition: all 0.2s ease-out; }
.toast-leave-active { transition: all 0.15s ease-in; }
.toast-enter-from { opacity: 0; transform: translateY(4px); }
.toast-leave-to { opacity: 0; }

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

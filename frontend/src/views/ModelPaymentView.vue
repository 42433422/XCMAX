<template>
  <div class="page-view mp-root" id="view-model-payment">
    <div class="page-content">
      <div class="page-header mp-hero">
        <div class="mp-hero-text">
          <h2>模型支付</h2>
          <p class="muted header-sub">
            个人使用：先选一档套餐，再用支付宝扫码付款。通道未接入商户前仅为演示，不会产生真实扣款。
          </p>
        </div>
      </div>

      <div v-if="loadError" class="card mp-panel mp-panel--error">
        <p class="text-error">{{ loadError }}</p>
        <p class="muted">请确认本机后端已启动，并能访问 <code>/api/model-payment/plans</code>。</p>
      </div>

      <div v-else class="card mp-panel mp-status mp-balance">
        <div class="mp-panel-head">
          <span class="mp-panel-icon mp-balance-icon" aria-hidden="true">¥</span>
          <div class="mp-balance-text">
            <div class="card-header mp-panel-title">账户余额</div>
            <p class="muted mp-panel-desc">累计已购买套餐总额，用于查看当前账户的充值情况。</p>
          </div>
          <div class="mp-balance-amount">
            <span class="mp-balance-currency">¥</span>
            <span class="mp-balance-num">{{ formatYuan(balanceCents) }}</span>
            <span class="mp-balance-unit">CNY</span>
          </div>
        </div>
      </div>

      <div v-if="loading" class="mp-loading">
        <span class="mp-loading-dot"></span>
        <span class="mp-loading-dot"></span>
        <span class="mp-loading-dot"></span>
        <span class="muted">正在加载可选套餐…</span>
      </div>
      <section v-else-if="plans.length" class="mp-plans-section">
        <h3 class="mp-section-kicker">个人套餐</h3>
        <p class="mp-section-lead muted">
          先选中卡片；点「支付宝扫码」后由后端下单。若返回 <code>qr_code</code>，下方会自动出现付款二维码。
        </p>
        <div class="mp-plans">
          <article
            v-for="(p, idx) in plans"
            :key="p.id"
            class="mp-plan"
            :class="['mp-plan--t' + (idx % 3), { 'is-selected': selectedId === p.id }]"
            role="button"
            tabindex="0"
            :aria-pressed="selectedId === p.id"
            @click="selectedId = p.id"
            @keydown.enter.prevent="selectedId = p.id"
          >
            <div class="mp-plan-topbar" aria-hidden="true" />
            <div class="mp-plan-head">
              <h3 class="mp-plan-title">{{ p.title }}</h3>
              <div class="mp-plan-head-tags">
                <span v-if="ownedCount(p.id) > 0" class="mp-owned">已购 ×{{ ownedCount(p.id) }}</span>
                <span v-if="p.badge" class="mp-badge">{{ p.badge }}</span>
              </div>
            </div>
            <p class="mp-desc">{{ p.description }}</p>
            <div class="mp-price-block">
              <span class="mp-price-currency">¥</span>
              <span class="mp-price-num">{{ formatYuan(p.amount_cents) }}</span>
              <span class="mp-price-unit">CNY</span>
            </div>
            <div class="mp-actions">
              <button
                type="button"
                class="mp-pay mp-pay--ali mp-pay--full"
                :disabled="checkoutBusy"
                @click.stop="pay(p.id)"
              >
                <span class="mp-pay-ico mp-pay-ico-ali" aria-hidden="true">支</span>
                <span>支付宝扫码</span>
              </button>
            </div>
          </article>
        </div>
      </section>

      <div v-if="checkoutQrSrc" class="card mp-panel mp-qr">
        <div class="card-header mp-panel-title">请用手机扫码支付</div>
        <div class="mp-qr-body">
          <img class="mp-qr-img" :src="checkoutQrSrc" width="220" height="220" alt="支付二维码" />
          <p class="muted mp-qr-hint">请使用支付宝扫一扫；是否支付成功以支付宝或本系统通知为准。</p>
        </div>
      </div>

      <div v-if="payHint" class="card mp-panel mp-result" :class="payHintLevel">
        <div class="mp-result-body">
          <span class="mp-result-ico" aria-hidden="true">{{ payHintLevel === 'mp-result--error' ? '!' : 'i' }}</span>
          <p class="mp-result-text">{{ payHint }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import QRCode from 'qrcode';
import {
  modelPaymentApi,
  type ModelPaymentEntitlement,
  type ModelPaymentPlan,
} from '@/api/modelPayment';
import { ApiError } from '@/api';

const loading = ref(true);
const loadError = ref('');
const plans = ref<ModelPaymentPlan[]>([]);
const entitlements = ref<ModelPaymentEntitlement[]>([]);
const selectedId = ref('');
const checkoutBusy = ref(false);
const payHint = ref('');
const payHintLevel = ref<'mp-result--info' | 'mp-result--error'>('mp-result--info');
const checkoutQrSrc = ref('');

function ownedCount(planId: string): number {
  const hit = entitlements.value.find((e) => e.plan_id === planId);
  return hit ? Number(hit.purchase_count || 0) : 0;
}

const balanceCents = computed<number>(() => {
  if (!entitlements.value.length || !plans.value.length) return 0;
  const priceMap = new Map<string, number>();
  for (const p of plans.value) {
    priceMap.set(p.id, Number(p.amount_cents) || 0);
  }
  return entitlements.value.reduce((sum, e) => {
    const price = priceMap.get(e.plan_id) ?? 0;
    const count = Number(e.purchase_count) || 0;
    return sum + price * count;
  }, 0);
});

async function loadEntitlements() {
  try {
    const res = await modelPaymentApi.getEntitlements();
    entitlements.value = res.success && res.data ? res.data.entitlements || [] : [];
  } catch {
    entitlements.value = [];
  }
}

async function applyQrFromCheckoutData(data: unknown) {
  checkoutQrSrc.value = '';
  if (!data || typeof data !== 'object') return;
  const d = data as Record<string, unknown>;
  const raw = d.qr_code;
  if (typeof raw !== 'string' || !raw.trim()) return;
  try {
    checkoutQrSrc.value = await QRCode.toDataURL(raw.trim(), {
      width: 220,
      margin: 2,
      errorCorrectionLevel: 'M',
    });
  } catch {
    checkoutQrSrc.value = '';
  }
}

function formatYuan(cents: number): string {
  const n = Number(cents);
  if (!Number.isFinite(n)) return '0.00';
  return (n / 100).toFixed(2);
}

async function loadPlans() {
  loading.value = true;
  loadError.value = '';
  try {
    const res = await modelPaymentApi.getPlans();
    if (!res.success || !res.data) {
      loadError.value = res.message || '无法加载套餐';
      return;
    }
    plans.value = res.data.plans || [];
    if (plans.value.length && !selectedId.value) {
      selectedId.value = plans.value[0].id;
    }
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function setPayHint(level: 'mp-result--info' | 'mp-result--error', message: string) {
  payHintLevel.value = level;
  payHint.value = message;
}

async function pay(planId: string) {
  checkoutBusy.value = true;
  payHint.value = '';
  checkoutQrSrc.value = '';
  try {
    const res = await modelPaymentApi.checkout(planId);
    if (res.success && res.data) {
      const d = res.data;
      if (d.redirect_url) {
        window.open(d.redirect_url, '_blank');
        setPayHint('mp-result--info', '已在新标签页打开支付宝收银台，付款完成后本页将显示已购记录。');
        return;
      }
      if (d.qr_code) {
        await applyQrFromCheckoutData(d);
        return;
      }
      if (d.setup_hint) {
        setPayHint('mp-result--info', d.setup_hint);
        return;
      }
      setPayHint('mp-result--info', '已创建订单，但暂未返回可跳转链接或二维码。');
      return;
    }
    setPayHint('mp-result--error', res.message || '下单失败，请稍后重试。');
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e);
    setPayHint('mp-result--error', msg || '下单请求异常，请稍后重试。');
  } finally {
    checkoutBusy.value = false;
  }
  void loadEntitlements();
}

onMounted(() => {
  void loadPlans();
  void loadEntitlements();
});
</script>

<style scoped>
.mp-root .page-content {
  max-width: 1200px;
}

.mp-hero {
  margin-bottom: 8px;
}

.mp-hero-text h2 {
  letter-spacing: -0.02em;
}

.header-sub {
  margin: 0.35rem 0 0;
  max-width: 40rem;
  line-height: 1.55;
  font-size: 0.95rem;
}

.mp-panel {
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  margin-bottom: 1.25rem;
}

.mp-panel--error {
  border-color: rgba(220, 38, 38, 0.2);
  background: linear-gradient(180deg, #fffefe 0%, #fff 100%);
}

.mp-panel-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.mp-panel-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 12px;
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
  color: #475569;
  font-size: 0.85rem;
  flex-shrink: 0;
}

.mp-panel-title {
  margin: 0 0 4px;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.mp-panel-desc {
  margin: 0;
  font-size: 0.875rem;
}

.mp-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.mp-balance .mp-panel-head {
  align-items: center;
  margin-bottom: 0;
  gap: 14px;
}

.mp-balance-text {
  flex: 1 1 auto;
  min-width: 0;
}

.mp-balance-icon {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  color: #1d4ed8;
  font-size: 1.05rem;
  font-weight: 800;
}

.mp-balance-amount {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  flex-shrink: 0;
  padding: 10px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid rgba(59, 130, 246, 0.22);
}

.mp-balance-currency {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1d4ed8;
  align-self: flex-start;
  margin-top: 0.35em;
}

.mp-balance-num {
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.mp-balance-unit {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #64748b;
  text-transform: uppercase;
  margin-left: 4px;
}

@media (max-width: 560px) {
  .mp-balance .mp-panel-head {
    flex-wrap: wrap;
  }
  .mp-balance-amount {
    width: 100%;
    justify-content: flex-end;
  }
}

.mp-pill {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
  font-size: 0.8125rem;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.mp-pill.on {
  background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
  border-color: rgba(5, 150, 105, 0.35);
}

.mp-pill:not(.on) .mp-pill-state {
  color: #94a3b8;
}

.mp-pill.on .mp-pill-state {
  color: #047857;
  font-weight: 700;
}

.mp-pill-label {
  font-weight: 600;
  color: #334155;
}

.mp-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2rem 0;
}

.mp-loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  animation: mp-bounce 1.2s ease-in-out infinite;
}

.mp-loading-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.mp-loading-dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes mp-bounce {
  0%,
  80%,
  100% {
    transform: scale(0.75);
    opacity: 0.45;
  }
  40% {
    transform: scale(1.1);
    opacity: 1;
  }
}

.mp-plans-section {
  margin-top: 0.5rem;
}

.mp-section-kicker {
  margin: 0 0 4px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #64748b;
}

.mp-section-lead {
  margin: 0 0 1.25rem;
  font-size: 0.875rem;
}

.mp-plans {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: 1.25rem;
}

.mp-plan {
  --accent: #059669;
  --accent-2: #10b981;
  --accent-soft: #ecfdf5;
  --ring: rgba(5, 150, 105, 0.35);

  position: relative;
  cursor: pointer;
  text-align: left;
  border-radius: 20px;
  padding: 1.35rem 1.4rem 1.25rem;
  background: linear-gradient(165deg, #ffffff 0%, #f8fafc 55%, #f1f5f9 100%);
  border: 1px solid rgba(15, 23, 42, 0.09);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 32px -12px rgba(15, 23, 42, 0.14);
  transition:
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.22s ease,
    border-color 0.2s ease;
  outline: none;
}

.mp-plan:hover {
  transform: translateY(-3px);
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.06),
    0 20px 40px -16px rgba(15, 23, 42, 0.18);
}

.mp-plan:focus-visible {
  box-shadow:
    0 0 0 3px #fff,
    0 0 0 6px var(--ring),
    0 12px 32px -12px rgba(15, 23, 42, 0.14);
}

.mp-plan.is-selected {
  border-color: var(--ring);
  box-shadow:
    0 0 0 1px var(--ring),
    0 16px 36px -14px rgba(15, 23, 42, 0.2);
}

.mp-plan--t1 {
  --accent: #4f46e5;
  --accent-2: #6366f1;
  --accent-soft: #eef2ff;
  --ring: rgba(79, 70, 229, 0.4);
}

.mp-plan--t2 {
  --accent: #0e7490;
  --accent-2: #06b6d4;
  --accent-soft: #ecfeff;
  --ring: rgba(14, 116, 144, 0.38);
}

.mp-plan-topbar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  border-radius: 20px 20px 0 0;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  opacity: 0.95;
}

.mp-plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
}

.mp-plan-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
  line-height: 1.35;
}

.mp-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 5px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.mp-plan-head-tags {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.mp-owned {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 5px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
  border: 1px solid rgba(5, 150, 105, 0.35);
}

.mp-desc {
  margin: 10px 0 1.1rem;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: #64748b;
  min-height: 2.6em;
}

.mp-price-block {
  display: flex;
  align-items: baseline;
  gap: 4px 8px;
  flex-wrap: wrap;
  margin-bottom: 1.15rem;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--accent-soft);
  border: 1px solid rgba(15, 23, 42, 0.07);
}

.mp-price-currency {
  font-size: 1rem;
  font-weight: 700;
  color: var(--accent);
  align-self: flex-start;
  margin-top: 0.35em;
}

.mp-price-num {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.mp-price-unit {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #94a3b8;
  text-transform: uppercase;
  margin-left: 2px;
}

.mp-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.mp-pay {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 12px;
  border-radius: 12px;
  border: none;
  font-size: 0.8125rem;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    filter 0.15s ease;
}

.mp-pay:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  filter: grayscale(0.2);
}

.mp-pay:not(:disabled):hover {
  transform: translateY(-1px);
}

.mp-pay:not(:disabled):active {
  transform: translateY(0);
}

.mp-pay--full {
  width: 100%;
}

.mp-pay--ali {
  color: #1e40af;
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.75) inset, 0 2px 8px rgba(37, 99, 235, 0.18);
  border: 1px solid rgba(59, 130, 246, 0.45);
}

.mp-pay--ali:not(:disabled):hover {
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.85) inset, 0 6px 16px rgba(37, 99, 235, 0.25);
}

.mp-pay-ico-ali {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 900;
  color: #fff;
  background: linear-gradient(135deg, #1677ff 0%, #0958d9 100%);
}

.mp-result {
  margin-top: 1.25rem;
  padding: 14px 18px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #ffffff;
}

.mp-result-body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.mp-result-ico {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  margin-top: 2px;
}

.mp-result-text {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.55;
  color: #334155;
  word-break: break-word;
}

.mp-result--info {
  background: linear-gradient(180deg, #eff6ff 0%, #e0f2fe 100%);
  border-color: rgba(59, 130, 246, 0.25);
}

.mp-result--info .mp-result-ico {
  background: #2563eb;
  color: #fff;
}

.mp-result--info .mp-result-text {
  color: #1e3a8a;
}

.mp-result--error {
  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);
  border-color: rgba(220, 38, 38, 0.25);
}

.mp-result--error .mp-result-ico {
  background: #dc2626;
  color: #fff;
}

.mp-result--error .mp-result-text {
  color: #7f1d1d;
}

.mp-qr {
  margin-top: 1.25rem;
  border-radius: 16px;
}

.mp-qr-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 8px 0 4px;
}

.mp-qr-img {
  display: block;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(15, 23, 42, 0.12);
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.mp-qr-hint {
  margin: 0;
  text-align: center;
  max-width: 22rem;
  font-size: 0.8125rem;
  line-height: 1.45;
}

</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { authApi } from '@/api/auth';
import modelPaymentApi, { type ModelPaymentPlan } from '@/api/modelPayment';

const BUDGET_STORAGE_KEY = 'xcagi_contact_budget';

const route = useRoute();
const router = useRouter();

const plans = ref<ModelPaymentPlan[]>([]);
const loading = ref(true);
const checkoutPlanId = ref<string | null>(null);
const errorMessage = ref('');
const subscription = ref<Record<string, unknown> | null>(null);
const budgetRange = ref('');

const redirectPath = computed(() => {
  const raw = route.query.redirect;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return typeof value === 'string' && value.startsWith('/') ? value : '/';
});

function resolveBudgetRange(): string {
  const fromQuery = route.query.budget_range ?? route.query.budget;
  const queryValue = Array.isArray(fromQuery) ? fromQuery[0] : fromQuery;
  if (typeof queryValue === 'string' && queryValue.trim()) {
    return queryValue.trim();
  }
  try {
    return (localStorage.getItem(BUDGET_STORAGE_KEY) || '').trim();
  } catch {
    return '';
  }
}

function isPermanentPlan(planId: string): boolean {
  return planId.startsWith('saas-permanent-');
}

function priceUnit(plan: ModelPaymentPlan): string {
  if (plan.id === 'saas-trial-30') return '/30天';
  if (isPermanentPlan(plan.id)) return '/永久';
  return '/月';
}

function formatYuan(cents: number): string {
  return (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

onMounted(async () => {
  document.title = '套餐与定价';
  budgetRange.value = resolveBudgetRange();
  try {
    const [planRes, subRes] = await Promise.all([
      modelPaymentApi.getPlans(budgetRange.value || undefined),
      authApi.getSubscriptionStatus().catch(() => null),
    ]);
    plans.value = (planRes?.data?.plans || []).filter((p: ModelPaymentPlan) => p.id.startsWith('saas-'));
    if (subRes && (subRes as { data?: Record<string, unknown> }).data) {
      subscription.value = (subRes as { data: Record<string, unknown> }).data;
    }
  } catch (e: unknown) {
    errorMessage.value = e instanceof Error ? e.message : '加载套餐失败';
  } finally {
    loading.value = false;
  }
});

async function purchase(planId: string) {
  checkoutPlanId.value = planId;
  errorMessage.value = '';
  try {
    const res = await modelPaymentApi.checkout(planId);
    const data = res?.data;
    if (!res?.success || !data) {
      errorMessage.value = res?.message || '下单失败';
      return;
    }
    if (data.redirect_url) {
      window.location.assign(data.redirect_url);
      return;
    }
    if (data.setup_hint) {
      errorMessage.value = data.setup_hint;
      return;
    }
    errorMessage.value = '支付渠道未就绪，请联系管理员配置支付宝';
  } catch (e: unknown) {
    errorMessage.value = e instanceof Error ? e.message : '支付请求失败';
  } finally {
    checkoutPlanId.value = null;
  }
}

async function goBack() {
  await router.replace(redirectPath.value);
}
</script>

<template>
  <main class="saas-pricing" aria-label="SaaS 套餐定价">
    <section class="saas-pricing-panel">
      <h1>选择套餐</h1>
      <p v-if="subscription?.reason === 'trial'" class="saas-trial-hint">
        试用剩余 {{ subscription.trial_days_remaining ?? '—' }} 天
        <span v-if="subscription.trial_expires_at">（至 {{ subscription.trial_expires_at }}）</span>
      </p>
      <p v-else-if="subscription?.active === false" class="saas-trial-expired" role="alert">
        试用已结束，请购买套餐以继续使用。
      </p>

      <p v-if="errorMessage" class="saas-error" role="alert">{{ errorMessage }}</p>
      <p v-if="loading" class="muted">加载中…</p>

      <div v-else class="saas-plan-grid">
        <article v-for="plan in plans" :key="plan.id" class="saas-plan-card">
          <div class="saas-plan-head">
            <h2>{{ plan.title }}</h2>
            <span v-if="plan.badge" class="saas-badge">{{ plan.badge }}</span>
          </div>
          <p class="saas-price">
            <span class="saas-price-num">¥{{ formatYuan(plan.amount_cents) }}</span>
            <span class="saas-price-unit">{{ priceUnit(plan) }}</span>
          </p>
          <p class="saas-desc">{{ plan.description }}</p>
          <button
            type="button"
            class="saas-buy-btn"
            :disabled="checkoutPlanId !== null"
            @click="purchase(plan.id)"
          >
            {{ checkoutPlanId === plan.id ? '跳转支付…' : '支付宝购买' }}
          </button>
        </article>
      </div>

      <button type="button" class="saas-back-link" @click="goBack">返回应用</button>
    </section>
  </main>
</template>

<style scoped>
.saas-pricing {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px 16px;
  background: #f3f4f7;
}

.saas-pricing-panel {
  width: min(960px, 100%);
  background: #fff;
  padding: 32px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.saas-plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-top: 24px;
}

.saas-plan-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 20px;
}

.saas-plan-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.saas-badge {
  font-size: 12px;
  background: #111827;
  color: #fff;
  padding: 2px 8px;
  border-radius: 4px;
}

.saas-price-num {
  font-size: 28px;
  font-weight: 700;
}

.saas-price-unit {
  color: #6b7280;
  margin-left: 4px;
}

.saas-desc {
  color: #4b5563;
  font-size: 14px;
  min-height: 48px;
}

.saas-buy-btn {
  width: 100%;
  margin-top: 12px;
  padding: 10px 16px;
  background: #111827;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.saas-buy-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.saas-trial-hint {
  color: #059669;
  margin-top: 8px;
}

.saas-trial-expired,
.saas-error {
  color: #b91c1c;
  margin-top: 8px;
}

.saas-back-link {
  margin-top: 24px;
  background: none;
  border: none;
  color: #2563eb;
  cursor: pointer;
  text-decoration: underline;
}
</style>

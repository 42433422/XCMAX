<template>
  <div class="bb" role="group" aria-label="账号与余量">
    <button
      type="button"
      class="bb__pill bb__pill--balance"
      :title="balanceTitle"
      @click="$emit('open-balance')"
    >
      <span class="bb__icon" aria-hidden="true">💎</span>
      <span class="bb__label">余量</span>
      <span class="bb__value">{{ formattedBalance }}</span>
    </button>

    <button
      v-if="!isMember"
      type="button"
      class="bb__pill bb__pill--upgrade"
      @click="$emit('upgrade')"
    >
      <span class="bb__icon" aria-hidden="true">✨</span>
      升级会员
    </button>
    <button
      v-else
      type="button"
      class="bb__pill bb__pill--member"
      :title="memberTitle"
      @click="$emit('upgrade')"
    >
      <span class="bb__icon" aria-hidden="true">👑</span>
      {{ memberLabel }}
    </button>

    <button
      type="button"
      class="bb__pill bb__pill--invite"
      @click="$emit('invite')"
      title="复制邀请链接，好友登录后双方各得额度"
    >
      <span class="bb__icon" aria-hidden="true">🎁</span>
      邀请
    </button>

    <span v-if="invited" class="bb__toast" role="status">{{ invitedText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  balance: number | string | null
  /** 当前会员等级，'free' / 'pro' / 'team' / ... */
  memberPlan?: string
  memberExpireAt?: string
  invited?: boolean
  invitedText?: string
}>()

defineEmits<{
  (e: 'open-balance'): void
  (e: 'upgrade'): void
  (e: 'invite'): void
}>()

const formattedBalance = computed(() => {
  const n = Number(props.balance)
  if (!Number.isFinite(n)) return '—'
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(2)
})

const isMember = computed(() => {
  const p = String(props.memberPlan || '').toLowerCase()
  return Boolean(p && p !== 'free' && p !== 'none')
})

const memberLabel = computed(() => {
  const p = String(props.memberPlan || '').toLowerCase()
  if (p === 'pro') return 'Pro 会员'
  if (p === 'vip_plus' || p === 'plan_pro') return 'VIP+ 会员'
  if (p === 'vip' || p === 'basic' || p === 'plan_basic') return 'VIP 会员'
  if (p === 'team') return '团队版'
  if (p === 'enterprise') return '企业版'
  if (p === 'svip' || p === 'plan_enterprise') return 'SVIP 会员'
  return '会员'
})

const memberTitle = computed(() => {
  if (!props.memberExpireAt) return memberLabel.value
  return `${memberLabel.value} · 有效期至 ${props.memberExpireAt}`
})

const balanceTitle = computed(() => {
  return `当前可用余量 ≈ ${props.balance ?? '—'}（点击查看明细 / 充值）`
})
</script>

<style scoped>
.bb {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  pointer-events: auto;
}

.bb__pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.32rem 0.7rem;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(226, 232, 240, 0.92);
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}

.bb__pill:hover {
  background: rgba(255, 255, 255, 0.08);
}

.bb__pill--balance .bb__value {
  font-weight: 700;
  color: #fbbf24;
}

.bb__pill--upgrade {
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.32), rgba(244, 114, 182, 0.42));
  border-color: rgba(251, 191, 36, 0.45);
  color: #fff;
  font-weight: 600;
}

.bb__pill--upgrade:hover {
  filter: brightness(1.08);
}

.bb__pill--member {
  background: linear-gradient(135deg, rgba(244, 114, 182, 0.4), rgba(168, 85, 247, 0.55));
  border-color: rgba(244, 114, 182, 0.55);
  color: #fff;
}

.bb__pill--invite {
  background: rgba(45, 212, 191, 0.18);
  border-color: rgba(45, 212, 191, 0.32);
  color: #5eead4;
}

.bb__pill--invite:hover {
  background: rgba(45, 212, 191, 0.32);
}

.bb__toast {
  font-size: 0.72rem;
  color: #5eead4;
  margin-left: 0.3rem;
  animation: bbToast 1.6s ease forwards;
}

@keyframes bbToast {
  0% { opacity: 0; transform: translateY(-4px); }
  10%, 80% { opacity: 1; transform: translateY(0); }
  100% { opacity: 0; }
}
</style>

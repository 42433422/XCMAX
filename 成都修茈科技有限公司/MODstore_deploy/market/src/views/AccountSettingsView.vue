<template>
  <div class="account-page account-page--console">
    <header class="account-console-head">
      <div class="account-console-head__titles">
        <p class="account-console-head__eyebrow">控制台</p>
        <h1 class="account-console-head__h1">账户中心</h1>
      </div>
      <div class="account-console-head__user">
        <div class="account-console-head__avatar-wrap">
          <button
            type="button"
            class="account-console-head__avatar account-console-head__avatar--btn"
            :aria-label="avatarBusy ? '上传头像中' : '点击更换头像'"
            :disabled="avatarBusy"
            @click="openAvatarPicker"
          >
            <img
              v-if="avatarPreviewUrl"
              :src="avatarPreviewUrl"
              alt=""
              class="account-console-head__avatar-img"
            />
            <span v-else class="account-console-head__avatar-letter">{{ avatarInitial }}</span>
            <span class="account-console-head__avatar-overlay">{{ avatarBusy ? '上传中…' : '更换' }}</span>
          </button>
          <input
            ref="avatarInputRef"
            type="file"
            class="sr-only"
            accept="image/jpeg,image/png,image/webp,image/gif"
            @change="onAvatarSelected"
          />
          <button
            v-if="avatarPreviewUrl || authUser?.avatar_url"
            type="button"
            class="account-console-head__avatar-remove"
            :disabled="avatarBusy"
            @click="removeAvatar"
          >
            移除头像
          </button>
        </div>
        <div class="account-console-head__meta">
          <div class="account-console-head__name">{{ displayUsername }}</div>
          <div v-if="email" class="account-console-head__email">{{ email }}</div>
          <div v-if="level" class="account-console-head__chips">
            <span class="acct-chip acct-chip--lv">Lv.{{ level.level }} {{ level.title || '成长等级' }}</span>
            <span
              :class="[
                'acct-chip',
                'acct-chip--tier',
                membershipTier ? `acct-chip--tier-${membershipTier}` : 'acct-chip--tier-free',
              ]"
              >{{ membershipLabel }}</span
            >
            <span v-if="isAdmin" class="acct-chip acct-chip--admin">管理员</span>
          </div>
        </div>
      </div>
    </header>

    <div v-if="msg" class="flash flash-ok">{{ msg }}</div>
    <div v-if="err" class="flash flash-err">{{ err }}</div>

    <div v-if="level" class="account-console-grid">
      <section class="acct-panel acct-panel--grow">
        <div class="acct-panel__rowhead">
          <h2 class="acct-panel__h2">成长与等级</h2>
          <div class="acct-panel__kpi">
            <span class="acct-panel__kpi-label">累计经验</span>
            <span class="acct-panel__kpi-val">{{ level.experience.toLocaleString() }}</span>
          </div>
        </div>
        <div class="acct-grow-bar">
          <div class="acct-grow-track">
            <div class="acct-grow-fill" :style="{ width: progressPercent + '%' }" />
          </div>
          <div class="acct-grow-meta">
            <template v-if="level.nextLevelMinExp !== null">
              <span
                >当前 Lv.{{ level.level }}，距 Lv.{{ level.level + 1 }} 还需
                <strong>{{ expToNextLevel.toLocaleString() }}</strong> 经验</span
              >
            </template>
            <span v-else>已达最高等级</span>
            <span class="acct-grow-pct">{{ progressPercent }}%</span>
          </div>
        </div>
        <details class="acct-details">
          <summary>经验如何累计？</summary>
          <p class="acct-details__body">
            每 <strong>1 元 = 100 经验</strong>（实付 / 实扣）：商品、会员、钱包充值等订单实付；使用大模型且<strong>未使用 BYOK</strong>时，预授权从钱包按用量结算的实扣金额（与顶部导航栏余额变动一致）。<strong>BYOK</strong> 不经平台钱包扣模型费，不计此项经验。订单退款成功会扣回该笔订单已发放的经验。
          </p>
        </details>
      </section>

      <section class="acct-panel acct-panel--plan">
        <h2 class="acct-panel__h2">会员与权益</h2>
        <p class="acct-plan-line">
          当前套餐：
          <strong :class="['acct-plan-tier', membershipTier ? `acct-plan-tier--${membershipTier}` : '']">{{
            membershipLabel
          }}</strong>
          <span v-if="isAdmin" class="acct-plan-admin-note">（你已具备后台管理权限）</span>
        </p>
        <p class="acct-plan-desc">{{ membershipHint }}</p>
        <div class="acct-plan-actions">
          <RouterLink to="/plans" class="btn btn-primary">套餐与计费</RouterLink>
          <RouterLink to="/wallet" class="btn btn-ghost">钱包与流水</RouterLink>
        </div>
      </section>
    </div>

    <nav class="acct-subnav" aria-label="快捷入口">
      <RouterLink to="/wallet" class="acct-subnav__link">钱包</RouterLink>
      <RouterLink :to="{ name: 'wallet-purchased' }" class="acct-subnav__link">已购</RouterLink>
      <RouterLink to="/notifications" class="acct-subnav__link">通知</RouterLink>
      <RouterLink to="/plans" class="acct-subnav__link">会员</RouterLink>
    </nav>

    <section id="api-keys" class="card account-api-keys" tabindex="-1" aria-labelledby="api-keys-heading">
      <h2 id="api-keys-heading" class="account-api-keys__h2">API 密钥</h2>
      <p class="account-api-keys__lead">
        在此创建、吊销 Personal Access Token，或将多条密钥<strong>加密下发到桌面</strong>（免逐条复制）。调用接口时使用
        <code>Authorization: Bearer pat_…</code>。
      </p>
      <div class="account-api-keys__embed">
        <DeveloperTokensPanel />
      </div>
      <p class="account-api-keys__more">
        <RouterLink :to="{ name: 'developer-portal' }" class="account-api-keys__link">Webhook 订阅与完整开发者门户 →</RouterLink>
      </p>
    </section>

    <div class="forms-grid">
      <section class="card">
        <h3 class="card-title">基本信息</h3>
        <div class="form-group">
          <label>用户名</label>
          <input v-model="username" class="input" :disabled="saving" />
        </div>
        <div class="form-group">
          <label>邮箱</label>
          <input :value="email" class="input" type="email" disabled />
          <span class="hint">邮箱修改请联系管理员</span>
        </div>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="saveProfile">保存</button>
      </section>

      <section class="card">
        <h3 class="card-title">修改密码</h3>
        <div class="form-group">
          <label>当前密码</label>
          <input v-model="pw.current" type="password" class="input" autocomplete="current-password" />
        </div>
        <div class="form-group">
          <label>新密码</label>
          <input v-model="pw.new1" type="password" class="input" autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label>确认新密码</label>
          <input v-model="pw.new2" type="password" class="input" autocomplete="new-password" />
        </div>
        <button type="button" class="btn btn-primary" :disabled="!canChangePw || savingPw" @click="changePw">
          {{ savingPw ? '提交中…' : '修改密码' }}
        </button>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '../api'
import DeveloperTokensPanel from './developer/DeveloperTokensPanel.vue'
import { normalizeMeResponse } from '../domain/accountLevel'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const {
  levelProfile,
  membership,
  membershipTier,
  membershipFetchFailed,
  username: storeUsername,
  isAdmin,
  user: authUser,
} = storeToRefs(authStore)

const username = ref('')
const email = ref('')
const saving = ref(false)
const savingPw = ref(false)
const msg = ref('')
const err = ref('')
const pw = ref({ current: '', new1: '', new2: '' })
const avatarInputRef = ref<HTMLInputElement | null>(null)
const avatarPreviewUrl = ref('')
const avatarBusy = ref(false)
let avatarObjectUrl = ''

function revokeAvatarObjectUrl() {
  if (avatarObjectUrl) {
    URL.revokeObjectURL(avatarObjectUrl)
    avatarObjectUrl = ''
  }
}

async function loadAvatarPreview() {
  revokeAvatarObjectUrl()
  const path = authUser.value?.avatar_url
  if (!path) {
    avatarPreviewUrl.value = ''
    return
  }
  try {
    const blob = await api.fetchAvatarBlob(String(path))
    avatarObjectUrl = URL.createObjectURL(blob)
    avatarPreviewUrl.value = avatarObjectUrl
  } catch {
    avatarPreviewUrl.value = ''
  }
}

function openAvatarPicker() {
  avatarInputRef.value?.click()
}

async function onAvatarSelected(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!/^image\/(jpeg|png|webp|gif)$/i.test(file.type)) {
    err.value = '请选择 JPG、PNG、WebP 或 GIF 图片'
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    err.value = '头像不能超过 2MB'
    return
  }
  msg.value = ''
  err.value = ''
  avatarBusy.value = true
  try {
    await api.uploadAvatar(file)
    msg.value = '头像已更新'
    await authStore.refreshSession(true)
    await loadAvatarPreview()
  } catch (e: any) {
    err.value = e?.message || '头像上传失败'
  } finally {
    avatarBusy.value = false
  }
}

async function removeAvatar() {
  if (!authUser.value?.avatar_url && !avatarPreviewUrl.value) return
  msg.value = ''
  err.value = ''
  avatarBusy.value = true
  try {
    await api.deleteAvatar()
    revokeAvatarObjectUrl()
    avatarPreviewUrl.value = ''
    msg.value = '已移除头像'
    await authStore.refreshSession(true)
  } catch (e: any) {
    err.value = e?.message || '移除失败'
  } finally {
    avatarBusy.value = false
  }
}

const canChangePw = computed(
  () =>
    pw.value.current.length > 0 &&
    pw.value.new1.length >= 6 &&
    pw.value.new1 === pw.value.new2,
)

const level = computed(() => levelProfile.value)
const progressPercent = computed(() => Math.round(((level.value?.progress ?? 0) as number) * 100))
const expToNextLevel = computed(() => {
  const l = level.value
  if (!l || l.nextLevelMinExp === null) return 0
  return Math.max(0, (l.nextLevelMinExp as number) - l.experience)
})

const displayUsername = computed(() => (username.value || storeUsername.value || '用户').trim() || '用户')
const avatarInitial = computed(() => {
  const s = displayUsername.value.trim()
  if (!s) return '?'
  return s.slice(0, 1).toUpperCase()
})

const membershipLabel = computed(() => {
  if (membershipFetchFailed.value) return '暂不可用'
  const m = membership.value
  if (m?.label) return String(m.label)
  if (m?.tier && m.tier !== 'free') return String(m.tier)
  return '普通用户'
})

const membershipHint = computed(() => {
  if (membershipFetchFailed.value) {
    return '无法连接支付服务以读取会员档位（网络或网关异常）。请稍后刷新页面；若已购买仍异常，请联系运维核对支付服务与数据库。'
  }
  const t = (membershipTier.value || 'free').toLowerCase()
  if (t === 'free' || !membership.value?.is_member) {
    return '未开通会员。升级可享受更高 AI 额度、BYOK、会员标识等权益。'
  }
  if (t === 'vip' || t === 'vip_plus') {
    return '你正在使用付费会员能力，可在「会员购买」中继续升级。'
  }
  if (t.startsWith('svip')) {
    return '你正在使用 SVIP 系列权益。可在套餐页按档升级。'
  }
  return '感谢支持，更多权益可在「会员购买」中查看。'
})

watch(
  () => authUser.value?.avatar_url,
  () => {
    void loadAvatarPreview()
  },
)

onMounted(async () => {
  try {
    const me = normalizeMeResponse(await api.me())
    username.value = me.username || ''
    email.value = me.email || ''
    await authStore.refreshSession(true)
    await authStore.refreshMembership()
    await loadAvatarPreview()
  } catch (e: any) {
    err.value = e?.message || '加载失败'
  }
})

onBeforeUnmount(() => {
  revokeAvatarObjectUrl()
})

async function saveProfile() {
  msg.value = ''
  err.value = ''
  saving.value = true
  try {
    await api.updateProfile(username.value.trim())
    msg.value = '已保存'
    await authStore.refreshSession(true)
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function changePw() {
  msg.value = ''
  err.value = ''
  savingPw.value = true
  try {
    await api.changePassword(pw.value.current, pw.value.new1)
    msg.value = '密码已更新'
    pw.value = { current: '', new1: '', new2: '' }
  } catch (e: any) {
    err.value = e?.message || '修改失败'
  } finally {
    savingPw.value = false
  }
}
</script>

<style scoped>
.account-page {
  max-width: 1080px;
  margin: 0 auto;
  /* 与全局 --layout-gutter 同节奏；原 main-content 横向 padding 已取消 */
  padding: 0 clamp(12px, 3.5vw, 40px) 2.5rem;
  color: #fff;
}
.account-page--console {
  letter-spacing: -0.01em;
}

/* —— 顶栏：单块信息，避免与下方卡片重复 —— */
.account-console-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem 1.5rem;
  margin-bottom: 1.25rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.account-console-head__eyebrow {
  margin: 0 0 0.2rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4);
}
.account-console-head__h1 {
  margin: 0;
  font-size: clamp(1.35rem, 2.2vw, 1.65rem);
  font-weight: 700;
}
.account-console-head__user {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  min-width: 0;
}
.account-console-head__avatar-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}
.account-console-head__avatar {
  flex-shrink: 0;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  font-weight: 700;
  background: linear-gradient(145deg, rgba(99, 102, 241, 0.4), rgba(14, 165, 233, 0.22));
  border: 1px solid rgba(99, 102, 241, 0.4);
  position: relative;
  overflow: hidden;
  padding: 0;
  color: #fff;
}
.account-console-head__avatar--btn {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.account-console-head__avatar--btn:hover:not(:disabled) {
  border-color: rgba(129, 140, 248, 0.65);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.25);
}
.account-console-head__avatar--btn:disabled {
  opacity: 0.7;
  cursor: wait;
}
.account-console-head__avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.account-console-head__avatar-letter {
  line-height: 1;
}
.account-console-head__avatar-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 2px;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #fff;
  background: linear-gradient(transparent 35%, rgba(0, 0, 0, 0.72));
  opacity: 0;
  transition: opacity 0.15s ease;
  pointer-events: none;
}
.account-console-head__avatar--btn:hover:not(:disabled) .account-console-head__avatar-overlay,
.account-console-head__avatar--btn:focus-visible .account-console-head__avatar-overlay {
  opacity: 1;
}
.account-console-head__avatar-remove {
  border: none;
  background: none;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.68rem;
  cursor: pointer;
  padding: 0 2px;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.account-console-head__avatar-remove:hover:not(:disabled) {
  color: rgba(255, 255, 255, 0.85);
}
.account-console-head__avatar-remove:disabled {
  opacity: 0.5;
  cursor: wait;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.account-console-head__meta {
  min-width: 0;
}
.account-console-head__name {
  font-weight: 600;
  font-size: 0.95rem;
  color: #fff;
}
.account-console-head__email {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.45);
  word-break: break-all;
  margin-top: 0.1rem;
}
.account-console-head__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.45rem;
}
.acct-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.22rem 0.55rem;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 600;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
}
.acct-chip--lv {
  color: #c7d2fe;
  border-color: rgba(99, 102, 241, 0.35);
  background: rgba(99, 102, 241, 0.15);
}
.acct-chip--tier-free {
  color: rgba(255, 255, 255, 0.75);
}
.acct-chip--tier-vip {
  color: #67e8f9;
  border-color: rgba(103, 232, 249, 0.35);
}
.acct-chip--tier-vip_plus {
  color: #fde047;
  border-color: rgba(253, 224, 71, 0.35);
}
.acct-chip--tier-svip1 { color: #c084fc; border-color: rgba(192, 132, 252, 0.35); }
.acct-chip--tier-svip2 { color: #f472b6; border-color: rgba(244, 114, 182, 0.35); }
.acct-chip--tier-svip3 { color: #34d399; border-color: rgba(52, 211, 153, 0.35); }
.acct-chip--tier-svip4 { color: #fb923c; border-color: rgba(251, 146, 60, 0.35); }
.acct-chip--tier-svip5 { color: #fb7185; border-color: rgba(251, 113, 133, 0.35); }
.acct-chip--tier-svip6 { color: #818cf8; border-color: rgba(129, 140, 248, 0.35); }
.acct-chip--tier-svip7 { color: #fbbf24; border-color: rgba(251, 191, 36, 0.4); }
.acct-chip--tier-svip8 {
  color: #fff;
  border: none;
  background: linear-gradient(120deg, rgba(244, 114, 182, 0.5), rgba(251, 191, 36, 0.45), rgba(52, 211, 153, 0.4));
}
.acct-chip--admin {
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(248, 113, 113, 0.12);
}
.acct-plan-admin-note {
  margin-left: 0.35rem;
  font-size: 0.78rem;
  font-weight: 500;
  color: rgba(252, 165, 165, 0.95);
}

/* —— 主区：两列面板（类控制台「套餐 / 用量」分区） —— */
.account-console-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 0.85rem;
  margin-bottom: 1.1rem;
}
@media (max-width: 840px) {
  .account-console-grid {
    grid-template-columns: 1fr;
  }
}
.acct-panel {
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 1rem 1.1rem;
  min-width: 0;
}
.acct-panel--grow {
  background: linear-gradient(165deg, rgba(99, 102, 241, 0.1), rgba(8, 145, 178, 0.05));
  border-color: rgba(99, 102, 241, 0.18);
}
.acct-panel--plan {
  display: flex;
  flex-direction: column;
}
.acct-panel__rowhead {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem 1rem;
  margin-bottom: 0.85rem;
}
.acct-panel__h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.acct-panel__kpi {
  text-align: right;
}
.acct-panel__kpi-label {
  display: block;
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45);
}
.acct-panel__kpi-val {
  font-size: 1.35rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  background: linear-gradient(90deg, #e0e7ff, #a5b4fc);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.acct-grow-bar {
  margin-bottom: 0.35rem;
}
.acct-grow-track {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.acct-grow-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #6366f1, #38bdf8);
  transition: width 0.35s ease;
}
.acct-grow-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.45rem;
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.65);
}
.acct-grow-meta strong {
  color: #fff;
  font-weight: 600;
}
.acct-grow-pct {
  font-variant-numeric: tabular-nums;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.75rem;
}
.acct-details {
  margin-top: 0.65rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 0.45rem;
}
.acct-details summary {
  cursor: pointer;
  font-size: 0.78rem;
  color: rgba(165, 180, 252, 0.95);
  user-select: none;
}
.acct-details summary:hover {
  color: #c7d2fe;
}
.acct-details__body {
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.48);
}
.acct-plan-line {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.75);
}
.acct-plan-tier {
  font-weight: 700;
}
.acct-plan-tier--free {
  color: rgba(255, 255, 255, 0.85);
}
.acct-plan-tier--vip {
  color: #67e8f9;
}
.acct-plan-tier--vip_plus {
  color: #fde047;
}
.acct-plan-tier--svip1 { color: #c084fc; }
.acct-plan-tier--svip2 { color: #f472b6; }
.acct-plan-tier--svip3 { color: #34d399; }
.acct-plan-tier--svip4 { color: #fb923c; }
.acct-plan-tier--svip5 { color: #fb7185; }
.acct-plan-tier--svip6 { color: #818cf8; }
.acct-plan-tier--svip7 { color: #fbbf24; }
.acct-plan-tier--svip8 {
  background: linear-gradient(90deg, #f472b6, #fbbf24, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.acct-plan-desc {
  margin: 0 0 1rem;
  font-size: 0.8rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.5);
  flex: 1;
}
.acct-plan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: auto;
}

/* —— 次级导航：横条分段 —— */
.acct-subnav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 1.35rem;
  padding: 0.35rem;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.acct-subnav__link {
  padding: 0.38rem 0.75rem;
  border-radius: 7px;
  font-size: 0.8rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.78);
  text-decoration: none;
  border: 1px solid transparent;
}
.acct-subnav__link:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.acct-subnav__link.router-link-active {
  background: rgba(99, 102, 241, 0.22);
  border-color: rgba(99, 102, 241, 0.35);
  color: #e0e7ff;
}

/* ---- Forms ---- */
.forms-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  align-items: start;
}
@media (max-width: 720px) {
  .forms-grid {
    grid-template-columns: 1fr;
  }
}

.form-group {
  margin-bottom: 1rem;
}
.form-group label {
  display: block;
  margin-bottom: 0.35rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.65);
}
.input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: #0a0a0a;
  color: #fff;
  box-sizing: border-box;
}
.hint {
  display: block;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
  margin-top: 0.25rem;
}
.btn {
  padding: 0.55rem 1.25rem;
  border-radius: 8px;
  border: none;
  background: #6366f1;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
  text-align: center;
  font-size: 0.9rem;
  box-sizing: border-box;
}
.btn-ghost {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.9);
}
.btn-ghost:hover {
  border-color: rgba(99, 102, 241, 0.5);
  color: #c7d2fe;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.flash {
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  margin-bottom: 0.75rem;
  font-size: 0.9rem;
}
.flash-ok {
  background: rgba(34, 197, 94, 0.15);
  color: #86efac;
}
.flash-err {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}

/* 表单区卡片（与上方控制台面板区分命名） */
.card {
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 1.1rem 1.15rem;
}
.card-title {
  margin: 0 0 0.85rem;
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.account-api-keys {
  margin-bottom: 1.5rem;
  scroll-margin-top: 88px;
}
.account-api-keys__h2 {
  margin: 0 0 0.75rem;
  font-size: 1.15rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
}
.account-api-keys__lead {
  margin: 0 0 1rem;
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.55;
  max-width: 52rem;
}
.account-api-keys__lead code {
  font-size: 0.75rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.55);
  color: #e2e8f0;
}
.account-api-keys__embed {
  border-radius: 12px;
  overflow: hidden;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  background: #111111;
  padding: 20px;
}
.account-api-keys__more {
  margin: 1rem 0 0;
  font-size: 0.85rem;
}
.account-api-keys__link {
  color: #a5b4fc;
  text-decoration: none;
}
.account-api-keys__link:hover {
  text-decoration: underline;
}

/* ====== 浅色主题覆盖 ====== */
html[data-workbench-theme='light'] .account-page {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-console-head {
  border-bottom-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .account-console-head__eyebrow {
  color: #86868b;
}
html[data-workbench-theme='light'] .account-console-head__h1 {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-console-head__avatar {
  background: linear-gradient(145deg, rgba(99, 102, 241, 0.18), rgba(14, 165, 233, 0.1));
  border-color: rgba(99, 102, 241, 0.25);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-console-head__avatar-remove {
  color: #86868b;
}
html[data-workbench-theme='light'] .account-console-head__avatar-remove:hover:not(:disabled) {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-console-head__name {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-console-head__email {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-chip {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.03);
}
html[data-workbench-theme='light'] .acct-chip--lv {
  color: #4f46e5;
  border-color: rgba(99, 102, 241, 0.25);
  background: rgba(99, 102, 241, 0.08);
}
html[data-workbench-theme='light'] .acct-chip--tier-free {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-chip--tier-vip {
  color: #0891b2;
  border-color: rgba(8, 145, 178, 0.25);
}
html[data-workbench-theme='light'] .acct-chip--tier-vip_plus {
  color: #ca8a04;
  border-color: rgba(202, 138, 4, 0.25);
}
html[data-workbench-theme='light'] .acct-chip--tier-svip1 { color: #7c3aed; border-color: rgba(124, 58, 237, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip2 { color: #db2777; border-color: rgba(219, 39, 119, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip3 { color: #059669; border-color: rgba(5, 150, 105, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip4 { color: #ea580c; border-color: rgba(234, 88, 12, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip5 { color: #e11d48; border-color: rgba(225, 29, 72, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip6 { color: #4f46e5; border-color: rgba(79, 70, 229, 0.25); }
html[data-workbench-theme='light'] .acct-chip--tier-svip7 { color: #d97706; border-color: rgba(217, 119, 6, 0.3); }
html[data-workbench-theme='light'] .acct-chip--tier-svip8 {
  color: #1d1d1f;
  border: none;
  background: linear-gradient(120deg, rgba(244, 114, 182, 0.2), rgba(251, 191, 36, 0.18), rgba(52, 211, 153, 0.15));
}
html[data-workbench-theme='light'] .acct-chip--admin {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.25);
  background: rgba(220, 38, 38, 0.06);
}
html[data-workbench-theme='light'] .acct-plan-admin-note {
  color: #dc2626;
}
html[data-workbench-theme='light'] .acct-panel {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .acct-panel--grow {
  background: linear-gradient(165deg, rgba(99, 102, 241, 0.06), rgba(8, 145, 178, 0.03));
  border-color: rgba(99, 102, 241, 0.12);
}
html[data-workbench-theme='light'] .acct-panel__h2 {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-panel__kpi-label {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-panel__kpi-val {
  background: linear-gradient(90deg, #4f46e5, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
html[data-workbench-theme='light'] .acct-grow-track {
  background: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .acct-grow-fill {
  background: linear-gradient(90deg, #6366f1, #38bdf8);
}
html[data-workbench-theme='light'] .acct-grow-meta {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-grow-meta strong {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-grow-pct {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-details {
  border-top-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .acct-details summary {
  color: #0071e3;
}
html[data-workbench-theme='light'] .acct-details summary:hover {
  color: #005bb5;
}
html[data-workbench-theme='light'] .acct-details__body {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-plan-line {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-plan-tier--free {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-plan-tier--vip {
  color: #0891b2;
}
html[data-workbench-theme='light'] .acct-plan-tier--vip_plus {
  color: #ca8a04;
}
html[data-workbench-theme='light'] .acct-plan-tier--svip1 { color: #7c3aed; }
html[data-workbench-theme='light'] .acct-plan-tier--svip2 { color: #db2777; }
html[data-workbench-theme='light'] .acct-plan-tier--svip3 { color: #059669; }
html[data-workbench-theme='light'] .acct-plan-tier--svip4 { color: #ea580c; }
html[data-workbench-theme='light'] .acct-plan-tier--svip5 { color: #e11d48; }
html[data-workbench-theme='light'] .acct-plan-tier--svip6 { color: #4f46e5; }
html[data-workbench-theme='light'] .acct-plan-tier--svip7 { color: #d97706; }
html[data-workbench-theme='light'] .acct-plan-desc {
  color: #86868b;
}
html[data-workbench-theme='light'] .acct-subnav {
  background: rgba(0, 0, 0, 0.03);
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .acct-subnav__link {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-subnav__link:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .acct-subnav__link.router-link-active {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
  color: #4f46e5;
}
html[data-workbench-theme='light'] .form-group label {
  color: #86868b;
}
html[data-workbench-theme='light'] .input {
  border-color: rgba(0, 0, 0, 0.1);
  background: #ffffff;
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .input:focus {
  border-color: #0071e3;
  outline: none;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.12);
}
html[data-workbench-theme='light'] .hint {
  color: #86868b;
}
html[data-workbench-theme='light'] .btn {
  background: #0071e3;
  color: #fff;
}
html[data-workbench-theme='light'] .btn:hover {
  background: #005bb5;
}
html[data-workbench-theme='light'] .btn-ghost {
  background: transparent;
  border-color: rgba(0, 0, 0, 0.12);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .btn-ghost:hover {
  border-color: rgba(0, 113, 227, 0.4);
  color: #0071e3;
}
html[data-workbench-theme='light'] .flash-ok {
  background: rgba(34, 197, 94, 0.1);
  color: #16a34a;
}
html[data-workbench-theme='light'] .flash-err {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}
html[data-workbench-theme='light'] .card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .card-title {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-api-keys__h2 {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-api-keys__lead {
  color: #86868b;
}
html[data-workbench-theme='light'] .account-api-keys__lead code {
  background: rgba(0, 0, 0, 0.05);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .account-api-keys__embed {
  border-color: rgba(0, 0, 0, 0.06);
  background: #ffffff;
}
html[data-workbench-theme='light'] .account-api-keys__link {
  color: #0071e3;
}
html[data-workbench-theme='light'] .account-api-keys__link:hover {
  color: #005bb5;
}
</style>

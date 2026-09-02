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
      <div class="account-api-keys__head">
        <h2 id="api-keys-heading" class="account-api-keys__h2">API 密钥</h2>
        <p class="account-api-keys__lead">
          调用接口：<code>Authorization: Bearer pat_…</code>
        </p>
      </div>
      <div class="account-api-keys__embed">
        <DeveloperTokensPanel embedded />
      </div>
      <p class="account-api-keys__more">
        <RouterLink :to="{ name: 'developer-portal' }" class="account-api-keys__link">Webhook · 桌面加密导出 · 开发者门户 →</RouterLink>
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
// 拆分后本文件为组装入口（façade）：逻辑在 ./account-settings/，样式在 ./account-settings/account-settings.css。
import { RouterLink } from 'vue-router'
import DeveloperTokensPanel from './developer/DeveloperTokensPanel.vue'
import { useAccountSettings } from './account-settings/useAccountSettings'

const {
  authUser,
  isAdmin,
  username,
  email,
  saving,
  savingPw,
  msg,
  err,
  pw,
  avatarInputRef,
  avatarPreviewUrl,
  avatarBusy,
  openAvatarPicker,
  onAvatarSelected,
  removeAvatar,
  canChangePw,
  level,
  progressPercent,
  expToNextLevel,
  displayUsername,
  avatarInitial,
  membershipLabel,
  membershipHint,
  membershipTier,
  saveProfile,
  changePw,
} = useAccountSettings()
</script>

<style scoped src="./account-settings/account-settings.css"></style>

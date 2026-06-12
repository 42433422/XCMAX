<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import QRCode from 'qrcode';
import { useRoute, useRouter } from 'vue-router';
import { ApiError } from '@/api';
import { authApi } from '@/api/auth';
import { applyMarketTokensAfterFhdLogin } from '@/api/marketAccount';
import {
  loginAccountInputPlaceholder,
  loginPageTitle,
  loginPasswordInputPlaceholder,
} from '@/constants/loginBranding';
import { isSunbirdAccountUsername } from '@/constants/accountModBinding';
import { fetchProductSku } from '@/utils/productSku';
import { useAccountProfileStore } from '@/stores/accountProfile';
import {
  isAdminConsoleSpa,
  resolveAdminConsoleLoginUrl,
} from '@/utils/adminConsoleUrl';
import { ADMIN_OPERATOR_HOME_ROUTE } from '@/constants/adminOperatorNav';
import type { AccountKind } from '@/api/auth';
import { loadLoginPreferences, saveLoginPreferences } from '@/utils/loginPreferences';
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate';
import OtpCells from '@/components/OtpCells.vue';

const route = useRoute();
const router = useRouter();
const accountProfileStore = useAccountProfileStore();

const username = ref('');
const accountKind = ref<AccountKind>(isAdminConsoleSpa() ? 'admin' : 'enterprise');
const password = ref('');
const showPassword = ref(false);
const loading = ref(false);
const errorMessage = ref('');
const altLoginHint = ref('');
const oidcEnabled = ref(false);
const loginMode = ref<'password' | 'phone' | 'qr'>('password');
const phone = ref('');
const smsCode = ref('');
const sendingCode = ref(false);
const qrDataUrl = ref('');
const qrPollTimer = ref<number | null>(null);
const qrExpiresAt = ref(0);
const qrId = ref('');
const qrPollSecret = ref('');
const usernameFocused = ref(false);
const passwordFocused = ref(false);
const rememberPassword = ref(false);
const autoLogin = ref(false);
let autoLoginAttempted = false;

watch(rememberPassword, (enabled) => {
  if (!enabled) autoLogin.value = false;
});

watch(autoLogin, (enabled) => {
  if (enabled) rememberPassword.value = true;
});

function peelNestedLoginRedirect(raw: string): string {
  let v = raw.trim();
  for (let i = 0; i < 5 && v.startsWith('/login'); i++) {
    const q = v.indexOf('?');
    if (q < 0) return '/';
    const nested = new URLSearchParams(v.slice(q + 1)).get('redirect');
    v = nested ? decodeURIComponent(nested.trim()) : '/';
  }
  const pathOnly = v.split('?')[0].split('#')[0];
  return pathOnly;
}

const redirectPath = computed(() => {
  const raw = route.query.redirect;
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value || typeof value !== 'string') return '/';
  let v = value.trim();
  try {
    v = decodeURIComponent(v);
  } catch {
    /* keep */
  }
  v = peelNestedLoginRedirect(v);
  if (!v.startsWith('/') || v.startsWith('//') || v.startsWith('/login')) return '/';
  return v;
});

const canSubmit = computed(() => {
  if (loading.value) return false;
  if (loginMode.value === 'phone') {
    return phone.value.trim().length >= 5 && smsCode.value.trim().length >= 6;
  }
  if (loginMode.value === 'qr') return false;
  return username.value.trim().length > 0 && password.value.length > 0;
});

const qrCountdown = computed(() => {
  const left = Math.max(0, qrExpiresAt.value - Math.floor(Date.now() / 1000));
  return left;
});

const productSku = ref<string>('generic');
const baseUrl = import.meta.env.BASE_URL;
const isEnterpriseEdition = computed(() => productSku.value === 'enterprise');

const loginHeading = computed(() =>
  accountKind.value === 'admin' ? '管理员登录' : '企业账号登录',
);
const accountPlaceholder = computed(() => loginAccountInputPlaceholder(productSku.value));
const passwordPlaceholder = computed(() => loginPasswordInputPlaceholder());
const registerRoute = computed(() => ({
  name: 'login-register' as const,
  query: route.query,
}));
const forgotAccountRoute = computed(() => ({
  name: 'login-forgot-account' as const,
  query: route.query,
}));
const forgotPasswordRoute = computed(() => ({
  name: 'login-forgot-password' as const,
  query: route.query,
}));
const loginHelpRoute = computed(() => ({
  name: 'login-help' as const,
  query: route.query,
}));

function applySavedLoginPreferences() {
  const prefs = loadLoginPreferences();
  rememberPassword.value = prefs.rememberPassword;
  autoLogin.value = prefs.autoLogin;
  if (prefs.rememberPassword && prefs.username) {
    username.value = prefs.username;
    password.value = prefs.password;
  }
}

async function tryAutoLogin() {
  if (autoLoginAttempted || loading.value || loginMode.value !== 'password') return;
  if (!autoLogin.value || !rememberPassword.value) return;
  if (!username.value.trim() || !password.value) return;
  autoLoginAttempted = true;
  await submitLogin();
}

onMounted(async () => {
  applySavedLoginPreferences();
  productSku.value = await fetchProductSku();
  document.title = loginPageTitle(productSku.value);
  try {
    const st = await authApi.getOidcStatus();
    oidcEnabled.value = Boolean(st?.data?.enabled);
  } catch {
    oidcEnabled.value = false;
  }
  const oidcOk = route.query.oidc;
  if (oidcOk === 'ok') {
    await completeLoginSuccess({ success: true } as Record<string, unknown>);
    return;
  }
  const oidcErr = route.query.oidc_error;
  if (oidcErr) {
    errorMessage.value = String(route.query.oidc_message || '企业 SSO 登录失败');
    return;
  }
  await tryAutoLogin();
});

onUnmounted(() => {
  stopQrPoll();
});

function stopQrPoll() {
  if (qrPollTimer.value != null) {
    window.clearInterval(qrPollTimer.value);
    qrPollTimer.value = null;
  }
}

async function completeLoginSuccess(raw: Record<string, unknown>) {
  clearHostPackSkippedSession();
  await applyMarketTokensAfterFhdLogin(raw);
  accountProfileStore.applyFromLoginPayload(raw);
  const loginUser =
    raw?.data && typeof raw.data === 'object' && !Array.isArray(raw.data)
      ? (raw.data as Record<string, unknown>)
      : raw;
  const accountUsername = String(loginUser?.username || username.value || phone.value || '').trim();
  const sunbirdAccount = isSunbirdAccountUsername(accountUsername);
  if (isEnterpriseEdition.value || sunbirdAccount) {
    try {
      const { readEntitledModIdsFromAuthPayload, useModsStore } = await import('@/stores/mods');
      const entitled = readEntitledModIdsFromAuthPayload(raw);
      await useModsStore().initialize(true, {
        entitledModIds: entitled,
        forceFromEntitlements: sunbirdAccount || entitled.length > 0,
        accountUsername,
      });
    } catch (modErr) {
      console.warn('[Login] mods refresh after auth:', modErr);
    }
  }
  await router.replace(
    isAdminConsoleSpa() && (redirectPath.value === '/' || !redirectPath.value)
      ? `/${ADMIN_OPERATOR_HOME_ROUTE}`
      : redirectPath.value,
  );
}

function startOidcLogin() {
  window.location.href = '/api/auth/oidc/start';
}

async function sendPhoneCode() {
  if (phone.value.trim().length < 5) {
    errorMessage.value = '请输入有效手机号';
    return;
  }
  sendingCode.value = true;
  errorMessage.value = '';
  try {
    const res = await authApi.sendPhoneCode(phone.value.trim());
    altLoginHint.value = String((res as { message?: string }).message || '验证码已发送');
  } catch (error: unknown) {
    errorMessage.value = error instanceof ApiError ? error.message : '发送验证码失败';
  } finally {
    sendingCode.value = false;
  }
}

async function startQrLogin() {
  stopQrPoll();
  errorMessage.value = '';
  qrDataUrl.value = '';
  try {
    const res = await authApi.issueAuthQr(navigator.userAgent.slice(0, 120));
    const data =
      (res as { data?: Record<string, unknown> }).data ??
      (res as unknown as Record<string, unknown>);
    qrId.value = String(data.qr_id || '');
    qrPollSecret.value = String(data.poll_secret || '');
    qrExpiresAt.value = Number(data.expires_at || 0);
    const payload = `xcagi://auth-qr?qr_id=${encodeURIComponent(qrId.value)}`;
    qrDataUrl.value = await QRCode.toDataURL(payload, { width: 220, margin: 1 });
    qrPollTimer.value = window.setInterval(() => void pollQrStatus(), 2000);
  } catch (error: unknown) {
    errorMessage.value = error instanceof ApiError ? error.message : '无法生成登录二维码';
  }
}

async function pollQrStatus() {
  if (!qrId.value || !qrPollSecret.value) return;
  if (qrCountdown.value <= 0) {
    stopQrPoll();
    errorMessage.value = '二维码已过期，请刷新';
    return;
  }
  try {
    const res = await authApi.pollAuthQr(qrId.value, qrPollSecret.value);
    const data = (res as { data?: Record<string, unknown> }).data || {};
    if (data.status === 'confirmed') {
      stopQrPoll();
      await completeLoginSuccess({ success: true, ...data } as Record<string, unknown>);
    } else if (data.status === 'expired') {
      stopQrPoll();
      errorMessage.value = '二维码已过期，请重新获取';
    }
  } catch {
    /* ignore transient poll errors */
  }
}

function switchLoginMode(mode: 'password' | 'phone' | 'qr') {
  loginMode.value = mode;
  errorMessage.value = '';
  altLoginHint.value = '';
  if (mode === 'qr') {
    void startQrLogin();
  } else {
    stopQrPoll();
    qrDataUrl.value = '';
  }
}

function formatLoginFailurePayload(payload: Record<string, unknown> | null | undefined): string {
  const r = payload && typeof payload === 'object' ? payload : {};
  const errObj = r.error && typeof r.error === 'object' ? (r.error as Record<string, unknown>) : null;
  const errorCode =
    (errObj && typeof errObj.code === 'string' && errObj.code.trim()) ||
    (typeof r.error_code === 'string' && r.error_code.trim()) ||
    '';
  const message =
    (typeof r.message === 'string' && r.message.trim()) ||
    (errObj && typeof errObj.message === 'string' && errObj.message.trim()) ||
    '';
  const errorId = typeof r.error_id === 'string' && r.error_id.trim() ? r.error_id.trim() : '';

  let out = '';
  if (message) {
    out = message;
    if (errorId && !out.includes(errorId)) {
      out = `${out}（错误编号 ${errorId}）`;
    }
  } else if (errorId) {
    out = `登录失败（错误编号 ${errorId}），请联系管理员排查后端日志。`;
  } else {
    out = '登录失败，请检查账号或密码';
  }

  if (
    import.meta.env.DEV &&
    (errorCode === 'MARKET_AUTH_FAILED' || errorCode === 'LOCAL_AUTH_MISMATCH')
  ) {
    out += '。本地开发可试：企业演示 xcagi-enterprise-demo / Demo@2026；平台管理员请点「管理员登录」或访问 /admin/（admin / admin123）。';
  }
  return out;
}

function selectEnterpriseLogin() {
  accountKind.value = 'enterprise';
  altLoginHint.value = '';
  errorMessage.value = '';
}

function selectAdminLogin() {
  const url = resolveAdminConsoleLoginUrl(redirectPath.value);
  window.location.href = url;
}

async function submitLogin() {
  if (!canSubmit.value) {
    errorMessage.value =
      loginMode.value === 'phone' ? '请输入手机号和验证码' : '请输入账号和密码';
    return;
  }
  loading.value = true;
  errorMessage.value = '';
  try {
    const result =
      loginMode.value === 'phone'
        ? await authApi.loginWithPhoneCode(phone.value.trim(), smsCode.value.trim(), accountKind.value)
        : await authApi.login(username.value.trim(), password.value, accountKind.value);
    const raw = result as unknown as Record<string, unknown>;
    const ok = raw?.success === true || (raw?.data as Record<string, unknown> | undefined)?.success === true;
    if (!ok) {
      const nested = (raw?.data as Record<string, unknown> | undefined) || {};
      errorMessage.value = formatLoginFailurePayload({
        ...nested,
        message: raw.message ?? nested.message,
        error_id: raw.error_id ?? nested.error_id,
        error: raw.error ?? nested.error,
      });
      return;
    }
    saveLoginPreferences({
      rememberPassword: rememberPassword.value,
      autoLogin: autoLogin.value,
      username: username.value.trim(),
      password: password.value,
    });
    await completeLoginSuccess(raw);
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      const d = error.data && typeof error.data === 'object' ? (error.data as Record<string, unknown>) : {};
      errorMessage.value = formatLoginFailurePayload({
        ...d,
        message:
          (typeof d.message === 'string' && d.message) ||
          (typeof (d.error as { message?: string } | undefined)?.message === 'string' &&
            (d.error as { message: string }).message) ||
          error.message,
        error_id: d.error_id,
        error: d.error,
      });
    } else {
      const err = error as { response?: { data?: { message?: string; error?: { message?: string } } } };
      const data = err.response?.data;
      errorMessage.value = data?.error?.message || data?.message || '登录失败，请稍后再试';
    }
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-view" aria-label="登录">
    <!-- 左侧品牌区（宽屏） -->
    <aside class="login-brand" aria-hidden="true">
      <div class="login-brand-inner">
        <h2 class="login-brand-name">{{ isAdminConsoleSpa() ? 'XCMAX 服务器后台' : 'XCAGI 企业版' }}</h2>
        <p class="login-brand-desc">
          <template v-if="isAdminConsoleSpa()">平台运维 · 系统管理<br>服务器后台与自动化治理</template>
          <template v-else>智能企业管理平台<br>让 AI 驱动您的业务增长</template>
        </p>
        <ul class="login-brand-features">
          <li>企业级 AI 对话与智能体</li>
          <li>审批工作流与 ERP 集成</li>
          <li>即时通讯与团队协作</li>
        </ul>
      </div>
    </aside>

    <!-- 右侧登录区 -->
    <section class="login-panel" aria-labelledby="login-heading">
      <router-link class="login-register-link" :to="registerRoute">注册账号</router-link>

      <div class="login-panel-inner">
        <h1 id="login-heading" class="login-heading">{{ loginHeading }}</h1>
        <p class="login-subheading" role="note">
          <template v-if="accountKind === 'admin'">管理员账号 · 仅限运营人员</template>
          <template v-else>使用企业账号登录后展示企业品牌</template>
        </p>

        <div v-if="accountKind === 'enterprise'" class="login-mode-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'password' }"
            @click="switchLoginMode('password')"
          >
            账号密码
          </button>
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'phone' }"
            @click="switchLoginMode('phone')"
          >
            手机验证码
          </button>
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'qr' }"
            @click="switchLoginMode('qr')"
          >
            扫码登录
          </button>
        </div>

        <form v-if="loginMode !== 'qr'" class="login-form" @submit.prevent="submitLogin" novalidate>
          <template v-if="loginMode === 'password'">
          <div class="login-field" :class="{ 'is-focused': usernameFocused }">
            <label class="login-label" for="lv-username">账号</label>
            <input
              id="lv-username"
              v-model="username"
              type="text"
              class="login-input"
              name="username"
              autocomplete="username"
              :placeholder="accountPlaceholder"
              :disabled="loading"
              autofocus
              @focus="usernameFocused = true"
              @blur="usernameFocused = false"
            />
          </div>

          <div class="login-field login-field--password" :class="{ 'is-focused': passwordFocused }">
            <label class="login-label" for="lv-password">密码</label>
            <input
              id="lv-password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              class="login-input"
              name="password"
              autocomplete="current-password"
              :placeholder="passwordPlaceholder"
              :disabled="loading"
              @focus="passwordFocused = true"
              @blur="passwordFocused = false"
            />
            <button
              type="button"
              class="login-eye-btn"
              :disabled="loading"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            </button>
          </div>

          <div class="login-options" role="group" aria-label="登录选项">
            <label class="login-option">
              <input
                v-model="autoLogin"
                type="checkbox"
                class="login-option-input"
                :disabled="loading"
              />
              <span>免登录</span>
            </label>
            <label class="login-option">
              <input
                v-model="rememberPassword"
                type="checkbox"
                class="login-option-input"
                :disabled="loading"
              />
              <span>记住密码</span>
            </label>
          </div>
          </template>

          <template v-else>
            <div class="login-field">
              <label class="login-label" for="lv-phone">手机号</label>
              <input
                id="lv-phone"
                v-model="phone"
                type="tel"
                class="login-input"
                autocomplete="tel"
                placeholder="请输入手机号"
                :disabled="loading"
              />
            </div>
            <div class="login-field login-field--sms">
              <div class="login-sms-head">
                <label class="login-label" for="lv-sms-send">验证码</label>
                <button
                  id="lv-sms-send"
                  type="button"
                  class="login-sms-btn login-sms-btn--inline"
                  :disabled="loading || sendingCode"
                  @click="sendPhoneCode"
                >
                  {{ sendingCode ? '发送中' : '获取验证码' }}
                </button>
              </div>
              <OtpCells v-model="smsCode" :disabled="loading" />
            </div>
          </template>

          <transition name="fade">
            <div v-if="errorMessage" class="login-error" role="alert">
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
              <span>{{ errorMessage }}</span>
            </div>
          </transition>

          <button class="login-submit" type="submit" :disabled="!canSubmit || loading">
            <span>{{ loading ? '正在登录…' : '登 录' }}</span>
            <span v-if="loading" class="login-spinner" aria-hidden="true"></span>
            <svg v-else viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
          </button>
        </form>

        <div v-else class="login-qr-panel">
          <p class="login-subheading">请使用 XCAGI Android App 扫描二维码并确认登录</p>
          <img v-if="qrDataUrl" :src="qrDataUrl" alt="登录二维码" class="login-qr-image" width="220" height="220" />
          <p v-if="qrExpiresAt" class="login-hint">剩余 {{ qrCountdown }} 秒 · 过期后请切换 Tab 刷新</p>
          <button type="button" class="login-sso" :disabled="loading" @click="startQrLogin">刷新二维码</button>
        </div>

        <!-- SSO 仅在启用时显示 -->
        <div v-if="oidcEnabled && accountKind === 'enterprise'" class="login-alt">
          <div class="login-divider"><span>或</span></div>
          <button type="button" class="login-sso" :disabled="loading" @click="startOidcLogin">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
            <span>企业 SSO 登录</span>
          </button>
        </div>

        <transition name="fade">
          <p v-if="altLoginHint" class="login-hint" role="status">{{ altLoginHint }}</p>
        </transition>

        <footer class="login-footer">
          <router-link :to="forgotAccountRoute">忘记账号</router-link>
          <span class="login-footer-sep" aria-hidden="true">·</span>
          <router-link :to="forgotPasswordRoute">忘记密码</router-link>
          <span class="login-footer-sep" aria-hidden="true">·</span>
          <router-link :to="loginHelpRoute">帮助</router-link>
        </footer>

        <div v-if="!isAdminConsoleSpa()" class="login-admin-entry">
          <button
            type="button"
            class="login-admin-link"
            :disabled="loading"
            @click="selectAdminLogin"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            管理员登录（独立运维台）
          </button>
        </div>
      </div>
      <img
        class="login-panel-logo"
        :src="`${baseUrl}startup/xc-logo-text.jpg`"
        width="64"
        height="64"
        alt=""
        aria-hidden="true"
        decoding="async"
        style="
          position: absolute;
          right: 28px;
          bottom: 24px;
          width: 64px;
          height: 64px;
          max-width: 64px;
          max-height: 64px;
          object-fit: contain;
          pointer-events: none;
        "
      />
    </section>
  </main>
</template>

<style scoped>
.login-mode-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  align-items: end;
  margin: 4px 0 22px;
  padding: 0;
}
.login-mode-tabs button {
  position: relative;
  justify-self: center;
  min-width: 0;
  padding: 0 4px 10px;
  border: 0;
  border-radius: 0;
  background: transparent;
  font: inherit;
  font-size: 14px;
  line-height: 1.4;
  color: var(--xc-color-muted, #6b7280);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--xc-transition-fast, 0.15s ease);
}
.login-mode-tabs button::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 0;
  width: 0;
  height: 2px;
  border-radius: 1px;
  background: var(--xc-color-primary, #2563eb);
  transform: translateX(-50%);
  transition: width var(--xc-transition-fast, 0.15s ease);
}
.login-mode-tabs button:hover:not(.active):not(:disabled) {
  color: var(--xc-color-text-secondary, #374151);
}
.login-mode-tabs button.active {
  color: var(--xc-color-primary, #2563eb);
  font-weight: var(--xc-font-weight-medium, 500);
}
.login-mode-tabs button.active::after {
  width: 28px;
}
.login-qr-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 8px 0 16px;
}
.login-qr-image {
  border-radius: 8px;
  border: 1px solid var(--xc-color-border, #e5e7eb);
  background: #fff;
}

/* ─── 布局 ─────────────────────────────────────────────── */
.login-view {
  min-height: 100vh;
  display: flex;
  align-items: stretch;
  background: var(--xc-color-page-bg);
}

/* ─── 左侧品牌区 ────────────────────────────────────────── */
.login-brand {
  flex: 0 0 420px;
  background: linear-gradient(145deg, var(--xc-color-primary) 0%, #1565c0 60%, #0a3880 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 48px;
  position: relative;
  overflow: hidden;
}

.login-brand::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 20% 30%, rgba(255,255,255,0.08) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(255,255,255,0.05) 0%, transparent 45%);
  pointer-events: none;
}

.login-brand-inner {
  position: relative;
  z-index: 1;
  color: #fff;
}

.login-brand-name {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 10px;
  letter-spacing: 0.5px;
}

.login-brand-desc {
  font-size: 14px;
  line-height: 1.7;
  margin: 0 0 28px;
  opacity: 0.75;
}

.login-brand-features {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.login-brand-features li {
  font-size: 13px;
  opacity: 0.8;
  display: flex;
  align-items: center;
  gap: 8px;
}

.login-brand-features li::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255,255,255,0.6);
  flex: none;
}

/* ─── 右侧登录面板 ─────────────────────────────────────── */
.login-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  background: var(--xc-color-surface);
  position: relative;
}

.login-register-link {
  position: absolute;
  top: 24px;
  right: 28px;
  font-size: 13px;
  font-weight: 500;
  color: var(--xc-color-primary);
  text-decoration: none;
  padding: 6px 14px;
  border: 1px solid var(--xc-color-primary-soft);
  border-radius: var(--xc-radius-full);
  background: var(--xc-color-primary-surface);
  transition: var(--xc-transition-fast);
}

.login-register-link:hover {
  background: var(--xc-color-primary-soft);
}

.login-panel-inner {
  width: 100%;
  max-width: 380px;
}

.login-panel-logo {
  position: absolute;
  right: 28px;
  bottom: 24px;
  width: 64px;
  height: 64px;
  max-width: 64px;
  max-height: 64px;
  object-fit: contain;
  pointer-events: none;
  user-select: none;
}

.login-heading {
  margin: 0 0 6px;
  font-size: var(--xc-font-2xl);
  font-weight: var(--xc-font-weight-bold);
  color: var(--xc-color-text);
  letter-spacing: -0.3px;
}

/* 交付说明：标题下介绍文案保留，UI 迭代时勿整段删除 */
.login-subheading {
  margin: 0 0 28px;
  font-size: var(--xc-font-sm);
  color: var(--xc-color-muted);
  line-height: 1.65;
}

/* ─── 表单字段 ─────────────────────────────────────────── */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}

.login-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.login-label {
  font-size: var(--xc-font-sm);
  font-weight: var(--xc-font-weight-medium);
  color: var(--xc-color-text-secondary);
}

.login-input {
  width: 100%;
  height: 44px;
  padding: 0 var(--xc-space-3);
  border: 1.5px solid var(--xc-color-border);
  border-radius: var(--xc-radius-md);
  background: var(--xc-color-surface-3);
  color: var(--xc-color-text);
  font: inherit;
  font-size: var(--xc-font-md);
  outline: none;
  transition: border-color var(--xc-transition-fast), box-shadow var(--xc-transition-fast), background var(--xc-transition-fast);
}

.login-input::placeholder {
  color: var(--xc-color-disabled);
}

.login-input:focus {
  border-color: var(--xc-color-primary);
  background: var(--xc-color-surface);
  box-shadow: 0 0 0 3px var(--xc-color-primary-soft);
}

.login-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-field--password {
  position: relative;
}

.login-field--password .login-input {
  padding-right: 44px;
}

.login-options {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: -4px;
}

.login-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xc-font-sm);
  color: var(--xc-color-text-secondary);
  cursor: pointer;
  user-select: none;
}

.login-option-input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--xc-color-primary, #2563eb);
  cursor: pointer;
}

.login-option:has(.login-option-input:disabled) {
  opacity: 0.55;
  cursor: not-allowed;
}

.login-eye-btn {
  position: absolute;
  right: 12px;
  bottom: 14px;
  width: 20px;
  height: 20px;
  border: 0;
  background: transparent;
  color: var(--xc-color-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: color var(--xc-transition-fast);
}

.login-eye-btn:hover:not(:disabled) {
  color: var(--xc-color-text);
}

.login-sms-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.login-sms-row {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.login-input--sms {
  flex: 1;
  min-width: 0;
  padding-right: var(--xc-space-3);
}

.login-sms-btn--inline {
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
}

.login-sms-btn {
  flex: none;
  height: 44px;
  padding: 0 14px;
  border: 1.5px solid var(--xc-color-primary);
  border-radius: var(--xc-radius-md);
  background: var(--xc-color-primary-surface);
  color: var(--xc-color-primary);
  font: inherit;
  font-size: 13px;
  font-weight: var(--xc-font-weight-medium);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--xc-transition-fast), border-color var(--xc-transition-fast), color var(--xc-transition-fast);
}

.login-sms-btn:hover:not(:disabled) {
  background: var(--xc-color-primary-soft);
  border-color: var(--xc-color-primary-light);
}

.login-sms-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ─── 错误提示 ─────────────────────────────────────────── */
.login-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--xc-radius-md);
  background: var(--xc-color-danger-bg);
  border: 1px solid rgba(192, 57, 43, 0.2);
  font-size: var(--xc-font-sm);
  color: var(--xc-color-danger);
  line-height: 1.5;
}

.login-error svg {
  flex: none;
  margin-top: 1px;
}

/* ─── 提交按钮 ─────────────────────────────────────────── */
.login-submit {
  margin-top: 8px;
  width: 100%;
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 0 var(--xc-space-4);
  border: 0;
  border-radius: var(--xc-radius-md);
  background: var(--xc-color-primary);
  color: #fff;
  font: inherit;
  font-size: var(--xc-font-md);
  font-weight: var(--xc-font-weight-semibold);
  cursor: pointer;
  letter-spacing: 2px;
  transition: background var(--xc-transition-fast), box-shadow var(--xc-transition-fast), transform var(--xc-transition-fast);
  box-shadow: 0 2px 12px rgba(13, 71, 161, 0.3);
}

.login-submit:hover:not(:disabled) {
  background: var(--xc-color-primary-light);
  box-shadow: 0 4px 20px rgba(13, 71, 161, 0.4);
  transform: translateY(-1px);
}

.login-submit:active:not(:disabled) {
  transform: translateY(0);
  background: var(--xc-color-primary-hover);
}

.login-submit:disabled {
  cursor: not-allowed;
  opacity: 0.5;
  box-shadow: none;
  transform: none;
}

.login-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ─── SSO ──────────────────────────────────────────────── */
.login-alt {
  margin-bottom: 20px;
}

.login-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  color: var(--xc-color-disabled);
  font-size: var(--xc-font-xs);
}

.login-divider::before,
.login-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--xc-color-border);
}

.login-sso {
  width: 100%;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1.5px solid var(--xc-color-border);
  border-radius: var(--xc-radius-md);
  background: var(--xc-color-surface);
  color: var(--xc-color-text-secondary);
  font: inherit;
  font-size: var(--xc-font-md);
  cursor: pointer;
  transition: var(--xc-transition-fast);
}

.login-sso:hover:not(:disabled) {
  border-color: var(--xc-color-primary);
  color: var(--xc-color-primary);
  background: var(--xc-color-primary-surface);
}

.login-sso:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ─── 辅助文字 ─────────────────────────────────────────── */
.login-hint {
  margin: -10px 0 16px;
  font-size: var(--xc-font-sm);
  color: var(--xc-color-muted);
  text-align: center;
  line-height: 1.5;
}

/* ─── 底部链接 ─────────────────────────────────────────── */
.login-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 4px 10px;
  font-size: var(--xc-font-sm);
  padding-top: var(--xc-space-4);
  border-top: 1px solid var(--xc-color-border);
}

.login-footer a {
  color: var(--xc-color-muted);
  text-decoration: none;
  transition: color var(--xc-transition-fast);
}

.login-footer a:hover {
  color: var(--xc-color-primary);
}

.login-footer-sep {
  color: var(--xc-color-border-strong);
}

/* ─── 管理员入口 ────────────────────────────────────────── */
.login-admin-entry {
  margin-top: var(--xc-space-3);
  text-align: center;
}

.login-admin-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  background: transparent;
  padding: 4px 8px;
  font: inherit;
  font-size: var(--xc-font-sm);
  color: var(--xc-color-disabled);
  cursor: pointer;
  border-radius: var(--xc-radius-sm);
  transition: color var(--xc-transition-fast), background var(--xc-transition-fast);
}

.login-admin-link:hover:not(:disabled) {
  color: var(--xc-color-primary);
  background: var(--xc-color-primary-surface);
}

.login-admin-link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ─── 动画 ──────────────────────────────────────────────── */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 200ms ease, transform 200ms ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ─── 响应式 ────────────────────────────────────────────── */
@media (max-width: 768px) {
  .login-brand {
    display: none;
  }
  .login-panel {
    justify-content: flex-start;
    padding-top: 80px;
  }
}

@media (max-width: 480px) {
  .login-panel {
    padding: 60px 16px 32px;
  }
  .login-register-link {
    right: 16px;
    top: 16px;
  }
  .login-panel-logo {
    right: 16px;
    bottom: 16px;
  }
}
</style>

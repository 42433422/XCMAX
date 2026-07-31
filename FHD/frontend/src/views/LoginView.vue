<script setup lang="ts">
import './LoginView.extracted.css'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import QRCode from 'qrcode';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { ApiError } from '@/api';
import { authApi } from '@/api/auth';
import { applyMarketTokensAfterFhdLogin } from '@/api/marketAccount';
import {
  loginAccountInputPlaceholder,
  loginPageTitle,
  loginPasswordInputPlaceholder,
} from '@/constants/loginBranding';
import { fetchProductSku } from '@/utils/productSku';
import { useAccountProfileStore } from '@/stores/accountProfile';
import {
  DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
  isAdminConsoleSpa,
  resolveAdminConsoleLoginUrl,
} from '@/utils/adminConsoleUrl';
import { isDesktopShell } from '@/utils/desktopShell';
import { ADMIN_OPERATOR_HOME_ROUTE } from '@/constants/adminOperatorNav';
import type { AccountKind } from '@/api/auth';
import { loadLoginPreferences, saveLoginPreferences } from '@/utils/loginPreferences';
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate';
import OtpCells from '@/components/OtpCells.vue';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const accountProfileStore = useAccountProfileStore();

const username = ref('');
const accountKind = ref<AccountKind>(isAdminConsoleSpa() ? 'admin' : 'enterprise');
const password = ref('');
const mfaCode = ref('');
const mfaRequired = ref(false);
const showPassword = ref(false);
const loading = ref(false);
/** 桌面壳：隐藏「管理员登录」入口（管理端仅网页 SSOT） */
const showAdminEntry = computed(() => !isAdminConsoleSpa() && !isDesktopShell());
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
  if (mfaRequired.value && mfaCode.value.trim().length !== 6) return false;
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
  accountKind.value === 'admin' ? t('login.headingAdmin') : t('login.headingEnterprise'),
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
  if (isAdminConsoleSpa()) {
    saveLoginPreferences({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    });
    return;
  }
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

let loginViewActive = true;

onMounted(async () => {
  applySavedLoginPreferences();
  const sku = await fetchProductSku();
  if (!loginViewActive) return;
  productSku.value = sku;
  if (typeof document !== 'undefined') {
    document.title = loginPageTitle(productSku.value);
  }
  try {
    const st = await authApi.getOidcStatus();
    if (!loginViewActive) return;
    oidcEnabled.value = Boolean(st?.data?.enabled);
  } catch {
    if (!loginViewActive) return;
    oidcEnabled.value = false;
  }
  const oidcOk = route.query.oidc;
  if (oidcOk === 'ok') {
    await completeLoginSuccess({ success: true } as Record<string, unknown>);
    return;
  }
  const oidcErr = route.query.oidc_error;
  if (oidcErr) {
    errorMessage.value = String(route.query.oidc_message || t('login.errSsoFailed'));
    return;
  }
  const gateError = route.query.error;
  if (typeof gateError === 'string' && gateError.trim()) {
    errorMessage.value = gateError.trim();
  }
  await tryAutoLogin();
});

onUnmounted(() => {
  loginViewActive = false;
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
  accountProfileStore.applyFromLoginPayload(raw);
  // SSOT：桌面壳禁止管理员会话（派生 account_kind=admin 时拒入）。
  // 管理端 SPA（:5011）本身就是网页运维台，不得套用桌面禁令。
  if (!isAdminConsoleSpa() && isDesktopShell() && accountProfileStore.isAdminAccount) {
    try {
      await authApi.logout().catch(() => undefined);
    } catch {
      /* ignore */
    }
    errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE;
    return;
  }
  const loginUser =
    raw?.data && typeof raw.data === 'object' && !Array.isArray(raw.data)
      ? (raw.data as Record<string, unknown>)
      : raw;
  const accountUsername = String(loginUser?.username || username.value || phone.value || '').trim();
  await router.replace(
    isAdminConsoleSpa() && (redirectPath.value === '/' || !redirectPath.value)
      ? `/${ADMIN_OPERATOR_HOME_ROUTE}`
      : redirectPath.value,
  );

  // Token handoff and MOD discovery are optional post-login bootstrap work.
  // They must never hold the login button in "正在登录" or delay the first
  // usable ERP screen when the market/MOD service is slow or offline.
  if (!isAdminConsoleSpa()) {
    void applyMarketTokensAfterFhdLogin(raw).catch((marketErr) => {
      console.warn('[Login] market token handoff after auth:', marketErr);
    });
  }
  if (isEnterpriseEdition.value) {
    void (async () => {
      try {
        const { readEntitledModIdsFromAuthPayload, useModsStore } = await import('@/stores/mods');
        const entitled = readEntitledModIdsFromAuthPayload(raw);
        await useModsStore().initialize(true, {
          entitledModIds: entitled,
          forceFromEntitlements: entitled.length > 0,
          accountUsername,
        });
      } catch (modErr) {
        console.warn('[Login] mods refresh after auth:', modErr);
      }
    })();
  }
}

function startOidcLogin() {
  window.location.href = '/api/auth/oidc/start';
}

async function sendPhoneCode() {
  if (phone.value.trim().length < 5) {
    errorMessage.value = t('login.errInvalidPhone');
    return;
  }
  sendingCode.value = true;
  errorMessage.value = '';
  try {
    const res = await authApi.sendPhoneCode(phone.value.trim());
    altLoginHint.value = String((res as { message?: string }).message || t('login.errCodeSent'));
  } catch (error: unknown) {
    errorMessage.value = error instanceof ApiError ? error.message : t('login.errSendCodeFailed');
  } finally {
    sendingCode.value = false;
  }
}

async function startQrLogin() {
  stopQrPoll();
  errorMessage.value = '';
  qrDataUrl.value = '';
  try {
    const res = await authApi.issueAuthQr(navigator.userAgent.slice(0, 120), accountKind.value);
    const data =
      (res as { data?: Record<string, unknown> }).data ??
      (res as unknown as Record<string, unknown>);
    qrId.value = String(data.qr_id || '');
    qrPollSecret.value = String(data.poll_secret || '');
    qrExpiresAt.value = Number(data.expires_at || 0);
    const qrAccountKind = String(data.account_kind || accountKind.value || 'enterprise');
    const payload =
      `xcagi://auth-qr?qr_id=${encodeURIComponent(qrId.value)}` +
      `&account_kind=${encodeURIComponent(qrAccountKind)}`;
    qrDataUrl.value = await QRCode.toDataURL(payload, { width: 220, margin: 1 });
    qrPollTimer.value = window.setInterval(() => void pollQrStatus(), 2000);
  } catch (error: unknown) {
    errorMessage.value = error instanceof ApiError ? error.message : t('login.errQrGenerateFailed');
  }
}

async function pollQrStatus() {
  if (!qrId.value || !qrPollSecret.value) return;
  if (qrCountdown.value <= 0) {
    stopQrPoll();
    errorMessage.value = t('login.errQrExpired');
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
      errorMessage.value = t('login.errQrExpiredRetry');
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
      out = `${out}${t('login.errIdSuffix', { id: errorId })}`;
    }
  } else if (errorId) {
    out = t('login.errWithId', { id: errorId });
  } else {
    out = t('login.errLoginFailed');
  }

  if (
    import.meta.env.DEV &&
    (errorCode === 'MARKET_AUTH_FAILED' || errorCode === 'LOCAL_AUTH_MISMATCH')
  ) {
    out += t('login.devHint');
  }
  return out;
}

function selectEnterpriseLogin() {
  accountKind.value = 'enterprise';
  altLoginHint.value = '';
  errorMessage.value = '';
}

function selectAdminLogin() {
  // 桌面端禁止进管理端（防御：入口已隐藏，仍拦截直调）
  if (isDesktopShell()) {
    errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE;
    return;
  }
  const url = resolveAdminConsoleLoginUrl(redirectPath.value);
  if (!url) {
    errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE;
    return;
  }
  window.location.href = url;
}

async function submitLogin() {
  if (!canSubmit.value) {
    errorMessage.value =
      loginMode.value === 'phone' ? t('login.errNeedPhoneAndCode') : t('login.errNeedUsernamePassword');
    return;
  }
  loading.value = true;
  errorMessage.value = '';
  try {
    const result =
      loginMode.value === 'phone'
        ? await authApi.loginWithPhoneCode(phone.value.trim(), smsCode.value.trim(), accountKind.value)
        : await authApi.login(
            username.value.trim(),
            password.value,
            accountKind.value,
            mfaRequired.value ? mfaCode.value.trim() : '',
          );
    const raw = result as unknown as Record<string, unknown>;
    const ok = raw?.success === true || (raw?.data as Record<string, unknown> | undefined)?.success === true;
    if (!ok) {
      const nested = (raw?.data as Record<string, unknown> | undefined) || {};
      mfaRequired.value = Boolean(raw.mfa_required ?? nested.mfa_required);
      errorMessage.value = formatLoginFailurePayload({
        ...nested,
        message: raw.message ?? nested.message,
        error_id: raw.error_id ?? nested.error_id,
        error: raw.error ?? nested.error,
      });
      return;
    }
    saveLoginPreferences({
      rememberPassword: !isAdminConsoleSpa() && rememberPassword.value,
      autoLogin: !isAdminConsoleSpa() && autoLogin.value,
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
      errorMessage.value = data?.error?.message || data?.message || t('login.errLoginFailedRetry');
    }
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-view" :aria-label="$t('login.pageAria')">
    <!-- 左侧品牌区（宽屏） -->
    <aside class="login-brand" aria-hidden="true">
      <div class="login-brand-inner">
        <h2 class="login-brand-name">{{ isAdminConsoleSpa() ? $t('login.brandAdmin') : $t('login.brandEnterprise') }}</h2>
        <p class="login-brand-desc">
          <template v-if="isAdminConsoleSpa()">{{ $t('login.brandAdminDesc') }}<br>{{ $t('login.brandAdminDesc2') }}</template>
          <template v-else>{{ $t('login.brandEnterpriseDesc') }}<br>{{ $t('login.brandEnterpriseDesc2') }}</template>
        </p>
        <ul class="login-brand-features">
          <li>{{ $t('login.featureAi') }}</li>
          <li>{{ $t('login.featureWorkflow') }}</li>
          <li>{{ $t('login.featureIm') }}</li>
        </ul>
      </div>
    </aside>

    <!-- 右侧登录区 -->
    <section class="login-panel" aria-labelledby="login-heading">
      <router-link class="login-register-link" :to="registerRoute">{{ $t('login.register') }}</router-link>

      <div class="login-panel-inner">
        <h1 id="login-heading" class="login-heading">{{ loginHeading }}</h1>
        <p class="login-subheading" role="note">
          <template v-if="accountKind === 'admin'">{{ $t('login.subheadingAdmin') }}</template>
          <template v-else>{{ $t('login.subheadingEnterprise') }}</template>
        </p>

        <div v-if="accountKind === 'enterprise'" class="login-mode-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'password' }"
            @click="switchLoginMode('password')"
          >
            {{ $t('login.tabPassword') }}
          </button>
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'phone' }"
            @click="switchLoginMode('phone')"
          >
            {{ $t('login.tabPhone') }}
          </button>
          <button
            type="button"
            role="tab"
            :class="{ active: loginMode === 'qr' }"
            @click="switchLoginMode('qr')"
          >
            {{ $t('login.tabQr') }}
          </button>
        </div>

        <form v-if="loginMode !== 'qr'" class="login-form" @submit.prevent="submitLogin" novalidate>
          <template v-if="loginMode === 'password'">
          <div class="login-field" :class="{ 'is-focused': usernameFocused }">
            <label class="login-label" for="lv-username">{{ $t('login.labelUsername') }}</label>
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
            <label class="login-label" for="lv-password">{{ $t('login.labelPassword') }}</label>
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
              :aria-label="showPassword ? $t('login.hidePassword') : $t('login.showPassword')"
              @click="showPassword = !showPassword"
            >
              <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            </button>
          </div>

          <div v-if="mfaRequired" class="login-field">
            <label class="login-label" for="lv-mfa-code">{{ $t('login.labelMfaCode') }}</label>
            <input
              id="lv-mfa-code"
              v-model="mfaCode"
              class="login-input"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              maxlength="6"
              :placeholder="$t('login.mfaCodePlaceholder')"
              :disabled="loading"
            />
          </div>

          <div
            v-if="!isAdminConsoleSpa()"
            class="login-options"
            role="group"
            :aria-label="$t('login.loginOptions')"
          >
            <label class="login-option">
              <input
                v-model="autoLogin"
                type="checkbox"
                class="login-option-input"
                :disabled="loading"
              />
              <span>{{ $t('login.autoLogin') }}</span>
            </label>
            <label class="login-option">
              <input
                v-model="rememberPassword"
                type="checkbox"
                class="login-option-input"
                :disabled="loading"
              />
              <span>{{ $t('login.rememberPassword') }}</span>
            </label>
          </div>
          </template>

          <template v-else>
            <div class="login-field">
              <label class="login-label" for="lv-phone">{{ $t('login.labelPhone') }}</label>
              <input
                id="lv-phone"
                v-model="phone"
                type="tel"
                class="login-input"
                autocomplete="tel"
                :placeholder="$t('login.phonePlaceholder')"
                :disabled="loading"
              />
            </div>
            <div class="login-field login-field--sms">
              <div class="login-sms-head">
                <label class="login-label" for="lv-sms-send">{{ $t('login.labelSmsCode') }}</label>
                <button
                  id="lv-sms-send"
                  type="button"
                  class="login-sms-btn login-sms-btn--inline"
                  :disabled="loading || sendingCode"
                  @click="sendPhoneCode"
                >
                  {{ sendingCode ? $t('login.sendingCode') : $t('login.getSmsCode') }}
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
            <span>{{ loading ? $t('login.submitting') : $t('login.submit') }}</span>
            <span v-if="loading" class="login-spinner" aria-hidden="true"></span>
            <svg v-else viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
          </button>
        </form>

        <div v-else class="login-qr-panel">
          <p class="login-subheading">{{ $t('login.qrHint') }}</p>
          <img v-if="qrDataUrl" :src="qrDataUrl" :alt="$t('login.qrAlt')" class="login-qr-image" width="220" height="220" />
          <p v-if="qrExpiresAt" class="login-hint">{{ $t('login.qrCountdown', { seconds: qrCountdown }) }}</p>
          <button type="button" class="login-sso" :disabled="loading" @click="startQrLogin">{{ $t('login.refreshQr') }}</button>
        </div>

        <!-- SSO 仅在启用时显示 -->
        <div v-if="oidcEnabled && accountKind === 'enterprise'" class="login-alt">
          <div class="login-divider"><span>{{ $t('login.orDivider') }}</span></div>
          <button type="button" class="login-sso" :disabled="loading" @click="startOidcLogin">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
            <span>{{ $t('login.ssoLogin') }}</span>
          </button>
        </div>

        <transition name="fade">
          <p v-if="altLoginHint" class="login-hint" role="status">{{ altLoginHint }}</p>
        </transition>

        <footer class="login-footer">
          <router-link :to="forgotAccountRoute">{{ $t('login.forgotAccount') }}</router-link>
          <span class="login-footer-sep" aria-hidden="true">·</span>
          <router-link :to="forgotPasswordRoute">{{ $t('login.forgotPassword') }}</router-link>
          <span class="login-footer-sep" aria-hidden="true">·</span>
          <router-link :to="loginHelpRoute">{{ $t('login.help') }}</router-link>
        </footer>

        <div v-if="showAdminEntry" class="login-admin-entry">
          <button
            type="button"
            class="login-admin-link"
            :disabled="loading"
            @click="selectAdminLogin"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            {{ $t('login.adminEntry') }}
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



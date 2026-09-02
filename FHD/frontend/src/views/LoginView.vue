<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authApi } from '@/api/auth'
import { loginPageTitle } from '@/constants/loginBranding'
import { fetchProductSku } from '@/utils/productSku'
import { isDesktopShell } from '@/utils/desktopShell'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { canResumeRecentDesktopSession } from '@/utils/authSessionCache'
import OtpCells from '@/components/OtpCells.vue'
import LoginAccountActions from '@/components/login/LoginAccountActions.vue'
import { useLoginViewState } from './login-view/useLoginViewState'
import { useLoginViewMeta } from './login-view/useLoginViewMeta'
import { useLoginViewSession } from './login-view/useLoginViewSession'
import { useLoginViewQr } from './login-view/useLoginViewQr'
import { useLoginViewActions } from './login-view/useLoginViewActions'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// 逻辑按领域拆分到 login-view/ 下的 composables，此处仅组装（模板与拆分前逐字一致）
const state = useLoginViewState(route)
const meta = useLoginViewMeta(state)
const session = useLoginViewSession(state, { router })
const qr = useLoginViewQr(state, { completeLoginSuccess: session.completeLoginSuccess })
const actions = useLoginViewActions(state, { qr, completeLoginSuccess: session.completeLoginSuccess })

const {
  username,
  accountKind,
  password,
  showPassword,
  loading,
  errorMessage,
  altLoginHint,
  oidcEnabled,
  loginMode,
  phone,
  smsCode,
  sendingCode,
  qrDataUrl,
  qrPollTimer,
  qrExpiresAt,
  qrId,
  qrPollSecret,
  usernameFocused,
  passwordFocused,
  rememberPassword,
  autoLogin,
  redirectPath,
  canSubmit,
  qrCountdown,
  productSku,
  baseUrl,
  isEnterpriseEdition,
  showAdminEntry,
} = state

const {
  loginHeading,
  accountPlaceholder,
  passwordPlaceholder,
  forgotAccountRoute,
  forgotPasswordRoute,
  loginHelpRoute,
} = meta

const { stopQrPoll, startQrLogin, pollQrStatus } = qr
const {
  applySavedLoginPreferences,
  tryAutoLogin,
  sendPhoneCode,
  switchLoginMode,
  formatLoginFailurePayload,
  selectEnterpriseLogin,
  selectAdminLogin,
  submitLogin,
  startOidcLogin,
} = actions
const { completeLoginSuccess } = session

let loginViewActive = true

onMounted(async () => {
  applySavedLoginPreferences()
  const sku = await fetchProductSku()
  if (!loginViewActive) return
  productSku.value = sku
  if (typeof document !== 'undefined') document.title = loginPageTitle(productSku.value)
  if (await canResumeRecentDesktopSession(isDesktopShell(), isEnterpriseEdition.value, route.query))
    return void router.replace(redirectPath.value)
  try {
    const st = await authApi.getOidcStatus()
    if (!loginViewActive) return
    oidcEnabled.value = Boolean(st?.data?.enabled)
  } catch {
    if (!loginViewActive) return
    oidcEnabled.value = false
  }
  const oidcOk = route.query.oidc
  if (oidcOk === 'ok') {
    await completeLoginSuccess({ success: true } as Record<string, unknown>)
    return
  }
  const oidcErr = route.query.oidc_error
  if (oidcErr) {
    errorMessage.value = String(route.query.oidc_message || t('login.errSsoFailed'))
    return
  }
  const gateError = route.query.error
  if (typeof gateError === 'string' && gateError.trim()) {
    errorMessage.value = gateError.trim()
  }
  await tryAutoLogin()
})

onUnmounted(() => {
  loginViewActive = false
  stopQrPoll()
})
</script>

<template>
  <main class="login-view" :aria-label="$t('login.pageAria')">
    <!-- 左侧品牌区（宽屏） -->
    <aside class="login-brand" aria-hidden="true">
      <div class="login-brand-inner">
        <h2 class="login-brand-name">
          {{ isAdminConsoleSpa() ? $t('login.brandAdmin') : $t('login.brandEnterprise') }}
        </h2>
        <p class="login-brand-desc">
          <template v-if="isAdminConsoleSpa()">{{ $t('login.brandAdminDesc') }}<br />{{ $t('login.brandAdminDesc2') }}</template>
          <template v-else>{{ $t('login.brandEnterpriseDesc') }}<br />{{ $t('login.brandEnterpriseDesc2') }}</template>
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
      <LoginAccountActions v-if="!isAdminConsoleSpa()" :enterprise="isEnterpriseEdition" />

      <div class="login-panel-inner">
        <h1 id="login-heading" class="login-heading">{{ loginHeading }}</h1>
        <p class="login-subheading" role="note">
          <template v-if="accountKind === 'admin'">{{ $t('login.subheadingAdmin') }}</template>
          <template v-else>{{ $t('login.subheadingEnterprise') }}</template>
        </p>

        <div v-if="accountKind === 'enterprise'" class="login-mode-tabs" role="tablist">
          <button type="button" role="tab" :class="{ active: loginMode === 'password' }" @click="switchLoginMode('password')">
            {{ $t('login.tabPassword') }}
          </button>
          <button type="button" role="tab" :class="{ active: loginMode === 'phone' }" @click="switchLoginMode('phone')">
            {{ $t('login.tabPhone') }}
          </button>
          <button type="button" role="tab" :class="{ active: loginMode === 'qr' }" @click="switchLoginMode('qr')">
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
                <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                  <path
                    d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"
                  />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
            </div>

            <div class="login-options" role="group" :aria-label="$t('login.loginOptions')">
              <label class="login-option">
                <input v-model="autoLogin" type="checkbox" class="login-option-input" :disabled="loading" />
                <span>{{ $t('login.autoLogin') }}</span>
              </label>
              <label class="login-option">
                <input v-model="rememberPassword" type="checkbox" class="login-option-input" :disabled="loading" />
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
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                <path
                  fill-rule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clip-rule="evenodd"
                />
              </svg>
              <span>{{ errorMessage }}</span>
            </div>
          </transition>

          <button class="login-submit" type="submit" :disabled="!canSubmit || loading">
            <span>{{ loading ? $t('login.submitting') : $t('login.submit') }}</span>
            <span v-if="loading" class="login-spinner" aria-hidden="true"></span>
            <svg v-else viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path
                fill-rule="evenodd"
                d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
        </form>

        <div v-else class="login-qr-panel">
          <p class="login-subheading">{{ $t('login.qrHint') }}</p>
          <img v-if="qrDataUrl" :src="qrDataUrl" :alt="$t('login.qrAlt')" class="login-qr-image" width="220" height="220" />
          <p v-if="qrExpiresAt" class="login-hint">
            {{ $t('login.qrCountdown', { seconds: qrCountdown }) }}
          </p>
          <button type="button" class="login-sso" :disabled="loading" @click="startQrLogin">
            {{ $t('login.refreshQr') }}
          </button>
        </div>

        <!-- SSO 仅在启用时显示 -->
        <div v-if="oidcEnabled && accountKind === 'enterprise'" class="login-alt">
          <div class="login-divider">
            <span>{{ $t('login.orDivider') }}</span>
          </div>
          <button type="button" class="login-sso" :disabled="loading" @click="startOidcLogin">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
              <polyline points="10 17 15 12 10 7" />
              <line x1="15" y1="12" x2="3" y2="12" />
            </svg>
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
          <button type="button" class="login-admin-link" :disabled="loading" @click="selectAdminLogin">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
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

<style scoped src="./login-view/login-view.css"></style>

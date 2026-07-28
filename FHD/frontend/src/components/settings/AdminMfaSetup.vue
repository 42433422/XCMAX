<template>
  <section class="admin-mfa" aria-labelledby="admin-mfa-title">
    <div class="admin-mfa__status">
      <div>
        <h3 id="admin-mfa-title">管理员动态验证</h3>
        <p>使用认证器生成一次性验证码，保护管理端登录。</p>
      </div>
      <span :class="{ enabled: mfaEnabled }">
        {{ mfaEnabled ? '已启用' : '未启用' }}
      </span>
    </div>

    <p v-if="error" class="admin-mfa__error" role="alert">{{ error }}</p>
    <p v-if="message" class="admin-mfa__message" role="status">{{ message }}</p>

    <button
      v-if="!mfaEnabled && !setupSecret"
      type="button"
      class="admin-mfa__button"
      :disabled="loading"
      @click="startSetup"
    >
      {{ loading ? '正在生成...' : '绑定认证器' }}
    </button>

    <div v-if="setupSecret" class="admin-mfa__setup">
      <img v-if="qrDataUrl" :src="qrDataUrl" alt="管理员 MFA 绑定二维码">
      <div class="admin-mfa__setup-fields">
        <label>
          <span>绑定密钥</span>
          <input :value="setupSecret" type="text" readonly>
        </label>
        <label>
          <span>动态验证码</span>
          <input
            v-model="verificationCode"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="6"
            placeholder="6 位验证码"
          >
        </label>
        <button
          type="button"
          class="admin-mfa__button"
          :disabled="loading || verificationCode.length !== 6"
          @click="enableMfa"
        >
          {{ loading ? '正在校验...' : '确认启用' }}
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { authApi } from '@/api/auth'

const loading = ref(false)
const mfaEnabled = ref(false)
const setupSecret = ref('')
const qrDataUrl = ref('')
const verificationCode = ref('')
const error = ref('')
const message = ref('')

function responseError(value: unknown, fallback: string): string {
  if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>
    if (typeof row.message === 'string' && row.message.trim()) return row.message
  }
  return fallback
}

async function refreshStatus(): Promise<void> {
  try {
    const response = await authApi.getCurrentUser()
    const payload = response?.data
    mfaEnabled.value = Boolean(payload?.user?.mfa_enabled)
  } catch (cause) {
    error.value = responseError(cause, '无法读取管理员安全状态')
  }
}

async function startSetup(): Promise<void> {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await authApi.setupMfa()
    if (!response?.success || !response.data?.secret || !response.data?.otpauth_uri) {
      throw new Error(response?.message || '生成 MFA 密钥失败')
    }
    setupSecret.value = response.data.secret
    qrDataUrl.value = await QRCode.toDataURL(response.data.otpauth_uri, {
      width: 220,
      margin: 1,
      errorCorrectionLevel: 'M',
    })
  } catch (cause) {
    error.value = responseError(cause, '生成 MFA 密钥失败')
  } finally {
    loading.value = false
  }
}

async function enableMfa(): Promise<void> {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const response = await authApi.enableMfa(verificationCode.value)
    if (!response?.success) throw new Error(response?.message || '动态验证码校验失败')
    mfaEnabled.value = true
    setupSecret.value = ''
    qrDataUrl.value = ''
    verificationCode.value = ''
    message.value = 'MFA 已启用，下次登录需要输入动态验证码'
  } catch (cause) {
    error.value = responseError(cause, '动态验证码校验失败')
  } finally {
    loading.value = false
  }
}

onMounted(refreshStatus)
</script>

<style scoped>
.admin-mfa {
  width: 100%;
  padding: 16px;
}

.admin-mfa__status {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.admin-mfa h3,
.admin-mfa p {
  margin: 0;
}

.admin-mfa h3 {
  font-size: 15px;
}

.admin-mfa__status p {
  margin-top: 6px;
  color: #65758b;
  font-size: 13px;
}

.admin-mfa__status > span {
  flex: none;
  padding: 4px 8px;
  border-radius: 4px;
  color: #9a3412;
  background: #ffedd5;
  font-size: 12px;
  font-weight: 700;
}

.admin-mfa__status > span.enabled {
  color: #166534;
  background: #dcfce7;
}

.admin-mfa__button {
  margin-top: 14px;
  border: 0;
  border-radius: 6px;
  padding: 9px 14px;
  color: #fff;
  background: #315dd8;
  font-weight: 700;
  cursor: pointer;
}

.admin-mfa__button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.admin-mfa__setup {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
  margin-top: 16px;
}

.admin-mfa__setup img {
  width: 220px;
  height: 220px;
}

.admin-mfa__setup-fields {
  display: grid;
  align-content: start;
  gap: 12px;
}

.admin-mfa__setup-fields label,
.admin-mfa__setup-fields span {
  display: block;
}

.admin-mfa__setup-fields span {
  margin-bottom: 5px;
  color: #475569;
  font-size: 12px;
}

.admin-mfa__setup-fields input {
  width: 100%;
  min-height: 38px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 8px 10px;
}

.admin-mfa__error,
.admin-mfa__message {
  margin-top: 12px !important;
  font-size: 13px;
}

.admin-mfa__error {
  color: #b42318;
}

.admin-mfa__message {
  color: #166534;
}

@media (max-width: 640px) {
  .admin-mfa__setup {
    grid-template-columns: 1fr;
  }
}
</style>

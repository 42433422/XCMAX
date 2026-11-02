<template>
  <div v-if="status" class="chat-model-recovery" role="alert">
    <span>{{ status }}</span>
    <button v-if="needsRecovery" type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="followPlatform">
      {{ loading ? '正在恢复…' : '恢复平台默认模型' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import chatApi from '@/api/chat'
import { PLATFORM_MODEL_CHANGED_EVENT, PLATFORM_MODEL_CHANGED_KEY } from '@/api/platformModel'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const props = withDefaults(defineProps<{ scopeKey?: string }>(), { scopeKey: '' })
const status = ref(''), needsRecovery = ref(false), loading = ref(false)
let active = true, epoch = 0

async function check() {
  if (!active || loading.value) return
  const request = ++epoch, isCurrentAccount = captureAuthSession()
  const current = () => active && request === epoch && isCurrentAccount()
  status.value = ''; needsRecovery.value = false
  try {
    const result = await chatApi.getModelStatus()
    if (current() && result?.ok !== true) throw { status: 400, data: result }
  } catch (error) {
    if (!current()) return
    const err = error as { status?: number; data?: { code?: string; detail?: { code?: string } } }
    needsRecovery.value = ['INVALID_CHAT_PREFERENCE', 'NO_BYOK_CHAT_MODEL'].includes(err?.data?.detail?.code || err?.data?.code || '')
    status.value = needsRecovery.value ? '个人模型选择暂不可用。' : ''
  }
}

async function followPlatform() {
  if (!active || loading.value || !needsRecovery.value) return
  const request = ++epoch, isCurrentAccount = captureAuthSession()
  const current = () => active && request === epoch && isCurrentAccount()
  loading.value = true
  try {
    const result = await chatApi.followPlatformModel()
    if (!current()) return
    if (!result?.ok) throw new Error('preference not saved')
    status.value = ''; needsRecovery.value = false
  } catch {
    if (current()) status.value = '恢复未确认，请稍后重试。'
  } finally { if (current()) loading.value = false }
}

function reset() { epoch++; status.value = ''; needsRecovery.value = loading.value = false; void check() }
function retire() { active = false; epoch++; status.value = ''; needsRecovery.value = loading.value = false }
const onStorage = (event: StorageEvent) => { if (event.key === PLATFORM_MODEL_CHANGED_KEY) void check() }
watch(() => [getAuthSessionEpoch(), productReadAccountEpoch.value, props.scopeKey], reset, { immediate: true, flush: 'sync' })
window.addEventListener(PLATFORM_MODEL_CHANGED_EVENT, check)
window.addEventListener('storage', onStorage)
onDeactivated(retire)
onActivated(() => { if (!active) { active = true; reset() } })
onBeforeUnmount(() => { retire(); window.removeEventListener(PLATFORM_MODEL_CHANGED_EVENT, check); window.removeEventListener('storage', onStorage) })
</script>

<style scoped>
.chat-model-recovery { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 4px 2px; color: var(--app-text-muted, #667085); font-size: 12px; line-height: 1.5; }
</style>

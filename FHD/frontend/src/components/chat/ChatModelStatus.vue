<template>
  <details ref="panel" class="chat-model-status" data-testid="chat-model-status">
    <summary>{{ failed ? '模型配置需检查' : '模型信息' }}</summary>
    <p role="status">{{ status }}</p>
    <p v-if="model">当前解析默认：{{ provider }} / {{ model }}。选路：{{ chatRouteSourceLabel(routeSource) }}；凭据来源：{{ chatKeySourceLabel(keySource) }}；配置版本：{{ revision || '未提供' }}。</p>
    <p v-if="actual" data-testid="actual-model-route">{{ actual.route_state === 'completed' ? '上一模型请求实际返回' : actual.route_state === 'failed' ? '上次模型调用失败' : '已选择模型，未收到完成回执（含中断）' }}：{{ actual.provider }} / {{ actual.model }}。选路：{{ chatRouteSourceLabel(actual.route_source) }}；凭据来源：{{ chatKeySourceLabel(actual.key_source) }}；配置版本：{{ actual.config_revision || '未提供' }}。</p>
    <p v-else>本会话尚无实际模型回执。默认解析不代表请求已执行。</p>
    <p>跟随平台会在下一请求读取最新配置；个人显式选择和 BYOK 独立保留。平台模型由管理员在服务器统一维护。</p>
    <template v-if="invalidPreference">
      <p>个人模型选择不能用于聊天。可重新选择聊天模型，或主动改为跟随平台；后者使用平台额度并保留个人 BYOK 配置。</p>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="followPlatform">改为跟随平台（使用平台额度）</button>
    </template>
    <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">{{ loading ? '正在查询…' : '重新查询平台模型' }}</button>
  </details>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import chatApi from '@/api/chat'
import { PLATFORM_MODEL_CHANGED_EVENT, PLATFORM_MODEL_CHANGED_KEY } from '@/api/platformModel'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { lastChatModelRoute, chatRouteSourceLabel, chatKeySourceLabel } from '@/utils/chatModelRoute'

const props = withDefaults(defineProps<{ sessionId?: string; modId?: string }>(), { sessionId: 'default', modId: '' })
const panel = ref<HTMLDetailsElement | null>(null)
const provider = ref(''), model = ref(''), routeSource = ref(''), keySource = ref(''), revision = ref<string | null>(null)
const status = ref('正在查询平台模型…'), loading = ref(false), failed = ref(false), invalidPreference = ref(false)
const actual = computed(() => lastChatModelRoute(props.sessionId, resolveChatIdentity(props.modId)))
let active = true, epoch = 0
async function refresh() {
  if (!active) return
  const request = ++epoch, isCurrentAccount = captureAuthSession()
  const current = () => active && request === epoch && isCurrentAccount()
  provider.value = model.value = routeSource.value = keySource.value = ''
  revision.value = null
  status.value = '正在查询平台模型…'
  loading.value = true; failed.value = invalidPreference.value = false
  try {
    const route = await chatApi.getModelStatus()
    if (!current()) return
    if (route?.ok !== true || !route.provider?.trim() || !route.model?.trim()) throw { status: 400, data: route }
    provider.value = route.provider.trim(); model.value = route.model.trim()
    routeSource.value = route.route_source || ''; keySource.value = route.key_source || ''; revision.value = route.config_revision || null
    status.value = '服务器已解析当前默认；实际调用以回执为准。'
  } catch (error) {
    if (!current()) return
    const err = error as { status?: number; data?: { code?: string; detail?: { code?: string } } }
    const code = Number(err?.status)
    invalidPreference.value = ['INVALID_CHAT_PREFERENCE', 'NO_BYOK_CHAT_MODEL'].includes(err?.data?.detail?.code || err?.data?.code || '')
    failed.value = true
    status.value = invalidPreference.value ? '个人模型选择不适用于聊天，请重新选择或恢复跟随平台。'
      : code === 400 ? '平台尚无可用模型配置，请联系管理员检查服务器模型设置。'
        : code === 401 || code === 403 ? '无法查询平台模型：请核对本机会话或联系管理员检查模型服务授权。'
          : '平台模型状态暂时无法查询，请重试或联系管理员检查服务。'
  } finally { if (current()) loading.value = false }
}
async function followPlatform() {
  if (loading.value || !invalidPreference.value || !active) return
  const request = ++epoch, isCurrentAccount = captureAuthSession()
  const current = () => active && request === epoch && isCurrentAccount()
  loading.value = true
  try {
    const result = await chatApi.followPlatformModel()
    if (!current()) return
    if (!result.ok) throw new Error('preference not saved')
    await refresh()
  } catch {
    if (current()) { status.value = '模型选择未确认保存，请重新查询后再试。'; failed.value = true }
  } finally { if (current()) loading.value = false }
}
function retire() { active = false; epoch++; provider.value = model.value = ''; loading.value = false }
const onStorage = (event: StorageEvent) => { if (event.key === PLATFORM_MODEL_CHANGED_KEY) void refresh() }
watch(() => [getAuthSessionEpoch(), productReadAccountEpoch.value, props.modId], () => { if (panel.value) panel.value.open = false; void refresh() }, { immediate: true, flush: 'sync' })
window.addEventListener(PLATFORM_MODEL_CHANGED_EVENT, refresh)
window.addEventListener('storage', onStorage)
onDeactivated(retire)
onActivated(() => { if (!active) { active = true; void refresh() } })
onBeforeUnmount(() => { retire(); window.removeEventListener(PLATFORM_MODEL_CHANGED_EVENT, refresh); window.removeEventListener('storage', onStorage) })
defineExpose({ refreshAndReveal() { if (panel.value) panel.value.open = true; void refresh(); panel.value?.scrollIntoView?.({ block: 'nearest' }) } })
</script>

<style scoped>
.chat-model-status { padding: 4px 2px; color: var(--app-text-muted, #667085); font-size: 12px; line-height: 1.4; }
</style>

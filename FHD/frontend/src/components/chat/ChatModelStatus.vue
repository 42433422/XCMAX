<template>
  <details ref="panel" class="chat-model-status" data-testid="chat-model-status">
    <summary role="status">{{ status }}</summary>
    <p v-if="model">默认对话模型：{{ provider }} / {{ model }}。服务器已解析当前账户的默认对话模型；个人显式选择或直连配置可能覆盖，本次请求实际采用的模型尚未核实，尚未发起模型生成测试。</p>
    <p>平台模型由管理员在服务器统一维护。本地服务健康状态与平台模型状态分别检查。</p>
    <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">{{ loading ? '正在查询…' : '重新查询平台模型' }}</button>
  </details>
</template>

<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import chatApi from '@/api/chat'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const panel = ref<HTMLDetailsElement | null>(null)
const provider = ref(''), model = ref(''), status = ref('正在查询平台模型…'), loading = ref(false)
let active = true, epoch = 0
async function refresh() {
  if (!active) return
  const request = ++epoch, isCurrentAccount = captureAuthSession()
  const current = () => active && request === epoch && isCurrentAccount()
  provider.value = model.value = ''
  status.value = '正在查询平台模型…'
  loading.value = true
  try {
    const route = await chatApi.getModelStatus()
    if (!current()) return
    if (route?.ok !== true || !route.provider?.trim() || !route.model?.trim()) throw new Error('Unresolved model')
    provider.value = route.provider.trim(); model.value = route.model.trim()
    status.value = `默认对话模型：${provider.value} / ${model.value}（服务器已解析）`
  } catch (error) {
    if (!current()) return
    const code = Number((error as { status?: number })?.status)
    status.value = code === 400 ? '平台尚无可用模型配置，请联系管理员检查服务器模型设置。'
      : code === 401 || code === 403 ? '无法查询平台模型：请核对本机会话或联系管理员检查模型服务授权。'
        : '平台模型状态暂时无法查询，请重试或联系管理员检查服务。'
  } finally { if (current()) loading.value = false }
}
function retire() { active = false; epoch++; provider.value = model.value = ''; loading.value = false }
watch(() => [getAuthSessionEpoch(), productReadAccountEpoch.value], refresh, { immediate: true, flush: 'sync' })
onDeactivated(retire)
onActivated(() => { if (!active) { active = true; void refresh() } })
onBeforeUnmount(retire)
defineExpose({ refreshAndReveal() { if (panel.value) panel.value.open = true; void refresh(); panel.value?.scrollIntoView?.({ block: 'nearest' }) } })
</script>

<style scoped>
.chat-model-status { padding: 4px 2px; color: var(--app-text-muted, #667085); font-size: 12px; line-height: 1.4; }
</style>

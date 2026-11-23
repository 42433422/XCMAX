<template>
  <section class="kellai-composer" aria-label="人工确认发送消息">
    <label>
      收件渠道与联系人
      <select v-model="selectedKey" :disabled="locked || messagesLoading" aria-label="收件渠道与联系人">
        <option value="">请选择已核验的联系人</option>
        <option v-for="target in targets" :key="target.key" :value="target.key">
          {{ target.name }} · {{ target.channel.name }} · {{ target.contact_id }}
        </option>
      </select>
    </label>
    <p v-if="!targets.length">当前会话没有已连接且支持发送的联系人。请在连接与账号中查看渠道能力。</p>
    <template v-if="target">
      <textarea v-model="content" :disabled="locked" maxlength="10000" rows="3" aria-label="消息内容" placeholder="输入要发送的消息，确认接收人后发送" />
      <div class="kellai-composer__actions">
        <button v-if="copilotDraft?.status === 'approved_for_manual_send'" type="button" :disabled="locked" @click="useDraft">使用已批准草稿</button>
        <button type="button" :disabled="locked || !content.trim() || !target.channel.connected" @click="send">确认发送给 {{ target.name }}</button>
      </div>
    </template>
    <div v-for="item in customerReceipts" :key="item.key" class="kellai-composer__receipt" role="status">
      <strong>{{ receiptLabel(item.state) }}</strong>
      <small>{{ item.channel }} · {{ item.contact }}</small>
      <span v-if="item.state === 'accepted'">渠道已受理；尚无送达确认。</span>
      <span v-if="item.state === 'sent'">平台已确认发出；尚无送达确认。</span>
      <span v-if="item.state === 'unknown' || item.state === 'sending'">请查询原请求回执，暂不重复发送。</span>
      <span v-if="item.state === 'requires_desktop_execution'">此渠道需要在客来来桌面端执行。</span>
      <span v-if="item.delivery.receipt.error || item.delivery.error">{{ item.delivery.receipt.error || item.delivery.error }}</span>
      <span v-if="item.delivery.receipt.persisted === false">发送记录尚未同步到会话，请保留此回执。</span>
      <small>请求 {{ item.delivery.request_id }}</small>
      <small v-if="item.delivery.receipt.provider_message_id">渠道凭据 {{ item.delivery.receipt.provider_message_id }}</small>
      <button type="button" :disabled="item.delivery.checking" @click="store.queryReceipt(item.key)">{{ item.delivery.checking ? '查询中…' : '查询回执' }}</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { KellaiSendReceipt } from '@/api/kellaiBinding'
import { deliveryTargetKey, useKellaiStore } from '@/stores/kellai'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const store = useKellaiStore()
const { activeCustomerId, activeCustomer, channels, messages, copilotDraft, deliveries, blockedTargets, messagesLoading } = storeToRefs(store)
const selectedKey = ref('')
const content = ref('')
const customerReceipts = computed(() => Object.entries(deliveries.value).flatMap(([key, delivery]) => {
  try {
    const [customerId, channel, contact] = JSON.parse(delivery.target_key)
    return customerId === activeCustomerId.value ? [{ key, channel, contact, delivery, state: receiptState(delivery.receipt) }] : []
  } catch { return [] }
}))
const targets = computed(() => {
  const seen = new Set<string>()
  return messages.value.flatMap(message => {
    const channel = channels.value.find(item => item.type === message.channel_type)
    if (!channel?.enabled || !channel.connected || !channel.capabilities.send || !message.contact_id || !activeCustomerId.value) return []
    const input = { customer_id: activeCustomerId.value, channel_type: channel.type, contact_id: message.contact_id }
    const key = deliveryTargetKey(input)
    if (seen.has(key)) return []
    seen.add(key)
    return [{ ...input, key, channel, name: message.contact_name || activeCustomer.value?.display_name || message.contact_id }]
  })
})
const target = computed(() => targets.value.find(item => item.key === selectedKey.value))
const locked = computed(() => blockedTargets.value.has(selectedKey.value))

watch([activeCustomerId, productReadAccountEpoch], () => { selectedKey.value = ''; content.value = '' }, { flush: 'sync' })
watch(targets, (items) => {
  if (!items.some(item => item.key === selectedKey.value)) selectedKey.value = items.length === 1 ? items[0].key : ''
}, { immediate: true })
function useDraft(): void {
  if (!locked.value && copilotDraft.value?.status === 'approved_for_manual_send') content.value = copilotDraft.value.reply_draft
}
async function send(): Promise<void> {
  if (!target.value || locked.value || !content.value.trim()) return
  const selected = target.value
  const text = content.value.trim()
  const requestId = await store.submitMessage({ customer_id: selected.customer_id, channel_type: selected.channel_type, contact_id: selected.contact_id, content: text })
  if (requestId && selectedKey.value === selected.key && content.value.trim() === text && ['accepted', 'delivered'].includes(deliveries.value[requestId]?.receipt.status)) {
    content.value = ''
    await store.loadMessages(selected.customer_id)
  }
}
function receiptLabel(status: string): string {
  return ({ sending: '发送处理中', accepted: '渠道已受理', sent: '渠道确认已发出', delivered: '渠道确认送达', read: '渠道确认已读', unknown: '发送结果未知', failed: '发送失败', rejected: '请求未获准', requires_desktop_execution: '需要桌面执行' } as Record<string, string>)[status] || `渠道状态：${status}`
}
function receiptState(receipt: KellaiSendReceipt): string {
  // Ledger acceptance and verified provider progress are separate contracts.
  // An uncertain ledger entry cannot be promoted by an unbound provider field.
  return receipt.status === 'accepted' && ['sent', 'delivered', 'read', 'failed'].includes(receipt.provider_state || '')
    ? receipt.provider_state!
    : receipt.status
}
</script>

<style scoped>
.kellai-composer { display: grid; gap: 10px; padding: 16px; border-top: 1px solid var(--el-border-color-light, #e2e8f0); }
.kellai-composer label { display: grid; gap: 6px; font-size: 13px; }
.kellai-composer textarea, .kellai-composer select { width: 100%; box-sizing: border-box; padding: 9px; border: 1px solid var(--el-border-color, #cbd5e1); border-radius: 8px; background: var(--el-bg-color, #fff); color: inherit; font: inherit; }
.kellai-composer button { cursor: pointer; border: 1px solid var(--el-border-color, #cbd5e1); background: var(--el-bg-color, #fff); color: inherit; border-radius: 6px; padding: 7px 12px; }
.kellai-composer button:disabled { cursor: not-allowed; opacity: .55; }
.kellai-composer__actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.kellai-composer__receipt { display: grid; gap: 6px; padding: 10px; background: var(--el-fill-color-light, #f1f5f9); border-radius: 8px; overflow-wrap: anywhere; }
.kellai-composer p, .kellai-composer small { margin: 0; color: var(--el-text-color-secondary, #64748b); font-size: 12px; }
</style>

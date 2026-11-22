<template>
  <section class="kellai-inbox" aria-labelledby="kellai-inbox-title">
    <header v-if="!embedded" class="kellai-inbox__head">
      <span class="kellai-inbox__avatar" aria-hidden="true">客</span>
      <div class="kellai-inbox__heading">
        <h2 id="kellai-inbox-title">统一聊天 · 客来来</h2>
        <p>外部账号、联系人和消息由本机工具连接；发送前确认账号与接收人。</p>
      </div>
      <span :class="['kellai-inbox__status', `is-${binding.state}`]">{{ statusLabel }}</span>
      <button type="button" class="kellai-inbox__button is-quiet" :disabled="busy" @click="refreshAll">
        刷新
      </button>
    </header>

    <div v-if="error" class="kellai-inbox__error" role="alert">{{ error }}</div>

    <div v-if="binding.state !== 'connected'" class="kellai-inbox__connect">
      <div class="kellai-inbox__connect-copy">
        <h3>{{ binding.state === 'pending' ? '等待客来来确认授权' : '连接客来来账号工具' }}</h3>
        <p v-if="binding.message">{{ binding.message }}</p>
        <p v-if="binding.state === 'revoked'">原授权已撤销，请重新确认连接；历史发送请求保留用于核对。</p>
        <p>
          授权范围由当前 XCMAX 账号确认。第三方凭据保留在本机工具，AI 通过已授权连接执行。
        </p>
        <ul v-if="binding.available_scopes?.length">
          <li v-for="scope in binding.available_scopes.filter(item => KELLAI_READ_SCOPES.includes(item.id))" :key="scope.id">
            <strong>{{ scope.label }}</strong>
            <span>{{ scope.description }}</span>
          </li>
        </ul>
      </div>
      <div class="kellai-inbox__connect-actions">
        <button type="button" class="kellai-inbox__button is-primary" :disabled="busy" @click="startBinding()">
          {{ busy ? '正在处理…' : binding.state === 'pending' ? '重新打开授权页' : '绑定客来来' }}
        </button>
        <button type="button" class="kellai-inbox__button" :disabled="busy" @click="handleOpenKellai">
          打开客来来
        </button>
      </div>
    </div>

    <template v-else>
      <div class="kellai-inbox__summary">
        <span>{{ contacts.length }} 个联系人映射</span>
        <span>{{ binding.connection?.authorized_scopes?.length || 0 }} 项授权权限</span>
        <span v-if="binding.connection?.authorized_by?.display_name">
          由 {{ binding.connection.authorized_by.display_name }} 授权
        </span>
        <button type="button" class="kellai-inbox__link" :disabled="busy" @click="disconnect">
          解除绑定
        </button>
      </div>

      <div class="kellai-inbox__workspace">
        <aside class="kellai-inbox__contacts" aria-label="外部联系人列表">
          <div v-if="contactsLoading" class="kellai-inbox__empty">正在读取联系人…</div>
          <template v-else>
            <button
              v-for="customer in contacts"
              :key="`${customer.connection_id}:${customer.customer_id}`"
              type="button"
              :class="['kellai-inbox__customer', { active: customer.customer_id === activeContactId && customer.connection_id === activeConnectionId }]"
              @click="selectContact(customer)"
            >
              <span class="kellai-inbox__customer-avatar" aria-hidden="true">{{ avatarText(customer.contact_name) }}</span>
              <span class="kellai-inbox__customer-main">
                <strong>{{ customer.contact_name }}</strong>
                <small>{{ `${channelLabel([customer.channel_type])} · ${customer.connection_id}` }}</small>
                <em>{{ customer.contact_id }}</em>
              </span>
            </button>
          </template>
          <div v-if="!contactsLoading && !contacts.length" class="kellai-inbox__empty">
            <p>{{ scopes.includes('messages.read') ? '暂无联系人。请在客来来选择账号添加联系人，或同步收件箱后刷新。' : '尚未授权读取联系人和消息，请在连接与账号中更新授权。' }}</p>
            <button v-if="scopes.includes('messages.read')" type="button" class="kellai-inbox__button" @click="handleOpenKellai">打开客来来</button>
          </div>
        </aside>

        <main class="kellai-inbox__conversation">
          <header v-if="activeContact" class="kellai-inbox__conversation-head">
            <div>
              <h3>{{ activeContact.contact_name }}</h3>
              <p>
                {{ channelLabel([activeContact.channel_type]) }} · {{ activeContact.connection_id }}
              </p>
            </div>
            <span class="kellai-inbox__readonly">{{ canSend ? '人工确认发送' : '只读' }}</span>
          </header>

          <div v-if="messagesLoading" class="kellai-inbox__empty is-center">正在读取会话…</div>
          <div v-else-if="activeContact && orderedMessages.length" class="kellai-inbox__messages">
            <article
              v-for="message in orderedMessages"
              :key="message.id"
              :class="['kellai-inbox__message-row', message.direction === 'outbound' ? 'mine' : 'theirs']"
            >
              <div class="kellai-inbox__message">
                <span>{{ message.direction === 'outbound' ? '我方' : message.contact_name || activeContact.contact_name }}</span>
                <img
                  v-if="messageImageSrc(message)"
                  class="kellai-inbox__message-image"
                  :src="messageImageSrc(message)"
                  :alt="message.content || '客户图片'"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                />
                <p v-else-if="isImagePlaceholder(message.content)" class="kellai-inbox__image-fallback">
                  [图片]（暂无预览地址）
                </p>
                <p v-else>{{ message.content }}</p>
                <footer>
                  <small>{{ message.channel_type || '客户渠道' }}</small>
                  <time>{{ formatTime(message.created_at) }}</time>
                </footer>
              </div>
            </article>
          </div>
          <div v-else class="kellai-inbox__empty is-center">
            {{ activeContact ? '该联系人暂无可读取的消息' : '从左侧选择账号下的联系人查看消息' }}
          </div>

          <KellaiMessageComposer v-if="activeContact && canSend" />

          <footer class="kellai-inbox__guardrail">
            <i class="fa fa-shield" aria-hidden="true"></i>
            AI 任务统一使用 XCMAX 的工具审批和结果核验。未知发送只查询原回执。
          </footer>
        </main>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { KELLAI_READ_SCOPES, useKellaiStore } from '@/stores/kellai'
import KellaiMessageComposer from './kellaiInbox/KellaiMessageComposer.vue'
import { avatarText, channelLabel, formatTime, isImagePlaceholder, messageImageSrc } from './kellaiInbox/kellaiInboxShared'

defineProps<{ embedded?: boolean }>()
const store = useKellaiStore()
const {
  binding, contacts, activeContactId, activeConnectionId, busy, contactsLoading, messagesLoading,
  error, statusLabel, activeContact, orderedMessages, canSend, scopes,
} = storeToRefs(store)
const { refreshAll, selectContact, startBinding, disconnect, handleOpenKellai } = store
onMounted(store.attach)
onBeforeUnmount(store.detach)
</script>

<style scoped src="./KellaiCustomerInbox.css"></style>

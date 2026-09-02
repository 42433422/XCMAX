<template>
  <div class="cs-page">
    <header class="cs-head">
      <div class="cs-head__main">
        <h1>AI 客服</h1>
        <p>直接说问题就行；需要跟进时会帮你建工单，并在右侧显示进度</p>
      </div>
    </header>

    <section class="cs-layout">
      <main class="cs-chat">
        <div class="cs-toolbar">
          <div class="cs-toolbar__left">
            <b>对话</b>
            <span class="cs-muted">{{ activeSessionId ? '进行中' : '新会话' }}</span>
          </div>
          <button type="button" class="cs-btn cs-btn--ghost" @click="newSession">新会话</button>
        </div>

        <div ref="messagesEl" class="cs-messages">
          <article v-for="msg in messages" :key="msg.id" :class="['cs-message', `cs-message--${msg.role}`]">
            <div class="cs-bubble">
              <p
                v-if="msg.content && msg.content !== '[用户补充了图片资料]'"
                class="cs-bubble__text"
                v-html="renderCsBubbleHtml(msg.content)"
                @click="onBubbleClick($event, msg)"
              />
              <p v-else-if="msg.imageDataUrl" class="cs-bubble__text">已附上图片</p>
              <img v-if="msg.imageDataUrl" :src="msg.imageDataUrl" alt="补充图片" class="cs-bubble__img" />
            </div>
          </article>

          <div v-if="messages.length === 0" class="cs-empty">
            <p class="cs-empty__title">先说说你遇到的问题，也可以点下面的示例开始</p>
            <div class="cs-chips">
              <button v-for="chip in quickPrompts" :key="chip" type="button" class="cs-chip" @click="usePrompt(chip)">
                {{ chip }}
              </button>
            </div>
          </div>
        </div>

        <form class="cs-composer" @submit.prevent="send">
          <input ref="imageInputRef" type="file" accept="image/*" class="cs-image-input" @change="onImagePicked" />
          <div v-if="pendingImageDataUrl" class="cs-attach">
            <img :src="pendingImageDataUrl" alt="待发送图片预览" class="cs-attach__preview" />
            <button type="button" class="cs-link" @click="clearPendingImage">移除图片</button>
          </div>
          <p v-if="imagePickError" class="cs-error cs-attach-error">{{ imagePickError }}</p>
          <textarea
            v-model="draft"
            rows="2"
            placeholder="尽量带上订单号、说明；也可点「图片」上传截图补充材料…"
            @keydown.meta.enter.prevent="send"
            @keydown.ctrl.enter.prevent="send"
          />
          <div class="cs-composer__footer">
            <div class="cs-composer__left">
              <button type="button" class="cs-btn cs-btn--ghost" :disabled="loading || imagePicking" @click="openImagePicker">
                {{ imagePicking ? '处理中…' : '图片' }}
              </button>
              <span :class="{ 'cs-error': !!error }">{{ error || 'Enter 换行 · ⌘/Ctrl+Enter 发送' }}</span>
            </div>
            <button type="submit" class="cs-btn" :disabled="loading || imagePicking || (!draft.trim() && !pendingImageDataUrl)">
              {{ loading ? '处理中…' : '发送' }}
            </button>
          </div>
        </form>
      </main>

      <CsTicketPanel
        :tickets="tickets"
        :expanded-ids="expandedTicketIds"
        :all-tickets-expanded="allTicketsExpanded"
        @toggle-all="toggleAllTickets"
        @refresh="loadTickets"
        @open="openTicket"
        @toggle="toggleTicket"
      />
    </section>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./customer-service/，样式在 ./customer-service/customer-service.css。
import { useRoute } from 'vue-router'
import { renderCsBubbleHtml } from '../utils/csBubbleText'
import CsTicketPanel from './customer-service/CsTicketPanel.vue'
import * as csHelpers from './customer-service/customerServiceHelpers'
import { useCustomerServiceChat } from './customer-service/useCustomerServiceChat'
import { useCustomerServiceImage } from './customer-service/useCustomerServiceImage'
import { useCustomerServiceTickets } from './customer-service/useCustomerServiceTickets'

const route = useRoute()

const image = useCustomerServiceImage()
const {
  pendingImageDataUrl, imagePickError, imagePicking, imageInputRef,
  openImagePicker, clearPendingImage, onImagePicked,
} = image

const ticketStore = useCustomerServiceTickets()
const { tickets, expandedTicketIds, allTicketsExpanded, toggleTicket, toggleAllTickets, loadTickets } = ticketStore

const {
  draft, loading, error, activeSessionId, messages, messagesEl, quickPrompts,
  usePrompt, send, sendText, onBubbleClick, newSession, visibleCards, openTicket,
} = useCustomerServiceChat({
  route,
  pendingImageDataUrl,
  imagePicking,
  clearPendingImage,
  loadTickets,
  expandedTicketIds,
})

// 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const shortLifeLabel = csHelpers.shortLifeLabel
const friendlyTicketTitle = csHelpers.friendlyTicketTitle
/* eslint-enable @typescript-eslint/no-unused-vars */

defineExpose({ visibleCards })
</script>

<style scoped src="./customer-service/customer-service.css"></style>

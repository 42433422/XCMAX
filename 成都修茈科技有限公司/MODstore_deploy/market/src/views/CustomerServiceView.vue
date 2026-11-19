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
            <span class="cs-muted">{{ openedTicketRef || (activeSessionId ? '进行中' : '新会话') }}</span>
          </div>
          <button type="button" class="cs-btn cs-btn--ghost" @click="newSession">新会话</button>
        </div>

        <div ref="messagesEl" class="cs-messages">
          <article v-for="msg in messages" :key="msg.id" :class="['cs-message', `cs-message--${msg.role}`]">
            <div class="cs-bubble">
              <span v-if="msg.receiptLabel" class="cs-muted">{{ msg.receiptLabel }}</span>
              <p
                v-if="!openedTicketRef && msg.role === 'assistant' && msg.content"
                class="cs-bubble__text"
                v-html="renderCsBubbleHtml(msg.content)"
                @click="onBubbleClick($event, msg)"
              />
              <p v-else-if="msg.content && msg.content !== '[用户补充了图片资料]'" class="cs-bubble__text">{{ msg.content }}</p>
              <p v-else-if="msg.imageDataUrl || msg.content === '[用户补充了图片资料]'" class="cs-bubble__text">已附上图片</p>
              <img v-if="msg.imageDataUrl" :src="msg.imageDataUrl" alt="补充图片" class="cs-bubble__img" />
              <button
                v-if="intakeConfirmation?.message === msg"
                type="button"
                class="cs-btn cs-btn--ghost cs-bubble__confirmation"
                @click="confirmIntake(msg)"
              >
                {{ intakeConfirmation.intake.kind === 'invalid'
                  ? '确认仅为演练、未实际发生并提交工单'
                  : '确认仅涉及与平台无关的事项并提交工单' }}
              </button>
            </div>
          </article>

          <p v-if="openedTicketRef && loading && !messages.length" class="cs-muted" role="status">正在读取原客服会话…</p>
          <div v-if="!openedTicketRef && messages.length === 0" class="cs-empty">
            <p class="cs-empty__title">先说说你遇到的问题，也可以点下面的示例开始</p>
            <div class="cs-chips">
              <button v-for="chip in quickPrompts" :key="chip" type="button" class="cs-chip" @click="usePrompt(chip)">
                {{ chip }}
              </button>
            </div>
          </div>
        </div>

        <section v-if="showDecision" class="cs-composer" aria-label="原工单验收">
          <label v-if="showDecisionNote" for="cs-decision-note">原问题现在的使用结果（至少 4 个字）</label>
          <textarea
            v-if="showDecisionNote"
            id="cs-decision-note"
            v-model="decisionNote"
            rows="2"
            maxlength="2000"
            :disabled="decisionBusy"
          />
          <p v-if="decisionNotice" class="cs-muted" role="status">{{ decisionNotice }}</p>
          <p v-if="acceptanceNeedsRefresh && !decisionBusy" class="cs-muted" role="status">暂未刷新验收状态，请先核对原工单。</p>
          <div class="cs-decision-actions">
            <button v-if="acceptanceNeedsRefresh" type="button" class="cs-btn cs-btn--ghost" :disabled="decisionBusy" @click="refreshAcceptance">
              核对验收状态
            </button>
            <template v-else-if="pendingDecision">
              <button type="button" class="cs-btn cs-btn--ghost" :disabled="decisionBusy" @click="checkDecision">核对原工单</button>
              <button
                v-if="pendingDecision.decision === 'resolved' ? canResolve : canReopen"
                type="button" class="cs-btn" :disabled="decisionBusy || !validDecisionNote"
                @click="submitDecision(pendingDecision.decision)"
              >按原请求重试</button>
            </template>
            <template v-else>
              <button v-if="canResolve" type="button" class="cs-btn" :disabled="decisionBusy || !validDecisionNote" @click="submitDecision('resolved')">
                确认问题已解决
              </button>
              <button v-if="canReopen" type="button" class="cs-btn cs-btn--ghost" :disabled="decisionBusy || !validDecisionNote" @click="submitDecision('reopen')">
                问题仍存在，重新处理
              </button>
            </template>
          </div>
        </section>

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
            :disabled="readOnly || decisionBusy"
            placeholder="尽量带上订单号、说明；也可点「图片」上传截图补充材料…"
            @keydown.meta.enter.prevent="send"
            @keydown.ctrl.enter.prevent="send"
          />
          <div class="cs-composer__footer">
            <div class="cs-composer__left">
              <button type="button" class="cs-btn cs-btn--ghost" :disabled="readOnly || decisionBusy || imagePicking" @click="openImagePicker">
                {{ imagePicking ? '处理中…' : '图片' }}
              </button>
              <span :class="{ 'cs-error': !!error }">{{ error || (readOnly ? '仅查看原会话' : 'Enter 换行 · ⌘/Ctrl+Enter 发送') }}</span>
            </div>
            <button type="submit" class="cs-btn" :disabled="readOnly || decisionBusy || imagePicking || (!draft.trim() && !pendingImageDataUrl)">
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
import { useCustomerServiceDecision } from './customer-service/useCustomerServiceDecision'
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

const chat = useCustomerServiceChat({
  route,
  pendingImageDataUrl,
  imagePicking,
  clearPendingImage,
  loadTickets,
  expandedTicketIds,
})
const {
  draft, loading, error, activeSessionId, openedTicketRef, readOnly, messages, messagesEl, quickPrompts,
  usePrompt, send, sendText, confirmIntake, intakeConfirmation, onBubbleClick, newSession, visibleCards, openTicket,
  acceptanceNeedsRefresh, refreshAcceptance,
} = chat
const {
  note: decisionNote, notice: decisionNotice, pending: pendingDecision, busy: decisionBusy,
  visible: showDecision, validNote: validDecisionNote, canResolve, canReopen, checkDecision, submitDecision,
  showNote: showDecisionNote,
} = useCustomerServiceDecision(chat, loadTickets)

// 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const shortLifeLabel = csHelpers.shortLifeLabel
const friendlyTicketTitle = csHelpers.friendlyTicketTitle
/* eslint-enable @typescript-eslint/no-unused-vars */

defineExpose({ visibleCards })
</script>

<style scoped src="./customer-service/customer-service.css"></style>

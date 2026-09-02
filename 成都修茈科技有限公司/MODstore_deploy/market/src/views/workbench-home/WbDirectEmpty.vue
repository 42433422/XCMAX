<script setup lang="ts">
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 218–271 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  wbSidebar, showDirectChatSurface, directMessages, homeStarterCards, homeSuggestionChips, recentHomeConversations,
  applyStarterPrompt, pickHomeConversation, formatHomeConvTime, titleEnterDone, contentEnter, directTitleTw,
  directSubTw,
} = props.wb
</script>

<template>
              <div
                v-if="!directMessages.length"
                class="wb-direct-empty-body"
                :class="{ 'wb-content-enter': contentEnter }"
              >
              <div class="wb-direct-empty-columns">
              <div class="wb-direct-empty-stack">
              <div class="wb-direct-empty-title" :class="{ 'wb-title-enter': titleEnterDone }">
                <h1 :key="'direct-' + wbSidebar.activeMode" class="wb-direct-title">{{ directTitleTw.displayed.value }}</h1>
                <p :key="'sub-' + wbSidebar.activeMode" class="wb-direct-sub">{{ directSubTw.displayed.value }}<span v-if="directSubTw.isTyping.value" class="wb-cursor">▌</span></p>
              </div>
              <div v-if="showDirectChatSurface" class="wb-direct-starters">
                <p class="wb-direct-starters__section-title">试试这些</p>
                <div class="wb-direct-starters__cards">
                  <button
                    v-for="card in homeStarterCards"
                    :key="card.label"
                    type="button"
                    class="wb-direct-starter-card"
                    @click="applyStarterPrompt(card.prompt, { requiresAttachment: card.requiresAttachment, label: card.label })"
                  >
                    <span class="wb-direct-starter-card__label">{{ card.label }}</span>
                    <span class="wb-direct-starter-card__desc">{{ card.desc }}</span>
                  </button>
                </div>
                <template v-if="homeSuggestionChips.length">
                  <p class="wb-direct-starters__section-title">快捷提问</p>
                  <div class="wb-direct-starters__chips">
                    <button
                      v-for="(chip, i) in homeSuggestionChips"
                      :key="`chip-${i}`"
                      type="button"
                      class="wb-direct-starter-chip"
                      @click="applyStarterPrompt(chip)"
                    >
                      {{ chip }}
                    </button>
                  </div>
                </template>
                <template v-if="recentHomeConversations.length">
                  <p class="wb-direct-starters__section-title">最近对话</p>
                  <ul class="wb-direct-starters__recent-list">
                    <li v-for="conv in recentHomeConversations" :key="conv.id">
                      <button type="button" class="wb-direct-starter-recent" @click="pickHomeConversation(conv.id)">
                        <span class="wb-direct-starter-recent__title">{{ conv.title || '新对话' }}</span>
                        <span class="wb-direct-starter-recent__time">{{ formatHomeConvTime(conv.updatedAt) }}</span>
                      </button>
                    </li>
                  </ul>
                </template>
              </div>
              </div>
              </div>
              </div>
</template>

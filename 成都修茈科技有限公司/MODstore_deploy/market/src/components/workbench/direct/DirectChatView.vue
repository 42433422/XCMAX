<template>
  <div class="wb-direct">
    <div class="wb-direct__scroll" ref="scrollRef">
      <div class="wb-direct__center">
        <div v-if="!hasMessages" class="wb-direct__welcome">
          <h2 class="wb-direct__greeting">有什么想问的？</h2>
          <p class="wb-direct__subtitle">选择一个话题开始，或直接输入你的问题</p>

          <div class="wb-direct__suggestions">
            <button
              v-for="card in suggestionCards"
              :key="card.label"
              type="button"
              class="wb-direct__card"
              @click="onSuggestionSelect(card.prompt)"
            >
              <span class="wb-direct__card-icon" v-html="card.icon" />
              <span class="wb-direct__card-label">{{ card.label }}</span>
              <span class="wb-direct__card-desc">{{ card.desc }}</span>
            </button>
          </div>
        </div>

        <div v-else class="wb-direct__messages">
          <!-- ChatMessageList placeholder -->
        </div>
      </div>
    </div>

    <div class="wb-direct__input-bar">
      <div class="wb-direct__input-wrapper">
        <button
          type="button"
          class="wb-direct__attach-btn"
          aria-label="添加附件"
          @click="emit('attach-file')"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
            <line x1="10" y1="4" x2="10" y2="16" />
            <line x1="4" y1="10" x2="16" y2="10" />
          </svg>
        </button>

        <textarea
          ref="textareaRef"
          v-model="inputText"
          class="wb-direct__textarea"
          :placeholder="'直接问问题，例如：帮我写一份门店日报自动化方案…'"
          rows="1"
          @input="autoResize"
          @keydown.enter.exact="onEnterSubmit"
        />

        <button
          type="button"
          class="wb-direct__send-btn"
          :class="{ 'wb-direct__send-btn--active': canSend }"
          :disabled="!canSend"
          aria-label="发送"
          @click="onSend"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M3 9L15 3L9 15L8 10L3 9Z" fill="currentColor" />
          </svg>
        </button>
      </div>

      <div class="wb-direct__input-footer">
        <div class="wb-direct__model-toggle">
          <button
            type="button"
            class="wb-direct__model-opt"
            :class="{ 'wb-direct__model-opt--active': modelMode === 'auto' }"
            @click="modelMode = 'auto'"
          >
            Auto
          </button>
          <button
            type="button"
            class="wb-direct__model-opt"
            :class="{ 'wb-direct__model-opt--active': modelMode === 'manual' }"
            @click="modelMode = 'manual'"
          >
            自选
          </button>
        </div>

        <button type="button" class="wb-direct__employee-btn">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="7" cy="4.5" r="2.5" />
            <path d="M2 13c0-2.76 2.24-5 5-5s5 2.24 5 5" />
          </svg>
          <span>选择员工</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'

const emit = defineEmits<{
  send: [text: string]
  'attach-file': []
  'new-chat': []
}>()

const hasMessages = ref(false)
const inputText = ref('')
const modelMode = ref<'auto' | 'manual'>('auto')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLDivElement | null>(null)

const canSend = computed(() => inputText.value.trim().length > 0)

const suggestionCards = [
  {
    label: '帮我分析数据',
    desc: '上传表格或描述需求，快速获得洞察',
    prompt: '帮我分析数据',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="7" rx="1"/><rect x="9" y="8" width="4" height="11" rx="1"/><rect x="15" y="3" width="4" height="16" rx="1"/></svg>',
  },
  {
    label: '写一份方案',
    desc: '从大纲到完整方案，一键生成',
    prompt: '写一份方案',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-4-6z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="14" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/></svg>',
  },
  {
    label: '总结文档要点',
    desc: '粘贴或上传文档，提炼核心要点',
    prompt: '总结文档要点',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="11" x2="14" y2="11"/><line x1="8" y1="14" x2="12" y2="14"/></svg>',
  },
  {
    label: '生成代码片段',
    desc: '描述需求，自动生成可运行的代码',
    prompt: '生成代码片段',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="8 7 4 11 8 15"/><polyline points="14 7 18 11 14 15"/><line x1="12" y1="5" x2="10" y2="17"/></svg>',
  },
]

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function onEnterSubmit(e: KeyboardEvent) {
  if (e.isComposing) return
  e.preventDefault()
  onSend()
}

function onSend() {
  const text = inputText.value.trim()
  if (!text) return
  hasMessages.value = true
  emit('send', text)
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })
}

function onSuggestionSelect(prompt: string) {
  inputText.value = prompt
  onSend()
}
</script>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./DirectChatView.css，模板与逻辑保持原样。 -->
<style scoped src="./DirectChatView.css"></style>

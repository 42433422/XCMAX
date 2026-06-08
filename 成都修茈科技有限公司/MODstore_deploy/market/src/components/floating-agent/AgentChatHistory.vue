<template>
  <div
    ref="scrollEl"
    class="chat-history"
    :class="{ 'chat-history--corp': corpMode }"
    role="log"
    aria-label="对话历史"
    aria-live="polite"
  >
    <CorpWelcomeBoard
      v-if="showCorpWelcome"
      :title="welcomeTitle"
      :subtitle="emptyDesc"
      :tasks="quickTips"
      :is-contact-page="isContactPage"
      :is-mobile-contact="isMobileContact"
      @task="onTask"
    />
    <div v-else-if="!messages.length && quickTips.length" class="chat-empty">
      <p class="chat-empty-title">需要我做什么？</p>
      <p class="chat-empty-desc">{{ emptyDesc }}</p>
      <p class="chat-empty-sub">
        <button
          v-for="(tip, i) in quickTips"
          :key="i"
          type="button"
          class="quick-tip"
          @click="onQuickTip(tip)"
        >
          {{ tip.label }}
        </button>
      </p>
    </div>

    <AgentMessageBubble v-for="msg in messages" :key="msg.id" :msg="msg" />

    <AgentActionPreview
      v-if="pendingAction"
      :action="pendingAction"
      @confirm="pendingAction?.resolve(true)"
      @cancel="pendingAction?.resolve(false)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import {
  getCorpQuickActions,
  getCorpWelcomeDesc,
  getCorpWelcomeTitle,
  getMarketQuickActions,
  getMarketWelcomeDesc,
  isContactPagePath,
  type QuickAction,
} from '../../content/siteKnowledge'
import { useCorpMobileViewport } from '../../corp-butler/corpViewport'
import AgentMessageBubble from './AgentMessageBubble.vue'
import AgentActionPreview from './AgentActionPreview.vue'
import CorpWelcomeBoard from './CorpWelcomeBoard.vue'

const props = withDefaults(defineProps<{ corpMode?: boolean }>(), { corpMode: false })

const emit = defineEmits<{
  (e: 'quick', text: string): void
  (e: 'task', action: QuickAction): void
}>()

const agentStore = useAgentStore()
const { messages, pendingAction } = storeToRefs(agentStore)
const route = useRoute()

/** 仅工作台内嵌 market-about 落地页；官网独立 bundle 恒为 false */
const isMarketPublicLanding = computed(
  () => !props.corpMode && String(route.name || '') === 'about',
)

const corpPathname = computed(() =>
  typeof window !== 'undefined' ? window.location.pathname : '/',
)

const isContactPage = computed(() => isContactPagePath(corpPathname.value))

const isMobileViewport = useCorpMobileViewport()

const isMobileContact = computed(
  () => props.corpMode && isContactPage.value && isMobileViewport.value,
)

const showCorpWelcome = computed(() => {
  if (!props.corpMode || isMarketPublicLanding.value) return false
  if (isMobileContact.value) return true
  return quickTips.value.length > 0 && !messages.value.length
})

const welcomeTitle = computed(() => {
  if (!props.corpMode || isMarketPublicLanding.value) return undefined
  if (isMobileContact.value) return 'Hi，我来帮您填需求问卷'
  return getCorpWelcomeTitle(corpPathname.value)
})

const emptyDesc = computed(() => {
  if (props.corpMode) {
    if (isMarketPublicLanding.value) return getMarketWelcomeDesc('market-about')
    if (isMobileContact.value) {
      return '您可以用 AI 一键填表：填写公司名称和行业/业务类型后，我会自动写好下方整份问卷。'
    }
    return getCorpWelcomeDesc(corpPathname.value)
  }
  return getMarketWelcomeDesc(String(route.name || ''))
})

const quickTips = computed(() => {
  if (props.corpMode) {
    if (isMarketPublicLanding.value) return getMarketQuickActions('market-about')
    if (isMobileContact.value) return []
    return getCorpQuickActions(corpPathname.value)
  }
  return getMarketQuickActions(String(route.name || ''))
})

function onQuickTip(tip: QuickAction) {
  if (tip.task) {
    emit('task', tip)
    return
  }
  emit('quick', tip.message || tip.label)
}

function onTask(action: QuickAction) {
  emit('task', action)
}

const scrollEl = ref<HTMLDivElement | null>(null)

watch(
  messages,
  () => {
    nextTick(() => {
      if (scrollEl.value) {
        scrollEl.value.scrollTop = scrollEl.value.scrollHeight
      }
    })
  },
  { deep: true },
)
</script>

<script lang="ts">
export default { name: 'AgentChatHistory' }
</script>

<style scoped>
.chat-history {
  flex: 1 1 0%;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 0;
  min-height: 0;
  scroll-behavior: smooth;
}

.chat-history--corp {
  flex: 1 1 auto;
  min-height: 120px;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: flex-start;
  gap: 6px;
  color: rgba(255, 255, 255, 0.55);
  font-size: 0.88rem;
  text-align: left;
  padding: 18px;
  border: 1px dashed rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.025);
}

.chat-empty-title {
  margin: 0;
  color: rgba(255, 255, 255, 0.82);
  font-weight: 750;
}

.chat-empty-desc {
  margin: 0 0 6px;
  color: rgba(255, 255, 255, 0.42);
  font-size: 0.78rem;
  line-height: 1.5;
}

.chat-empty-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-start;
  margin: 0;
}

.quick-tip {
  padding: 4px 9px;
  border-radius: 7px;
  font-size: 0.78rem;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.09);
  color: rgba(226, 232, 240, 0.82);
  cursor: pointer;
  transition: all 0.15s;
}

.quick-tip:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
</style>

<script setup>
import { defineProps } from 'vue'

// 拆分自 BrainView.vue 模板（原第 43–101 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  brainAgentSessionId, agentSending, clearAgentChat, agentScrollRef,
  agentMessages, agentInput, onAgentComposerKeydown, clientTier, sendAgentMessage,
} = props.tm
</script>

<template>
      <section class="brain-agent-console" aria-label="Agent 对话">
        <header class="brain-agent-console__head">
          <div class="brain-agent-console__title">
            <span class="brain-agent-console__dot" aria-hidden="true" />
            <span>Agent</span>
            <span class="brain-agent-console__sub">unified_chat</span>
          </div>
          <div class="brain-agent-console__actions">
            <span
              v-if="brainAgentSessionId"
              class="brain-agent-console__session-id"
              :title="brainAgentSessionId"
            >session {{ brainAgentSessionId.slice(0, 10) }}…</span>
            <button type="button" class="brain-agent-console__btn" :disabled="agentSending" @click="clearAgentChat">
              清空会话
            </button>
          </div>
        </header>
        <div ref="agentScrollRef" class="brain-agent-console__messages" role="log" aria-live="polite">
          <div v-if="!agentMessages.length" class="brain-agent-console__empty muted">
            输入问题或任务说明：<strong>Ctrl+Enter</strong> / <strong>⌘+Enter</strong> 或点「发送」；换行用普通 Enter。与主助手同源 Planner；会话 ID 存于 sessionStorage。
          </div>
          <div
            v-for="m in agentMessages"
            :key="m.id"
            class="brain-agent-msg"
            :class="'brain-agent-msg--' + m.role"
          >
            <div class="brain-agent-msg__role">{{ m.role === 'user' ? 'You' : m.role === 'assistant' ? 'Agent' : '…' }}</div>
            <pre class="brain-agent-msg__body">{{ m.content }}</pre>
          </div>
          <div v-if="agentSending" class="brain-agent-msg brain-agent-msg--assistant brain-agent-msg--pending">
            <div class="brain-agent-msg__role">Agent</div>
            <div class="brain-agent-msg__body brain-agent-msg__typing">正在思考…</div>
          </div>
        </div>
        <div class="brain-agent-console__composer">
          <textarea
            v-model="agentInput"
            class="brain-agent-console__input"
            rows="3"
            :disabled="agentSending"
            placeholder="描述任务或提问…（Ctrl+Enter / ⌘+Enter 发送）"
            spellcheck="true"
            @keydown="onAgentComposerKeydown"
          />
          <div class="brain-agent-console__composer-bar">
            <span class="brain-agent-console__hint muted">{{ clientTier === 'p2' ? 'P2 · 工具集更宽' : 'P1 · 默认' }}</span>
            <button
              type="button"
              class="btn btn-primary btn-sm brain-agent-console__send"
              :disabled="agentSending || !agentInput.trim()"
              @click="sendAgentMessage"
            >
              发送
            </button>
          </div>
        </div>
      </section>
</template>

<style scoped src="./brain.css"></style>

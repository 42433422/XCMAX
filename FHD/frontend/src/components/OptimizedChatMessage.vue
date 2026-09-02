<template>
  <div :class="['message', message.role, { 'is-measuring': !measureResult }]" :style="messageStyle">
    <!-- 骨架屏占位，测量完成前显示 -->
    <template v-if="!measureResult">
      <div class="message-skeleton">
        <div class="skeleton-line" style="width: 80%"></div>
        <div class="skeleton-line" style="width: 60%"></div>
        <div class="skeleton-line" style="width: 40%"></div>
      </div>
    </template>

    <!-- 实际内容，测量完成后显示 -->
    <template v-else>
      <!-- 折叠消息 -->
      <template v-if="isCollapsed">
        <CollapsedMessagePreview :preview="collapsedPreview" expand-label="展开详情" @expand="expand" />
      </template>

      <!-- 完整消息 -->
      <template v-else>
        <div class="message-html" v-html="sanitizedContent"></div>

        <!-- 发货单下载按钮 -->
        <div v-if="message.role === 'ai' && message.shipmentDownloadUrl" class="message-shipment-actions">
          <a class="btn btn-primary btn-sm" :href="message.shipmentDownloadUrl" download> 下载发货单 </a>
        </div>

        <!-- 收起按钮 -->
        <MessageCollapseLink v-if="message.role === 'ai' && canCollapse" class="message-fold-action" label="收起" @collapse="collapse" />
      </template>

      <!-- 上下文摘要 -->
      <ContextSummaryPills v-if="message.contextSummary" class="context-summary" :summary="message.contextSummary" />

      <!-- 思考步骤 -->
      <details v-if="message.thinkingSteps" class="thinking-panel">
        <summary>查看思考步骤</summary>
        <pre>{{ message.thinkingSteps }}</pre>
      </details>

      <!-- TODO 步骤 -->
      <div v-if="message.todoSteps?.length" class="todo-panel">
        <div class="todo-title">执行 TODO</div>
        <ul>
          <li v-for="(step, idx) in message.todoSteps" :key="idx">{{ step }}</li>
        </ul>
      </div>

      <!-- 执行轨迹 -->
      <div v-if="message.workflowAction || message.nodeResults?.length" class="trace-panel">
        <div class="trace-title">执行轨迹</div>
        <div class="trace-stages">
          <span class="trace-chip">Thinking</span>
          <span class="trace-chip">Plan</span>
          <span class="trace-chip">Execute</span>
        </div>
        <div class="trace-action" v-if="message.workflowAction">状态：{{ message.workflowAction }}</div>
        <ul v-if="message.nodeResults?.length" class="trace-list">
          <li v-for="(nr, idx) in message.nodeResults" :key="idx">
            <span :class="['trace-status', nr.success ? 'ok' : 'fail']">
              {{ nr.success ? '成功' : '失败' }}
            </span>
            <span>{{ nr.node_id }} · {{ nr.tool_id }}.{{ nr.action }}</span>
            <span v-if="nr.retries || nr.duration_ms" class="trace-node-meta">
              <template v-if="nr.retries">重试 {{ nr.retries }} 次</template>
              <template v-if="nr.retries && nr.duration_ms"> · </template>
              <template v-if="nr.duration_ms">{{ nr.duration_ms }}ms</template>
            </span>
            <span v-if="nr.error || nr.message" class="trace-node-error">
              {{ nr.error || nr.message }}
            </span>
            <span v-if="nr.recovery_hint" class="trace-node-hint"> 恢复建议：{{ nr.recovery_hint }} </span>
          </li>
        </ul>
      </div>

      <!-- 时间戳 -->
      <div class="time">{{ message.time }}</div>

      <!-- TTS 按钮 -->
      <button v-if="message.role === 'ai' && canSpeak" class="message-tts-btn" :class="{ 'is-playing': isPlaying }" @click.stop="toggleTts">
        <i class="fa" :class="isPlaying ? 'fa-stop' : 'fa-volume-up'" aria-hidden="true"></i>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { measureText, type MeasureResult } from '@/utils/pretext'
import { plainTextFromChatHtml, sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import type { UiChatMessage } from '@/types/chat-ui'
import ContextSummaryPills from '@/components/chat/ContextSummaryPills.vue'
import CollapsedMessagePreview from '@/components/chat/CollapsedMessagePreview.vue'
import MessageCollapseLink from '@/components/chat/MessageCollapseLink.vue'

interface Props {
  message: UiChatMessage
  maxWidth: number
  canCollapse?: boolean
  canSpeak?: boolean
  isPlaying?: boolean
  defaultCollapsed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  maxWidth: 600,
  canCollapse: false,
  canSpeak: false,
  isPlaying: false,
  defaultCollapsed: false,
})

const emit = defineEmits<{
  (e: 'toggle-tts'): void
  (e: 'collapse'): void
  (e: 'expand'): void
}>()

// 测量结果
const measureResult = ref<MeasureResult | null>(null)
const isCollapsed = ref(props.defaultCollapsed)

// 清理后的内容
const sanitizedContent = computed(() => {
  return sanitizeChatBubbleHtml(props.message.content)
})

// 折叠预览文本
const collapsedPreview = computed(() => {
  const text = plainTextFromChatHtml(props.message.content)
  return text.slice(0, 100) + (text.length > 100 ? '...' : '')
})

const contextSummaryText = computed(() => {
  const summary = props.message.contextSummary
  if (summary == null) return ''
  if (typeof summary === 'string') return summary.trim()
  if (typeof summary === 'object' && !Array.isArray(summary)) {
    const items = (summary as { items?: unknown }).items
    if (Array.isArray(items)) {
      return items
        .map((item) => String(item).trim())
        .filter(Boolean)
        .join(' + ')
    }
  }
  return String(summary).trim()
})

// 消息样式（用于虚拟列表定位）
const messageStyle = computed(() => {
  if (!measureResult.value) {
    return {
      minHeight: '80px', // 骨架屏最小高度
    }
  }

  return {
    height: `${measureResult.value.height + 40}px`, // 加上 padding 和元信息高度
  }
})

// 执行文本测量
function performMeasure() {
  const plainText = plainTextFromChatHtml(props.message.content)
  // 使用 requestIdleCallback 在空闲时测量，避免阻塞主线程
  if ('requestIdleCallback' in window) {
    requestIdleCallback(
      () => {
        measureResult.value = measureText({
          text: plainText,
          width: props.maxWidth - 32, // 减去 padding
          fontSize: 14,
          lineHeight: 1.5,
        })
      },
      { timeout: 100 },
    )
  } else {
    // 降级方案：setTimeout
    setTimeout(() => {
      measureResult.value = measureText({
        text: plainText,
        width: props.maxWidth - 32,
        fontSize: 14,
        lineHeight: 1.5,
      })
    }, 0)
  }
}

// 折叠/展开
function collapse() {
  isCollapsed.value = true
  emit('collapse')
}

function expand() {
  isCollapsed.value = false
  emit('expand')
}

// TTS 切换
function toggleTts() {
  emit('toggle-tts')
}

// 监听消息变化，重新测量
watch(
  () => props.message.content,
  () => {
    measureResult.value = null
    performMeasure()
  },
  { immediate: true },
)

onMounted(() => {
  if (!measureResult.value) {
    performMeasure()
  }
})

defineExpose({
  get measureResult() {
    return measureResult.value
  },
  set measureResult(value: MeasureResult | null) {
    measureResult.value = value
  },
  get isCollapsed() {
    return isCollapsed.value
  },
  set isCollapsed(value: boolean) {
    isCollapsed.value = value
  },
  get sanitizedContent() {
    return sanitizedContent.value
  },
  get collapsedPreview() {
    return collapsedPreview.value
  },
  get messageStyle() {
    return messageStyle.value
  },
  collapse,
  expand,
  toggleTts,
})
</script>

<style scoped src="./OptimizedChatMessage.css"></style>

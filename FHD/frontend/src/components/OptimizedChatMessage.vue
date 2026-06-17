<template>
  <div
    :class="['message', message.role, { 'is-measuring': !measureResult }]"
    :style="messageStyle"
  >
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
        <CollapsedMessagePreview
          :preview="collapsedPreview"
          expand-label="展开详情"
          @expand="expand"
        />
      </template>
      
      <!-- 完整消息 -->
      <template v-else>
        <div class="message-html" v-html="sanitizedContent"></div>
        
        <!-- 发货单下载按钮 -->
        <div
          v-if="message.role === 'ai' && message.shipmentDownloadUrl"
          class="message-shipment-actions"
        >
          <a
            class="btn btn-primary btn-sm"
            :href="message.shipmentDownloadUrl"
            download
          >
            下载发货单
          </a>
        </div>
        
        <!-- 收起按钮 -->
        <MessageCollapseLink
          v-if="message.role === 'ai' && canCollapse"
          class="message-fold-action"
          label="收起"
          @collapse="collapse"
        />
      </template>
      
      <!-- 上下文摘要 -->
      <ContextSummaryPills
        v-if="contextSummaryText"
        :summary="contextSummaryText"
      />
      
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
        <div class="trace-action" v-if="message.workflowAction">
          状态：{{ message.workflowAction }}
        </div>
        <ul v-if="message.nodeResults?.length" class="trace-list">
          <li v-for="(nr, idx) in message.nodeResults" :key="idx">
            <span :class="['trace-status', nr.success ? 'ok' : 'fail']">
              {{ nr.success ? '成功' : '失败' }}
            </span>
            <span>{{ nr.node_id }} · {{ nr.tool_id }}.{{ nr.action }}</span>
          </li>
        </ul>
      </div>
      
      <!-- 时间戳 -->
      <div class="time">{{ message.time }}</div>
      
      <!-- TTS 按钮 -->
      <button
        v-if="message.role === 'ai' && canSpeak"
        class="message-tts-btn"
        :class="{ 'is-playing': isPlaying }"
        @click.stop="toggleTts"
      >
        <i
          class="fa"
          :class="isPlaying ? 'fa-stop' : 'fa-volume-up'"
          aria-hidden="true"
        ></i>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue';
import DOMPurify from 'dompurify';
import { measureText, type MeasureResult } from '@/utils/pretext';
import type { UiChatMessage } from '@/types/chat-ui';
import CollapsedMessagePreview from '@/components/chat/CollapsedMessagePreview.vue';
import MessageCollapseLink from '@/components/chat/MessageCollapseLink.vue';
import ContextSummaryPills from '@/components/chat/ContextSummaryPills.vue';

interface Props {
  message: UiChatMessage;
  maxWidth: number;
  canCollapse?: boolean;
  canSpeak?: boolean;
  isPlaying?: boolean;
  defaultCollapsed?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  maxWidth: 600,
  canCollapse: false,
  canSpeak: false,
  isPlaying: false,
  defaultCollapsed: false,
});

const emit = defineEmits<{
  (e: 'toggle-tts'): void;
  (e: 'collapse'): void;
  (e: 'expand'): void;
}>();

// 测量结果
const measureResult = ref<MeasureResult | null>(null);
const isCollapsed = ref(props.defaultCollapsed);

// 清理后的内容
const sanitizedContent = computed(() => {
  return DOMPurify.sanitize(props.message.content);
});

// 折叠预览文本
const collapsedPreview = computed(() => {
  const text = props.message.content.replace(/<[^>]*>/g, '');
  return text.slice(0, 100) + (text.length > 100 ? '...' : '');
});

const contextSummaryText = computed(() => {
  const summary = props.message.contextSummary;
  if (summary == null) return '';
  if (typeof summary === 'string') return summary.trim();
  if (typeof summary === 'object' && !Array.isArray(summary)) {
    const items = (summary as { items?: unknown }).items;
    if (Array.isArray(items)) {
      return items.map((item) => String(item).trim()).filter(Boolean).join(' + ');
    }
  }
  return String(summary).trim();
});

// 消息样式（用于虚拟列表定位）
const messageStyle = computed(() => {
  if (!measureResult.value) {
    return {
      minHeight: '80px', // 骨架屏最小高度
    };
  }
  
  return {
    height: `${measureResult.value.height + 40}px`, // 加上 padding 和元信息高度
  };
});

// 执行文本测量
function performMeasure() {
  // 使用 requestIdleCallback 在空闲时测量，避免阻塞主线程
  if ('requestIdleCallback' in window) {
    requestIdleCallback(() => {
      measureResult.value = measureText({
        text: props.message.content.replace(/<[^>]*>/g, ''),
        width: props.maxWidth - 32, // 减去 padding
        fontSize: 14,
        lineHeight: 1.5,
      });
    }, { timeout: 100 });
  } else {
    // 降级方案：setTimeout
    setTimeout(() => {
      measureResult.value = measureText({
        text: props.message.content.replace(/<[^>]*>/g, ''),
        width: props.maxWidth - 32,
        fontSize: 14,
        lineHeight: 1.5,
      });
    }, 0);
  }
}

// 折叠/展开
function collapse() {
  isCollapsed.value = true;
  emit('collapse');
}

function expand() {
  isCollapsed.value = false;
  emit('expand');
}

// TTS 切换
function toggleTts() {
  emit('toggle-tts');
}

// 监听消息变化，重新测量
watch(() => props.message.content, () => {
  measureResult.value = null;
  performMeasure();
}, { immediate: true });

onMounted(() => {
  if (!measureResult.value) {
    performMeasure();
  }
});
</script>

<style scoped>
.message {
  position: relative;
  padding: 12px 16px;
  margin: 8px 0;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.message.user {
  background: #e3f2fd;
  margin-left: 20%;
}

.message.ai {
  background: #f5f5f5;
  margin-right: 20%;
}

.message.is-measuring {
  opacity: 0.7;
}

/* 骨架屏样式 */
.message-skeleton {
  padding: 8px 0;
}

.skeleton-line {
  height: 14px;
  background: linear-gradient(90deg, #e0e0e0 25%, #f0f0f0 50%, #e0e0e0 75%);
  background-size: 200% 100%;
  border-radius: 4px;
  margin: 8px 0;
  animation: skeleton-loading 1.5s infinite;
}

@keyframes skeleton-loading {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* 折叠消息样式 — 见 CollapsedMessagePreview.vue */

.message-html {
  font-size: 14px;
  line-height: 1.5;
  word-wrap: break-word;
}

.message-html :deep(p) {
  margin: 8px 0;
}

.message-html :deep(ul), .message-html :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.message-html :deep(li) {
  margin: 4px 0;
}

.message-html :deep(code) {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 13px;
}

.message-html :deep(pre) {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
}

/* 操作按钮 */
.message-shipment-actions {
  margin-top: 12px;
}

/* 元信息样式 */
.context-summary {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 6px;
  font-size: 12px;
  color: #666;
}

.thinking-panel {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 6px;
}

.thinking-panel summary {
  cursor: pointer;
  font-size: 12px;
  color: #666;
}

.thinking-panel pre {
  margin-top: 8px;
  padding: 8px;
  background: #f5f5f5;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
}

.todo-panel {
  margin-top: 12px;
  padding: 8px 12px;
  background: #e8f5e9;
  border-radius: 6px;
}

.todo-title {
  font-size: 12px;
  font-weight: 600;
  color: #2e7d32;
  margin-bottom: 4px;
}

.todo-panel ul {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
}

.todo-panel li {
  margin: 2px 0;
  color: #555;
}

.trace-panel {
  margin-top: 12px;
  padding: 8px 12px;
  background: #e3f2fd;
  border-radius: 6px;
}

.trace-title {
  font-size: 12px;
  font-weight: 600;
  color: #1976d2;
  margin-bottom: 4px;
}

.trace-stages {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}

.trace-chip {
  padding: 2px 8px;
  background: #1976d2;
  color: white;
  border-radius: 12px;
  font-size: 11px;
}

.trace-action {
  font-size: 12px;
  color: #555;
  margin: 4px 0;
}

.trace-list {
  margin: 8px 0 0 0;
  padding-left: 0;
  list-style: none;
  font-size: 12px;
}

.trace-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}

.trace-status {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.trace-status.ok {
  background: #4caf50;
  color: white;
}

.trace-status.fail {
  background: #f44336;
  color: white;
}

/* 时间戳 */
.time {
  margin-top: 8px;
  font-size: 11px;
  color: #999;
  text-align: right;
}

/* TTS 按钮 */
.message-tts-btn {
  position: absolute;
  bottom: 8px;
  left: 8px;
  width: 28px;
  height: 28px;
  border: 1px solid #dbe3f0;
  background: #fff;
  color: #5b6b88;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.message-tts-btn .fa {
  font-size: 12px;
  line-height: 1;
}

.message-tts-btn .fa-stop {
  font-size: 10px;
}

.message-tts-btn:hover {
  background: #f0f6ff;
  border-color: #4a90e2;
  color: #2d7bd6;
}

.message-tts-btn.is-playing {
  background: #1976d2;
  color: white;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}
</style>

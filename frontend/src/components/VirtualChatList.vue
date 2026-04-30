<template>
  <div class="virtual-chat-list" ref="containerRef">
    <!-- 总高度占位 -->
    <div class="virtual-list-phantom" :style="{ height: `${totalHeight}px` }"></div>
    
    <!-- 可视区域 -->
    <div class="virtual-list-content" :style="{ transform: `translateY(${offsetY}px)` }">
      <OptimizedChatMessage
        v-for="item in visibleItems"
        :key="item.index"
        :message="item.message"
        :max-width="maxMessageWidth"
        :can-collapse="item.index < messages.length - 1"
        :can-speak="item.message.role === 'ai'"
        :is-playing="playingMsgIdx === item.index"
        :default-collapsed="isMessageCollapsed(item.index)"
        @toggle-tts="toggleTts(item.index)"
        @collapse="collapseMessage(item.index)"
        @expand="expandMessage(item.index)"
      />
    </div>
    
    <!-- 加载更多提示 -->
    <div v-if="isLoading" class="loading-more">
      <span class="loading-spinner"></span>
      加载中...
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue';
import OptimizedChatMessage from './OptimizedChatMessage.vue';
import { batchEstimateMessageHeights } from '@/utils/pretext';

interface ChatMessage {
  role: 'user' | 'ai';
  content: string;
  time: string;
  shipmentDownloadUrl?: string;
  contextSummary?: string;
  thinkingSteps?: string;
  todoSteps?: string[];
  workflowAction?: string;
  nodeResults?: Array<{
    success: boolean;
    node_id: string;
    tool_id: string;
    action: string;
  }>;
}

interface Props {
  messages: ChatMessage[];
  maxMessageWidth?: number;
  isLoading?: boolean;
  bufferSize?: number; // 上下缓冲的 item 数量
}

const props = withDefaults(defineProps<Props>(), {
  maxMessageWidth: 600,
  isLoading: false,
  bufferSize: 5,
});

const emit = defineEmits<{
  (e: 'load-more'): void;
  (e: 'update:playing-msg-idx', idx: number | null): void;
}>();

// 容器引用
const containerRef = ref<HTMLElement | null>(null);

// 滚动状态
const scrollTop = ref(0);
const containerHeight = ref(0);

// 消息高度缓存（使用 Pretext.js 预估）
const messageHeights = ref<number[]>([]);
const collapsedMessages = ref<Set<number>>(new Set());
const playingMsgIdx = ref<number | null>(null);

// 计算总高度
const totalHeight = computed(() => {
  return messageHeights.value.reduce((sum, height) => sum + height, 0);
});

// 计算每个消息的偏移量
const messageOffsets = computed(() => {
  const offsets: number[] = [];
  let currentOffset = 0;
  
  for (const height of messageHeights.value) {
    offsets.push(currentOffset);
    currentOffset += height;
  }
  
  return offsets;
});

// 计算可见区域的起始和结束索引
const visibleRange = computed(() => {
  const start = Math.max(0, findStartIndex(scrollTop.value));
  const end = Math.min(
    props.messages.length - 1,
    findEndIndex(scrollTop.value + containerHeight.value)
  );
  
  // 添加缓冲
  const bufferedStart = Math.max(0, start - props.bufferSize);
  const bufferedEnd = Math.min(props.messages.length - 1, end + props.bufferSize);
  
  return { start: bufferedStart, end: bufferedEnd };
});

// 可见的 item
const visibleItems = computed(() => {
  const { start, end } = visibleRange.value;
  const items = [];
  
  for (let i = start; i <= end; i++) {
    items.push({
      index: i,
      message: props.messages[i],
    });
  }
  
  return items;
});

// 内容偏移量
const offsetY = computed(() => {
  if (visibleRange.value.start === 0) return 0;
  return messageOffsets.value[visibleRange.value.start];
});

// 查找起始索引
function findStartIndex(offset: number): number {
  let low = 0;
  let high = messageOffsets.value.length - 1;
  
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (messageOffsets.value[mid] < offset) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  
  return low;
}

// 查找结束索引
function findEndIndex(offset: number): number {
  let low = 0;
  let high = messageOffsets.value.length - 1;
  
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (messageOffsets.value[mid] > offset) {
      high = mid - 1;
    } else {
      low = mid;
    }
  }
  
  return low;
}

// 使用 Pretext.js 批量计算消息高度
function calculateMessageHeights() {
  const messages = props.messages.map(msg => ({
    content: msg.content,
    fontSize: 14,
  }));
  
  // 使用 Pretext.js 批量预估高度
  const heights = batchEstimateMessageHeights(
    messages,
    props.maxMessageWidth - 32
  );
  
  // 加上 padding 和元信息的高度
  messageHeights.value = heights.map(h => h + 40);
}

// 检查消息是否折叠
function isMessageCollapsed(index: number): boolean {
  return collapsedMessages.value.has(index);
}

// 折叠消息
function collapseMessage(index: number) {
  collapsedMessages.value.add(index);
  // 重新计算高度
  const baseHeight = messageHeights.value[index];
  messageHeights.value[index] = 60; // 折叠后的高度
}

// 展开消息
function expandMessage(index: number) {
  collapsedMessages.value.delete(index);
  // 重新计算该消息高度
  calculateMessageHeights();
}

// TTS 切换
function toggleTts(index: number) {
  if (playingMsgIdx.value === index) {
    playingMsgIdx.value = null;
  } else {
    playingMsgIdx.value = index;
  }
  emit('update:playing-msg-idx', playingMsgIdx.value);
}

// 滚动处理
function handleScroll() {
  if (!containerRef.value) return;
  
  scrollTop.value = containerRef.value.scrollTop;
  
  // 检查是否需要加载更多
  const scrollHeight = containerRef.value.scrollHeight;
  const clientHeight = containerRef.value.clientHeight;
  
  if (scrollTop.value + clientHeight >= scrollHeight - 100) {
    emit('load-more');
  }
}

// 更新容器高度
function updateContainerHeight() {
  if (containerRef.value) {
    containerHeight.value = containerRef.value.clientHeight;
  }
}

// 监听消息变化
watch(() => props.messages, () => {
  calculateMessageHeights();
}, { immediate: true, deep: true });

// 滚动到底部（新消息时）
function scrollToBottom() {
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight;
  }
}

// 暴露方法
defineExpose({
  scrollToBottom,
});

onMounted(() => {
  updateContainerHeight();
  
  if (containerRef.value) {
    containerRef.value.addEventListener('scroll', handleScroll);
    window.addEventListener('resize', updateContainerHeight);
  }
});

onUnmounted(() => {
  if (containerRef.value) {
    containerRef.value.removeEventListener('scroll', handleScroll);
    window.removeEventListener('resize', updateContainerHeight);
  }
});
</script>

<style scoped>
.virtual-chat-list {
  position: relative;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}

.virtual-list-phantom {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: -1;
}

.virtual-list-content {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  will-change: transform;
}

.loading-more {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.8);
  color: white;
  border-radius: 20px;
  font-size: 14px;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

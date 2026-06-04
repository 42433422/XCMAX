<template>
  <div class="chat-view page-view active" id="view-chat">
    <div class="quick-actions">
      <button
        v-for="quickBtn in visibleQuickButtons"
        :key="quickBtn.text"
        class="quick-btn"
        :data-quick="quickBtn.text"
        :data-action="quickBtn.text === '测试预览' ? 'test-preview' : null"
        @click="sendQuick(quickBtn.text)"
      >
        {{ quickBtn.label }}
      </button>
    </div>
    <div class="chat-container" :style="chatPaneStyle">
      <!-- 使用 VirtualChatList 替代原有消息列表 -->
      <div class="chat-messages-shell">
        <VirtualChatList
          ref="virtualListRef"
          :messages="messages"
          :max-message-width="600"
          :is-loading="isLoading && !isStreamingReply"
          @load-more="loadMoreMessages"
          @update:playing-msg-idx="playingMsgIdx = $event"
        />
      </div>
      <div v-if="isTaskPaneResizable" class="chat-pane-handle-slot">
        <PaneResizeHandle
          orientation="vertical"
          label="调整任务面板宽度"
          @resize-start="onTaskPaneResizeStart"
          @reset="resetTaskPaneWidth"
        />
      </div>
      <div class="right-panel">
        <div class="panel-header">{{ currentTask ? '当前任务' : '当前任务' }}</div>
        <div class="panel-content panel-content-task" id="taskPanel">
          <div class="task-panel-body">
            <template v-if="currentTask">
              <div class="task-card" :class="{ 'excel-import-task': currentTask?.type === 'excel_import' }">
                <div class="task-header">{{ currentTask.title }}</div>
                <div class="task-description">{{ currentTask.description }}</div>
                <div v-if="currentTask?.type === 'excel_import' && !currentTask?.completed" class="excel-import-preview">
                  <div class="excel-import-stats">
                    <div class="stat-item">
                      <span class="stat-label">待导入记录：</span>
                      <span class="stat-value">{{ currentTask?.payload?.params?.record_count || 0 }} 条</span>
                    </div>
                  </div>
                </div>
                <div class="task-actions" v-if="!currentTask.completed">
                  <button class="btn btn-primary" @click="executeTask" :disabled="isExecuting">
                    {{ isExecuting ? '执行中...' : '确认执行' }}
                  </button>
                  <button class="btn btn-secondary" @click="cancelTask">取消</button>
                </div>
              </div>
            </template>
            <div v-else class="no-task">暂无任务</div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 输入区域 -->
    <div class="chat-input-area">
      <textarea
        v-model="inputMessage"
        class="chat-input"
        placeholder="输入消息..."
        @keydown.enter.prevent="sendMessage"
      />
      <button class="btn btn-primary send-btn" @click="sendMessage" :disabled="!inputMessage.trim() || isLoading">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted } from 'vue';
import PaneResizeHandle from '@/components/PaneResizeHandle.vue';
import { useResizablePane } from '@/composables/useResizablePane';
import VirtualChatList from '@/components/VirtualChatList.vue';
import { useChatStore } from '@/stores/chat';

// Store
const chatStore = useChatStore();
const CHAT_RIGHT_PANE_MQ = '(max-width: 1023px)';

// Refs
const virtualListRef = ref<InstanceType<typeof VirtualChatList> | null>(null);
const inputMessage = ref('');
const playingMsgIdx = ref<number | null>(null);
const isExecuting = ref(false);
const isTaskPaneResizable = ref(true);
let taskPaneViewportMedia: MediaQueryList | null = null;

// Computed
const messages = computed(() => chatStore.messages);
const isLoading = computed(() => chatStore.isLoading);
const isStreamingReply = computed(() => chatStore.isStreamingReply);
const currentTask = computed(() => chatStore.currentTask);
const {
  paneStyle: chatPaneStyle,
  startResize: onTaskPaneResizeStart,
  resetSize: resetTaskPaneWidth,
  stopResize: stopTaskPaneResize,
} = useResizablePane({
  paneKey: 'chat.task-panel',
  cssVarName: '--chat-right-pane-width',
  orientation: 'vertical',
  invertDelta: true,
  defaultSize: 300,
  minSize: 240,
  maxSize: 420,
  enabled: () => isTaskPaneResizable.value,
});

// 快捷按钮
const visibleQuickButtons = computed(() => [
  { text: '查员工', label: '查员工' },
  { text: '考勤单', label: '考勤单' },
  { text: '打印考勤表', label: '打印考勤表' },
  { text: '生成考勤统计', label: '生成考勤统计' },
]);

// Methods
async function sendMessage() {
  if (!inputMessage.value.trim() || isLoading.value) return;
  
  const message = inputMessage.value;
  inputMessage.value = '';
  
  await chatStore.sendMessage(message);
  
  // 滚动到底部
  setTimeout(() => {
    virtualListRef.value?.scrollToBottom();
  }, 100);
}

async function sendQuick(text: string) {
  await chatStore.sendMessage(text);
  
  setTimeout(() => {
    virtualListRef.value?.scrollToBottom();
  }, 100);
}

function loadMoreMessages() {
  // 加载历史消息
  chatStore.loadMoreMessages();
}

async function executeTask() {
  if (!currentTask.value) return;
  
  isExecuting.value = true;
  try {
    await chatStore.executeTask(currentTask.value.id);
  } finally {
    isExecuting.value = false;
  }
}

function cancelTask() {
  chatStore.clearTask();
}

function onTaskPaneViewportChange(event: MediaQueryList | MediaQueryListEvent) {
  isTaskPaneResizable.value = !event.matches;
  if (!isTaskPaneResizable.value) {
    stopTaskPaneResize();
  }
}

onMounted(() => {
  // 初始化聊天
  chatStore.initChat();
  taskPaneViewportMedia = window.matchMedia(CHAT_RIGHT_PANE_MQ);
  onTaskPaneViewportChange(taskPaneViewportMedia);
  if (typeof taskPaneViewportMedia.addEventListener === 'function') {
    taskPaneViewportMedia.addEventListener('change', onTaskPaneViewportChange);
  } else if (typeof taskPaneViewportMedia.addListener === 'function') {
    taskPaneViewportMedia.addListener(onTaskPaneViewportChange);
  }
});

onBeforeUnmount(() => {
  stopTaskPaneResize();
  if (!taskPaneViewportMedia) return;
  if (typeof taskPaneViewportMedia.removeEventListener === 'function') {
    taskPaneViewportMedia.removeEventListener('change', onTaskPaneViewportChange);
  } else if (typeof taskPaneViewportMedia.removeListener === 'function') {
    taskPaneViewportMedia.removeListener(onTaskPaneViewportChange);
  }
});
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.quick-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #e0e0e0;
  overflow-x: auto;
}

.quick-btn {
  padding: 6px 12px;
  border: 1px solid #d0d0d0;
  border-radius: 16px;
  background: white;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

.quick-btn:hover {
  background: #f5f5f5;
  border-color: #b0b0b0;
}

.chat-container {
  display: flex;
  flex: 1;
  overflow: hidden;
  --chat-right-pane-width: 300px;
}

.chat-messages-shell {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

.right-panel {
  width: var(--chat-right-pane-width);
  min-width: 240px;
  max-width: 420px;
  flex: 0 0 var(--chat-right-pane-width);
  border-left: 1px solid #e0e0e0;
  background: #fafafa;
  display: flex;
  flex-direction: column;
}

.chat-pane-handle-slot {
  position: relative;
  flex: 0 0 0;
  width: 0;
}

.panel-header {
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid #e0e0e0;
  background: white;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.task-card {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.task-header {
  font-weight: 600;
  margin-bottom: 8px;
}

.task-description {
  color: #666;
  font-size: 14px;
  margin-bottom: 12px;
}

.task-actions {
  display: flex;
  gap: 8px;
}

.no-task {
  text-align: center;
  color: #999;
  padding: 32px;
}

.chat-input-area {
  display: flex;
  gap: 12px;
  padding: 16px;
  border-top: 1px solid #e0e0e0;
  background: white;
}

.chat-input {
  flex: 1;
  padding: 12px;
  border: 1px solid #d0d0d0;
  border-radius: 8px;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  min-height: 44px;
  max-height: 120px;
}

.chat-input:focus {
  outline: none;
  border-color: #1976d2;
}

.send-btn {
  align-self: flex-end;
  padding: 10px 24px;
}
</style>


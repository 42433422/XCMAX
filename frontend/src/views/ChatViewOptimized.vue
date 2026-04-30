<template>
  <div class="chat-view page-view active" id="view-chat">
    <TtsSetupBanner />
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
    <div class="chat-container">
      <!-- 使用 VirtualChatList 替代原有消息列表 -->
      <VirtualChatList
        ref="virtualListRef"
        :messages="messages"
        :max-message-width="600"
        :is-loading="isLoading && !isStreamingReply"
        @load-more="loadMoreMessages"
        @update:playing-msg-idx="playingMsgIdx = $event"
      />
      
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
import { ref, computed, onMounted } from 'vue';
import VirtualChatList from '@/components/VirtualChatList.vue';
import TtsSetupBanner from '@/components/TtsSetupBanner.vue';
import { useChatStore } from '@/stores/chat';

// Store
const chatStore = useChatStore();

// Refs
const virtualListRef = ref<InstanceType<typeof VirtualChatList> | null>(null);
const inputMessage = ref('');
const playingMsgIdx = ref<number | null>(null);
const isExecuting = ref(false);

// Computed
const messages = computed(() => chatStore.messages);
const isLoading = computed(() => chatStore.isLoading);
const isStreamingReply = computed(() => chatStore.isStreamingReply);
const currentTask = computed(() => chatStore.currentTask);

// 快捷按钮
const visibleQuickButtons = computed(() => [
  { text: '查看产品', label: '查看产品' },
  { text: '查看订单', label: '查看订单' },
  { text: '打印标签', label: '打印标签' },
  { text: '生成发货单', label: '生成发货单' },
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

onMounted(() => {
  // 初始化聊天
  chatStore.initChat();
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
}

.chat-messages {
  flex: 1;
  overflow: hidden;
}

.right-panel {
  width: 300px;
  border-left: 1px solid #e0e0e0;
  background: #fafafa;
  display: flex;
  flex-direction: column;
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

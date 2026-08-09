<script setup lang="ts">
import { computed } from 'vue'
import type { ChatApprovalCard } from '@/types/chat-ui'

const props = defineProps<{
  card: ChatApprovalCard
  busy?: boolean
}>()

defineEmits<{
  confirm: []
  cancel: []
  'open-approval': [path: string]
}>()

const hasPersistedApproval = computed(
  () => Boolean(props.card.approval_path || props.card.approval_request_ids?.length),
)
</script>

<template>
  <div class="approval-inline" data-testid="chat-approval-inline-card">
    <div class="approval-head">
      <span class="approval-dot" aria-hidden="true"></span>
      <span class="approval-title">{{ card.approval_required ? '需要审批确认' : '执行前确认' }}</span>
      <span v-if="card.intent" class="approval-intent">{{ card.intent }}</span>
    </div>
    <div v-if="card.reason" class="approval-reason">{{ card.reason }}</div>
    <div v-if="card.blocking_nodes?.length" class="approval-chips">
      <span v-for="node in card.blocking_nodes" :key="node" class="approval-chip">{{ node }}</span>
    </div>
    <ul v-if="card.todo?.length" class="approval-todo">
      <li v-for="(step, idx) in card.todo" :key="idx">{{ step }}</li>
    </ul>
    <div v-if="card.approval_request_ids?.length" class="approval-request-nos">
      审批请求号：{{ card.approval_request_ids.join('、') }}
    </div>
    <div class="approval-actions">
      <button
        v-if="hasPersistedApproval"
        type="button"
        class="approval-btn approval-btn--primary"
        :disabled="busy"
        @click="$emit('open-approval', card.approval_path || '/mod/xcagi-approval-bridge/approval-hub/workspace')"
      >
        前往审批
      </button>
      <button v-else type="button" class="approval-btn approval-btn--primary" :disabled="busy" @click="$emit('confirm')">
        {{ card.approval_required ? '提交审批' : '确认执行' }}
      </button>
      <button v-if="!hasPersistedApproval" type="button" class="approval-btn approval-btn--ghost" :disabled="busy" @click="$emit('cancel')">
        取消
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Trae/Cursor 风格：无框、左侧色条、inline。 */
.approval-inline {
  --ap-fg: var(--xc-color-text-primary, #1f2937);
  --ap-muted: #6b7280;
  --ap-amber: #f59e0b;
  --ap-blue: #3b82f6;
  --ap-green: #10b981;
  --ap-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  position: relative;
  margin-top: 6px;
  padding: 2px 0 2px 10px;
  border-left: 2px solid var(--ap-amber);
  font-size: 12px;
  line-height: 1.6;
  color: var(--ap-fg);
}

.approval-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.approval-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ap-amber);
  flex-shrink: 0;
}

.approval-title {
  color: var(--ap-fg);
  font-weight: 500;
  font-size: 12px;
}

.approval-intent {
  color: var(--ap-muted);
  font-family: var(--ap-mono);
  font-size: 11px;
}

.approval-reason {
  color: var(--ap-muted);
  font-size: 12px;
  margin-top: 2px;
  padding-left: 12px;
}

.approval-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
  padding-left: 12px;
}

.approval-chip {
  background: rgba(59, 130, 246, 0.1);
  color: var(--ap-blue);
  padding: 0 5px;
  border-radius: 2px;
  font-family: var(--ap-mono);
  font-size: 10px;
}

.approval-todo {
  margin: 4px 0 0 16px;
  padding-left: 12px;
  font-size: 11px;
  color: var(--ap-muted);
  font-family: var(--ap-mono);
}

.approval-request-nos {
  margin-top: 4px;
  padding-left: 12px;
  color: var(--ap-muted);
  font-family: var(--ap-mono);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.approval-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  padding-left: 12px;
}

.approval-btn {
  background: transparent;
  border: 1px solid transparent;
  padding: 2px 10px;
  border-radius: 2px;
  font-size: 11px;
  cursor: pointer;
  line-height: 1.5;
  transition: background 0.12s;
}

.approval-btn--primary {
  color: var(--ap-green);
  border-color: rgba(16, 185, 129, 0.4);
}

.approval-btn--primary:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.1);
}

.approval-btn--primary:disabled,
.approval-btn--ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.approval-btn--ghost {
  color: var(--ap-muted);
  border-color: rgba(127, 127, 127, 0.3);
}

.approval-btn--ghost:hover:not(:disabled) {
  background: rgba(127, 127, 127, 0.08);
}

@media (prefers-color-scheme: dark) {
  .approval-inline {
    --ap-fg: #e5e7eb;
    --ap-muted: #9ca3af;
  }

  .approval-title {
    color: #e5e7eb;
  }

  .approval-chip {
    background: rgba(59, 130, 246, 0.2);
    color: #93c5fd;
  }

  .approval-btn--primary {
    color: #6ee7b7;
    border-color: rgba(16, 185, 129, 0.5);
  }

  .approval-btn--ghost {
    color: #9ca3af;
    border-color: rgba(255, 255, 255, 0.15);
  }

  .approval-btn--ghost:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.05);
  }
}
</style>

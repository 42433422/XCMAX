<template>
  <Transition name="suggestion-slide">
    <div v-if="suggestion" class="suggestion-toast" role="status" aria-live="polite">
      <div class="suggestion-content">
        <span class="suggestion-icon">💡</span>
        <p>{{ suggestion.message }}</p>
      </div>
      <div class="suggestion-actions">
        <button
          v-if="suggestion.actionLabel"
          type="button"
          class="suggestion-btn suggestion-btn--primary"
          @click="onAction"
        >
          {{ suggestion.actionLabel }}
        </button>
        <button type="button" class="suggestion-btn suggestion-btn--ghost" @click="$emit('dismiss', suggestion.id)">
          忽略
        </button>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import type { Suggestion } from '../../composables/agent/useAgentSuggestions'

const props = defineProps<{ suggestion: Suggestion | null }>()
const emit = defineEmits<{
  (e: 'dismiss', id: string): void
  (e: 'open-panel'): void
}>()

const router = useRouter()
const agentStore = useAgentStore()

function onAction() {
  if (!props.suggestion) return
  if (props.suggestion.actionRoute) {
    void router.push({ name: props.suggestion.actionRoute })
    emit('dismiss', props.suggestion.id)
  } else {
    agentStore.openPanel()
    emit('open-panel')
    emit('dismiss', props.suggestion.id)
  }
}
</script>

<style scoped>
.suggestion-toast {
  position: fixed;
  bottom: 100px;
  right: 24px;
  width: min(320px, calc(100vw - 48px));
  background: #1a1a2e;
  border: 1px solid rgba(0, 180, 255, 0.3);
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  z-index: 11050;
}

.suggestion-content {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.suggestion-icon {
  font-size: 1.2rem;
  flex-shrink: 0;
  margin-top: 1px;
}

.suggestion-content p {
  font-size: 0.84rem;
  color: rgba(255, 255, 255, 0.82);
  line-height: 1.45;
  margin: 0;
}

.suggestion-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.suggestion-btn {
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}

.suggestion-btn--primary {
  background: rgba(0, 180, 255, 0.15);
  color: #7dd3fc;
  border: 1px solid rgba(0, 180, 255, 0.3);
}

.suggestion-btn--primary:hover {
  background: rgba(0, 180, 255, 0.25);
}

.suggestion-btn--ghost {
  background: transparent;
  color: rgba(255, 255, 255, 0.35);
}

.suggestion-btn--ghost:hover {
  color: rgba(255, 255, 255, 0.6);
}

.suggestion-slide-enter-active,
.suggestion-slide-leave-active {
  transition: all 0.25s ease;
}

.suggestion-slide-enter-from,
.suggestion-slide-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>

<template>
  <div class="msg-act" :class="`msg-act--${role}`" role="group" aria-label="消息操作">
    <button v-if="role === 'assistant'" type="button" class="msg-act__btn" :title="speakLabel" @click="$emit('speak')">
      {{ speakLabel }}
    </button>
    <button type="button" class="msg-act__btn" title="复制原文" aria-label="复制" @click="onCopy">
      {{ copied ? '已复制' : '复制' }}
    </button>
    <button v-if="role === 'user'" type="button" class="msg-act__btn" title="编辑后重发" @click="$emit('edit')">
      编辑
    </button>
    <button v-if="role === 'assistant' && canRegenerate" type="button" class="msg-act__btn" title="重新生成" aria-label="重新生成" @click="$emit('regenerate')">
      重新生成
    </button>
    <button
      v-if="role === 'assistant'"
      type="button"
      class="msg-act__btn"
      :class="{ 'msg-act__btn--up': feedback === 'up' }"
      title="赞"
      @click="$emit('feedback', feedback === 'up' ? null : 'up')"
    >👍</button>
    <button
      v-if="role === 'assistant'"
      type="button"
      class="msg-act__btn"
      :class="{ 'msg-act__btn--down': feedback === 'down' }"
      title="踩"
      @click="$emit('feedback', feedback === 'down' ? null : 'down')"
    >👎</button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  role: 'user' | 'assistant' | 'system'
  content: string
  feedback?: 'up' | 'down' | null
  canRegenerate?: boolean
  speaking?: boolean
}>()

defineEmits<{
  (e: 'edit'): void
  (e: 'regenerate'): void
  (e: 'speak'): void
  (e: 'feedback', v: 'up' | 'down' | null): void
}>()

const copied = ref(false)
const speakLabel = computed(() => (props.speaking ? '停止' : '朗读'))

async function onCopy() {
  try {
    await navigator.clipboard.writeText(props.content || '')
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 1500)
  } catch {
    copied.value = false
  }
}
</script>

<style scoped>
.msg-act {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
  margin-top: 0.5rem;
  opacity: 0;
  transition: opacity 200ms ease;
}

.msg-act:hover,
.msg-act:focus-within {
  opacity: 1;
}

@media (hover: none) {
  .msg-act {
    opacity: 1;
  }
}

.msg-act--user {
  justify-content: flex-end;
}

.msg-act__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 1.52rem;
  padding: 0.12rem 0.56rem;
  border-radius: 999px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
    rgba(15, 23, 42, 0.2);
  border: 1px solid rgba(148, 163, 184, 0.12);
  color: rgba(203, 213, 225, 0.68);
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.025em;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.055);
  transition:
    background 140ms ease,
    color 140ms ease,
    border-color 140ms ease,
    transform 140ms ease;
}

.msg-act__btn:hover {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.03)),
    rgba(99, 102, 241, 0.16);
  color: #fff;
  border-color: rgba(165, 180, 252, 0.3);
  transform: translateY(-1px);
}

.msg-act__btn--up {
  background:
    linear-gradient(180deg, rgba(94, 234, 212, 0.16), rgba(45, 212, 191, 0.07)),
    rgba(15, 23, 42, 0.22);
  color: #5eead4;
  border-color: rgba(45, 212, 191, 0.32);
}

.msg-act__btn--down {
  background:
    linear-gradient(180deg, rgba(248, 113, 113, 0.14), rgba(248, 113, 113, 0.06)),
    rgba(15, 23, 42, 0.22);
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.28);
}

html[data-workbench-theme='light'] .msg-act__btn {
  background: rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(0, 0, 0, 0.08);
  color: #86868b;
}

html[data-workbench-theme='light'] .msg-act__btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
  border-color: rgba(0, 113, 227, 0.2);
}

html[data-workbench-theme='light'] .msg-act__btn--up {
  background: rgba(52, 168, 83, 0.08);
  color: #34a853;
  border-color: rgba(52, 168, 83, 0.2);
}

html[data-workbench-theme='light'] .msg-act__btn--down {
  background: rgba(215, 0, 21, 0.08);
  color: #d70015;
  border-color: rgba(215, 0, 21, 0.2);
}
</style>

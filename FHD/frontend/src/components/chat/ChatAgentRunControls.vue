<template>
  <button
    v-if="task.type === 'agent_run' && (task.status === 'running' || task.status === 'queued')"
    class="btn btn-secondary btn-sm"
    @click="$emit('pause', task.id)"
  >
    <i class="fa fa-pause" aria-hidden="true" />
    {{ $t('chat.pauseTask') }}
  </button>
  <button
    v-if="task.type === 'agent_run' && task.status === 'paused'"
    class="btn btn-primary btn-sm"
    @click="$emit('resume', task.id)"
  >
    <i class="fa fa-play" aria-hidden="true" />
    {{ $t('chat.resumeTask') }}
  </button>
  <button
    v-if="task.status === 'failed' || task.status === 'cancelled'"
    class="btn btn-primary btn-sm"
    @click="$emit('retry', task.id)"
  >
    {{ $t('chat.retryTask') }}
  </button>
  <button
    v-if="task.status === 'running' || task.status === 'queued' || task.status === 'paused'"
    class="btn btn-secondary btn-sm"
    @click="$emit('cancel', task.id)"
  >
    {{ $t('chat.cancel') }}
  </button>
</template>

<script setup lang="ts">
import type { TaskItem } from '@/composables/useChatPersistence'

defineProps<{ task: TaskItem }>()
defineEmits<{
  pause: [id: string]
  resume: [id: string]
  retry: [id: string]
  cancel: [id: string]
}>()
</script>

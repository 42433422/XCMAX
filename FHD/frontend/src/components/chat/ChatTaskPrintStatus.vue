<template>
  <button
    v-if="!task.printPending && !task.printCompleted && !task.printTerminal"
    type="button"
    class="btn btn-success btn-sm"
    data-action="start-print"
    @click="$emit('start-print')"
  >
    {{ $t('chat.startPrint') }}
  </button>
  <span v-else-if="task.printPending" class="task-print-pending">
    已提交打印队列，等待设备完成；尚未标记已打印。
    <button
      v-if="task.printJobToken"
      type="button"
      class="btn btn-secondary btn-sm"
      data-action="check-print-status"
      :disabled="task.printStatusChecking"
      @click="$emit('check-print-status')"
    >
      {{ task.printStatusChecking ? '正在检查' : '检查打印状态' }}
    </button>
  </span>
  <span v-else-if="task.printCompleted" class="task-print-pending">
    已由打印机确认完成，发货记录已更新。
  </span>
  <span v-else class="task-print-pending">
    当前打印任务未完成且不能重复提交；请重新生成发货单后再打印。
  </span>
</template>

<script setup lang="ts">
import type { ShipmentTask } from '@/composables/useShipmentTask'

defineProps<{ task: ShipmentTask }>()
defineEmits<{ 'start-print': []; 'check-print-status': [] }>()
</script>

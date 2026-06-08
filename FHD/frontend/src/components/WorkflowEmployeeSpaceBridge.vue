<script setup lang="ts">
/**
 * 全局事件桥：副窗/星标链路在 window 上派发的 CustomEvent，在智能对话未挂载时仍写入员工空间快照。
 * 不操作聊天任务列表（仍由 useChatView 负责）。
 */
import { onBeforeUnmount, onMounted } from 'vue'
import { useWorkflowEmployeeSpaceStore } from '@/stores/workflowEmployeeSpace'

const space = useWorkflowEmployeeSpaceStore()

function onLabelPrint(evt: Event) {
  const d = (evt as CustomEvent).detail || {}
  space.applyLabelPrintBridge(d)
}

function onReceipt(evt: Event) {
  const d = (evt as CustomEvent).detail || {}
  space.applyReceiptBridge(d)
}

function onWechatAiTask(evt: Event) {
  const d = (evt as CustomEvent).detail || {}
  space.applyWechatMsgBridge(d)
}

function onStarFeedPolled(evt: Event) {
  const d = (evt as CustomEvent).detail || {}
  space.applyWechatStarFeedPolledBridge(d)
}

onMounted(() => {
  window.addEventListener('xcagi:workflow-label-print-signal', onLabelPrint)
  window.addEventListener('xcagi:workflow-receipt-feedback-signal', onReceipt)
  window.addEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTask)
  window.addEventListener('xcagi:wechat-star-feed-polled', onStarFeedPolled)
})

onBeforeUnmount(() => {
  window.removeEventListener('xcagi:workflow-label-print-signal', onLabelPrint)
  window.removeEventListener('xcagi:workflow-receipt-feedback-signal', onReceipt)
  window.removeEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTask)
  window.removeEventListener('xcagi:wechat-star-feed-polled', onStarFeedPolled)
})
</script>

<template>
  <span style="display: none" aria-hidden="true" />
</template>

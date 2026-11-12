<template>
  <div class="page-view chat-debug-view" id="view-chat-debug">
    <div class="page-content">
      <div class="page-header">
        <h2>聊天调试工作台</h2>
        <p class="muted">测试普通版/专业版的意图和流程分支。此页只做本地模拟，不调用真实工具。</p>
      </div>

      <CdInputCard :tm="tm" />
      <CdTestPackCard :tm="tm" />
      <CdResultCards :tm="tm" />
      <CdCompareCard :tm="tm" />
    </div>
  </div>
</template>

<script setup>
// 原超大 SFC 已拆分至 ./chat-debug/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import CdInputCard from './chat-debug/CdInputCard.vue'
import CdTestPackCard from './chat-debug/CdTestPackCard.vue'
import CdResultCards from './chat-debug/CdResultCards.vue'
import CdCompareCard from './chat-debug/CdCompareCard.vue'
import { assembleChatDebug } from './chat-debug/assemble'

const tm = assembleChatDebug()
</script>

<style scoped src="./chat-debug/chat-debug.css"></style>

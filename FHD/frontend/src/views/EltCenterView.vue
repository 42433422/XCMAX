<template>
<main id="view-business-docking" class="elt-center elt-center--chatlike">
  <header class="elt-chat-header">
    <div>
      <h1>数据对接中心</h1>
      <p>上传 → 自动分类 → 选模板并入库。分类自动完成；核对所选文档后，点击「使用此模板并入库」才开始写入。</p>
    </div>
    <div class="elt-chat-header__actions">
      <RouterLink class="elt-chat-header__link" to="/template-preview">打开模板库</RouterLink>
    </div>
  </header>

  <AwEltAutoIngestList />
  <section class="elt-intake-shell" aria-label="导入会话">
    <ol class="elt-workflow-steps elt-workflow-steps--quiet" aria-label="导入流程">
      <li v-for="(step, index) in steps" :key="step.id" :aria-current="currentStep === step.id ? 'step' : undefined" :class="{ active: currentStep === step.id }"><span>{{ index + 1 }}</span>{{ step.label }}</li>
    </ol>
    <ReviewedExcelTemplate archive-on-select @stage="setStage" @saved="onTemplateSaved" />
  </section>
</main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ReviewedExcelTemplate from '@/components/template/ReviewedExcelTemplate.vue'
import AwEltAutoIngestList from '../../../mods/xcagi-approval-bridge/frontend/views/approval-workspace/AwEltAutoIngestList.vue'
import { ELT_CENTER_TABS } from './eltCenter/eltCenterState'

const steps = ELT_CENTER_TABS
const currentStep = ref('archive')

function setStage(stage: string) {
  currentStep.value = stage === 'archive' ? 'archive' : stage === 'template' || stage === 'cleaning' ? 'template' : 'classification'
}

function onTemplateSaved() {
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'elt-center' } }))
}
</script>

<style scoped src="./EltCenterView.css"></style>

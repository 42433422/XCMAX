<template>
<main id="view-business-docking" class="elt-center elt-center--chatlike">
  <header class="elt-chat-header">
    <h1>数据对接中心</h1>
    <RouterLink class="elt-chat-header__link" to="/template-preview">打开模板库</RouterLink>
  </header>

  <section class="elt-intake-shell" aria-label="导入会话">
    <ol class="elt-workflow-steps" aria-label="导入流程">
      <li v-for="(step, index) in steps" :key="step.id" :aria-current="currentStep === step.id ? 'step' : undefined" :class="{ active: currentStep === step.id }"><span>{{ index + 1 }}</span>{{ step.label }}</li>
    </ol>
    <ReviewedExcelTemplate archive-on-select @stage="setStage" @saved="onTemplateSaved" />
  </section>
</main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ReviewedExcelTemplate from '@/components/template/ReviewedExcelTemplate.vue'
import { ELT_CENTER_TABS } from './eltCenter/eltCenterState'

const steps = ELT_CENTER_TABS
const currentStep = ref('archive')

function setStage(stage: string) {
  currentStep.value = stage === 'archive' ? 'archive' : stage === 'template' || stage === 'cleaning' ? 'template' : 'classification'
}

function onTemplateSaved() {
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'etl-center' } }))
}
</script>

<style scoped src="./EltCenterView.css"></style>

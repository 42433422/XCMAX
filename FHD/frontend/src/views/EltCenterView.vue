<template>
<main id="view-business-docking" class="etl-center etl-center--chatlike">
  <header class="etl-chat-header">
    <div>
      <h1>数据对接中心</h1>
      <p>上传 → 自动分类 → 选模板并入库。分类自动完成；核对所选文档后，点击「使用此模板并入库」才开始写入。</p>
    </div>
    <div class="etl-chat-header__actions">
      <RouterLink class="etl-chat-header__link" to="/template-preview">打开模板库</RouterLink>
    </div>
  </header>

  <nav class="etl-workspaces" aria-label="数据对接工作区">
    <button type="button" :class="{ active: workspace === 'archive' }" :aria-pressed="workspace === 'archive'" @click="returnToArchive">导入</button>
    <button type="button" :class="{ active: workspace === 'history' }" :aria-pressed="workspace === 'history'" @click="workspace = 'history'">历史导入任务</button>
  </nav>

  <section v-show="workspace === 'archive'" class="etl-intake-shell" aria-label="导入会话">
    <ol class="etl-workflow-steps etl-workflow-steps--quiet" aria-label="导入流程">
      <li v-for="(step, index) in steps" :key="step.id" :aria-current="currentStep === step.id ? 'step' : undefined" :class="{ active: currentStep === step.id }"><span>{{ index + 1 }}</span>{{ step.label }}</li>
    </ol>
    <ReviewedExcelTemplate archive-on-select @stage="setStage" @saved="onTemplateSaved" />
  </section>
  <EltRunHistory v-if="workspace === 'history'" @return-to-import="returnToArchive" />
</main>
</template>

<script setup lang="ts">
import { defineAsyncComponent, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ReviewedExcelTemplate from '@/components/template/ReviewedExcelTemplate.vue'
import { ETL_CENTER_TABS } from './eltCenter/eltCenterState'

const EltRunHistory = defineAsyncComponent(() => import('./eltCenter/EltRunHistory.vue'))
const route = useRoute()
const router = useRouter()
const workspace = ref(route.query.run_id ? 'history' : 'archive')
const steps = ETL_CENTER_TABS
const currentStep = ref('archive')

watch(() => route.query.run_id, (id) => {
  if (id) workspace.value = 'history'
})

function returnToArchive() {
  workspace.value = 'archive'
  if (route.query.run_id) {
    const query = { ...route.query }
    delete query.run_id
    void router.replace({ query })
  }
}

function setStage(stage: string) {
  currentStep.value = stage === 'archive' ? 'archive' : stage === 'template' || stage === 'cleaning' ? 'template' : 'classification'
}

function onTemplateSaved() {
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'etl-center' } }))
}
</script>

<style scoped src="./EltCenterView.css"></style>

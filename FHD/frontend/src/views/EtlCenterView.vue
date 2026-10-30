<template src="./EtlCenterView.template.html"></template>

<script setup lang="ts">
import { defineAsyncComponent, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ReviewedExcelTemplate from '@/components/template/ReviewedExcelTemplate.vue'
import { ETL_CENTER_TABS } from './etlCenter/etlCenterState'

const EtlRunHistory = defineAsyncComponent(() => import('./etlCenter/EtlRunHistory.vue'))
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

<style scoped src="./EtlCenterView.css"></style>

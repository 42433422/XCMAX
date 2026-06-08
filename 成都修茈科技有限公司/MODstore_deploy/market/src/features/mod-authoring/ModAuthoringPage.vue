<script setup lang="ts">
import { ref, watch } from 'vue'
import { provideModAuthoring } from './composables/useModAuthoringContext'
import { EXPERT_MODE_STORAGE_KEY } from './types'
import ModAuthoringHeader from './ModAuthoringHeader.vue'
import ModAuthoringExpert from './expert/ModAuthoringExpert.vue'
import ModAuthoringWizard from './wizard/ModAuthoringWizard.vue'
import ExpertEmployeeModals from './expert/ExpertEmployeeModals.vue'
import './shared/mod-authoring.css'

function readExpertMode(): boolean {
  try {
    return localStorage.getItem(EXPERT_MODE_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

const expertMode = ref(readExpertMode())
const ctx = provideModAuthoring()
const { loading, loadError, modData, message, messageOk, goRepo, tab } = ctx

watch(expertMode, (v) => {
  try {
    if (v) localStorage.setItem(EXPERT_MODE_STORAGE_KEY, '1')
    else localStorage.removeItem(EXPERT_MODE_STORAGE_KEY)
  } catch {
    /* ignore */
  }
})

function openExpert(tabId?: string) {
  expertMode.value = true
  if (tabId) ctx.tab.value = tabId
}
</script>

<template>
  <div class="authoring-page">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="loadError" class="panel panel-err">
      <p>{{ loadError }}</p>
      <button type="button" class="btn" @click="goRepo">返回 Mod 仓库</button>
    </div>
    <template v-else-if="modData">
      <ModAuthoringHeader v-model:expert-mode="expertMode" />

      <div
        v-if="message"
        :class="['flash', messageOk ? 'flash-ok' : 'flash-err', message.length > 80 ? 'flash-multiline' : '']"
        role="status"
      >
        {{ message }}
      </div>

      <ModAuthoringExpert v-if="expertMode" />
      <ModAuthoringWizard v-else @open-expert="openExpert" />
      <ExpertEmployeeModals />
    </template>
  </div>
</template>

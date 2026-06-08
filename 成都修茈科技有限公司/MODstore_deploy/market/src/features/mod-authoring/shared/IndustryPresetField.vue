<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const {
  industryPresetList,
  selectedIndustryPreset,
  savingManifest,
  applyIndustryPresetToManifest,
  manifestSidebarStatus,
} = useModAuthoringContext()
</script>

<template>
  <div class="industry-adapt-panel">
    <h3 class="sub-title">行业</h3>
    <div class="industry-adapt-row">
      <select v-model="selectedIndustryPreset" class="input industry-adapt-select industry-select">
        <option v-for="p in industryPresetList" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="savingManifest"
        @click="applyIndustryPresetToManifest"
      >
        {{ savingManifest ? '保存中…' : '保存' }}
      </button>
    </div>
    <p v-if="manifestSidebarStatus.industryId" class="muted small industry-saved-line">
      当前：{{ manifestSidebarStatus.industryName }}
      <span v-if="manifestSidebarStatus.menuCount > 0"> · 菜单 {{ manifestSidebarStatus.menuCount }} 项</span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'
import ExpertTabGuide from './ExpertTabGuide.vue'
import ExpertTabManifest from './ExpertTabManifest.vue'
import ExpertTabFrontend from './ExpertTabFrontend.vue'
import ExpertTabFiles from './ExpertTabFiles.vue'
import ExpertTabSnapshots from './ExpertTabSnapshots.vue'
import ExpertTabScan from './ExpertTabScan.vue'
const { EXPERT_TABS, tab } = useModAuthoringContext()
</script>

<template>
  <nav class="tabs">
    <button
      v-for="t in EXPERT_TABS"
      :key="t.id"
      type="button"
      class="tab"
      :class="{ active: tab === t.id }"
      @click="tab = t.id"
    >
      {{ t.label }}
    </button>
  </nav>

  <ExpertTabGuide v-show="tab === 'guide'" />
  <ExpertTabManifest v-show="tab === 'manifest'" />
  <ExpertTabFrontend v-show="tab === 'frontend'" />
  <ExpertTabFiles v-show="tab === 'files'" />
  <ExpertTabSnapshots v-show="tab === 'snapshots'" />
  <ExpertTabScan v-show="tab === 'scan'" />
</template>

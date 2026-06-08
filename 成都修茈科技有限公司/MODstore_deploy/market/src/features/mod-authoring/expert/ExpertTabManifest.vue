<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { manifestText, manifestSaveWarnings, savingManifest, saveManifest, loading, reload } =
  useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <div class="panel-actions">
      <h2 class="panel-title panel-title--inline">配置</h2>
      <button type="button" class="btn btn-primary" :disabled="savingManifest" @click="saveManifest">
        {{ savingManifest ? '保存中…' : '保存' }}
      </button>
      <button type="button" class="btn" :disabled="loading" @click="reload">重载</button>
    </div>
    <p v-if="manifestSaveWarnings.length" class="warn-block">
      <span v-for="(w, i) in manifestSaveWarnings" :key="i">{{ w }}<br v-if="i < manifestSaveWarnings.length - 1" /></span>
    </p>
    <textarea v-model="manifestText" class="code-area" spellcheck="false" />
  </section>
</template>

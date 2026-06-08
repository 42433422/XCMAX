<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const {
  sortedFiles,
  selectedPath,
  fileContent,
  loadingFile,
  savingFile,
  fileWarnings,
  onPathSelect,
  loadSelectedFile,
  saveFile,
} = useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">文件</h2>
    <div class="file-toolbar">
      <select v-model="selectedPath" class="select" @change="onPathSelect">
        <option value="">选择文件…</option>
        <option v-for="p in sortedFiles" :key="p" :value="p">{{ p }}</option>
      </select>
      <button type="button" class="btn" :disabled="!selectedPath || loadingFile" @click="loadSelectedFile">读</button>
      <button type="button" class="btn btn-primary" :disabled="!selectedPath || savingFile" @click="saveFile">
        {{ savingFile ? '…' : '存' }}
      </button>
    </div>
    <p v-if="fileWarnings.length" class="warn-block">
      <span v-for="(w, i) in fileWarnings" :key="i">{{ w }}<br v-if="i < fileWarnings.length - 1" /></span>
    </p>
    <textarea v-model="fileContent" class="code-area" spellcheck="false" :placeholder="selectedPath ? '' : '先选文件'" />
  </section>
</template>

<script setup lang="ts">
import IndustryPresetField from '../shared/IndustryPresetField.vue'
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { modId, nameDraft, descriptionDraft, saveDescriptionFromWizard, savingManifest } =
  useModAuthoringContext()
</script>

<template>
  <section class="panel wizard-panel">
    <div class="form-group full-width mod-name-field">
      <label class="label visually-hidden" for="mod-display-name">Mod 名称</label>
      <input
        id="mod-display-name"
        v-model="nameDraft"
        class="input panel-title panel-title-input"
        type="text"
        maxlength="128"
        placeholder="填写 Mod 显示名称"
        autocomplete="off"
        spellcheck="false"
      />
      <p class="muted small mod-id-line">
        可编辑显示名 · ID <code class="mono">{{ modId }}</code>
      </p>
    </div>
    <div class="form-group full-width">
      <label class="label">介绍</label>
      <textarea
        v-model="descriptionDraft"
        class="input textarea"
        rows="2"
        maxlength="2000"
        placeholder="一句话说明用途"
      />
    </div>
    <button
      type="button"
      class="btn btn-primary btn-sm"
      :disabled="savingManifest"
      @click="() => void saveDescriptionFromWizard()"
    >
      {{ savingManifest ? '保存中…' : '保存' }}
    </button>
    <IndustryPresetField />
  </section>
</template>

<script setup>
import { defineProps } from 'vue'

// 拆分自 BrainView.vue 模板（原第 311–341 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  activityLines, modelsLoading, modelsError, publicModels, architectureDiagram,
} = props.tm
</script>

<template>
        <aside class="brain-obs" aria-label="观测与活动">
          <div class="brain-obs-section">
            <div class="brain-obs-title">活动流</div>
            <p class="muted brain-obs-hint">占位：后续可对接 Planner / Agent 事件或审计日志。</p>
            <ul class="brain-activity-log">
              <li v-for="(line, i) in activityLines" :key="i" class="brain-activity-log__item">
                <span class="brain-activity-log__ts">{{ line.ts }}</span>
                <span class="brain-activity-log__msg">{{ line.msg }}</span>
              </li>
            </ul>
          </div>
          <details class="brain-details brain-obs-details brain-obs-models">
            <summary>模型注册（GET /api/fhd/ai/models）</summary>
            <div v-if="modelsLoading" class="muted brain-models-hint">加载中…</div>
            <div v-else-if="modelsError" class="muted text-warn">{{ modelsError }}</div>
            <ul v-else-if="publicModels.length" class="brain-models-list">
              <li v-for="m in publicModels" :key="m.id" class="brain-models-item">
                <div class="brain-models-row">
                  <code class="brain-mono brain-models-id">{{ m.id }}</code>
                  <span class="brain-models-chip">{{ m.provider }}</span>
                </div>
                <div class="brain-models-label">{{ m.label }}</div>
              </li>
            </ul>
            <p v-else class="muted brain-models-hint">暂无条目（可在后端配置 FHD_PUBLIC_MODEL_REGISTRY_JSON）</p>
          </details>
          <details class="brain-details brain-obs-details">
            <summary>架构简图（折叠）</summary>
            <pre class="brain-diagram brain-diagram--compact" aria-label="三层架构简图">{{ architectureDiagram }}</pre>
          </details>
        </aside>
</template>

<style scoped src="./brain.css"></style>

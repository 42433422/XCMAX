<script setup>
import { defineProps } from 'vue'

// 拆分自 ChatDebugView.vue 模板（原第 95–131 行：当前模式结果 / 流程阶段 / 流程追踪）；
// 模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const { result } = props.tm
</script>

<template>
      <div class="card" v-if="result">
        <div class="card-header">当前模式结果</div>
        <div class="result-grid">
          <div class="result-item">
            <span class="result-label">模式</span>
            <span class="result-value">{{ result.modeLabel }}</span>
          </div>
          <div class="result-item">
            <span class="result-label">识别意图</span>
            <span class="result-value intent-pill">{{ result.intentLabel }}</span>
          </div>
          <div class="result-item">
            <span class="result-label">流程分支</span>
            <span class="result-value">{{ result.flow }}</span>
          </div>
          <div class="result-item">
            <span class="result-label">拟调用工具</span>
            <span class="result-value">{{ result.mockTools.join(' -> ') }}</span>
          </div>
        </div>
        <p><strong>模拟回复：</strong>{{ result.reply }}</p>
        <p class="muted"><strong>风险提示：</strong>{{ result.riskHint }}</p>
      </div>

      <div class="card" v-if="result && result.stages.length">
        <div class="card-header">流程阶段</div>
        <div class="stage-row">
          <div v-for="(s, idx) in result.stages" :key="`${s}-${idx}`" class="stage-chip">{{ s }}</div>
        </div>
      </div>

      <div class="card" v-if="result && result.steps.length">
        <div class="card-header">流程追踪</div>
        <ol class="steps">
          <li v-for="(step, idx) in result.steps" :key="idx">{{ step }}</li>
        </ol>
      </div>
</template>

<style scoped src="./chat-debug.css"></style>

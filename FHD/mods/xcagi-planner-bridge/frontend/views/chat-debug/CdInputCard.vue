<script setup>
import { defineProps } from 'vue'

// 拆分自 ChatDebugView.vue 模板（原第 9–60 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  presetCases, applyPreset, mode, inputText,
  runSimulation, runCompareSimulation, addToTestPack, resetResult,
} = props.tm
</script>

<template>
      <div class="card">
        <div class="card-header">输入与模式</div>
        <div class="form-group">
          <label>快速测试样例</label>
          <div class="preset-row">
            <button
              v-for="item in presetCases"
              :key="item.label"
              type="button"
              class="preset-btn"
              @click="applyPreset(item.text)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>模式</label>
          <div class="mode-switch">
            <button
              type="button"
              class="btn"
              :class="mode === 'normal' ? 'btn-primary' : 'btn-secondary'"
              @click="mode = 'normal'"
            >
              普通版
            </button>
            <button
              type="button"
              class="btn"
              :class="mode === 'pro' ? 'btn-primary' : 'btn-secondary'"
              @click="mode = 'pro'"
            >
              专业版
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>测试输入</label>
          <textarea
            v-model="inputText"
            rows="3"
            placeholder="例如：给成都客户生成并打印今天发货单"
          ></textarea>
        </div>
        <div class="action-row">
          <button class="btn btn-primary" @click="runSimulation">单模式模拟</button>
          <button class="btn btn-secondary" @click="runCompareSimulation">双模式对比</button>
          <button class="btn btn-success" @click="addToTestPack">加入测试包</button>
          <button class="btn btn-secondary" @click="resetResult">清空</button>
        </div>
      </div>
</template>

<style scoped src="./chat-debug.css"></style>

<script setup>
import { defineProps } from 'vue'

// 拆分自 ChatDebugView.vue 模板（原第 133–166 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const { compareResult } = props.tm
</script>

<template>
      <div class="card" v-if="compareResult">
        <div class="card-header">普通版 vs 专业版</div>
        <table class="data-table">
          <thead>
            <tr>
              <th>维度</th>
              <th>普通版</th>
              <th>专业版</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>意图</td>
              <td>{{ compareResult.normal.intentLabel }}</td>
              <td>{{ compareResult.pro.intentLabel }}</td>
            </tr>
            <tr>
              <td>流程</td>
              <td>{{ compareResult.normal.flow }}</td>
              <td>{{ compareResult.pro.flow }}</td>
            </tr>
            <tr>
              <td>拟调用工具</td>
              <td>{{ compareResult.normal.mockTools.join(' -> ') }}</td>
              <td>{{ compareResult.pro.mockTools.join(' -> ') }}</td>
            </tr>
            <tr>
              <td>回复摘要</td>
              <td>{{ compareResult.normal.reply }}</td>
              <td>{{ compareResult.pro.reply }}</td>
            </tr>
          </tbody>
        </table>
      </div>
</template>

<style scoped src="./chat-debug.css"></style>

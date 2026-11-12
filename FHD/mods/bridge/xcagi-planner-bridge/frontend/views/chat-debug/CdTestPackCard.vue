<script setup>
import { defineProps } from 'vue'

// 拆分自 ChatDebugView.vue 模板（原第 62–93 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  testPack, exportTestPackJson, exportTestPackTxt, clearTestPack,
  applyPreset, removeTestCase,
} = props.tm
</script>

<template>
      <div class="card">
        <div class="card-header">意图测试包</div>
        <div class="action-row" style="margin-bottom:10px;">
          <button class="btn btn-primary btn-sm" @click="exportTestPackJson" :disabled="!testPack.length">导出 JSON</button>
          <button class="btn btn-secondary btn-sm" @click="exportTestPackTxt" :disabled="!testPack.length">导出 TXT</button>
          <button class="btn btn-danger btn-sm" @click="clearTestPack" :disabled="!testPack.length">清空列表</button>
        </div>
        <div v-if="!testPack.length" class="muted">暂无测试句子，先在上方输入并点“加入测试包”。</div>
        <table v-else class="data-table test-pack-table">
          <thead>
            <tr>
              <th style="width:60px;">#</th>
              <th>测试句子</th>
              <th style="width:120px;">添加时间</th>
              <th style="width:170px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in testPack" :key="item.id">
              <td>{{ idx + 1 }}</td>
              <td>{{ item.text }}</td>
              <td>{{ item.timeLabel }}</td>
              <td>
                <div class="pack-actions">
                  <button class="btn btn-secondary btn-sm" @click="applyPreset(item.text)">回填</button>
                  <button class="btn btn-danger btn-sm" @click="removeTestCase(item.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
</template>

<style scoped src="./chat-debug.css"></style>

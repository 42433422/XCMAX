<script setup lang="ts">
// 拆分自 RepositoryView.vue 模板（原第 218–237 行 新建 Mod 弹窗）；模板逐字迁移，v-model 改为 computed + emits 写回，事件改为 emits，行为不变。
import { computed } from 'vue'
import type { IndustryPreset } from '../../constants/industryPresets'

const props = defineProps<{
  name: string
  industryId: string
  industryPresets: IndustryPreset[]
}>()

const emit = defineEmits<{
  (e: 'update:name', value: string): void
  (e: 'update:industryId', value: string): void
  (e: 'cancel'): void
  (e: 'create'): void
}>()

const name = computed({
  get: () => props.name,
  set: (value: string) => emit('update:name', value),
})
const industryId = computed({
  get: () => props.industryId,
  set: (value: string) => emit('update:industryId', value),
})
</script>

<template>
  <div class="modal-overlay" @click.self="$emit('cancel')">
    <div class="modal">
      <h2 class="modal-title">新建 Mod</h2>
      <div class="form-group">
        <label class="label">名称</label>
        <input v-model="name" class="input" placeholder="显示名称" />
      </div>
      <div class="form-group">
        <label class="label">目标行业</label>
        <select v-model="industryId" class="input">
          <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="$emit('cancel')">取消</button>
        <button class="btn btn-primary" @click="$emit('create')">创建</button>
      </div>
    </div>
  </div>
</template>

<style scoped src="./repository-view.css"></style>

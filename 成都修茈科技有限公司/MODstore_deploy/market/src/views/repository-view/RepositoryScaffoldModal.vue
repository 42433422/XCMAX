<script setup lang="ts">
// 拆分自 RepositoryView.vue 模板（原第 187–216 行 AI 脚手架弹窗）；模板逐字迁移，v-model 改为 computed + emits 写回，事件改为 emits，行为不变。
import { computed } from 'vue'
import type { IndustryPreset } from '../../constants/industryPresets'

const props = defineProps<{
  industryId: string
  brief: string
  idHint: string
  replace: boolean
  industryPresets: IndustryPreset[]
  scaffoldBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'update:industryId', value: string): void
  (e: 'update:brief', value: string): void
  (e: 'update:idHint', value: string): void
  (e: 'update:replace', value: boolean): void
  (e: 'cancel'): void
  (e: 'submit'): void
}>()

const industryId = computed({
  get: () => props.industryId,
  set: (value: string) => emit('update:industryId', value),
})
const brief = computed({
  get: () => props.brief,
  set: (value: string) => emit('update:brief', value),
})
const idHint = computed({
  get: () => props.idHint,
  set: (value: string) => emit('update:idHint', value),
})
const replace = computed({
  get: () => props.replace,
  set: (value: boolean) => emit('update:replace', value),
})
</script>

<template>
  <div class="modal-overlay" @click.self="$emit('cancel')">
    <div class="modal modal-wide">
      <h2 class="modal-title">AI 生成 Mod 脚手架</h2>
      <div class="form-group">
        <label class="label">目标行业</label>
        <select v-model="industryId" class="input industry-select">
          <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="label">描述</label>
        <textarea v-model="brief" class="input textarea" rows="4" placeholder="简要描述 Mod 用途" />
      </div>
      <div class="form-group">
        <label class="label">ID（可选）</label>
        <input v-model="idHint" class="input" placeholder="my-mod-id" />
      </div>
      <label class="checkbox-line">
        <input v-model="replace" type="checkbox" />
        若 id 已存在则覆盖导入
      </label>
      <div class="modal-actions">
        <button class="btn" type="button" :disabled="scaffoldBusy" @click="$emit('cancel')">取消</button>
        <button class="btn btn-primary" type="button" :disabled="scaffoldBusy" @click="$emit('submit')">
          {{ scaffoldBusy ? '生成中…' : '生成并导入' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="./repository-view.css"></style>

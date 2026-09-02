<script setup lang="ts">
// 拆分自 RepositoryView.vue 模板（原第 3–49 行 page-header）；模板逐字迁移，v-model 改为 computed + emits 写回，事件改为 emits，行为不变。
import { computed } from 'vue'
import type { IndustryPreset } from '../../constants/industryPresets'

const props = defineProps<{
  authoringIndustryId: string
  industryPresets: IndustryPreset[]
  headerMoreOpen: boolean
  purgeLibraryBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'update:authoringIndustryId', value: string): void
  (e: 'persist-industry'): void
  (e: 'open-create'): void
  (e: 'import', ev: Event): void
  (e: 'open-scaffold'): void
  (e: 'toggle-more'): void
  (e: 'purge'): void
}>()

const authoringIndustryId = computed({
  get: () => props.authoringIndustryId,
  set: (value: string) => emit('update:authoringIndustryId', value),
})
</script>

<template>
  <div class="page-header">
    <h1 class="page-title">Mod 能力货架</h1>
    <div class="industry-toolbar">
      <label class="label industry-toolbar-label">默认行业</label>
      <select v-model="authoringIndustryId" class="input industry-select" @change="$emit('persist-industry')">
        <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>
    <div class="header-actions">
      <button class="btn btn-primary" @click="$emit('open-create')">新建 Mod</button>
      <label class="btn">
        导入包（.zip / .xcmod）
        <input type="file" accept=".zip,.xcmod,.xcemp" class="hidden-input" @change="$emit('import', $event)" />
      </label>
      <button
        type="button"
        class="btn btn-secondary"
        title="使用已配置的默认大模型生成 manifest + 脚手架并导入（见 LLM 设置）"
        @click="$emit('open-scaffold')"
      >
        AI 生成脚手架
      </button>
      <div class="header-more-wrap">
        <button
          type="button"
          class="btn btn-sm"
          aria-haspopup="menu"
          :aria-expanded="headerMoreOpen"
          @click.stop="$emit('toggle-more')"
        >
          更多
        </button>
        <div v-if="headerMoreOpen" class="header-more-menu" role="menu" @click.stop>
          <button
            type="button"
            class="header-more-item header-more-item--danger"
            role="menuitem"
            :disabled="purgeLibraryBusy"
            title="删除当前账号 Mod 能力货架中的全部包（需登录），并清除本页提示与「带入员工制作」预填缓存；不可恢复"
            @click="$emit('purge')"
          >
            {{ purgeLibraryBusy ? '清空中…' : '一键清理' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./repository-view.css"></style>

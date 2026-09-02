<script setup lang="ts">
import type { TraditionalModeCtx } from './assemble'

// 拆分自 TraditionalModeView.vue 模板（原第 420–443 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: TraditionalModeCtx }>()

const {
  inductMissingModal, closeInductMissingModal, inductModalMissingList,
  inductCreateSelected, inductSelKey, inductCommitLoading, confirmInductCommitFromModal,
} = props.tm
</script>

<template>
    <div v-if="inductMissingModal" class="modal-overlay" @click.self="closeInductMissingModal">
      <div class="modal-box induct-missing-modal">
        <div class="modal-header">缺失主数据</div>
        <div class="modal-body">
          <p class="muted induct-missing-lead">以下数据在库中不存在。勾选「新增」后将在入库前创建；取消勾选将仍尝试入库（可能失败）。</p>
          <div v-if="inductModalMissingList.length === 0" class="muted">无待确认项</div>
          <div v-else class="induct-missing-groups">
            <div v-for="grp in inductModalMissingList" :key="grp.key" class="induct-missing-group">
              <div class="induct-missing-group-title">{{ grp.label }}</div>
              <label v-for="item in grp.items" :key="grp.key + ':' + item" class="induct-missing-item">
                <input type="checkbox" v-model="inductCreateSelected[inductSelKey(grp.key, item)]" />
                <span>{{ item }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeInductMissingModal">取消</button>
          <button type="button" class="btn btn-primary" :disabled="inductCommitLoading" @click="confirmInductCommitFromModal">
            {{ inductCommitLoading ? '处理中…' : '确认并入库' }}
          </button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./traditional-mode.css"></style>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="$emit('update:visible', false)">
    <div class="modal-content cs-add-customer-modal">
      <div class="modal-header">
        <h3>添加企业客户</h3>
        <button class="modal-close" type="button" @click="$emit('update:visible', false)">&times;</button>
      </div>
      <div class="modal-body">
        <p class="muted cs-add-customer-hint">
          内部客服列表显示「已勾选企业用户」的市场账号，以及已有商机 pipeline 档案的用户。勾选企业后刷新即可出现在左侧列表。
        </p>
        <input
          :value="filter"
          type="search"
          class="cs-input"
          placeholder="搜索用户名或邮箱"
          @input="$emit('update:filter', ($event.target as HTMLInputElement).value)"
          @keydown.enter.prevent
        >
        <div v-if="loading" class="loading-hint">加载用户…</div>
        <ul v-else class="cs-add-customer-list">
          <li
            v-for="u in pickerRows"
            :key="u.id"
            class="cs-add-customer-row"
            :class="{ 'is-listed': isCustomerListed(u.id) }"
          >
            <div class="cs-add-customer-row__main">
              <strong>{{ u.username }}</strong>
              <span class="muted">#{{ u.id }}</span>
              <span v-if="u.is_enterprise" class="cs-tag cs-tag--ok">企业</span>
              <span v-else-if="u.has_pipeline" class="cs-tag">有 pipeline</span>
            </div>
            <button
              v-if="!u.is_enterprise"
              type="button"
              class="btn btn-xs btn-secondary"
              :disabled="savingId === u.id"
              @click="$emit('mark-enterprise', u)"
            >
              {{ savingId === u.id ? '保存中…' : '设为企业客户' }}
            </button>
            <span v-else-if="isCustomerListed(u.id)" class="muted">已在列表</span>
            <button
              v-else
              type="button"
              class="btn btn-xs btn-ghost"
              @click="$emit('open-customer', u.id)"
            >
              打开
            </button>
          </li>
        </ul>
        <p v-if="!loading && !pickerRows.length" class="empty-hint">
          无匹配用户。可在用户 Mod 管理中创建市场账号后再添加。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export type AddCustomerPickerRow = {
  id: number
  username: string
  email?: string
  is_enterprise?: boolean
  has_pipeline?: boolean
}

defineProps<{
  visible: boolean
  loading: boolean
  filter: string
  savingId: number
  pickerRows: AddCustomerPickerRow[]
  isCustomerListed: (userId: number) => boolean
}>()

defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update:filter', value: string): void
  (e: 'mark-enterprise', u: AddCustomerPickerRow): void
  (e: 'open-customer', userId: number): void
}>()
</script>
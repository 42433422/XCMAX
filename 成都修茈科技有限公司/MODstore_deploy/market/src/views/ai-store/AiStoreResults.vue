<script setup lang="ts">
// 拆分自 AiStoreView.vue 模板（原第 198–318 行）；模板逐字迁移，事件改为 emits，行为不变。
import EmployeePackTypeIcon from '../../components/store/EmployeePackTypeIcon.vue'
import { isCatalogSaved } from '../../utils/catalogSaved'
import {
  complianceStatusLabel,
  customerServiceLink,
  employeeRoleLabel,
  formatSocialCount,
  truncate,
  type AiStoreDisplayGroup,
  type AiStoreItem,
} from './aiStoreTypes'

const props = defineProps<{
  groups: AiStoreDisplayGroup[]
  attachModId: string
  attachingId: number | string | null
  downloadingId: number | string | null
  favBusyId: number | string | null
  delistingId: number | string | null
  isAdmin: boolean | undefined
  savedRevision: number
}>()

defineEmits<{
  (e: 'attach', item: AiStoreItem): void
  (e: 'download', item: AiStoreItem): void
  (e: 'like', item: AiStoreItem): void
  (e: 'save', item: AiStoreItem): void
  (e: 'delist', item: AiStoreItem): void
}>()

function isItemSaved(id: number | string | undefined) {
  props.savedRevision
  return isCatalogSaved(id)
}
</script>

<template>
  <section
    v-for="group in groups"
    :key="group.key"
    class="store-group"
    :class="{ 'store-group--flat': !group.title }"
  >
    <header v-if="group.title" class="store-group__hd">
      <EmployeePackTypeIcon :kind="group.kind" />
      <h3 class="store-group__title">{{ group.title }}</h3>
      <span class="store-group__count">{{ group.items.length }} 个</span>
    </header>
    <div class="store-grid">
      <article v-for="item in group.items" :key="item.id" class="store-card">
        <header class="store-card__head">
          <EmployeePackTypeIcon :pkg-id="item.pkg_id" class="store-card__avatar" />
          <div class="store-card__titles">
            <div class="store-card__title-line">
              <h3 class="card-title">{{ item.name }}</h3>
              <span v-if="employeeRoleLabel(item.pkg_id)" class="card-role" :class="'card-role--' + employeeRoleLabel(item.pkg_id)">
                {{ employeeRoleLabel(item.pkg_id) === 'read' ? '读取' : '生成' }}
              </span>
            </div>
            <p class="card-meta">{{ item.pkg_id }} · v{{ item.version }}</p>
          </div>
        </header>
        <p class="card-desc">{{ truncate(item.description, 88) }}</p>
        <div class="card-badges">
          <span class="tag tag-industry">{{ item.industry || '通用' }}</span>
          <span
            v-if="item.license_scope === 'enterprise' && item.security_level === 'enterprise'"
            class="tag tag-enterprise"
          >企业级</span>
          <span v-if="item.purchased" class="tag tag-owned">已购</span>
          <span v-if="item.compliance_status && item.compliance_status !== 'approved'" class="tag tag-review">
            {{ complianceStatusLabel(item.compliance_status) }}
          </span>
        </div>
        <footer class="card-footer">
          <div class="card-footer__left">
            <span class="price" :class="{ free: item.price <= 0 }">
              {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
            </span>
            <button
              v-if="attachModId && item.artifact === 'employee_pack'"
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="attachingId === item.id"
              @click="$emit('attach', item)"
            >
              {{ attachingId === item.id ? '添加中…' : '添加到 Mod' }}
            </button>
            <button
              v-else
              type="button"
              class="btn btn-download btn-sm"
              :disabled="downloadingId === item.id"
              @click="$emit('download', item)"
            >
              {{ downloadingId === item.id ? '下载中…' : '下载' }}
            </button>
          </div>
          <div class="card-footer__social">
            <button
              type="button"
              class="card-social card-social--like"
              :class="{ 'card-social--on': item.favorited }"
              :disabled="favBusyId === item.id"
              :aria-pressed="!!item.favorited"
              :title="item.favorited ? '取消点赞' : '点赞'"
              @click="$emit('like', item)"
            >
              <span class="card-social__icon" aria-hidden="true">
                <svg class="card-social__svg" viewBox="0 0 24 24" focusable="false">
                  <path
                    class="card-social__glyph card-social__glyph--heart"
                    d="M12 20.5s-6.2-4.35-8.2-7.4C2.4 10.6 2.8 6.9 5.5 5.2c1.6-.9 3.6-.5 4.9 1 1.3-1.5 3.3-1.9 4.9-1 2.7 1.7 3.1 5.4 1.7 7.9-2 3.05-8.2 7.4-8.2 7.4z"
                  />
                </svg>
              </span>
              <span class="card-social__label">{{ formatSocialCount(item.favorite_count) }}</span>
            </button>
            <button
              type="button"
              class="card-social card-social--save"
              :class="{ 'card-social--on': isItemSaved(item.id) }"
              :aria-pressed="isItemSaved(item.id)"
              :title="isItemSaved(item.id) ? '取消收藏' : '收藏'"
              @click="$emit('save', item)"
            >
              <span class="card-social__icon" aria-hidden="true">
                <svg class="card-social__svg" viewBox="0 0 24 24" focusable="false">
                  <path
                    class="card-social__glyph card-social__glyph--star"
                    d="M12 3.2l2.35 4.76 5.25.77-3.8 3.7.9 5.23L12 15.9l-4.7 2.76.9-5.23-3.8-3.7 5.25-.77L12 3.2z"
                  />
                </svg>
              </span>
              <span class="card-social__label">收藏</span>
            </button>
          </div>
          <div class="card-actions">
            <button
              v-if="isAdmin"
              type="button"
              class="btn btn-danger btn-sm"
              :disabled="delistingId === item.id"
              @click="$emit('delist', item)"
            >
              {{ delistingId === item.id ? '下架中' : '下架' }}
            </button>
            <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn btn-detail btn-sm">
              详情
            </router-link>
            <router-link :to="customerServiceLink(item, 'complaint')" class="card-link-muted">申诉</router-link>
          </div>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped src="./ai-store.css"></style>

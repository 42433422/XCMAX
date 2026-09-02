/**
 * 客户端车间详情侧栏（仅 client 视图）。
 *
 * 由 AdminDutyEmployeeGraph.vue 模板块机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './adminDutyTypes'
import { YUANGON_AREAS } from '../../../domain/yuangonDutyRoster'
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyWorkshop } from './useAdminDutyWorkshop'

const emit = defineEmits<{
  (e: 'update:selectedWorkshop', v: Deref<AdminDutyState['selectedWorkshop']>): void
}>()

const props = defineProps<{
  selectedWorkshop: Deref<AdminDutyState['selectedWorkshop']>
  viewMode: Deref<AdminDutyState['viewMode']>
  workshopRouteCopied: Deref<AdminDutyState['workshopRouteCopied']>
  selectedWorkshopLinkedEmployees: Deref<AdminDutyWorkshop['selectedWorkshopLinkedEmployees']>
  selectedWorkshopRouteHref: Deref<AdminDutyWorkshop['selectedWorkshopRouteHref']>
  openSelectedWorkshopInClient: Deref<AdminDutyWorkshop['openSelectedWorkshopInClient']>
  copySelectedWorkshopRoute: Deref<AdminDutyWorkshop['copySelectedWorkshopRoute']>
  focusEmployeeFromWorkshop: Deref<AdminDutyWorkshop['focusEmployeeFromWorkshop']>
}>()

const selectedWorkshop = computed({
  get: () => props.selectedWorkshop,
  set: (v) => emit('update:selectedWorkshop', v),
})

</script>

<template>
              <transition name="dg-slide">
                <div v-if="selectedWorkshop && viewMode === 'client'" class="dg-detail dg-detail--workshop">
                  <div class="dg-detail-header">
                    <h3 class="dg-detail-name">{{ selectedWorkshop.label }}</h3>
                    <span
                      class="dg-workshop-status"
                      :class="selectedWorkshop.enabled ? 'dg-workshop-status--on' : 'dg-workshop-status--off'"
                    >
                      {{ selectedWorkshop.enabled ? '已启用' : '已停用' }}
                    </span>
                  </div>
                  <p class="dg-detail-id">{{ selectedWorkshop.id }}</p>
                  <p v-if="selectedWorkshop.description" class="dg-detail-meta">{{ selectedWorkshop.description }}</p>
                  <p class="dg-detail-meta">
                    类型：{{ selectedWorkshop.kind === 'gear' ? '档位车间' : '功能页车间' }}
                  </p>
                  <p v-if="selectedWorkshop.tags?.length" class="dg-detail-meta">
                    标签：{{ selectedWorkshop.tags.join(' · ') }}
                  </p>
                  <p v-if="selectedWorkshop.linkedAreaId" class="dg-detail-meta">
                    关联编制区：{{ YUANGON_AREAS[selectedWorkshop.linkedAreaId]?.label || selectedWorkshop.linkedAreaId }}
                  </p>

                  <div v-if="selectedWorkshopLinkedEmployees.length" class="dg-workshop-linked">
                    <p class="dg-workshop-linked__title">关联在岗员工</p>
                    <ul class="dg-workshop-linked__list">
                      <li v-for="emp in selectedWorkshopLinkedEmployees" :key="emp.id">
                        <button type="button" class="dg-workshop-linked__btn" @click="focusEmployeeFromWorkshop(emp.id)">
                          {{ emp.name || emp.id }}
                        </button>
                      </li>
                    </ul>
                    <p class="dg-workshop-linked__hint">点击员工将切换到「中心图」并定位节点。</p>
                  </div>

                  <div class="dg-workshop-actions">
                    <button
                      type="button"
                      class="dg-btn dg-btn--primary dg-btn--block"
                      :disabled="!selectedWorkshopRouteHref"
                      @click="openSelectedWorkshopInClient"
                    >
                      在浏览器打开客户端
                    </button>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost dg-btn--block"
                      :disabled="!selectedWorkshopRouteHref"
                      @click="copySelectedWorkshopRoute"
                    >
                      {{ workshopRouteCopied ? '已复制路径' : '复制客户端路径' }}
                    </button>
                  </div>
                  <p v-if="selectedWorkshopRouteHref" class="dg-workshop-route">
                    <code>{{ selectedWorkshopRouteHref }}</code>
                  </p>
                  <button type="button" class="dg-btn dg-btn--ghost dg-btn--sm" @click="selectedWorkshop = null">关闭</button>
                </div>
              </transition>
</template>

<style scoped src="../AdminDutyEmployeeGraph.css"></style>

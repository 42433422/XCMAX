/**
 * 顶部工具栏（标题 / 统计 / 视图切换 / 更多操作 / 返回与关闭）。
 *
 * 由 AdminDutyEmployeeGraph.vue 模板块机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './adminDutyTypes'
import { ALL_PLANNED_IDS } from './adminDutyConstants'
import type { AdminDutyData } from './useAdminDutyData'
import type { AdminDutyGap } from './useAdminDutyGap'
import type { AdminDutyGraphBuild } from './useAdminDutyGraphBuild'
import type { AdminDutyPanels } from './useAdminDutyPanels'
import type { AdminDutyState } from './useAdminDutyState'
import type { Router } from 'vue-router'

const emit = defineEmits<{
  (e: 'update:showStatsDetail', v: Deref<AdminDutyState['showStatsDetail']>): void
  (e: 'update:viewMode', v: Deref<AdminDutyState['viewMode']>): void
  (e: 'update:showMoreActions', v: Deref<AdminDutyState['showMoreActions']>): void
  (e: 'update:autoRefresh', v: Deref<AdminDutyState['autoRefresh']>): void
  (e: 'close'): void
}>()

const props = defineProps<{
  open: boolean
  isPage: boolean
  router: Router
  showStatsDetail: Deref<AdminDutyState['showStatsDetail']>
  viewMode: Deref<AdminDutyState['viewMode']>
  showMoreActions: Deref<AdminDutyState['showMoreActions']>
  autoRefresh: Deref<AdminDutyState['autoRefresh']>
  load: Deref<AdminDutyData['load']>
  employees: Deref<AdminDutyState['employees']>
  loading: Deref<AdminDutyState['loading']>
  loadingP2: Deref<AdminDutyState['loadingP2']>
  capLoading: Deref<AdminDutyState['capLoading']>
  countdown: Deref<AdminDutyState['countdown']>
  llmStatusFailed: Deref<AdminDutyState['llmStatusFailed']>
  selectedEmp: Deref<AdminDutyState['selectedEmp']>
  showGapPanel: Deref<AdminDutyState['showGapPanel']>
  showNoKeyPanel: Deref<AdminDutyState['showNoKeyPanel']>
  showRunPanel: Deref<AdminDutyState['showRunPanel']>
  showAllHandsPanel: Deref<AdminDutyState['showAllHandsPanel']>
  allHandsBusy: Deref<AdminDutyState['allHandsBusy']>
  gapSummary: Deref<AdminDutyGap['gapSummary']>
  stats: Deref<AdminDutyGraphBuild['stats']>
  openNoKeyPanel: Deref<AdminDutyPanels['openNoKeyPanel']>
  togglePanel: Deref<AdminDutyPanels['togglePanel']>
}>()

const showStatsDetail = computed({
  get: () => props.showStatsDetail,
  set: (v) => emit('update:showStatsDetail', v),
})

const viewMode = computed({
  get: () => props.viewMode,
  set: (v) => emit('update:viewMode', v),
})

const showMoreActions = computed({
  get: () => props.showMoreActions,
  set: (v) => emit('update:showMoreActions', v),
})

const autoRefresh = computed({
  get: () => props.autoRefresh,
  set: (v) => emit('update:autoRefresh', v),
})

</script>

<template>
          <div class="dg-header">
            <div class="dg-header-left">
              <span class="dg-title">在岗员工节点图</span>
              <span
                class="dg-roster-hint"
                title="节点仅 yuangonDutyRoster 编制内岗位 + 数字管家；不含 catalog 中其它员工包。若仍出现编制外名称，说明浏览器仍在使用旧前端资源，请重新构建并强刷（Ctrl+F5）或清 CDN 缓存。"
              >编制 {{ ALL_PLANNED_IDS.size }} 岗</span>

              <div v-if="employees.length" class="dg-stats">
                <span class="dg-stat">共 <strong>{{ stats.total }}</strong> 人</span>
                <span class="dg-stat dg-stat--ok">✓ {{ stats.catalogOk }}</span>
                <span class="dg-stat dg-stat--healthy">♥ {{ stats.healthy }}</span>
                <span v-if="stats.execReady" class="dg-stat dg-stat--ok">▶ {{ stats.execReady }}</span>
                <button
                  type="button"
                  class="dg-stat dg-stat--toggle"
                  :class="{ 'dg-stat--toggle-open': showStatsDetail }"
                  @click="showStatsDetail = !showStatsDetail"
                >{{ showStatsDetail ? '▴ 收起' : '▾ 更多' }}</button>
                <template v-if="showStatsDetail">
                  <span v-if="stats.v1Only" class="dg-stat dg-stat--warn">仅目录 {{ stats.v1Only }}</span>
                  <span v-if="stats.depEdges" class="dg-stat dg-stat--dep">依赖边 {{ stats.depEdges }}</span>
                  <span v-if="stats.highRisk" class="dg-stat dg-stat--warn">高风险 {{ stats.highRisk }}</span>
                  <span
                    v-if="llmStatusFailed"
                    class="dg-stat dg-stat--warn"
                    title="无法拉取 /api/llm/status，无法判断平台密钥与 BYOK；非全员无密钥"
                  >⚠ 密钥状态未加载</span>
                  <template v-else>
                    <span v-if="stats.llmActive" class="dg-stat dg-stat--llm-ok">⚡ LLM {{ stats.llmActive }}</span>
                    <button
                      v-if="stats.llmNoKey"
                      type="button"
                      class="dg-stat dg-stat--llm-err dg-stat--clickable"
                      :class="{ 'dg-stat--active': showNoKeyPanel }"
                      title="点击查看哪些员工无密钥，并一键改为「自动」或去添加账户密钥"
                      @click="openNoKeyPanel"
                    >✗ 无密钥 {{ stats.llmNoKey }}</button>
                  </template>
                  <span v-if="capLoading" class="dg-stat dg-stat--muted">能力校验中…</span>
                  <span v-if="loadingP2" class="dg-stat dg-stat--muted">⟳ 刷新中…</span>
                </template>
              </div>
            </div>

            <div class="dg-header-right">
              <div class="dg-toggle-group">
                <button :class="['dg-toggle', { active: viewMode === 'hub'  }]" @click="viewMode = 'hub' ">中心图</button>
                <button :class="['dg-toggle', { active: viewMode === 'department' }]" @click="viewMode = 'department'">六部门</button>
                <button :class="['dg-toggle', { active: viewMode === 'legacy-area' }]" @click="viewMode = 'legacy-area'">物理分区</button>
                <button :class="['dg-toggle', { active: viewMode === 'client' }]" @click="viewMode = 'client'">客户端车间</button>
              </div>

              <div class="dg-more-wrap">
                <button
                  :class="['dg-btn dg-btn--outline', { 'dg-btn--active': showMoreActions }]"
                  @click="showMoreActions = !showMoreActions"
                >操作 ▾</button>
                <transition name="dg-fade">
                  <div v-if="showMoreActions" class="dg-more-menu" @click="showMoreActions = false">
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showGapPanel }]"
                      @click="togglePanel('gap')"
                    >
                      缺岗分析
                      <span v-if="gapSummary.missing" class="dg-badge dg-badge--red">{{ gapSummary.missing }}</span>
                    </button>
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showRunPanel }]"
                      @click="togglePanel('run')"
                    >运行协作图</button>
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showAllHandsPanel }]"
                      :disabled="allHandsBusy"
                      @click="togglePanel('allhands')"
                    >{{ allHandsBusy ? '员工大会进行中…' : '员工大会汇报' }}</button>
                    <button
                      v-if="stats.llmNoKey && !llmStatusFailed"
                      :class="['dg-more-item', { 'dg-more-item--active': showNoKeyPanel }]"
                      @click="togglePanel('nokey')"
                    >✗ 无密钥修复 ({{ stats.llmNoKey }})</button>
                  </div>
                </transition>
              </div>

              <button
                :class="['dg-btn', autoRefresh ? 'dg-btn--refresh-on' : 'dg-btn--ghost']"
                :title="autoRefresh ? `自动刷新已开启，${countdown}s 后刷新` : '开启自动刷新（30 s）'"
                @click="autoRefresh = !autoRefresh"
              >
                {{ autoRefresh ? `⟳ ${countdown}s` : '⟳' }}
              </button>

              <button class="dg-btn dg-btn--ghost" :disabled="loading" @click="load">
                {{ loading ? '…' : '↻' }}
              </button>
              <button
                v-if="isPage"
                type="button"
                class="dg-close dg-close--text"
                aria-label="返回数据库管理"
                @click="router.push({ name: 'admin-database' })"
              >
                ← 返回
              </button>
              <button v-else class="dg-close" aria-label="关闭" @click="emit('close')">✕</button>
            </div>
            <div v-if="$slots.pageActions" class="dg-header-actions">
              <slot name="pageActions" />
            </div>
          </div>
</template>

<style scoped src="../AdminDutyEmployeeGraph.css"></style>

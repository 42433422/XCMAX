/**
 * LLM 无密钥员工修复面板。
 *
 * 由 DutyRosterGraphPanel.vue 模板机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './dutyRosterTypes'
import type { DutyNoKey } from './useDutyNoKey'
import type { DutyRosterState } from './useDutyRosterState'

const emit = defineEmits<{
  (e: 'update:showNoKeyPanel', v: Deref<DutyRosterState['showNoKeyPanel']>): void
}>()

const props = defineProps<{
  showNoKeyPanel: Deref<DutyRosterState['showNoKeyPanel']>
  noKeyLoading: Deref<DutyRosterState['noKeyLoading']>
  noKeyError: Deref<DutyRosterState['noKeyError']>
  noKeyData: Deref<DutyRosterState['noKeyData']>
  noKeyBusyRow: Deref<DutyRosterState['noKeyBusyRow']>
  loadNoKeyEmployees: Deref<DutyNoKey['loadNoKeyEmployees']>
  alignSingleEmployeeToAuto: Deref<DutyNoKey['alignSingleEmployeeToAuto']>
  gotoAddKey: Deref<DutyNoKey['gotoAddKey']>
}>()

const showNoKeyPanel = computed({
  get: () => props.showNoKeyPanel,
  set: (v) => emit('update:showNoKeyPanel', v),
})

</script>

<template>
            <transition name="dg-slide-top">
              <div v-if="showNoKeyPanel" class="dg-nokey-panel">
                <div class="dg-nokey-header">
                  <span class="dg-nokey-title">✗ 无密钥员工修复</span>
                  <span v-if="noKeyData" class="dg-nokey-meta">
                    fernet={{ noKeyData.fernet_configured ? '已配置' : '未配置' }} ·
                    账户可用密钥={{ noKeyData.any_provider_has_key ? '有' : '无' }}
                  </span>
                  <button class="dg-btn dg-btn--ghost dg-btn--sm" :disabled="noKeyLoading" @click="loadNoKeyEmployees">
                    {{ noKeyLoading ? '加载中…' : '刷新' }}
                  </button>
                  <button class="dg-btn dg-btn--ghost dg-btn--sm" @click="showNoKeyPanel = false">关闭</button>
                </div>
                <p v-if="noKeyError" class="dg-nokey-error">{{ noKeyError }}</p>
                <p v-else-if="noKeyLoading" class="dg-nokey-empty">加载中…</p>
                <p v-else-if="noKeyData && noKeyData.count === 0" class="dg-nokey-empty">
                  当前账户视角下没有无密钥员工。
                </p>
                <div v-else-if="noKeyData" class="dg-nokey-list">
                  <div v-for="row in noKeyData.items" :key="row.pkg_id" class="dg-nokey-row">
                    <div class="dg-nokey-row__main">
                      <span class="dg-nokey-row__name">{{ row.name }}</span>
                      <span class="dg-nokey-row__pkg">{{ row.pkg_id }}</span>
                      <span class="dg-nokey-row__provider">
                        当前 provider=<code>{{ row.current_provider }}</code> ·
                        model=<code>{{ row.current_model || '(empty)' }}</code>
                      </span>
                    </div>
                    <div class="dg-nokey-row__actions">
                      <button
                        v-if="row.suggested_action === 'align_to_auto'"
                        type="button"
                        class="dg-btn dg-btn--primary dg-btn--sm"
                        :disabled="!!noKeyBusyRow[row.pkg_id]"
                        title="把该员工 manifest 改为 provider=model_name=auto，跟随账户里任一可用密钥"
                        @click="alignSingleEmployeeToAuto(row)"
                      >
                        {{ noKeyBusyRow[row.pkg_id] ? '处理中…' : '改为自动' }}
                      </button>
                      <button
                        v-else
                        type="button"
                        class="dg-btn dg-btn--outline dg-btn--sm"
                        title="员工已是 auto 但账户里没有任一可用密钥；请去 LLM 凭据页添加"
                        @click="gotoAddKey"
                      >
                        去添加密钥
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </transition>

            <!-- ── Gap panel (Phase 3-b) ─────────────────────────────────── -->
</template>

<style scoped src="../DutyRosterGraphPanel.css"></style>

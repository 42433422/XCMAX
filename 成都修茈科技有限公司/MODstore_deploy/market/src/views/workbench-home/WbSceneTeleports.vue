<script setup lang="ts">
import ConsumptionTierControl from '../../components/workbench/ConsumptionTierControl.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 168–216 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  wbSidebar, wbNav, directLoading, directChatEmployeeId, directEmployeeOptions, consumptionTier,
  tierPanelOpen, empPanelOpen, empDropdownOpen, tierPanelAnchorStyle, empPanelAnchorStyle,
} = props.wb
</script>

<template>
          <Teleport to="body">
            <div
              v-if="tierPanelOpen && wbSidebar.activeMode === 'direct'"
              class="wb-scene-panel wb-scene-panel--popover"
              :class="{ 'wb-scene-panel--tier-mobile': wbNav.isMobile }"
              :style="tierPanelAnchorStyle"
              :key="'tier-direct'"
              role="dialog"
              aria-label="消费档位"
            >
              <p v-if="!wbNav.isMobile" class="wb-scene-panel-hint">消费档位影响回复质量与资源消耗：1 更省，10 更强。</p>
              <ConsumptionTierControl v-model="consumptionTier" @change="tierPanelOpen = false" />
            </div>
          </Teleport>
          <Teleport to="body" :disabled="wbNav.isMobile">
            <div
              v-if="empPanelOpen && wbSidebar.activeMode === 'direct'"
              class="wb-scene-panel"
              :class="{ 'wb-scene-panel--popover': !wbNav.isMobile }"
              :style="empPanelAnchorStyle"
              :key="'emp-direct'"
              role="dialog"
              aria-label="选择员工"
            >
            <p v-if="!wbNav.isMobile" class="wb-scene-panel-hint">绑定员工后，回答会优先使用该员工的技能与知识库。</p>
            <label class="wb-scene-panel-label" for="wb-direct-employee-select">选择员工</label>
            <div class="wb-emp-select" :class="{ 'wb-emp-select--open': empDropdownOpen, 'wb-emp-select--disabled': directLoading }">
              <button type="button" class="wb-emp-select__trigger" :disabled="directLoading" aria-haspopup="listbox" :aria-expanded="empDropdownOpen" @click="empDropdownOpen = !empDropdownOpen">
                <span class="wb-emp-select__value">{{ directChatEmployeeId ? directEmployeeOptions.find(o => o.id === directChatEmployeeId)?.name || directChatEmployeeId : '不绑定（通用检索）' }}</span>
                <svg class="wb-emp-select__chevron" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3.5 5.25L7 8.75L10.5 5.25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
              <Transition name="wb-emp-dropdown">
                <div v-if="empDropdownOpen" class="wb-emp-select__dropdown">
                  <button type="button" class="wb-emp-select__option" :class="{ 'wb-emp-select__option--active': !directChatEmployeeId }" role="option" :aria-selected="!directChatEmployeeId" @click="directChatEmployeeId = ''; empDropdownOpen = false">
                    <span class="wb-emp-select__option-icon">🌐</span>
                    <span class="wb-emp-select__option-text">不绑定（通用检索）</span>
                  </button>
                  <button v-for="opt in directEmployeeOptions" :key="opt.id" type="button" class="wb-emp-select__option" :class="{ 'wb-emp-select__option--active': directChatEmployeeId === opt.id }" role="option" :aria-selected="directChatEmployeeId === opt.id" @click="directChatEmployeeId = opt.id; empDropdownOpen = false">
                    <span class="wb-emp-select__option-icon"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="3" y="4" width="10" height="7" rx="1.5"/><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5"/></svg></span>
                    <span class="wb-emp-select__option-content">
                      <span class="wb-emp-select__option-name">{{ opt.name }}</span>
                      <span class="wb-emp-select__option-meta">{{ opt.id }} · {{ opt.sourceLabel }}</span>
                    </span>
                  </button>
                </div>
              </Transition>
            </div>
            </div>
          </Teleport>
</template>

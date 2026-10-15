<template>
  <div class="top-quick-nav">
    <i class="fa fa-search top-quick-nav__icon" aria-hidden="true"></i>
    <input
      ref="inputRef"
      v-model="query"
      class="top-quick-nav__input"
      type="text"
      role="combobox"
      :aria-expanded="open ? 'true' : 'false'"
      aria-controls="top-quick-nav-list"
      aria-label="输入功能名快速跳转"
      placeholder="输入功能名快速跳转"
      autocomplete="off"
      @focus="onFocus"
      @keydown="onKeydown"
      @blur="onBlur"
    />
    <ul v-if="open" id="top-quick-nav-list" class="top-quick-nav__list" role="listbox" aria-label="功能列表">
      <li v-if="!filtered.length" class="top-quick-nav__empty">没有匹配的功能</li>
      <li
        v-for="(item, idx) in filtered"
        :key="`${item.source}-${item.key}`"
        class="top-quick-nav__option"
        :class="{ highlighted: idx === highlightIndex }"
        role="option"
        :aria-selected="idx === highlightIndex ? 'true' : 'false'"
        @mouseenter="highlightIndex = idx"
        @mousedown.prevent="choose(item)"
      >
        <i v-if="item.iconClass" class="fa top-quick-nav__option-icon" :class="item.iconClass" aria-hidden="true"></i>
        <span class="top-quick-nav__option-name">{{ item.name }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
/**
 * 顶部中间快捷跳转框：输入功能名即搜全部侧边栏入口（与 Sidebar 同源 useVisibleNavItems），
 * 回车/点击后经 MainLayout 的 navigateToView 跳转（与侧栏点击完全同路径）。
 */
import { computed, ref } from 'vue'
import { useVisibleNavItems } from '@/composables/useVisibleNavItems'

const emit = defineEmits(['select'])

const { visibleNavItems } = useVisibleNavItems()

const query = ref('')
const open = ref(false)
const highlightIndex = ref(0)
const inputRef = ref(null)

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const items = visibleNavItems.value || []
  if (!keyword) return items
  return items.filter((item) => String(item.name || '').toLowerCase().includes(keyword))
})

function onFocus() {
  open.value = true
  highlightIndex.value = 0
}

function onBlur() {
  // 延迟关闭：让选项的 mousedown（已 preventDefault 不夺焦）先完成选择
  window.setTimeout(() => {
    open.value = false
  }, 120)
}

function choose(item) {
  if (!item?.key) return
  emit('select', item.key)
  query.value = ''
  open.value = false
  inputRef.value?.blur?.()
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    open.value = false
    inputRef.value?.blur?.()
    return
  }
  if (!open.value) {
    open.value = true
    return
  }
  const total = filtered.value.length
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (total) highlightIndex.value = (highlightIndex.value + 1) % total
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (total) highlightIndex.value = (highlightIndex.value - 1 + total) % total
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const item = filtered.value[highlightIndex.value]
    if (item) choose(item)
  }
}
</script>

<style scoped>
.top-quick-nav {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(420px, 36vw);
  z-index: 40;
}

.top-quick-nav__icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: rgba(100, 116, 139, 0.8);
  pointer-events: none;
}

.top-quick-nav__input {
  width: 100%;
  height: 32px;
  box-sizing: border-box;
  padding: 0 12px 0 30px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #334155;
  font-size: 13px;
  outline: none;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.top-quick-nav__input::placeholder {
  color: rgba(100, 116, 139, 0.65);
}

.top-quick-nav__input:focus {
  border-color: rgba(11, 114, 217, 0.45);
  box-shadow: 0 0 0 3px rgba(24, 144, 255, 0.14);
  background: #fff;
}

.top-quick-nav__list {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  margin: 0;
  padding: 6px;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 12px;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.14);
}

.top-quick-nav__option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
}

.top-quick-nav__option.highlighted {
  background: rgba(239, 246, 255, 0.96);
  color: #0b72d9;
}

.top-quick-nav__option-icon {
  width: 16px;
  text-align: center;
  font-size: 13px;
  color: rgba(71, 85, 105, 0.85);
}

.top-quick-nav__option.highlighted .top-quick-nav__option-icon {
  color: #0b72d9;
}

.top-quick-nav__empty {
  padding: 10px;
  font-size: 12px;
  color: rgba(100, 116, 139, 0.8);
  text-align: center;
}

@media (max-width: 1023px) {
  .top-quick-nav {
    display: none;
  }
}
</style>

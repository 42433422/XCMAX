<script setup lang="ts">
import { ref } from 'vue'
import { listByCategory, type NodeKind } from '../composables/useNodeRegistry'

defineEmits<{
  (e: 'add', kind: NodeKind): void
}>()

const groups = listByCategory()
const collapsed = ref<Record<string, boolean>>({})

function toggle(cat: string) {
  collapsed.value[cat] = !collapsed.value[cat]
}

function onDragStart(ev: DragEvent, kind: NodeKind) {
  if (!ev.dataTransfer) return
  ev.dataTransfer.setData('application/wf2-node-kind', kind)
  ev.dataTransfer.effectAllowed = 'move'
}
</script>

<template>
  <aside class="wf2-library">
    <h3 class="wf2-library__title">节点库</h3>
    <p class="wf2-library__hint">点击或拖入画布</p>
    <div v-for="g in groups" :key="g.category" class="wf2-library__group">
      <button class="wf2-library__group-head" type="button" @click="toggle(g.category)">
        <div class="wf2-library__group-label">
          <span class="wf2-library__group-bar" :style="{ background: g.items[0]?.accent || '#6366f1' }" />
          <span>{{ g.label }}</span>
        </div>
        <span class="wf2-library__group-count">{{ g.items.length }}</span>
      </button>
      <transition name="wf2-lib-collapse">
        <ul v-show="!collapsed[g.category]" class="wf2-library__list">
          <li
            v-for="m in g.items"
            :key="m.kind"
            class="wf2-library__item"
            :draggable="true"
            @dragstart="onDragStart($event, m.kind)"
            @click="$emit('add', m.kind)"
          >
            <span class="wf2-library__item-icon" :style="{ background: m.accent }">{{ m.icon }}</span>
            <div class="wf2-library__item-text">
              <span class="wf2-library__item-label">{{ m.label }}</span>
              <span class="wf2-library__item-desc">{{ m.description }}</span>
            </div>
          </li>
        </ul>
      </transition>
    </div>
  </aside>
</template>

<style scoped>
.wf2-library {
  width: 264px;
  flex-shrink: 0;
  background: rgba(15, 23, 42, 0.82);
  backdrop-filter: blur(16px);
  border-right: 1px solid rgba(148, 163, 184, 0.08);
  padding: 20px 14px;
  overflow-y: auto;
  height: 100%;
}

.wf2-library__title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
}

.wf2-library__hint {
  margin: 0 0 16px;
  font-size: 12px;
  color: #64748b;
}

.wf2-library__group {
  margin-bottom: 6px;
}

.wf2-library__group-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.wf2-library__group-head:hover {
  background: rgba(148, 163, 184, 0.08);
  color: #e2e8f0;
}

.wf2-library__group-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wf2-library__group-bar {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}

.wf2-library__group-count {
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  background: rgba(148, 163, 184, 0.1);
  padding: 2px 8px;
  border-radius: 999px;
}

.wf2-library__list {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
}

.wf2-library__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 10px;
  border-radius: 10px;
  cursor: grab;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.wf2-library__item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 0;
  border-radius: 0 2px 2px 0;
  background: var(--item-accent, #6366f1);
  transition: height 0.25s ease;
}

.wf2-library__item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.wf2-library__item:hover::before {
  height: 60%;
}

.wf2-library__item:active {
  cursor: grabbing;
}

.wf2-library__item-icon {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 15px;
  flex-shrink: 0;
  box-shadow: 0 0 12px color-mix(in srgb, var(--item-accent, #6366f1) 30%, transparent);
}

.wf2-library__item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.wf2-library__item-label {
  font-size: 13px;
  color: #e2e8f0;
  font-weight: 600;
}

.wf2-library__item-desc {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 折叠动画 */
.wf2-lib-collapse-enter-active,
.wf2-lib-collapse-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.wf2-lib-collapse-enter-from,
.wf2-lib-collapse-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
}

.wf2-lib-collapse-enter-to,
.wf2-lib-collapse-leave-from {
  opacity: 1;
  max-height: 400px;
}
</style>

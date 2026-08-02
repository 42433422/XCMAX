<template>
  <section class="list-view" aria-label="知识卡片">
    <div class="list-view__head">
      <div>
        <span class="section-kicker">Knowledge Nodes</span>
        <h3>知识与主题</h3>
      </div>
      <label class="filter-field">
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model.trim="filterModel" type="search" placeholder="筛选节点" />
      </label>
    </div>
    <div v-if="nodes.length" class="node-card-grid">
      <button
        v-for="node in nodes"
        :key="node.id"
        type="button"
        class="node-card"
        :class="[`node-card--${node.type}`, { active: selectedNodeId === node.id }]"
        @click="emit('select', node)"
      >
        <span class="node-card__icon">
          <i :class="`fa ${nodeIcon(node.type)}`" aria-hidden="true"></i>
        </span>
        <span class="node-card__body">
          <span class="node-card__type">{{ nodeTypeLabel(node.type) }}</span>
          <strong>{{ node.label }}</strong>
          <span>{{ node.summary || '等待更多上下文' }}</span>
        </span>
        <i class="fa fa-angle-right node-card__arrow" aria-hidden="true"></i>
      </button>
    </div>
    <div v-else class="view-empty">
      <i class="fa fa-sitemap" aria-hidden="true"></i>
      <strong>还没有知识节点</strong>
      <button type="button" @click="emit('import')">导入第一份资料</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { KnowledgeGraphNode } from '@/api/knowledgeBase'
import { nodeIcon, nodeTypeLabel } from '@/composables/persyKnowledgeFormatters'

const props = defineProps<{
  nodes: KnowledgeGraphNode[]
  selectedNodeId: string
  filter: string
}>()

const emit = defineEmits<{
  'update:filter': [value: string]
  select: [node: KnowledgeGraphNode]
  import: []
}>()

const filterModel = computed({
  get: () => props.filter,
  set: (value: string) => emit('update:filter', value),
})
</script>

<style scoped>
.section-kicker {
  color: #738179;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.list-view {
  height: 100%;
  overflow: auto;
  padding: 24px 24px 96px;
  background: #f7f9f8;
}

.list-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.list-view__head h3 {
  margin: 2px 0 0;
  color: #17211d;
  font-size: 17px;
  line-height: 1.25;
}

.filter-field {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  width: min(260px, 44vw);
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid #d4ded9;
  border-radius: 7px;
  background: #ffffff;
  color: #7a8880;
}

.filter-field input {
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  font: inherit;
  font-size: 12px;
}

.node-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 50%;
}

.view-empty button {
  border: 0;
  background: transparent;
  color: #1d6259;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.view-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  text-align: center;
}

.view-empty > i {
  color: #9aaba2;
  font-size: 28px;
}

.view-empty strong {
  color: #27352f;
  font-size: 14px;
}

.view-empty span {
  font-size: 11px;
}

.node-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 10px;
}

.node-card {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 108px;
  padding: 14px;
  border: 1px solid #dce4e0;
  border-radius: 8px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
  text-align: left;
}

.node-card:hover,
.node-card.active {
  border-color: #7fa997;
  box-shadow: 0 8px 20px rgba(35, 52, 44, 0.08);
}

.node-card__icon {
  width: 34px;
  height: 34px;
  color: #ffffff;
  background: #268578;
}

.node-card--source .node-card__icon {
  background: #c56f3d;
}

.node-card--topic .node-card__icon {
  background: #2f6f8f;
}

.node-card__body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.node-card__type {
  color: #7a8880;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
}

.node-card__body strong,
.node-card__body > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-card__body strong {
  font-size: 13px;
}

.node-card__body > span:last-child {
  color: #6e7c75;
  font-size: 11px;
}

.node-card__arrow {
  color: #a0aea7;
}

@media (max-width: 767px) {
  .list-view {
    padding: 60px 12px 82px;
  }

  .list-view__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-field {
    width: 100%;
  }

  .node-card-grid {
    grid-template-columns: 1fr;
  }

  .node-card {
    min-height: 92px;
  }
}
</style>

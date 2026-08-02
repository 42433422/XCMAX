<template>
  <section class="list-view" aria-label="资料来源">
    <div class="list-view__head">
      <div>
        <span class="section-kicker">Sources</span>
        <h3>资料来源</h3>
      </div>
      <span class="source-total">{{ documents.length }} 个来源</span>
    </div>
    <div v-if="documents.length" class="source-list">
      <div
        v-for="doc in documents"
        :key="doc.document_id || `${doc.source}-${doc.version_label}`"
        class="source-row"
      >
        <button type="button" class="source-row__select" @click="emit('select', doc)">
          <span class="source-row__icon">
            <i class="fa fa-file-text-o" aria-hidden="true"></i>
          </span>
          <span class="source-row__main">
            <strong>{{ doc.source || '未命名资料' }}</strong>
            <span>{{ parserLabel(doc.parser) }} · {{ numberText(doc.text_length) }} 字符</span>
          </span>
          <span class="source-row__metric">
            <strong>{{ numberText(doc.chunk_count) }}</strong>
            <span>节点</span>
          </span>
          <span class="source-row__version">{{ doc.version_label || versionLabel(doc.version) }}</span>
          <i class="fa fa-angle-right" aria-hidden="true"></i>
        </button>
        <button
          v-if="doc.document_id"
          type="button"
          class="source-row__delete"
          :disabled="deletingDocumentId === doc.document_id"
          title="删除资料"
          aria-label="删除资料"
          @click="emit('delete', doc)"
        >
          <i
            :class="deletingDocumentId === doc.document_id ? 'fa fa-circle-o-notch fa-spin' : 'fa fa-trash-o'"
            aria-hidden="true"
          ></i>
        </button>
      </div>
    </div>
    <div v-else class="view-empty">
      <i class="fa fa-file-text-o" aria-hidden="true"></i>
      <strong>还没有资料来源</strong>
      <button type="button" @click="emit('import')">导入第一份资料</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { KnowledgeBaseDocument } from '@/api/knowledgeBase'
import {
  numberText,
  parserLabel,
  versionLabel,
} from '@/composables/persyKnowledgeFormatters'

defineProps<{
  documents: KnowledgeBaseDocument[]
  deletingDocumentId: string
}>()

const emit = defineEmits<{
  select: [doc: KnowledgeBaseDocument]
  delete: [doc: KnowledgeBaseDocument]
  import: []
}>()
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

.source-row__icon {
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

.source-total {
  color: #718078;
  font-size: 11px;
  font-weight: 700;
}

.source-row__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.source-row > .fa-angle-right {
  color: #a0aea7;
}

.source-row__delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid #d2dcd7;
  border-radius: 6px;
  color: #68766f;
  background: #ffffff;
  cursor: pointer;
}

.source-row__delete:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.source-list {
  border-top: 1px solid #dce4e0;
}

.source-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 38px;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  border-bottom: 1px solid #dce4e0;
}

.source-row__select {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 68px 58px 16px;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
  padding: 13px 8px;
  border: 0;
  background: transparent;
  color: #27352f;
  cursor: pointer;
  text-align: left;
}

.source-row:hover,
.source-row__select:hover {
  background: #eef3f0;
}

.source-row__delete {
  color: #943a34;
}

.source-row__icon {
  width: 34px;
  height: 34px;
  color: #8b4a27;
  background: #f6e6dc;
}

.source-row__main {
  gap: 3px;
}

.source-row__main strong,
.source-row__main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-row__main strong {
  font-size: 13px;
}

.source-row__main span,
.source-row__metric span,
.source-row__version {
  color: #748179;
  font-size: 10px;
}

.source-row__metric {
  text-align: right;
}

.source-row__metric strong,
.source-row__metric span {
  display: block;
}

.source-row__version {
  text-align: center;
}

@media (max-width: 767px) {
  .list-view {
    padding: 60px 12px 82px;
  }

  .list-view__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .source-row {
    grid-template-columns: minmax(0, 1fr) 34px;
    gap: 4px;
  }

  .source-row__select {
    grid-template-columns: 34px minmax(0, 1fr) 48px 14px;
    gap: 8px;
  }

  .source-row__version {
    display: none;
  }

  .source-row__metric {
    min-width: 0;
  }
}
</style>

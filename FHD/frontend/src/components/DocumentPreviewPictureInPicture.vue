<template>
  <aside
    v-if="documentPreviewPip.visible"
    class="document-pip"
    :class="{ 'document-pip--minimized': documentPreviewPip.minimized }"
    aria-label="文档悬浮预览"
  >
    <button v-if="documentPreviewPip.minimized" class="document-pip__chip" type="button" @click="expandDocumentPreview">
      <span class="document-pip__file-icon">{{ fileBadge }}</span>
      <span>{{ documentPreviewPip.fileName }}</span>
    </button>

    <template v-else>
      <header class="document-pip__header">
        <div>
          <span class="document-pip__kicker">文档预览</span>
          <strong>{{ documentPreviewPip.fileName }}</strong>
        </div>
        <div class="document-pip__window-actions">
          <button type="button" title="最小化" aria-label="最小化" @click="minimizeDocumentPreview">−</button>
          <button type="button" title="关闭" aria-label="关闭" @click="closeDocumentPreview">×</button>
        </div>
      </header>

      <div class="document-pip__canvas">
        <iframe v-if="documentPreviewPip.kind === 'pdf'" :src="documentPreviewPip.url" title="PDF 文档预览"></iframe>
        <img v-else-if="documentPreviewPip.kind === 'image'" :src="documentPreviewPip.url" :alt="documentPreviewPip.fileName" />
        <div v-else-if="documentPreviewPip.kind === 'excel' && documentPreviewPip.previewRows.length" class="document-pip__sheet">
          <table>
            <tbody>
              <tr v-for="(row, rowIndex) in documentPreviewPip.previewRows" :key="rowIndex">
                <th>{{ rowIndex + 1 }}</th>
                <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="document-pip__paper">
          <div class="document-pip__paper-mark">{{ fileBadge }}</div>
          <h3>{{ documentPreviewPip.title }}</h3>
          <p v-if="documentPreviewPip.summary">{{ documentPreviewPip.summary }}</p>
          <p v-else>文档已生成。Office 文件请点击下方“打开文档”查看完整排版。</p>
          <div class="document-pip__lines" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
        </div>
      </div>

      <footer class="document-pip__footer">
        <span>{{ formatLabel }}</span>
        <a :href="documentPreviewPip.url" target="_blank" rel="noopener noreferrer"> 打开文档 </a>
        <a :href="documentPreviewPip.url" :download="documentPreviewPip.fileName"> 下载 </a>
      </footer>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { closeDocumentPreview, documentPreviewPip, expandDocumentPreview, minimizeDocumentPreview } from '@/state/documentPreviewPip'

const fileBadge = computed(() => {
  if (documentPreviewPip.kind === 'word') return 'W'
  if (documentPreviewPip.kind === 'excel') return 'X'
  if (documentPreviewPip.kind === 'pdf') return 'PDF'
  if (documentPreviewPip.kind === 'image') return 'IMG'
  return 'DOC'
})

const formatLabel = computed(() => {
  const labels = {
    word: 'Word 文档',
    excel: 'Excel 表格',
    pdf: 'PDF 文档',
    image: '图片文档',
    office: 'Office 文档',
  }
  return labels[documentPreviewPip.kind]
})
</script>

<style scoped>
.document-pip {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1760;
  display: flex;
  flex-direction: column;
  width: min(430px, calc(100vw - 32px));
  height: min(560px, calc(100vh - 100px));
  min-width: 320px;
  min-height: 360px;
  overflow: hidden;
  resize: both;
  border: 1px solid rgba(148, 163, 184, 0.52);
  border-radius: 18px;
  color: #172033;
  background: rgba(248, 250, 252, 0.98);
  box-shadow:
    0 26px 64px rgba(15, 23, 42, 0.26),
    0 4px 14px rgba(15, 23, 42, 0.12);
  animation: document-pip-enter 220ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.document-pip--minimized {
  width: min(310px, calc(100vw - 32px));
  height: auto;
  min-width: 0;
  min-height: 0;
  resize: none;
  border-radius: 13px;
}

.document-pip__chip {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 12px;
  border: 0;
  color: #334155;
  background: #fff;
  cursor: pointer;
}

.document-pip__chip span:last-child {
  overflow: hidden;
  font-size: 13px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-pip__file-icon,
.document-pip__paper-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(145deg, #0f7890, #0f766e);
  font-size: 10px;
  font-weight: 900;
}

.document-pip__file-icon {
  width: 30px;
  height: 30px;
}

.document-pip__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px;
  border-bottom: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.96);
}

.document-pip__header > div:first-child {
  min-width: 0;
}

.document-pip__header strong {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-pip__kicker {
  display: block;
  color: #0f7890;
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0.12em;
}

.document-pip__window-actions {
  display: flex;
  gap: 4px;
}

.document-pip__window-actions button {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 8px;
  color: #64748b;
  background: transparent;
  font-size: 18px;
  cursor: pointer;
}

.document-pip__window-actions button:hover {
  color: #0f172a;
  background: #f1f5f9;
}

.document-pip__canvas {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 18px;
  background:
    linear-gradient(45deg, rgba(148, 163, 184, 0.08) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(148, 163, 184, 0.08) 25%, transparent 25%), #e8edf2;
  background-size: 18px 18px;
}

.document-pip__canvas iframe,
.document-pip__canvas img {
  width: 100%;
  height: 100%;
  min-height: 360px;
  border: 0;
  border-radius: 5px;
  object-fit: contain;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.13);
}

.document-pip__paper {
  box-sizing: border-box;
  min-height: 100%;
  padding: 30px 28px;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 4px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.13);
}

.document-pip__sheet {
  min-width: max-content;
  min-height: 100%;
  border: 1px solid #cbd5e1;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.13);
}

.document-pip__sheet table {
  border-collapse: collapse;
  color: #334155;
  font-size: 11px;
}

.document-pip__sheet th,
.document-pip__sheet td {
  max-width: 180px;
  min-width: 84px;
  overflow: hidden;
  border: 1px solid #dbe3eb;
  padding: 7px 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-pip__sheet th {
  min-width: 34px;
  color: #64748b;
  background: #f1f5f9;
  text-align: center;
}

.document-pip__sheet tr:first-child td {
  color: #0f4c5c;
  background: #ecfeff;
  font-weight: 800;
}

.document-pip__paper-mark {
  width: 38px;
  height: 38px;
}

.document-pip__paper h3 {
  margin: 20px 0 10px;
  color: #0f172a;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 20px;
}

.document-pip__paper p {
  color: #475569;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.document-pip__lines {
  display: grid;
  gap: 12px;
  margin-top: 22px;
}

.document-pip__lines span {
  height: 7px;
  border-radius: 999px;
  background: #e8edf2;
}

.document-pip__lines span:nth-child(2) {
  width: 86%;
}
.document-pip__lines span:nth-child(3) {
  width: 94%;
}
.document-pip__lines span:nth-child(4) {
  width: 72%;
}
.document-pip__lines span:nth-child(5) {
  width: 90%;
}

.document-pip__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 11px 14px;
  border-top: 1px solid #e2e8f0;
  background: #fff;
}

.document-pip__footer span {
  margin-right: auto;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.document-pip__footer a {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 7px 10px;
  color: #334155;
  background: #fff;
  font-size: 12px;
  font-weight: 750;
  text-decoration: none;
}

.document-pip__footer a:last-child {
  border-color: #0f7890;
  color: #fff;
  background: #0f7890;
}

@keyframes document-pip-enter {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (max-width: 640px) {
  .document-pip {
    right: 16px;
    bottom: calc(76px + env(safe-area-inset-bottom, 0));
    min-width: 280px;
    height: min(500px, calc(100vh - 120px));
  }
}

@media (prefers-reduced-motion: reduce) {
  .document-pip {
    animation: none;
  }
}
</style>

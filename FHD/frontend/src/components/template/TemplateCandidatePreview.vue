<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type CSSProperties } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

type Cell = { cell: string; value: string; formula: boolean; rowspan: number; colspan: number; bold: boolean; italic: boolean; font_size: number; font_color: string; fill: string; align: string }
type Layout = { sheet: string; widths: number[]; rows: { height: number; cells: Cell[] }[]; truncated: boolean }
const props = defineProps<{
  title: string; explanation: string; layouts: Layout[]; initialSheet: number
  selected: boolean; canSelect: boolean; cellStyle: (cell: Cell) => CSSProperties
}>()
const emit = defineEmits<{ close: []; select: [] }>()
const panel = ref<HTMLElement | null>(null)
const sheetIndex = ref(props.layouts[props.initialSheet] ? props.initialSheet : 0)
const layout = computed(() => props.layouts[sheetIndex.value])
useDialogFocus(panel, () => true, () => emit('close'))
const overflow = ['overflow', 'overflow-x', 'overflow-y'].map(property => ({ property, value: document.body.style.getPropertyValue(property), priority: document.body.style.getPropertyPriority(property) }))
onMounted(() => document.body.style.setProperty('overflow', 'hidden'))
onBeforeUnmount(() => {
  overflow.forEach(({ property }) => document.body.style.removeProperty(property))
  overflow.forEach(({ property, value, priority }) => { if (value) document.body.style.setProperty(property, value, priority) })
})
</script>

<template>
  <Teleport to="body">
    <div class="template-preview-overlay" @click.self="emit('close')" @wheel.self.prevent @touchmove.self.prevent>
      <section ref="panel" class="template-preview-dialog" role="dialog" aria-modal="true" :aria-label="`${title}，放大预览`" tabindex="-1">
        <header>
          <h3>{{ title }}</h3>
          <button type="button" data-dialog-initial-focus aria-label="关闭放大预览" @click="emit('close')">关闭</button>
        </header>
        <div class="template-preview-toolbar">
          <label v-if="layouts.length">工作表 <select v-model.number="sheetIndex"><option v-for="(sheet, index) in layouts" :key="sheet.sheet" :value="index">{{ sheet.sheet }}{{ sheet.truncated ? '（预览截断）' : '' }}</option></select></label>
          <p>{{ explanation }}</p>
          <small>候选工作簿的近似布局；公式显示表达式，未计算结果。超出预览范围请下载核对。</small>
        </div>
        <div class="template-preview-viewport" tabindex="0" aria-label="工作表预览，可滚动">
          <div v-if="layout" class="template-preview-paper">
            <table><colgroup><col v-for="(width, col) in layout.widths" :key="col" :style="{ width: `${width * 7}px` }"></colgroup><tbody>
              <tr v-for="(row, rowIndex) in layout.rows" :key="rowIndex" :style="{ height: `${row.height * 1.333}px` }">
                <td v-for="cell in row.cells" :key="cell.cell" :rowspan="cell.rowspan" :colspan="cell.colspan" :style="cellStyle(cell)">{{ cell.value }}</td>
              </tr>
            </tbody></table>
          </div>
          <p v-else>此版本无成品布局预览，请重新生成后核对。</p>
        </div>
        <footer>
          <span v-if="selected">当前已选模板</span>
          <button type="button" :disabled="!canSelect || selected" @click="emit('select')">选择此模板</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.template-preview-overlay { position: fixed; inset: 0; z-index: 10050; display: grid; place-items: center; padding: var(--xc-space-4); background: color-mix(in srgb, var(--xc-color-text) 45%, transparent); }
.template-preview-dialog { display: flex; flex-direction: column; width: min(72rem, 100%); max-height: 92dvh; min-width: 0; border: 1px solid var(--xc-color-border); border-radius: var(--xc-radius-lg); background: var(--xc-color-surface); color: var(--xc-color-text); box-shadow: var(--xc-shadow-lg); overflow: hidden; }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: var(--xc-space-3); padding: var(--xc-space-3) var(--xc-space-4); flex-shrink: 0; }
header { border-bottom: 1px solid var(--xc-color-border); }
header h3 { margin: 0; font-size: var(--xc-font-lg); overflow-wrap: anywhere; }
header button { flex-shrink: 0; }
footer { border-top: 1px solid var(--xc-color-border); }
.template-preview-toolbar { padding: var(--xc-space-3) var(--xc-space-4); color: var(--xc-color-text-secondary); flex-shrink: 0; max-height: 25dvh; overflow: auto; }
.template-preview-toolbar p { margin: var(--xc-space-2) 0; overflow-wrap: anywhere; }
.template-preview-toolbar small { color: var(--xc-color-muted); }
.template-preview-viewport { min-height: 8rem; overflow: auto; overscroll-behavior: contain; padding: var(--xc-space-4); background: var(--xc-color-surface-2); }
.template-preview-paper { width: max-content; min-width: min(100%, 44rem); min-height: 32rem; padding: var(--xc-space-6); background: white; color: black; box-shadow: var(--xc-shadow-sm); }
table { border-collapse: collapse; table-layout: fixed; }
td { border: 1px solid currentColor; min-width: 24px; white-space: pre-wrap; overflow-wrap: anywhere; }
button, select { font: inherit; color: var(--xc-color-text); border: 1px solid var(--xc-color-border-strong); border-radius: var(--xc-radius-md); background: var(--xc-color-surface); padding: var(--xc-space-2) var(--xc-space-3); }
button { cursor: pointer; }
button:hover:not(:disabled) { border-color: var(--xc-color-primary); color: var(--xc-color-primary); }
button:disabled { opacity: 0.55; cursor: not-allowed; }
button:focus-visible, select:focus-visible, .template-preview-viewport:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: 2px; }
@media (max-width: 600px) { .template-preview-overlay { padding: var(--xc-space-2); } .template-preview-dialog { max-height: 96dvh; } .template-preview-toolbar { max-height: 25dvh; overflow: auto; } .template-preview-paper { padding: var(--xc-space-3); } footer { flex-wrap: wrap; } }
</style>

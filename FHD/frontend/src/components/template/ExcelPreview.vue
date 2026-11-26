<template>
  <div class="excel-preview">
    <div class="fake-excel">
      <div class="excel-toolbar">
        <span class="excel-title">{{ title }}</span>
      </div>
      <div class="excel-container">
        <table v-if="hasGridData" class="real-grid-table">
          <tbody>
            <tr v-for="(row, rowIndex) in visibleGridRows" :key="'real-row-' + (gridPageStart + rowIndex)">
              <td class="real-row-num">{{ gridPageStart + rowIndex + 1 }}</td>
              <td
                v-for="cell in row"
                 :key="'real-cell-' + (gridPageStart + rowIndex) + '-' + cell.col"
                class="real-grid-cell"
                :class="{
                  'has-content': cell.text,
                  'is-merged': cell.rowspan > 1 || cell.colspan > 1,
                }"
                :rowspan="cell.rowspan"
                :colspan="cell.colspan"
              >
                <span class="cell-text">{{ cell.text }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="excel-headers" v-show="!hasGridData">
          <div class="row-num-header"></div>
          <div v-for="(col, index) in visibleColumnCount" :key="'header-' + (displayColumnStart + index)" class="col-header">
            {{ getColumnHeader(displayColumnStart + index) }}
          </div>
        </div>
        <div class="excel-body" v-show="!hasGridData">
          <div v-for="(row, rowIndex) in visibleRowCount" :key="'row-' + (displayRowStart + rowIndex)" class="excel-row">
            <div class="row-num">{{ displayRowStart + rowIndex + 1 }}</div>
            <div
              v-for="(col, colIndex) in visibleColumnCount"
               :key="'cell-' + (displayRowStart + rowIndex) + '-' + (displayColumnStart + colIndex)"
              class="excel-cell"
              :class="{ 'has-content': getCellContent(displayRowStart + rowIndex, displayColumnStart + colIndex) }"
            >
              <span v-if="getCellContent(displayRowStart + rowIndex, displayColumnStart + colIndex)" class="cell-text">
                {{ getCellContent(displayRowStart + rowIndex, displayColumnStart + colIndex) }}
              </span>
            </div>
          </div>
        </div>
      </div>
      <nav v-if="rowPageCount > 1" class="excel-pagination" aria-label="Excel 行分页">
        <button type="button" :disabled="rowPage === 0" @click="changeRowPage(-1)">上一页</button>
        <span aria-live="polite">{{ rowPage + 1 }} / {{ rowPageCount }} · {{ hasGridData ? gridRows.length : displayRows }} 行</span>
        <button type="button" :disabled="rowPage + 1 >= rowPageCount" @click="changeRowPage(1)">下一页</button>
      </nav>
      <nav v-if="!hasGridData && columnPageCount > 1" class="excel-pagination" aria-label="Excel 列分页">
        <button type="button" :disabled="columnPage === 0" @click="columnPage--">上一组列</button>
        <span aria-live="polite">{{ columnPage + 1 }} / {{ columnPageCount }} · {{ displayColumns }} 列</span>
        <button type="button" :disabled="columnPage + 1 >= columnPageCount" @click="columnPage++">下一组列</button>
      </nav>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ExcelPreview',
  props: {
    fields: {
      type: Array,
      default: () => [],
    },
    sampleRows: {
      type: Array,
      default: () => [],
    },
    rows: {
      type: Number,
      default: 6,
    },
    columns: {
      type: Number,
      default: 5,
    },
    title: {
      type: String,
      default: 'Excel 模板预览',
    },
    gridData: {
      type: Object,
      default: null,
    },
  },
  data() {
    return { gridPage: 0, displayPage: 0, columnPage: 0 }
  },
  watch: {
    gridData() { this.gridPage = 0 },
    sampleRows() { this.displayPage = 0 },
    fields() { this.columnPage = 0 },
  },
  computed: {
    hasGridData() {
      return Boolean(this.gridData && Array.isArray(this.gridData.rows) && this.gridData.rows.length > 0)
    },
    gridRows() {
      if (!this.hasGridData) return []
      return this.gridData.rows
    },
    // Page boundaries advance over the end of any merged cell. A grid
    // page cannot split a rowspan without changing the preview's meaning.
    gridPageBounds() {
      const rows = this.gridRows
      const bounds = [0]
      let start = 0
      while (start < rows.length) {
        let end = Math.min(rows.length, start + 100)
        for (let index = start; index < end; index++) {
          for (const cell of Array.isArray(rows[index]) ? rows[index] : []) {
            const span = Number(cell?.rowspan || 1)
            if (Number.isFinite(span) && span > 1) end = Math.min(rows.length, Math.max(end, index + span))
          }
        }
        bounds.push(end)
        start = end
      }
      return bounds
    },
    gridPageStart() {
      return this.gridPageBounds[Math.min(this.gridPage, this.gridPageBounds.length - 2)] || 0
    },
    visibleGridRows() {
      if (!this.hasGridData) return []
      const start = this.gridPageStart
      return this.gridRows.slice(start, this.gridPageBounds[this.gridPage + 1] || this.gridRows.length)
    },
    rowPage() { return this.hasGridData ? this.gridPage : this.displayPage },
    rowPageCount() {
      return this.hasGridData ? Math.max(1, this.gridPageBounds.length - 1)
        : Math.max(1, Math.ceil(this.displayRows / 100))
    },
    displayRowStart() { return this.displayPage * 100 },
    visibleRowCount() { return Math.max(0, Math.min(100, this.displayRows - this.displayRowStart)) },
    columnPageCount() { return Math.max(1, Math.ceil(this.displayColumns / 24)) },
    displayColumnStart() { return this.columnPage * 24 },
    visibleColumnCount() { return Math.max(0, Math.min(24, this.displayColumns - this.displayColumnStart)) },
    displayRows() {
      if (this.sampleRows && this.sampleRows.length > 0) {
        return Math.max(this.rows, this.sampleRows.length)
      }
      return this.rows
    },
    displayColumns() {
      if (this.fields && this.fields.length > 0) {
        return Math.max(this.columns, this.fields.length)
      }
      return this.columns
    },
    columnHeaders() {
      if (this.fields && this.fields.length > 0) {
        return this.fields.map((f) => f.label || f.name || '')
      }
      return []
    },
  },
  methods: {
    changeRowPage(direction) {
      const target = Math.max(0, Math.min(this.rowPageCount - 1, this.rowPage + direction))
      if (this.hasGridData) this.gridPage = target
      else this.displayPage = target
    },
    getColumnHeader(index) {
      if (this.columnHeaders && this.columnHeaders[index]) {
        return this.columnHeaders[index]
      }
      const letters = 'ABCDEFGHIJ'
      return letters[index] || ''
    },

    getCellContent(rowIndex, colIndex) {
      if (this.sampleRows && this.sampleRows[rowIndex]) {
        const row = this.sampleRows[rowIndex]
        const headers = this.columnHeaders
        if (headers && headers[colIndex]) {
          const key = headers[colIndex]
          return row[key] !== undefined ? row[key] : ''
        }
        const values = Object.values(row)
        return values[colIndex] !== undefined ? values[colIndex] : ''
      }

      if (rowIndex === 0) {
        return this.getColumnHeader(colIndex)
      }

      if (rowIndex >= 1 && this.fields && this.fields[colIndex]) {
        const field = this.fields[colIndex]
        return field.value || field.sample || ''
      }

      return ''
    },
  },
}
</script>

<style scoped>
.excel-preview {
  width: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.fake-excel {
  border: 1px solid #d4d4d4;
  border-radius: 4px;
  overflow: hidden;
  background: white;
}

.excel-toolbar {
  background: #f5f5f5;
  padding: 8px 12px;
  border-bottom: 1px solid #d4d4d4;
  display: flex;
  align-items: center;
}

.excel-title {
  font-size: 12px;
  color: #666;
}

.excel-container {
  overflow-x: auto;
}
.excel-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px;
  font-size: 12px;
}
.excel-pagination button:disabled { opacity: .5; cursor: default; }

.real-grid-table {
  border-collapse: collapse;
  min-width: fit-content;
}

.real-row-num {
  width: 40px;
  min-width: 40px;
  padding: 6px;
  text-align: center;
  font-size: 12px;
  color: #999;
  border: 1px solid #d4d4d4;
  background: #fafafa;
}

.real-grid-cell {
  min-width: 92px;
  height: 30px;
  padding: 4px 6px;
  border: 1px solid #d4d4d4;
  font-size: 12px;
  color: #333;
  background: #fff;
}

.real-grid-cell.is-merged {
  background: #f7fbff;
}

.excel-headers {
  display: flex;
  background: #f0f0f0;
  border-bottom: 2px solid #d4d4d4;
  min-width: fit-content;
}

.row-num-header {
  width: 40px;
  min-width: 40px;
  padding: 6px 8px;
  text-align: center;
  font-weight: 500;
  font-size: 12px;
  color: #666;
  border-right: 1px solid #d4d4d4;
  background: #f5f5f5;
}

.col-header {
  width: 100px;
  min-width: 100px;
  padding: 6px 8px;
  text-align: center;
  font-weight: 500;
  font-size: 12px;
  color: #333;
  border-right: 1px solid #d4d4d4;
}

.excel-body {
  min-width: fit-content;
}

.excel-row {
  display: flex;
  border-bottom: 1px solid #d4d4d4;
}

.excel-row:last-child {
  border-bottom: none;
}

.excel-row:hover {
  background: #f9f9f9;
}

.row-num {
  width: 40px;
  min-width: 40px;
  padding: 8px;
  text-align: center;
  font-size: 12px;
  color: #999;
  border-right: 1px solid #d4d4d4;
  background: #fafafa;
}

.excel-cell {
  width: 100px;
  min-width: 100px;
  height: 32px;
  padding: 4px 8px;
  border-right: 1px solid #d4d4d4;
  font-size: 12px;
  vertical-align: middle;
}

.excel-cell.has-content {
  background: white;
}

.cell-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

import { createApp, defineComponent, h, nextTick, ref, shallowRef } from 'vue'
import DataTable from '../src/components/DataTable.vue'

type BusinessRow = { id: number; name: string; order: string; detail: string }
const rows = shallowRef<BusinessRow[]>([])
const selected = ref<number[]>([])
const columns = [
  { key: 'name', label: '客户' },
  { key: 'order', label: '订单' },
  { key: 'detail', label: '说明' },
]
function paint() {
  return new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
}
const bench = {
  async load(count: number) {
    const start = performance.now()
    rows.value = Array.from({ length: count }, (_, i) => ({
      id: i + 1, name: '客户 ' + i, order: '订单-' + i,
      detail: '长行测量 / ' + '状态'.repeat(i % 7 + 1),
    }))
    selected.value = []
    await nextTick()
    await paint()
    return performance.now() - start
  },
  async clear() {
    rows.value = []
    selected.value = []
    await nextTick()
    await paint()
  },
  count() { return rows.value.length },
  selectedCount() { return selected.value.length },
}
;(window as typeof window & { __xcmaxListBench: typeof bench }).__xcmaxListBench = bench

const Fixture = defineComponent({
  setup() {
    return () => h('main', { id: 'list-perf-fixture' }, [
      h('h1', 'Synthetic business data table benchmark'),
      h('p', { id: 'record-count' }, 'Loaded ' + rows.value.length + ' business records'),
      h(DataTable, {
        columns,
        data: rows.value,
        selectable: true,
        selectedIds: selected.value,
        hasMore: false,
        height: '620px',
        'onUpdate:selectedIds': (ids: number[]) => { selected.value = ids },
      }, {
        actions: ({ row, index }: { row: BusinessRow; index: number }) =>
          h('button', { type: 'button', 'data-record-action': row.id },
            '查看 ' + index),
      }),
    ])
  },
})
createApp(Fixture).mount('#app')

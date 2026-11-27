<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import { resolveDeskStatusLine } from '@/composables/useWorkflowEmployeeDesks'
import { applyOfficeActivity, buildOfficeLayout, loadOfficeAssets, OfficeState, renderFrame, startGameLoop, TILE_SIZE, type OfficeZone } from '@/utils/pixelOffice'

const props = defineProps<{ desks: WorkflowEmployeeDeskRow[]; zones: OfficeZone[]; selectedEmpId: string | null }>()
const emit = defineEmits<{ (e: 'select', empId: string): void }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const viewport = ref<HTMLElement | null>(null)
const selectedZone = ref('')
const zoom = ref(1)
const ratio = ref(1)
const error = ref('')
const ready = ref(false)
const visible = ref(true)
const reducedMotion = ref(false)
const active = ref(true)
const viewportWidth = ref(800)
const filteredZones = computed(() => selectedZone.value ? props.zones.filter(zone => zone.id === selectedZone.value) : props.zones)
const model = computed(() => buildOfficeLayout(filteredZones.value, props.desks))
const displayScale = computed(() => Math.max(1 / ratio.value, Math.min(2.5, viewportWidth.value / (model.value.layout.cols * TILE_SIZE))) * zoom.value)
const pixelZoom = computed(() => Math.max(1, Math.ceil(displayScale.value * ratio.value)))
const canvasWidth = computed(() => model.value.layout.cols * TILE_SIZE * pixelZoom.value)
const canvasHeight = computed(() => model.value.layout.rows * TILE_SIZE * pixelZoom.value)
const cssUnit = computed(() => TILE_SIZE * displayScale.value)
const displayWidth = computed(() => model.value.layout.cols * cssUnit.value)
const displayHeight = computed(() => model.value.layout.rows * cssUnit.value)
const rowById = computed(() => new Map(props.desks.map(row => [row.empId, row])))
const stateOf = (id: string) => rowById.value.get(id)?.snapshot?.officeState || 'offline'
const statusOf = (id: string) => {
  const row = rowById.value.get(id)
  return row ? resolveDeskStatusLine(row) : '状态待同步'
}
const stateLabel: Record<string, string> = { working: '执行中', reading: '分析中', waiting: '待处理', error: '需关注', done: '已完成', idle: '待命', offline: '待同步' }
let office: OfficeState | null = null
let loop: ReturnType<typeof startGameLoop> | null = null
let observer: IntersectionObserver | null = null
let resize: ResizeObserver | null = null
let motion: MediaQueryList | null = null
let disposed = false

function draw(ctx?: CanvasRenderingContext2D) {
  const target = ctx || canvas.value?.getContext('2d')
  if (!target || !office || !canvas.value) return
  target.imageSmoothingEnabled = false
  renderFrame(target, canvas.value.width, canvas.value.height, office.tileMap, office.furniture, office.getCharacters(), pixelZoom.value, 0, 0,
    { selectedAgentId: office.selectedAgentId, hoveredAgentId: null, hoveredTile: null, seats: office.seats, characters: office.characters },
    undefined, office.layout.tileColors, office.layout.cols, office.layout.rows)
}

function reconcileLoop() {
  loop?.stop()
  loop = null
  if (!ready.value || !canvas.value || !office) return
  draw()
  if (document.hidden || !visible.value || !active.value || reducedMotion.value || !props.desks.some(row => ['working', 'reading'].includes(row.snapshot?.officeState || ''))) return
  loop = startGameLoop(canvas.value, { update: dt => office?.update(dt), render: draw })
}

function syncSelection() {
  if (!office) return
  office.selectedAgentId = model.value.seats.find(seat => seat.empId === props.selectedEmpId)?.id ?? null
  draw()
}

function syncActivity() {
  if (!office) return
  applyOfficeActivity(office, model.value.seats, props.desks)
  syncSelection()
  reconcileLoop()
}

function rebuild() {
  if (!ready.value) return
  loop?.stop()
  office = new OfficeState(model.value.layout)
  for (const seat of model.value.seats) office.addAgent(seat.id, seat.id % 6, 0, seat.seatId, true)
  syncActivity()
  void nextTick(reconcileLoop)
}

async function initialize() {
  error.value = ''
  try {
    await loadOfficeAssets()
    if (disposed) return
    ready.value = true
    await nextTick()
    rebuild()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '办公室画面加载失败'
  }
}

function updateSize() {
  if (!viewport.value) return
  viewportWidth.value = Math.max(280, viewport.value.clientWidth - 24)
  ratio.value = Math.min(window.devicePixelRatio || 1, 2)
}
function updateMotion() { reducedMotion.value = motion?.matches ?? false; reconcileLoop() }

watch(() => `${JSON.stringify(props.zones)}|${props.desks.map(row => row.empId).join('\0')}|${selectedZone.value}`, rebuild)
watch(() => props.desks, syncActivity, { deep: true })
watch(() => props.selectedEmpId, () => {
  if (selectedZone.value && !filteredZones.value.some(zone => zone.employeeIds.includes(props.selectedEmpId || ''))) selectedZone.value = ''
  syncSelection()
})
watch([canvasWidth, canvasHeight], () => { void nextTick(reconcileLoop) })
onMounted(() => {
  updateSize()
  motion = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.value = motion.matches
  motion.addEventListener('change', updateMotion)
  document.addEventListener('visibilitychange', reconcileLoop)
  if (typeof ResizeObserver !== 'undefined' && viewport.value) { resize = new ResizeObserver(updateSize); resize.observe(viewport.value) }
  if (typeof IntersectionObserver !== 'undefined' && viewport.value) {
    observer = new IntersectionObserver(([entry]) => { visible.value = entry.isIntersecting; reconcileLoop() })
    observer.observe(viewport.value)
  }
  void initialize()
})
onActivated(() => { active.value = true; reconcileLoop() })
onDeactivated(() => { active.value = false; reconcileLoop() })
onBeforeUnmount(() => {
  disposed = true
  loop?.stop()
  resize?.disconnect()
  observer?.disconnect()
  motion?.removeEventListener('change', updateMotion)
  document.removeEventListener('visibilitychange', reconcileLoop)
})
</script>

<template>
  <section class="pixel-office" aria-label="按部门分区的员工办公室" :data-office-ready="ready">
    <div class="pixel-office-toolbar">
      <div class="pixel-office-zones" aria-label="部门筛选">
        <button type="button" :aria-pressed="!selectedZone" @click="selectedZone = ''">全公司</button>
        <button v-for="zone in zones" :key="zone.id" type="button" :aria-pressed="selectedZone === zone.id" @click="selectedZone = zone.id">
          <i :style="{ background: zone.color }" aria-hidden="true" />{{ zone.label }}
        </button>
      </div>
      <div class="pixel-office-zoom" aria-label="办公室缩放">
        <button type="button" aria-label="缩小办公室" :disabled="zoom <= .75" @click="zoom = Math.max(.75, zoom - .25)">−</button>
        <button type="button" aria-label="重置缩放" @click="zoom = 1">{{ Math.round(zoom * 100) }}%</button>
        <button type="button" aria-label="放大办公室" :disabled="zoom >= 2" @click="zoom = Math.min(2, zoom + .25)">+</button>
      </div>
    </div>
    <slot />
    <div v-if="error" class="pixel-office-error" role="alert">{{ error }} <button type="button" @click="initialize">重新加载画面</button></div>
    <div ref="viewport" class="pixel-office-viewport" tabindex="0" aria-label="办公室地图，可滚动查看各部门">
      <p v-if="!ready && !error" class="pixel-office-loading" role="status">正在布置办公室…</p>
      <div v-if="ready && zones.length" class="pixel-office-world" :style="{ width: displayWidth + 'px', height: displayHeight + 'px' }">
        <canvas ref="canvas" :width="canvasWidth" :height="canvasHeight" :style="{ width: displayWidth + 'px', height: displayHeight + 'px' }" aria-hidden="true" />
        <div v-for="room in model.rooms" :key="room.id" class="pixel-office-room" :style="{ left: (room.col + 1) * cssUnit + 'px', top: (room.row + 1.25) * cssUnit + 'px', width: (room.width - 3) * cssUnit + 'px', borderColor: room.color }">
          <strong>{{ room.label }}</strong><span>{{ room.count }} 位员工</span>
          <small v-if="room.detail" :title="room.detail">{{ room.detail }}</small>
        </div>
        <button v-for="seat in model.seats" :key="seat.empId" type="button" class="pixel-office-employee"
          :class="['pixel-office-employee--' + stateOf(seat.empId), { 'is-selected': selectedEmpId === seat.empId }]"
          :style="{ left: (seat.col - .5) * cssUnit + 'px', top: (seat.row - 1) * cssUnit + 'px', width: 3 * cssUnit + 'px', height: 3.9 * cssUnit + 'px' }"
          aria-haspopup="dialog" :aria-pressed="selectedEmpId === seat.empId" :aria-label="`${rowById.get(seat.empId)?.shortName}：${statusOf(seat.empId)}`"
          :data-employee-id="seat.empId" :data-office-state="stateOf(seat.empId)" :title="statusOf(seat.empId)" @click="emit('select', seat.empId)">
          <span class="pixel-office-activity">{{ stateLabel[stateOf(seat.empId)] }}</span>
          <span class="pixel-office-name">{{ rowById.get(seat.empId)?.shortName }}</span>
        </button>
      </div>
      <p v-if="ready && !zones.length" class="pixel-office-loading">部门编制尚未同步。</p>
    </div>
    <div class="pixel-office-legend" aria-label="工位状态说明">
      <span><i class="working" />执行 / 分析</span><span><i class="waiting" />待审批 / 待处理</span><span><i class="done" />已完成</span><span><i class="error" />需关注</span><span><i class="offline" />状态待核实</span>
    </div>
    <p v-if="!selectedZone && model.unassigned.length" class="pixel-office-unassigned">{{ model.unassigned.length }} 位员工尚未关联部门。</p>
  </section>
</template>

<style scoped>
.pixel-office { overflow: hidden; border: 1px solid #d7dfda; border-radius: 16px; background: #f6f8f4; }
.pixel-office-toolbar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 14px; background: #fff; border-bottom: 1px solid #e3e8e1; }
.pixel-office-zones, .pixel-office-zoom { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.pixel-office-toolbar button { border: 1px solid transparent; border-radius: 8px; padding: 7px 10px; font-size: 12px; color: #526359; background: #f1f5f1; cursor: pointer; }
.pixel-office-zones button { display: inline-flex; align-items: center; gap: 6px; }
.pixel-office-zones button[aria-pressed="true"] { color: #fff; background: #214d3d; }
.pixel-office-toolbar button:disabled { opacity: .4; cursor: default; }
.pixel-office-zones i, .pixel-office-legend i { display: inline-block; width: 7px; height: 7px; border-radius: 2px; }
.pixel-office-viewport { overflow: auto; max-height: 610px; min-height: 340px; padding: 12px; background-color: #dfe8d9; background-image: radial-gradient(#bccdb6 1px, transparent 1px); background-size: 12px 12px; }
.pixel-office-world { position: relative; margin: auto; }
.pixel-office-world canvas { position: absolute; inset: 0; image-rendering: pixelated; pointer-events: none; }
.pixel-office-room { position: absolute; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding-left: 8px; border-left: 3px solid; color: #37483c; pointer-events: none; }
.pixel-office-room strong { font-size: 13px; line-height: 1.4; }
.pixel-office-room > span { font-size: 10px; color: #75816f; }
.pixel-office-room small { flex-basis: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 9px; color: #7a8175; }
.pixel-office-employee { position: absolute; display: flex; flex-direction: column; align-items: center; justify-content: space-between; border: 1px solid transparent; border-radius: 5px; background: transparent; padding: 0; cursor: pointer; }
.pixel-office-employee:hover { background: #fff2; border-color: #8aa390; }
.pixel-office-employee.is-selected { outline: 2px solid #1d785b; outline-offset: 3px; }
.pixel-office-name { display: block; max-width: 135%; min-width: 38px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 2px 5px; border-radius: 4px; color: #294238; background: #f7faf2f2; box-shadow: 0 1px 2px #3452; font-size: 10px; }
.pixel-office-activity { display: inline-block; padding: 2px 5px; border: 1px solid #aebbad; border-radius: 4px; background: #e9eee5; color: #687564; font-size: 9px; line-height: 1.4; white-space: nowrap; }
.pixel-office-employee--working .pixel-office-activity, .pixel-office-employee--reading .pixel-office-activity { background: #dcf2ff; border-color: #82b6da; color: #216482; }
.pixel-office-employee--waiting .pixel-office-activity { background: #fff1c7; border-color: #dcb660; color: #906823; }
.pixel-office-employee--error .pixel-office-activity { background: #ffe2dc; border-color: #da8d80; color: #a33f35; }
.pixel-office-employee--done .pixel-office-activity { background: #d8efd9; border-color: #83b78e; color: #2f7447; }
.pixel-office-legend { display: flex; flex-wrap: wrap; gap: 14px; padding: 12px 16px; color: #657466; background: #fff; font-size: 10px; }
.pixel-office-legend span { display: inline-flex; align-items: center; gap: 5px; }
.pixel-office-legend .working { background: #4b9fc6; }.pixel-office-legend .waiting { background: #d6a44b; }.pixel-office-legend .done { background: #65a475; }.pixel-office-legend .error { background: #c86d61; }.pixel-office-legend .offline { background: #a4afa2; }
.pixel-office-loading { padding: 80px 20px; text-align: center; color: #6c7b65; font-size: 13px; }
.pixel-office-error { padding: 16px; color: #a33f35; background: #fff0eb; font-size: 13px; }.pixel-office-error button { margin-left: 12px; cursor: pointer; }
.pixel-office-unassigned { margin: 0; padding: 0 16px 12px; color: #8a774a; background: #fff; font-size: 11px; }
button:focus-visible, .pixel-office-viewport:focus-visible { outline: 2px solid #176a50; outline-offset: 2px; }
@media (max-width: 600px) { .pixel-office-viewport { max-height: 500px; } .pixel-office-toolbar { padding: 10px; } }
</style>

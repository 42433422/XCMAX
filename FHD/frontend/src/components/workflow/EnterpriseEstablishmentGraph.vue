<script setup lang="ts">
import { computed, nextTick, onMounted, watch } from 'vue'
import { VueFlow, useVueFlow, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { computeGridLayout } from '@/composables/useAutoLayout'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import {
  ENTERPRISE_ORG_LAYERS,
  resolveEnterpriseOrgLayer,
} from '@/constants/enterpriseWorkflowEstablishment'
import { asRecord, asString } from '@/utils/typeGuards'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps<{
  desks: WorkflowEmployeeDeskRow[]
  selectedEmpId: string | null
  isBusy: (row: WorkflowEmployeeDeskRow) => boolean
  enterpriseStackLabel?: string
}>()

const emit = defineEmits<{
  (e: 'select', empId: string): void
}>()

const NODE_W = 200
const NODE_H = 56
const OUTER_COLS = 2
const INNER_COLS = 2
const GROUP_GAP_X = 36
const GROUP_GAP_Y = 32

const flowGraph = computed(() => buildGraph())
const flowNodes = computed(() => flowGraph.value.nodes)
const flowEdges = computed(() => flowGraph.value.edges)

const { fitView } = useVueFlow({ id: 'enterprise-establishment-graph' })

function zoneNodeId(zoneId: string, empId: string): string {
  return `${zoneId}::${empId}`
}

function parseEmpIdFromNodeId(nodeId: string): string | null {
  if (!nodeId.includes('::')) return null
  return nodeId.split('::').slice(1).join('::') || null
}

function buildGraph(): { nodes: Node[]; edges: Edge[] } {
  const rawNodes: Node[] = []
  const rawEdges: Edge[] = []
  const groupIds: string[] = []

  const slotsByZone = new Map<string, { empId: string; row: WorkflowEmployeeDeskRow }[]>()
  for (const z of ENTERPRISE_ORG_LAYERS) {
    slotsByZone.set(z.id, [])
  }
  for (const row of props.desks) {
    const zid = resolveEnterpriseOrgLayer(row.empId, row.shortName, row.panelTitle)
    const list = slotsByZone.get(zid) ?? slotsByZone.get('management')!
    list.push({ empId: row.empId, row })
  }

  for (const zone of ENTERPRISE_ORG_LAYERS) {
    const slots = slotsByZone.get(zone.id) ?? []
    const groupId = `zone-${zone.id}`
    groupIds.push(groupId)
    const color = zone.color

    rawNodes.push({
      id: groupId,
      type: 'group',
      label: `${zone.code} ${zone.label}`,
      position: { x: 0, y: 0 },
      style: {
        background: color + '14',
        border: `1px solid ${color}55`,
        borderRadius: '12px',
        padding: '0',
        color,
        fontWeight: '700',
        fontSize: '0.78rem',
      },
    })

    if (!slots.length) {
      const placeholderId = zoneNodeId(zone.id, '__empty__')
      rawNodes.push({
        id: placeholderId,
        type: 'default',
        label: '暂无员工 Mod',
        parentNode: groupId,
        extent: 'parent',
        position: { x: 0, y: 0 },
        selectable: false,
        data: { placeholder: true },
        style: {
          width: `${NODE_W}px`,
          minWidth: `${NODE_W}px`,
          maxWidth: `${NODE_W}px`,
          opacity: '0.72',
        },
      })
      continue
    }

    for (const slot of slots) {
      const busy = props.isBusy(slot.row)
      const enabled = slot.row.enabled
      rawNodes.push({
        id: zoneNodeId(zone.id, slot.empId),
        type: 'default',
        label: slot.row.shortName,
        parentNode: groupId,
        extent: 'parent',
        position: { x: 0, y: 0 },
        data: {
          empId: slot.empId,
          enabled,
          busy,
          selected: props.selectedEmpId === slot.empId,
          zoneColor: color,
        },
        style: {
          width: `${NODE_W}px`,
          minWidth: `${NODE_W}px`,
          maxWidth: `${NODE_W}px`,
          borderRadius: '8px',
          border:
            props.selectedEmpId === slot.empId
              ? `2px solid ${color}`
              : '1px solid rgba(148, 163, 184, 0.55)',
          background: enabled
            ? busy
              ? 'linear-gradient(180deg, #eff6ff 0%, #fff 100%)'
              : '#fff'
            : '#f8fafc',
          padding: '8px 10px',
          fontSize: '0.82rem',
          boxShadow:
            props.selectedEmpId === slot.empId ? `0 0 0 2px ${color}33` : '0 1px 2px rgba(15,23,42,0.06)',
        },
      })
    }
  }

  applyZoneLayout(rawNodes, groupIds)
  return { nodes: rawNodes, edges: rawEdges }
}

function applyZoneLayout(rawNodes: Node[], groupIds: string[]) {
  const boxSizes = new Map<string, { w: number; h: number }>()

  for (const gid of groupIds) {
    const children = rawNodes.filter((n) => n.parentNode === gid)
    const { positions, width, height } = computeGridLayout(
      children.map((c) => c.id),
      {
        cols: INNER_COLS,
        cellWidth: NODE_W,
        cellHeight: NODE_H,
        gapX: 10,
        gapY: 10,
        paddingX: 12,
        paddingY: 30,
        paddingBottom: 12,
      },
    )
    for (const child of children) {
      const p = positions.get(child.id)
      if (p) child.position = p
    }
    const w = Math.max(width, 240)
    boxSizes.set(gid, { w, h: height })
    const group = rawNodes.find((n) => n.id === gid)
    if (group) {
      group.style = {
        ...(group.style as Record<string, string>),
        width: `${w}px`,
        height: `${height}px`,
        minWidth: `${w}px`,
      }
    }
  }

  const colWidths = [0, 1].map((c) =>
    Math.max(
      240,
      ...groupIds.filter((_, i) => i % OUTER_COLS === c).map((gid) => boxSizes.get(gid)!.w),
    ),
  )
  const rowHeights = [0, 1].map((r) =>
    Math.max(
      160,
      ...groupIds
        .filter((_, i) => Math.floor(i / OUTER_COLS) === r)
        .map((gid) => boxSizes.get(gid)!.h),
    ),
  )

  groupIds.forEach((gid, idx) => {
    const col = idx % OUTER_COLS
    const row = Math.floor(idx / OUTER_COLS)
    let x = 0
    for (let c = 0; c < col; c++) x += colWidths[c] + GROUP_GAP_X
    let y = 0
    for (let r = 0; r < row; r++) y += rowHeights[r] + GROUP_GAP_Y
    const group = rawNodes.find((n) => n.id === gid)
    if (group) group.position = { x, y }
  })
}

function onNodeClick({ node }: { node: Node }) {
  const data = asRecord(node.data)
  if (node.type === 'group' || data.placeholder) return
  const empId = asString(data.empId) || parseEmpIdFromNodeId(node.id)
  if (!empId) return
  emit('select', empId)
}

async function scheduleFit() {
  await nextTick()
  try {
    fitView({ padding: 0.14, duration: 200 })
  } catch {
    /* flow 未就绪 */
  }
}

watch(
  () => props.desks.map((d) => `${d.empId}:${d.enabled}:${d.snapshot?.visuallyBusy}`).join('|'),
  () => scheduleFit(),
)

watch(() => props.selectedEmpId, () => scheduleFit())

onMounted(() => scheduleFit())
</script>

<template>
  <div class="ewg-root" role="region" aria-label="企业四部门在岗节点图">
    <div v-if="enterpriseStackLabel" class="ewg-stack-banner" role="note">
      <span class="ewg-stack-banner__k">企业 Mod</span>
      <span class="ewg-stack-banner__v">{{ enterpriseStackLabel }}</span>
      <span class="ewg-stack-banner__hint">行业通用 + 定制 Mod · 员工上岗归属此栈</span>
    </div>
    <VueFlow
      id="enterprise-establishment-graph"
      :nodes="flowNodes"
      :edges="flowEdges"
      :nodes-connectable="false"
      :elements-selectable="true"
      fit-view-on-init
      class="ewg-flow"
      @node-click="onNodeClick"
    >
      <Background pattern-color="rgba(15, 23, 42, 0.06)" :gap="24" />
      <Controls position="bottom-left" />
      <MiniMap position="bottom-right" mask-color="rgba(237, 243, 250, 0.85)" />

      <template #node-group="{ label }">
        <div class="ewg-group-node">
          <span class="ewg-group-node__label">{{ label }}</span>
        </div>
      </template>

      <template #node-default="{ data, label }">
        <div
          class="ewg-node-inner"
          :class="{
            'ewg-node-inner--selected': data?.selected,
            'ewg-node-inner--placeholder': data?.placeholder,
          }"
        >
          <span class="ewg-node-label">{{ label }}</span>
          <span v-if="!data?.placeholder" class="ewg-node-dots" aria-hidden="true">
            <span
              class="ewg-node-dot"
              :class="{
                'ewg-node-dot--on': data?.enabled,
                'ewg-node-dot--busy': data?.busy,
              }"
            />
          </span>
        </div>
      </template>
    </VueFlow>
  </div>
</template>

<style scoped>
.ewg-root {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
  overflow: hidden;
}

.ewg-stack-banner {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 14px;
  border-bottom: 1px solid #e2e8f0;
  background: linear-gradient(90deg, #eff6ff 0%, #f8fafc 100%);
  font-size: 0.78rem;
}

.ewg-stack-banner__k {
  font-weight: 700;
  color: #1e40af;
}

.ewg-stack-banner__v {
  font-weight: 600;
  color: #0f172a;
}

.ewg-stack-banner__hint {
  color: #64748b;
}

.ewg-flow {
  flex: 1;
  width: 100%;
  min-height: 0;
  height: auto;
  min-height: 280px;
  background: var(--bg-color, #edf3fa);
}

.ewg-group-node {
  width: 100%;
  height: 100%;
  min-height: 48px;
  pointer-events: none;
  box-sizing: border-box;
}

.ewg-group-node__label {
  position: absolute;
  top: 8px;
  left: 12px;
  font-weight: 700;
  font-size: 0.78rem;
  line-height: 1.2;
  color: inherit;
  pointer-events: none;
}

.ewg-node-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  box-sizing: border-box;
}

.ewg-node-inner--selected {
  filter: brightness(1.02);
}

.ewg-node-inner--placeholder {
  justify-content: center;
  color: #9ca3af;
  font-size: 0.75rem;
}

.ewg-node-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ewg-node-dots {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.ewg-node-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #cbd5e1;
  box-shadow: 0 0 0 2px rgba(203, 213, 225, 0.35);
}

.ewg-node-dot--on {
  background: #34d399;
  box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.25);
}

.ewg-node-dot--busy {
  background: #2563eb;
  box-shadow: 0 0 6px rgba(37, 99, 235, 0.45);
}

.ewg-root :deep(.vue-flow__controls) {
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.1);
}

.ewg-root :deep(.vue-flow__controls-button) {
  background: #ffffff;
  border-color: rgba(213, 222, 235, 0.78);
  fill: #475569;
}

.ewg-root :deep(.vue-flow__minimap) {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(213, 222, 235, 0.78);
  border-radius: 8px;
}
</style>

<template>
  <section v-if="userId" class="admin-private-delivery" aria-label="客户定制交付状态">
    <header class="admin-private-delivery__head">
      <div>
        <h4>客户定制清单与交付状态</h4>
        <p class="muted">只读查看业务模块与 AI 员工每个节点的阶段、确认和返工记录；行业通用包不在此列。</p>
      </div>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="load">
        {{ loading ? '读取中…' : '刷新交付状态' }}
      </button>
    </header>
    <div v-if="error" class="admin-entitlements-alert admin-entitlements-alert--soft" role="status">
      {{ error }}
    </div>
    <div v-else-if="loading" class="admin-private-delivery__empty muted">正在读取客户交付状态…</div>
    <div v-else-if="!projects.length" class="admin-private-delivery__empty muted">该用户还没有客户私有 Mod 交付状态。</div>
    <div v-else class="admin-private-delivery__projects">
      <article v-for="project in projects" :key="project.mod_id" class="admin-private-delivery__project">
        <header class="admin-private-delivery__project-head">
          <div>
            <strong>{{ project.name }}</strong
            ><code>{{ project.mod_id }}</code>
          </div>
          <span class="admin-private-delivery__overall" :data-status="project.overall_status">
            {{ project.overall_label }}
          </span>
        </header>
        <div class="admin-private-delivery__tracks">
          <section v-for="track in tracks" :key="track.key" class="admin-private-delivery__track">
            <div class="admin-private-delivery__track-head">
              <strong>{{ track.label }}</strong
              ><span>{{ stageLabel(project, track.key) }}</span>
            </div>
            <small v-if="deliveryTrack(project, track.key)?.updated_at" class="muted">
              最近更新：{{ formatTime(deliveryTrack(project, track.key)?.updated_at) }}
            </small>
            <ul v-if="nodes(project, track.key).length" class="admin-private-delivery__nodes">
              <li v-for="node in nodes(project, track.key)" :key="node.id" :data-status="node.status || 'production'">
                <div class="admin-private-delivery__node-head">
                  <strong>{{ node.label || node.id }}</strong>
                  <span class="admin-private-delivery__node-status" :data-status="node.status || 'production'">
                    {{ nodeStatusLabel(node) }}
                  </span>
                </div>
                <small v-if="nodeNote(node)">{{ nodeNote(node) }}</small>
              </li>
            </ul>
            <small v-else class="muted">该轨道未声明定制清单节点</small>
            <ul v-if="timeline(project, track.key).length" class="admin-private-delivery__timeline">
              <li v-for="event in timeline(project, track.key)" :key="`${event.at}:${event.status}`">
                <span>{{ event.status_label }}</span>
                <small
                  >{{ formatTime(event.at) }}<template v-if="event.note"> · {{ event.note }}</template></small
                >
              </li>
            </ul>
            <small v-else class="muted">暂无确认或返工记录</small>
          </section>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

type TrackKey = 'modules' | 'business' | 'employees'
type Event = { status?: string; status_label?: string; at?: string; note?: string }
type Track = { status?: string; updated_at?: string; timeline?: Event[] }
type Node = {
  id: string
  label?: string
  status?: string
  status_label?: string
  timeline?: Event[]
}
type Project = {
  mod_id: string
  name: string
  overall_status?: string
  overall_label?: string
  tracks?: Partial<Record<TrackKey, Track>>
  track_nodes?: Partial<Record<'modules' | 'employees', Node[]>>
  stage_labels?: Partial<Record<TrackKey, Record<string, string>>>
}

const props = defineProps<{ userId: number | null }>()
const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')
const tracks: { key: TrackKey; label: string }[] = [
  { key: 'modules', label: '业务模块' },
  { key: 'employees', label: 'AI 员工' },
]
const labels: Record<string, string> = {
  production: '制作中',
  testing: '测试中',
  rework: '返工中',
  acceptance: '验收中',
  delivered: '已交付',
}

function deliveryTrack(project: Project, key: TrackKey) {
  return key === 'modules' ? project.tracks?.modules || project.tracks?.business || null : project.tracks?.[key] || null
}
function stageLabel(project: Project, key: TrackKey) {
  const status = String(deliveryTrack(project, key)?.status || 'production')
  return (
    project.stage_labels?.[key]?.[status] ||
    (key === 'modules' ? project.stage_labels?.business?.[status] : undefined) ||
    labels[status] ||
    status
  )
}
function nodes(project: Project, key: TrackKey): Node[] {
  const canonical = key === 'business' ? 'modules' : key
  const value = project.track_nodes?.[canonical as 'modules' | 'employees']
  return Array.isArray(value) ? value : []
}
function nodeStatusLabel(node: Node) {
  const status = String(node.status || 'production')
  return node.status_label || labels[status] || status
}
function nodeNote(node: Node) {
  const rows = Array.isArray(node.timeline) ? node.timeline : []
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const note = String(rows[i]?.note || '').trim()
    if (note) return note
  }
  return ''
}
function timeline(project: Project, key: TrackKey) {
  return (deliveryTrack(project, key)?.timeline || [])
    .slice(-5)
    .reverse()
    .map((event) => ({
      ...event,
      status_label: event.status_label || labels[String(event.status || '')] || event.status || '状态变更',
    }))
}
function formatTime(value?: string) {
  const raw = String(value || '').trim()
  if (!raw) return '—'
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString()
}
async function load() {
  if (!props.userId) return
  loading.value = true
  error.value = ''
  try {
    const body = (await xcmaxAdminApi.getUserPrivateDelivery(props.userId)) as {
      data?: { projects?: Project[] }
    }
    projects.value = Array.isArray(body.data?.projects) ? body.data.projects : []
  } catch (cause) {
    projects.value = []
    error.value = `客户交付状态读取失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    loading.value = false
  }
}
watch(
  () => props.userId,
  () => {
    projects.value = []
    error.value = ''
    void load()
  },
  { immediate: true },
)
</script>

<style scoped>
.admin-private-delivery {
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid #f1d6a8;
  border-radius: 12px;
  background: #fffaf0;
}
.admin-private-delivery__head,
.admin-private-delivery__project-head,
.admin-private-delivery__track-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.admin-private-delivery__head {
  margin-bottom: 12px;
}
.admin-private-delivery__head h4 {
  margin: 0 0 4px;
  color: #92400e;
}
.admin-private-delivery__head p {
  margin: 0;
  font-size: 12px;
}
.admin-private-delivery__empty {
  padding: 18px 10px;
  text-align: center;
  border: 1px dashed #e8c98f;
  border-radius: 8px;
}
.admin-private-delivery__projects {
  display: grid;
  gap: 12px;
}
.admin-private-delivery__project {
  padding: 12px;
  border: 1px solid #ead9b8;
  border-radius: 10px;
  background: #fff;
}
.admin-private-delivery__project-head code {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
}
.admin-private-delivery__overall {
  padding: 4px 9px;
  border-radius: 999px;
  color: #166534;
  background: #dcfce7;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.admin-private-delivery__overall[data-status='partial'] {
  color: #92400e;
  background: #fef3c7;
}
.admin-private-delivery__overall[data-status='rework'] {
  color: #b91c1c;
  background: #fee2e2;
}
.admin-private-delivery__tracks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.admin-private-delivery__track {
  padding: 10px;
  border: 1px solid #e8edf3;
  border-radius: 8px;
  background: #f8fafc;
}
.admin-private-delivery__track-head span {
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}
.admin-private-delivery__track > small {
  display: block;
  margin-top: 5px;
  font-size: 11px;
}
.admin-private-delivery__nodes,
.admin-private-delivery__timeline {
  display: grid;
  gap: 6px;
  margin: 9px 0 0;
  padding: 0;
  list-style: none;
}
.admin-private-delivery__nodes li {
  padding: 7px 9px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}
.admin-private-delivery__nodes li[data-status='rework'] {
  border-color: #fecaca;
  background: #fef2f2;
}
.admin-private-delivery__node-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.admin-private-delivery__node-status {
  padding: 2px 8px;
  border-radius: 999px;
  color: #166534;
  background: #dcfce7;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.admin-private-delivery__node-status[data-status='testing'],
.admin-private-delivery__node-status[data-status='acceptance'] {
  color: #92400e;
  background: #fef3c7;
}
.admin-private-delivery__node-status[data-status='production'] {
  color: #475569;
  background: #e2e8f0;
}
.admin-private-delivery__node-status[data-status='rework'] {
  color: #b91c1c;
  background: #fee2e2;
}
.admin-private-delivery__nodes li > small {
  display: block;
  margin-top: 4px;
  color: #9a3412;
  font-size: 11px;
  line-height: 1.4;
}
.admin-private-delivery__timeline li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  color: #334155;
  font-size: 12px;
}
.admin-private-delivery__timeline small {
  color: #94a3b8;
  font-size: 10px;
  text-align: right;
}
@media (max-width: 900px) {
  .admin-private-delivery__tracks {
    grid-template-columns: 1fr;
  }
}
</style>

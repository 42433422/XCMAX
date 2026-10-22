<template>
  <section class="cs-card" aria-label="同根因公共修复">
    <h3 class="cs-card-title">复用同根因公共修复</h3>
    <p class="cs-hint">适用于相同源版本和问题的公共修复。确认关联后，本客户仍须独立完成正式版本绑定和验收。</p>
    <button type="button" class="cs-btn" :disabled="busy" @click="findCandidates">查找可复用修复</button>
    <p v-if="error" role="alert" class="cs-error-text">{{ error }}</p>
    <p v-if="loaded && !candidates.length" class="cs-state">未发现符合当前原单版本与问题的公共修复。</p>
    <form v-if="candidates.length" @submit.prevent="linkRepair">
      <label>已完成修复的来源原单
        <select v-model="selected" :disabled="busy">
          <option value="">请选择来源修复</option>
          <option v-for="candidate in candidates" :key="candidate.source_action_id" :value="String(candidate.source_action_id)">
            {{ candidate.ticket_no }} · 修复 #{{ candidate.change_request_id }} · {{ candidate.repair_head_sha.slice(0, 12) }}
          </option>
        </select>
      </label>
      <label><input v-model="confirmed" type="checkbox" :disabled="busy" /> 已核对为同一根因，且此公共修复适用于本原单</label>
      <label>同根因与适用性核对记录<textarea v-model="note" minlength="8" maxlength="2000" required :disabled="busy" /></label>
      <button type="submit" class="cs-btn" :disabled="busy || !selected || !confirmed || note.trim().length < 8">确认关联到本原单</button>
    </form>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import api from '@/api/core'

type Candidate = { source_ticket_id: number; source_action_id: number; ticket_no: string; change_request_id: number; repair_head_sha: string }
const props = defineProps<{ ticketId: number }>()
const emit = defineEmits<{ linked: [] }>()
const candidates = ref<Candidate[]>([]), selected = ref(''), confirmed = ref(false), note = ref('')
const busy = ref(false), error = ref(''), loaded = ref(false), match = ref(''), requestId = ref('')
let active = true
onBeforeUnmount(() => { active = false })
watch([selected, confirmed, note], () => { requestId.value = '' })
const endpoint = () => `/api/xcmax/market-proxy/customer-service/issues/${props.ticketId}/shared-repair`

async function findCandidates() {
  busy.value = true; error.value = ''
  try {
    const result = await api.get<{ items: Candidate[]; match_sha256: string }>(`${endpoint()}-candidates`)
    if (!active) return
    if (!Array.isArray(result?.items) || typeof result.match_sha256 !== 'string') throw new Error('候选响应不完整，请重试')
    candidates.value = result.items; match.value = result.match_sha256; loaded.value = true
    selected.value = ''; confirmed.value = false; requestId.value = ''
  } catch (cause) { if (active) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (active) busy.value = false }
}

async function linkRepair() {
  const candidate = candidates.value.find(row => String(row.source_action_id) === selected.value)
  if (busy.value || !candidate || !confirmed.value || note.value.trim().length < 8) return
  requestId.value ||= crypto.randomUUID()
  busy.value = true; error.value = ''
  try {
    await api.post(endpoint(), {
      source_ticket_id: candidate.source_ticket_id, source_action_id: candidate.source_action_id,
      match_sha256: match.value, confirmed_same_root_cause: true, note: note.value.trim(), request_id: requestId.value,
    })
    if (active) { candidates.value = []; loaded.value = false; emit('linked') }
  } catch (cause) { if (active) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (active) busy.value = false }
}
</script>

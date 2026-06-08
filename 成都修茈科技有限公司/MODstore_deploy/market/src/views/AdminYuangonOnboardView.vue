<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const { t } = useI18n()
const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

type StatusPayload = {
  repo_root?: string
  yuangon_employee_count?: number
  catalog_employee_pack_count?: number
  missing_in_catalog?: string[]
  parse_errors?: string[]
  yuangon_pkg_ids?: string[]
}

const loading = ref(false)
const error = ref('')
const status = ref<StatusPayload | null>(null)
const pkgIds = ref('')
const dryRunBusy = ref(false)
const runBusy = ref(false)
const lastRun = ref<{ ok?: boolean; exit_code?: number; stdout_tail?: string; stderr_tail?: string } | null>(null)

async function loadStatus() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    status.value = (await api.adminYuangonOnboardStatus()) as StatusPayload
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
    status.value = null
  } finally {
    loading.value = false
  }
}

async function runScript(dryRun: boolean) {
  if (!isAdmin.value) return
  const busy = dryRun ? dryRunBusy : runBusy
  if (busy.value) return
  busy.value = true
  error.value = ''
  lastRun.value = null
  try {
    const body: Record<string, unknown> = {
      dry_run: dryRun,
      force: !dryRun,
      pkg_ids: pkgIds.value.trim() || undefined,
    }
    lastRun.value = (await api.adminYuangonOnboardRun(body)) as typeof lastRun.value
    await loadStatus()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

onMounted(() => void loadStatus())
</script>

<template>
  <div v-if="!isAdmin" class="yo-denied">
    <p>{{ t('admin.accessDenied') }}</p>
    <router-link to="/" class="btn">{{ t('common.back') }}</router-link>
  </div>
  <div v-else class="yo-page">
    <header class="yo-head">
      <h1>{{ t('admin.yuangonOnboard.title') }}</h1>
      <div class="yo-actions">
        <button type="button" class="btn ghost" :disabled="loading" @click="loadStatus">
          {{ loading ? '…' : t('common.refresh') }}
        </button>
        <router-link :to="{ name: 'admin-duty-employees' }" class="btn ghost">{{ t('admin.yuangonOnboard.backDuty') }}</router-link>
        <router-link :to="{ name: 'admin-ops-audit' }" class="btn ghost">{{ t('admin.yuangonOnboard.backOps') }}</router-link>
      </div>
    </header>

    <p class="yo-lead">{{ t('admin.yuangonOnboard.lead') }}</p>
    <p v-if="error" class="yo-err">{{ error }}</p>

    <section v-if="status" class="yo-card">
      <p><strong>{{ t('admin.yuangonOnboard.repo') }}</strong> <code class="yo-code">{{ status.repo_root }}</code></p>
      <p>
        {{ t('admin.yuangonOnboard.counts', { y: status.yuangon_employee_count ?? 0, c: status.catalog_employee_pack_count ?? 0 }) }}
      </p>
      <p v-if="(status.missing_in_catalog?.length ?? 0) > 0" class="yo-warn">
        {{ t('admin.yuangonOnboard.missing') }}
        <code class="yo-code">{{ (status.missing_in_catalog || []).join(', ') }}</code>
      </p>
      <p v-else class="muted">{{ t('admin.yuangonOnboard.noMissing') }}</p>
      <ul v-if="(status.parse_errors?.length ?? 0) > 0" class="yo-parse-err">
        <li v-for="(e, i) in status.parse_errors" :key="'pe' + i">{{ e }}</li>
      </ul>
    </section>

    <section class="yo-card">
      <label class="yo-field">
        <span>{{ t('admin.yuangonOnboard.pkgIds') }}</span>
        <input v-model="pkgIds" type="text" class="yo-input" :placeholder="t('admin.yuangonOnboard.pkgIdsPh')" />
      </label>
      <p class="muted yo-hint">{{ t('admin.yuangonOnboard.pkgIdsHint') }}</p>
      <div class="yo-run-btns">
        <button type="button" class="btn ghost" :disabled="dryRunBusy || runBusy" @click="runScript(true)">
          {{ dryRunBusy ? '…' : t('admin.yuangonOnboard.dryRun') }}
        </button>
        <button type="button" class="btn primary" :disabled="dryRunBusy || runBusy" @click="runScript(false)">
          {{ runBusy ? '…' : t('admin.yuangonOnboard.run') }}
        </button>
      </div>
      <p class="muted yo-hint">{{ t('admin.yuangonOnboard.forceHint') }}</p>
    </section>

    <section v-if="lastRun" class="yo-card yo-log">
      <p>
        <strong>{{ t('admin.yuangonOnboard.lastRun') }}</strong>
        <span :class="lastRun.ok ? 'ok' : 'bad'">{{ lastRun.ok ? 'OK' : 'FAIL' }}</span>
        <span v-if="lastRun.exit_code != null" class="muted">exit {{ lastRun.exit_code }}</span>
      </p>
      <pre v-if="lastRun.stdout_tail" class="yo-pre">{{ lastRun.stdout_tail }}</pre>
      <pre v-if="lastRun.stderr_tail" class="yo-pre yo-stderr">{{ lastRun.stderr_tail }}</pre>
    </section>
  </div>
</template>

<style scoped>
.yo-page {
  padding: 1rem 1.25rem;
  max-width: 960px;
  margin: 0 auto;
}
.yo-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.yo-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.yo-lead {
  color: var(--color-text-muted, #666);
  margin-bottom: 1rem;
}
.yo-err {
  color: #c44;
  margin-bottom: 0.75rem;
}
.yo-card {
  background: var(--color-surface-raised, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--color-border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}
.yo-code {
  font-size: 0.85em;
  word-break: break-all;
}
.yo-warn {
  color: #b85;
}
.yo-parse-err {
  margin: 0.5rem 0 0 1rem;
  font-size: 0.9rem;
  color: #c44;
}
.yo-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-bottom: 0.5rem;
}
.yo-input {
  padding: 0.45rem 0.6rem;
  border-radius: 6px;
  border: 1px solid var(--color-border, #444);
  background: var(--color-bg, #111);
  color: inherit;
  max-width: 100%;
}
.yo-hint {
  font-size: 0.88rem;
  margin-bottom: 0.75rem;
}
.yo-run-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.yo-log .ok {
  color: #6a6;
  margin-left: 0.5rem;
}
.yo-log .bad {
  color: #c66;
  margin-left: 0.5rem;
}
.yo-pre {
  margin-top: 0.5rem;
  padding: 0.75rem;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.35);
  overflow: auto;
  max-height: 320px;
  font-size: 0.8rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.yo-stderr {
  border-top: 1px dashed rgba(255, 255, 255, 0.12);
  margin-top: 0.5rem;
  padding-top: 0.75rem;
}
.yo-denied {
  padding: 2rem;
  text-align: center;
}
.muted {
  opacity: 0.75;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  text-decoration: none;
  border: 1px solid var(--color-border, #555);
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.btn.primary {
  background: var(--color-accent, #3b82f6);
  border-color: transparent;
  color: #fff;
}
.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.06);
}

html[data-workbench-theme='light'] .yo-card{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .yo-input{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .yo-pre{background:rgba(0,0,0,0.04)}
html[data-workbench-theme='light'] .yo-err{color:#dc2626}
html[data-workbench-theme='light'] .yo-warn{color:#d97706}
html[data-workbench-theme='light'] .yo-parse-err{color:#dc2626}
html[data-workbench-theme='light'] .yo-log .ok{color:#059669}
html[data-workbench-theme='light'] .yo-log .bad{color:#dc2626}
html[data-workbench-theme='light'] .yo-stderr{border-color:rgba(0,0,0,0.12)}
html[data-workbench-theme='light'] .btn{border-color:#d1d5db}
html[data-workbench-theme='light'] .btn.primary{background:#3b82f6;color:#fff}
html[data-workbench-theme='light'] .btn.ghost:hover{background:rgba(0,0,0,0.04)}
</style>

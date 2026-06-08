<template>
  <div class="mod-shell">
    <main class="main">
      <div class="hero">
        <div>
          <h1>{{ heroTitle }}</h1>
          <p class="hero-sub">
            <span v-if="primary" class="badge-primary">PRIMARY</span>
            <code class="mod-id">{{ modId }}</code>
            <span v-if="modMeta?.version" class="ver">· v{{ modMeta.version }}</span>
          </p>
        </div>
        <div class="action">
          <button type="button" class="btn btn-ghost" @click="goChat">返回助手</button>
          <button type="button" class="btn" :disabled="pushLoading || !modId" @click="pushToXcagi">
            {{ pushLoading ? '请求中…' : '推送到 XCAGI' }}
          </button>
        </div>
      </div>

      <p v-if="!modsStore.isLoaded && !modsStore.loadError" class="muted">正在加载 Mod 列表…</p>
      <p v-else-if="modsStore.loadError" class="muted text-warn">{{ modsStore.loadError }}</p>
      <p v-else-if="modsStore.isLoaded && !modMeta" class="muted text-warn">
        未找到 id 为 <code>{{ modId }}</code> 的扩展（请确认 manifest 已由后端扫描）。
      </p>

      <div v-if="menu.length" class="grid">
        <router-link
          v-for="item in menu"
          :key="item.id || item.path"
          :to="item.path"
          class="card"
        >
          <span class="card-title">{{ item.label }}</span>
          <span class="card-meta">{{ item.path }}</span>
        </router-link>
      </div>
      <p v-else-if="modMeta" class="muted">该 Mod 未在 manifest 中声明菜单，请从左侧侧栏进入扩展页面。</p>

      <p v-if="pushMessage" class="muted push-msg">{{ pushMessage }}</p>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useModsStore } from '@/stores/mods';
import { apiFetch } from '@/utils/apiBase';

const route = useRoute();
const router = useRouter();
const modsStore = useModsStore();

const modId = computed(() => String(route.params.modId || '').trim());
const modMeta = computed(
  () =>
    modsStore.modsForUi.find((m) => m.id === modId.value) ||
    modsStore.mods.find((m) => m.id === modId.value) ||
    null
);
const primary = computed(() => Boolean(modMeta.value?.primary));
const heroTitle = computed(() => modMeta.value?.name || modId.value || 'Mod');
const menu = computed(() => (Array.isArray(modMeta.value?.menu) ? modMeta.value!.menu! : []));

const pushLoading = ref(false);
const pushMessage = ref('');

function goChat() {
  router.push({ name: 'chat' });
}

async function pushToXcagi() {
  pushMessage.value = '';
  if (!modId.value) return;
  pushLoading.value = true;
  try {
    const res = await apiFetch(`/api/mods/${encodeURIComponent(modId.value)}/publish-to-xcagi`, {
      method: 'POST',
    });
    const j = (await res.json()) as {
      success?: boolean;
      message?: string;
      error?: string;
      data?: {
        message?: string;
        postgresql_summary?: { database_name?: string; host_port?: string };
        database_reachable?: boolean;
      };
    };
    if (j.success && j.data) {
      let line = j.data.message || '请求已处理。';
      const s = j.data.postgresql_summary;
      if (s && (s.database_name || s.host_port)) {
        const tail = [s.database_name, s.host_port].filter(Boolean).join(' @ ');
        if (tail) line += ` 当前进程连接：${tail}。`;
      }
      pushMessage.value = line;
      try {
        window.dispatchEvent(new CustomEvent('xcagi:test-db-status-refresh'));
      } catch {
        /* ignore */
      }
    } else {
      pushMessage.value = j.message || j.error || `请求失败（HTTP ${res.status}）`;
    }
  } catch (e) {
    pushMessage.value = e instanceof Error ? e.message : '网络错误';
  } finally {
    pushLoading.value = false;
  }
}

onMounted(async () => {
  await modsStore.initialize();
});
</script>

<style scoped>
.mod-shell {
  min-height: 100%;
  padding: 24px 20px 40px;
}

.main {
  max-width: 960px;
  margin: 0 auto;
}

.hero {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 28px;
}

.hero h1 {
  margin: 0 0 8px;
  font-size: 1.65rem;
  color: #1f2937;
}

.hero-sub {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  font-size: 0.95rem;
}

.badge-primary {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: #dbeafe;
  color: #1d4ed8;
}

.mod-id {
  font-size: 0.85rem;
}

.ver {
  color: #9ca3af;
}

.action {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #d1d5db;
  background: #fff;
  color: #374151;
  font-size: 0.9rem;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-ghost {
  background: #f9fafb;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.card-title {
  font-weight: 600;
  color: #111827;
}

.card-meta {
  font-size: 0.8rem;
  color: #9ca3af;
}

.muted {
  color: #6b7280;
  font-size: 0.9rem;
  line-height: 1.5;
}

.text-warn {
  color: #b45309;
}

.push-msg {
  margin-top: 16px;
  white-space: pre-wrap;
}
</style>

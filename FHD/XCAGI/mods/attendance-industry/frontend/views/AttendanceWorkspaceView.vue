<template>
  <section class="attendance-workspace" aria-label="考勤工作区">
    <header class="workspace-header">
      <h1>考勤工作区</h1>
      <nav aria-label="考勤工作区功能">
        <router-link
          v-for="item in sections"
          :key="item.section"
          :to="{ name: item.route }"
          :class="{ active: section === item.section }"
          :aria-current="section === item.section ? 'page' : undefined"
          >{{ item.label }}</router-link
        >
      </nav>
    </header>
    <div class="workspace-content">
      <p v-if="customSection && !conversionEnabled" class="workspace-status" :role="access === 'unavailable' ? 'alert' : 'status'">
        {{ access === 'checking' ? '正在核验权限…' : access === 'unavailable' ? '无法核验转换权限，请刷新重试。' : '当前账号未开通考勤表转换定制功能。' }}
      </p>
      <HomeView v-else-if="section === 'convert'" />
      <AttendanceSettingsView v-else-if="section === 'settings'" />
      <AttendanceManagementView v-else :key="section" :section="section" :conversion-enabled="conversionEnabled" />
    </div>
  </section>
</template>

<script setup lang="ts">
  import { computed, ref, watch } from 'vue';
  import { apiFetch } from '@/utils/apiBase';
  import { productReadAccountEpoch } from '@/utils/productReadAccountScope';
  import AttendanceManagementView from './AttendanceManagementView.vue';
  import AttendanceSettingsView from './AttendanceSettingsView.vue';
  import HomeView from './HomeView.vue';

  type ManagementSection = 'departments' | 'personnel' | 'schedules' | 'records';
  type Section = ManagementSection | 'convert' | 'settings';
  type ConversionAccess = 'checking' | 'granted' | 'denied' | 'unavailable';

  const props = withDefaults(defineProps<{ section?: Section }>(), { section: 'personnel' });
  const access = ref<ConversionAccess>('checking');
  const conversionEnabled = computed(() => access.value === 'granted');
  const customSection = computed(() => ['convert', 'settings'].includes(props.section));
  watch([() => props.section, productReadAccountEpoch], async (_, __, onCleanup) => {
    const controller = new AbortController();
    onCleanup(() => controller.abort());
    access.value = 'checking';
    try {
      const response = await apiFetch('/api/mod/attendance-industry/attendance/capabilities', { signal: controller.signal });
      if (!response.ok) {
        if (!controller.signal.aborted) access.value = [401, 403].includes(response.status) ? 'denied' : 'unavailable';
        return;
      }
      const data: unknown = await response.json();
      if (controller.signal.aborted) return;
      const features = data && typeof data === 'object' && 'custom_features' in data ? data.custom_features : undefined;
      access.value = Array.isArray(features) && features.includes('attendance-convert') ? 'granted' : 'denied';
    } catch {
      if (!controller.signal.aborted) access.value = 'unavailable';
    }
  }, { immediate: true, flush: 'sync' });

  const sections = computed(() => [
    { section: 'departments', label: '部门管理', route: 'attendance-industry-departments' },
    { section: 'personnel', label: '人员管理', route: 'attendance-industry-personnel' },
    { section: 'schedules', label: '排班资源', route: 'attendance-industry-schedules' },
    { section: 'records', label: '考勤记录', route: 'attendance-industry-records' },
    ...(conversionEnabled.value ? [
      { section: 'convert', label: '考勤表转换（定制）', route: 'attendance-industry-home' },
      { section: 'settings', label: '转换规则（定制）', route: 'attendance-industry-settings' },
    ] : []),
  ]);
</script>

<style scoped>
  .attendance-workspace {
    --workspace-gutter: clamp(16px, 2.5vw, 28px);
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    height: 100%;
    overflow: hidden;
  }
  .workspace-header {
    flex-shrink: 0;
    padding: 18px var(--workspace-gutter) 0;
    border-bottom: 1px solid var(--xc-color-border);
  }
  .workspace-header h1 {
    margin: 0 0 10px;
    color: var(--xc-color-text);
    font-size: 21px;
    line-height: 1.35;
  }
  .workspace-header nav {
    display: flex;
    gap: 18px;
    overflow-x: auto;
  }
  .workspace-header a {
    flex-shrink: 0;
    padding: 10px 2px;
    color: var(--xc-color-text-secondary);
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    border-bottom: 2px solid transparent;
  }
  .workspace-header a:is(:hover, .active) { color: var(--xc-color-primary); }
  .workspace-header a.active { border-color: currentColor; }
  .workspace-header a:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: -3px; }
  .workspace-status { margin: 16px var(--workspace-gutter); color: var(--xc-color-text-secondary); }
  .workspace-content {
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: auto;
  }
  .workspace-content > :deep(.page-view) {
    display: block;
    height: auto;
    min-height: 100%;
    overflow: visible;
    box-sizing: border-box;
  }
</style>

<template>
  <section class="attendance-workspace" aria-label="考勤工作区">
    <header class="workspace-header">
      <h1>考勤工作区</h1>
      <p>主系统统一维护部门、人员、排班资源和考勤记录。</p>
      <nav aria-label="考勤工作区功能">
        <router-link
          v-for="item in sections"
          :key="item.section"
          :to="item.path || { name: item.route }"
          :class="{ active: section === item.section }"
          :aria-current="section === item.section ? 'page' : undefined"
          >{{ item.label }}</router-link
        >
      </nav>
    </header>
    <div class="workspace-content">
      <p v-if="customSection && !conversionEnabled" role="status">
        {{ checking ? '正在核验定制功能权限…' : '当前账号未开通考勤表转换定制功能。' }}
      </p>
      <router-link v-else-if="customSection" to="/mod/sunbird-attendance-custom/convert">打开考勤定制 Mod</router-link>
      <AttendanceManagementView v-else :key="section" :section="section" :conversion-enabled="conversionEnabled" />
    </div>
  </section>
</template>

<script setup>
  import { computed, ref, watch } from 'vue';
  import { apiFetch } from '@/utils/apiBase';
  import AttendanceManagementView from './AttendanceManagementView.vue';

  const props = defineProps({ section: { type: String, default: 'personnel' } });
  const conversionEnabled = ref(false);
  const checking = ref(true);
  const customSection = computed(() => ['convert', 'settings'].includes(props.section));
  let generation = 0;
  watch(() => props.section, async () => {
    const current = ++generation;
    conversionEnabled.value = false;
    checking.value = true;
    try {
      const response = await apiFetch('/api/mod/attendance-industry/attendance/capabilities');
      const data = response.ok ? await response.json() : {};
      if (current === generation) {
        conversionEnabled.value = data.custom_features?.includes('attendance-convert') === true;
      }
    } catch {
      // 权限接口失败时不挂载定制页面；共享管理功能仍可使用。
    } finally {
      if (current === generation) checking.value = false;
    }
  }, { immediate: true });

  const sections = computed(() => [
    { section: 'departments', label: '部门管理', route: 'attendance-industry-departments' },
    { section: 'personnel', label: '人员管理', route: 'attendance-industry-personnel' },
    { section: 'schedules', label: '排班资源', route: 'attendance-industry-schedules' },
    { section: 'records', label: '考勤记录', route: 'attendance-industry-records' },
    ...(conversionEnabled.value ? [
      { section: 'convert', label: '考勤定制 Mod', path: '/mod/sunbird-attendance-custom/convert' },
    ] : []),
  ]);
</script>

<style scoped>
  .attendance-workspace {
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
    padding: 20px 28px 0;
    border-bottom: 1px solid var(--border-color, #e5e7eb);
  }
  .workspace-header h1 {
    margin: 0;
    font-size: 22px;
  }
  .workspace-header p {
    margin: 8px 0 16px;
    color: var(--text-secondary, #6b7280);
    font-size: 13px;
  }
  .workspace-header nav {
    display: flex;
    gap: 20px;
    overflow-x: auto;
  }
  .workspace-header a {
    flex-shrink: 0;
    padding: 10px 0 12px;
    color: var(--text-secondary, #6b7280);
    text-decoration: none;
    border-bottom: 2px solid transparent;
  }
  .workspace-header a.active {
    color: var(--primary-color, #2563eb);
    border-color: currentColor;
    font-weight: 600;
  }
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

<template>
  <section class="attendance-workspace" aria-label="考勤工作区">
    <header class="workspace-header">
      <h1>考勤工作区</h1>
      <p>统一维护部门、人员、排班和考勤，转换使用同一份人员名单。</p>
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
      <HomeView v-if="section === 'convert'" />
      <AttendanceSettingsView v-else-if="section === 'settings'" />
      <AttendanceManagementView v-else :key="section" :section="section" />
    </div>
  </section>
</template>

<script setup>
  import AttendanceManagementView from './AttendanceManagementView.vue';
  import AttendanceSettingsView from './AttendanceSettingsView.vue';
  import HomeView from './HomeView.vue';

  defineProps({ section: { type: String, default: 'personnel' } });

  const sections = [
    { section: 'departments', label: '部门管理', route: 'attendance-industry-departments' },
    { section: 'personnel', label: '人员管理', route: 'attendance-industry-personnel' },
    { section: 'schedules', label: '排班资源', route: 'attendance-industry-schedules' },
    { section: 'records', label: '考勤记录', route: 'attendance-industry-records' },
    { section: 'convert', label: '考勤表转换', route: 'attendance-industry-home' },
    { section: 'settings', label: '考勤设置', route: 'attendance-industry-settings' },
  ];
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

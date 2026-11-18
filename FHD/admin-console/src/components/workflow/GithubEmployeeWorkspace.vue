<script setup lang="ts">
  import 'element-plus/dist/index.css';
  import { computed, onMounted, ref } from 'vue';
  import { useRouter } from 'vue-router';
  import { ElAlert, ElButton, ElEmpty, ElInput, ElTabs, ElTabPane, ElTag } from 'element-plus';
  import api, { ApiError } from '@/api/core';
  import LocalHistory from '@host/components/employeeWorkspace/EmployeeWorkspaceLoopConsole.vue';
  import TicketGithubPanel from './TicketGithubPanel.vue';
  defineProps<{ initialPane?: string }>();
  type Item = {
    ticket_id: number;
    title: string;
    ticket_status: string;
    issue: { number?: number; status: string };
  };
  const router = useRouter(),
    pane = ref('github'),
    items = ref<Item[]>([]),
    selected = ref<number>(),
    search = ref(''),
    loading = ref(false),
    error = ref('');
  const repository = ref(''),
    configured = ref(false);
  const visible = computed(() =>
    items.value.filter((i) =>
      `${i.title} ${i.issue.number || ''}`.toLowerCase().includes(search.value.toLowerCase())
    )
  );
  const current = computed(() => items.value.find((i) => i.ticket_id === selected.value));
  async function load() {
    loading.value = true;
    try {
      const data = (await api.get('/api/xcmax/admin/customer-service/github/workspace')) as {
        items: Item[];
        repository: string;
        configured: boolean;
        readback_error?: string;
      };
      if (!Array.isArray(data.items)) throw new Error('GitHub 工作空间返回无效，请刷新');
      items.value = data.items;
      repository.value = data.repository;
      configured.value = data.configured;
      error.value = data.readback_error || '';
      if (!items.value.some((i) => i.ticket_id === selected.value))
        selected.value = items.value[0]?.ticket_id;
    } catch (e) {
      error.value =
        e instanceof ApiError && e.status === 404
          ? '当前服务版本未包含 GitHub 工作空间接口，请升级服务端后再试'
          : e instanceof Error
            ? e.message
            : 'GitHub 工作空间暂不可用';
    } finally {
      loading.value = false;
    }
  }
  onMounted(load);
</script>

<template>
  <section class="github-space" aria-label="员工云端工作空间" data-page-ready="true">
    <header class="github-space-head">
      <div>
        <h2>员工工作空间</h2>
        <span>GitHub Actions · AI 员工 · Para</span>
      </div>
      <div>
        <el-button :loading="loading" @click="load">刷新</el-button
        ><el-button type="primary" @click="router.push({ name: 'customer-service-tickets' })"
          >从工单发起</el-button
        >
      </div>
    </header>
    <el-tabs v-model="pane" class="github-space-tabs">
      <el-tab-pane label="GitHub 工作空间" name="github">
        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <el-alert
          v-else-if="!configured && !loading"
          title="云端连接尚未配置"
          type="warning"
          :closable="false"
        />
        <div class="github-space-layout" :class="{ selected: current }">
          <aside>
            <el-input
              v-model="search"
              clearable
              placeholder="搜索工单或 Issue"
              aria-label="搜索 GitHub 任务"
            />
            <div class="github-space-list">
              <button
                v-for="item in visible"
                :key="item.ticket_id"
                :aria-current="selected === item.ticket_id ? 'true' : undefined"
                @click="selected = item.ticket_id"
              >
                <strong>{{ item.title }}</strong
                ><span
                  ><el-tag size="small">{{
                    item.issue.number ? `#${item.issue.number}` : '待核对'
                  }}</el-tag>
                  工单 #{{ item.ticket_id }}</span
                >
              </button>
              <el-empty
                v-if="!visible.length"
                :description="
                  loading ? '正在读取' : error ? '尚未取得工单记录' : '暂无关联的 Issue'
                "
                :image-size="60"
              />
            </div>
            <small v-if="!error">{{ items.length }} 个关联工单</small>
          </aside>
          <main v-if="current">
            <div class="github-space-head">
              <el-button class="github-back" text @click="selected = undefined">返回列表</el-button>
              <h3>{{ current.title }}</h3>
              <el-button
                @click="
                  router.push({
                    name: 'customer-service-ticket-detail',
                    params: { ticketId: current.ticket_id },
                  })
                "
                >原工单</el-button
              >
            </div>
            <TicketGithubPanel
              :ticket-id="current.ticket_id"
              :ticket-status="current.ticket_status"
              @updated="load"
            />
          </main>
          <main v-else>
            <el-empty description="从工单创建 Issue 后，在这里跟进云端修复" :image-size="90" />
          </main>
        </div>
      </el-tab-pane>
      <el-tab-pane label="原执行记录" name="history" lazy
        ><LocalHistory archive-only
      /></el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
  .github-space {
    height: calc(100dvh - 130px);
    min-height: 380px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .github-space-head {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
  }
  .github-space-head h2,
  .github-space-head h3 {
    margin: 0;
    font-size: 18px;
  }
  .github-space-head h3 {
    font-size: 15px;
  }
  .github-space-head span {
    font-size: 12px;
    color: #64748b;
  }
  .github-space-tabs {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .github-space-tabs:deep(.el-tabs__content) {
    flex: 1;
    min-height: 0;
  }
  .github-space-tabs:deep(.el-tab-pane) {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .github-space-layout {
    display: grid;
    grid-template-columns: 290px minmax(0, 1fr);
    flex: 1;
    min-height: 0;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    background: #fff;
    overflow: hidden;
  }
  .github-space-layout aside {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-right: 1px solid #e2e8f0;
    min-height: 0;
  }
  .github-space-list {
    overflow: auto;
    flex: 1;
    min-height: 0;
  }
  .github-space-list button {
    display: grid;
    gap: 10px;
    width: 100%;
    text-align: left;
    border: 0;
    border-radius: 8px;
    background: transparent;
    padding: 14px;
    cursor: pointer;
  }
  .github-space-list button[aria-current='true'] {
    background: #edf2ff;
    color: #3156a6;
  }
  .github-space-list strong {
    font-size: 14px;
    line-height: 1.5;
  }
  .github-space-list span,
  .github-space-layout small {
    font-size: 12px;
    color: #64748b;
  }
  .github-space-layout main {
    padding: 22px;
    overflow: auto;
    min-width: 0;
  }
  .github-space-layout main > .github-space-head {
    margin-bottom: 24px;
  }
  .github-back {
    display: none;
  }
  @media (max-width: 850px) {
    .github-space-layout {
      grid-template-columns: 240px minmax(0, 1fr);
    }
  }
  @media (max-width: 650px) {
    .github-space-layout {
      grid-template-columns: 1fr;
    }
    .github-space-layout.selected aside {
      display: none;
    }
    .github-space-layout:not(.selected) main {
      display: none;
    }
    .github-back {
      display: inline-flex;
    }
    .github-space-head {
      flex-wrap: wrap;
    }
  }
</style>

<template>
  <main class="kellai-module" aria-label="客来来">
    <div class="kellai-panel">
      <ElTabs v-model="workspace" class="kellai-tabs" @tab-change="persistWorkspace">
        <ElTabPane label="连接与账号" name="connections">
          <div class="kellai-columns" data-tutorial-id="kellai-connections">
            <section aria-labelledby="kellai-auth-title">
              <h2 id="kellai-auth-title">连接授权</h2>
              <p v-if="binding.connection?.authorized_by?.display_name">客来来授权人：{{ binding.connection.authorized_by.display_name }}</p>
              <div v-if="scopes.length" class="kellai-controls"><ElTag v-for="scope in scopes" :key="scope" type="info" effect="plain" size="small">{{ scopeLabel(scope) }}</ElTag></div>
              <div class="kellai-grant">
                <div>
                  <label for="kellai-request-send">申请人工发送权限</label>
                  <p id="kellai-send-hint" class="kellai-muted">需在客来来确认后生效。</p>
                </div>
                <ElSwitch id="kellai-request-send" v-model="requestSend" aria-label="申请人工发送权限" aria-describedby="kellai-send-hint" :disabled="busy" />
              </div>
              <div class="kellai-controls">
                <ElButton type="primary" :loading="busy" @click="authorize">{{ binding.state === 'connected' ? '更新授权' : '连接客来来' }}</ElButton>
                <ElButton text @click="store.handleOpenKellai">客来来设置</ElButton>
                <ElButton v-if="binding.state === 'connected'" type="danger" text :disabled="busy" @click="store.disconnect">解除绑定</ElButton>
              </div>
              <p v-if="binding.pending" class="kellai-muted" role="status">等待客来来确认，当前权限仍有效。</p>
            </section>
            <section aria-labelledby="kellai-channels-title">
              <h2 id="kellai-channels-title">渠道状态</h2>
              <ElAlert v-if="channelError" :title="channelError" type="warning" :closable="false" />
              <p v-else-if="busy && !channels.length" class="kellai-muted" role="status">正在读取渠道…</p>
              <p v-else-if="binding.state !== 'connected'" class="kellai-muted">连接后可查看渠道。</p>
              <p v-else-if="!scopes.includes('channels.read')" class="kellai-muted">未授权读取渠道。</p>
              <p v-else-if="!channels.length" class="kellai-muted">暂无渠道，可在客来来设置中添加。</p>
              <div v-for="channel in channels" :key="channel.connection_id || channel.type" class="kellai-channel">
                <div class="kellai-channel__heading"><strong>{{ channel.name }}</strong><ElTag :type="channel.connected && channel.enabled ? 'success' : 'info'" size="small">{{ !channel.enabled ? '未启用' : channel.connected ? '已连接' : '未连接' }}</ElTag></div>
                <div class="kellai-controls"><ElTag v-for="capability in capabilityLabels(channel)" :key="capability" type="info" effect="plain" size="small">{{ capability }}</ElTag></div>
                <p class="kellai-muted">{{ channel.capabilities.reason || receiveLabel(channel.capabilities.receive_mode) }}</p>
                <small>{{ channel.connection_id }}</small>
              </div>
            </section>
          </div>
        </ElTabPane>
        <ElTabPane label="消息中心" name="messages" lazy>
          <KellaiCustomerInbox embedded />
        </ElTabPane>
        <ElTabPane label="联系人" name="contacts" lazy>
          <ElInput v-model="contactSearch" class="kellai-contact-search" placeholder="搜索客户名称或渠道" clearable aria-label="搜索联系人" />
          <ElTable :data="filteredCustomers" :empty-text="contactSearch.trim() ? '没有匹配的联系人' : '暂无已授权联系人'">
            <ElTableColumn prop="display_name" label="客户" min-width="150" />
            <ElTableColumn label="阶段" min-width="100"><template #default="{ row }">{{ row.stage_label || row.stage || '未分阶段' }}</template></ElTableColumn>
            <ElTableColumn label="来源渠道" min-width="160"><template #default="{ row }">{{ row.channel_sources?.join('、') || '未标记' }}</template></ElTableColumn>
            <ElTableColumn prop="last_message_preview" label="最近消息" min-width="220" show-overflow-tooltip />
            <ElTableColumn label="操作" width="100"><template #default="{ row }"><ElButton link type="primary" @click="openConversation(row.customer_id)">查看会话</ElButton></template></ElTableColumn>
          </ElTable>
        </ElTabPane>
        <ElTabPane label="数据接入" name="data" lazy>
          <LocalFileAccessCard />
          <section class="kellai-data">
            <h2>企业数据接入</h2>
            <ElButton type="primary" @click="router.push({ name: 'business-docking' })">打开数据对接中心</ElButton>
          </section>
        </ElTabPane>
        <ElTabPane label="自动化" name="automation" lazy>
          <div class="kellai-columns">
            <section>
              <h2>客户跟进</h2>
              <p class="kellai-muted">{{ activeCustomer?.display_name || '尚未选择客户' }} · 待跟进 {{ followUpMetrics?.open || 0 }} 项</p>
              <ElButton type="primary" @click="setWorkspace('messages')">打开消息中心</ElButton>
            </section>
            <section>
              <h2>自动回复与定时任务</h2>
              <ElButton text type="primary" @click="store.handleOpenKellai">在客来来管理</ElButton>
            </section>
          </div>
        </ElTabPane>
      </ElTabs>
      <div class="kellai-status">
        <span class="kellai-status__label" :class="{ 'is-connected': binding.state === 'connected' }" role="status">{{ statusLabel }}</span>
        <ElButton text :loading="busy" @click="store.refreshAll">刷新</ElButton>
      </div>
      <ElAlert v-if="error && workspace !== 'messages'" class="kellai-error" :title="error" type="error" :closable="false" show-icon />
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { ElAlert, ElButton, ElInput, ElSwitch, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
import type { KellaiChannel } from '@/api/kellaiBinding'
import KellaiCustomerInbox from '@/components/im/KellaiCustomerInbox.vue'
import LocalFileAccessCard from '@/components/LocalFileAccessCard.vue'
import { KELLAI_READ_SCOPES, useKellaiStore } from '@/stores/kellai'

const store = useKellaiStore()
const { binding, channels, customers, scopes, busy, error, channelError, statusLabel, activeCustomer, followUpMetrics } = storeToRefs(store)
const router = useRouter()
const route = useRoute()
const areas = ['connections', 'messages', 'contacts', 'data', 'automation']
function routeWorkspace(): string {
  const { workspace, source } = route.query
  if (typeof workspace === 'string' && areas.includes(workspace)) return workspace
  // Old links selected the optional WeChat source; open the authorized channel workspace instead.
  return source === 'wechat_local_db' ? 'messages' : 'connections'
}
const workspace = ref(routeWorkspace())
const requestSend = ref(false)
const contactSearch = ref('')
const filteredCustomers = computed(() => customers.value.filter(customer => `${customer.display_name} ${customer.channel_sources?.join(' ') || ''}`.toLowerCase().includes(contactSearch.value.trim().toLowerCase())))
watch(routeWorkspace, value => { workspace.value = value })
function persistWorkspace(): void { void router.replace({ query: { ...route.query, workspace: workspace.value }, hash: route.hash }) }
function setWorkspace(value: string): void { workspace.value = value; persistWorkspace() }
async function openConversation(customerId: number): Promise<void> {
  const customer = customers.value.find(item => item.customer_id === customerId)
  if (customer) { setWorkspace('messages'); await store.selectCustomer(customer) }
}
function authorize(): void { void store.startBinding([...KELLAI_READ_SCOPES, 'channels.read', ...(requestSend.value ? ['messages.send'] : [])]) }
function scopeLabel(id: string): string { return binding.value.available_scopes?.find(scope => scope.id === id)?.label || id }
function capabilityLabels(channel: KellaiChannel): string[] {
  const cap = channel.capabilities
  return [cap.send ? '支持发送' : '不支持发送', cap.receive ? '支持接收' : '不支持接收', ...(cap.contacts ? ['读取联系人'] : []), ...(cap.sync ? ['支持同步'] : []), ...(cap.transport ? [`执行方式：${cap.transport}`] : [])]
}
function receiveLabel(mode?: string): string { return ({ webhook: '通过已配置的回调接收消息', polling: '通过轮询接收消息', desktop: '需保持客来来桌面端运行', chatwoot: '通过 Chatwoot 收件箱接入' } as Record<string, string>)[mode || ''] || (mode ? `接收方式：${mode}` : '') }
onMounted(store.attach)
onBeforeUnmount(store.detach)
</script>

<style scoped>
.kellai-module {
  min-width: 0;
  height: 100%;
  overflow: auto;
  padding: clamp(12px, 2.5vw, 28px);
  box-sizing: border-box;
  background: var(--xc-color-page-bg);
  container-type: inline-size;
}

.kellai-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  inline-size: min(100%, 1200px);
  margin-inline: auto;
  border-radius: var(--xc-radius-lg);
  background: var(--xc-color-surface);
  box-shadow: var(--xc-shadow-md);
}

/* Element Plus owns the tab state; its header shares a grid row with refresh. */
.kellai-tabs {
  display: contents;
  --el-tabs-header-height: 48px;
}

.kellai-tabs > :deep(.el-tabs__header) {
  grid-area: 1 / 1;
  min-width: 0;
  margin: 0;
  padding-inline: 18px;
}

.kellai-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.kellai-tabs :deep(.el-tabs__item) { padding-inline: 12px; }

.kellai-tabs > :deep(.el-tabs__content) {
  grid-area: 3 / 1 / 4 / -1;
  min-width: 0;
  padding: 22px;
  border-block-start: 1px solid var(--xc-color-border);
}

.kellai-status, .kellai-controls, .kellai-grant, .kellai-channel__heading, .kellai-data {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kellai-status {
  grid-area: 1 / 2;
  justify-content: flex-end;
  padding-inline: 12px;
  white-space: nowrap;
}

.kellai-status__label {
  color: var(--xc-color-text-secondary);
  font-size: 12px;
}

.kellai-status__label::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-inline-end: 6px;
  border-radius: 50%;
  background: var(--xc-color-muted);
  vertical-align: 0.1em;
}

.kellai-status__label.is-connected::before { background: #15803d; }
.kellai-error { grid-area: 2 / 1 / 3 / -1; border-radius: 0; }

.kellai-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}

.kellai-columns > section + section {
  border-inline-start: 1px solid var(--xc-color-border);
  padding-inline-start: 24px;
}

.kellai-module h2 { margin: 0 0 12px; font-size: 15px; font-weight: 650; }
.kellai-module p { margin: 0 0 12px; line-height: 1.55; }
.kellai-muted, .kellai-module small { color: var(--xc-color-text-secondary); font-size: 13px; overflow-wrap: anywhere; }

.kellai-grant {
  justify-content: space-between;
  margin-block: 12px;
  padding-block: 10px;
  border-block: 1px solid var(--xc-color-border);
}

.kellai-grant p { margin: 4px 0 0; }
.kellai-controls { flex-wrap: wrap; }
.kellai-controls :deep(.el-button + .el-button) { margin-inline-start: 0; }
.kellai-channel { padding-block: 12px; }
.kellai-channel + .kellai-channel { border-block-start: 1px solid var(--xc-color-border); }
.kellai-channel__heading { justify-content: space-between; margin-block-end: 8px; }
.kellai-channel p { margin-block: 8px 2px; }
.kellai-contact-search { max-width: 320px; margin-block-end: 12px; }

.kellai-data {
  justify-content: space-between;
  flex-wrap: wrap;
  margin-block-start: 16px;
  padding-block-start: 16px;
  border-block-start: 1px solid var(--xc-color-border);
}

.kellai-data h2 { margin: 0; }

@container (max-width: 640px) {
  .kellai-status { grid-area: 1 / 1 / 2 / -1; padding-block-start: 4px; }
  .kellai-tabs > :deep(.el-tabs__header) { grid-area: 2 / 1 / 3 / -1; padding-inline: 10px; }
  .kellai-error { grid-row: 3; }
  .kellai-tabs > :deep(.el-tabs__content) { grid-row: 4; padding: 14px; }
  .kellai-columns { grid-template-columns: 1fr; gap: 16px; }
  .kellai-columns > section + section {
    border-inline-start: 0;
    padding-inline-start: 0;
    border-block-start: 1px solid var(--xc-color-border);
    padding-block-start: 16px;
  }
}
</style>

<template>
  <section class="kellai-module">
    <header class="kellai-module__header">
      <h1>智能生态 / 客来来</h1>
      <div><ElTag :type="binding.state === 'connected' ? 'success' : 'info'">{{ statusLabel }}</ElTag><ElButton :loading="busy" @click="store.refreshAll">刷新</ElButton></div>
    </header>
    <ElAlert v-if="error && workspace !== 'messages'" :title="error" type="error" :closable="false" show-icon />
    <ElTabs v-model="workspace" class="kellai-module__tabs" @tab-change="persistWorkspace">
      <ElTabPane label="连接与账号" name="connections">
        <div class="kellai-module__grid" data-tutorial-id="kellai-connections">
          <ElCard shadow="never">
            <template #header>本机连接授权</template>
            <p>使用当前 XCMAX 账号连接客来来。客户资料、会话与渠道配置以客来来为准。</p>
            <p v-if="binding.connection?.authorized_by?.display_name">客来来授权人：{{ binding.connection.authorized_by.display_name }}</p>
            <div class="kellai-module__tags"><ElTag v-for="scope in scopes" :key="scope">{{ scopeLabel(scope) }}</ElTag></div>
            <label class="kellai-module__grant"><ElSwitch v-model="requestSend" :disabled="busy" />申请人工发送权限</label>
            <p class="kellai-module__muted">申请后需要在客来来逐项确认；既有只读授权不会自动升级。解除绑定会停止后续读取与发送。</p>
            <div class="kellai-module__actions">
              <ElButton type="primary" :loading="busy" @click="authorize">{{ binding.state === 'connected' ? '更新授权' : '连接客来来' }}</ElButton>
              <ElButton @click="store.handleOpenKellai">打开客来来设置</ElButton>
              <ElButton v-if="binding.state === 'connected'" type="danger" plain :disabled="busy" @click="store.disconnect">解除绑定</ElButton>
            </div>
            <ElAlert v-if="binding.pending" title="等待客来来确认本次授权，当前连接仍保持原权限。" type="info" :closable="false" />
          </ElCard>
          <ElCard shadow="never">
            <template #header>渠道状态</template>
            <ElAlert v-if="channelError" :title="channelError" type="warning" :closable="false" />
            <ElEmpty v-if="!scopes.includes('channels.read')" description="申请渠道读取权限后显示真实连接与能力" :image-size="70" />
            <ElEmpty v-else-if="!channels.length" description="客来来尚未返回渠道，请检查本机服务与配置" :image-size="70" />
            <div v-for="channel in channels" :key="channel.connection_id || channel.type" class="kellai-module__channel">
              <div class="kellai-module__channel-heading"><strong>{{ channel.name }}</strong><ElTag :type="channel.connected ? 'success' : 'info'">{{ !channel.enabled ? '未启用' : channel.connected ? '已连接' : '未连接' }}</ElTag></div>
              <div class="kellai-module__tags"><ElTag v-for="capability in capabilityLabels(channel)" :key="capability">{{ capability }}</ElTag></div>
              <p class="kellai-module__muted">{{ channel.capabilities.reason || receiveLabel(channel.capabilities.receive_mode) }}</p>
              <small>{{ channel.connection_id }}</small>
            </div>
            <p class="kellai-module__muted">各渠道当前使用客来来配置的主账号；在客来来完成密钥、回调与桥接配置。能力以服务端返回为准。</p>
          </ElCard>
        </div>
      </ElTabPane>
      <ElTabPane label="消息中心" name="messages" lazy>
        <KellaiCustomerInbox embedded />
      </ElTabPane>
      <ElTabPane label="联系人" name="contacts" lazy>
        <ElInput v-model="contactSearch" placeholder="搜索已授权客户名称或渠道" clearable aria-label="搜索联系人" />
        <ElTable :data="filteredCustomers" empty-text="暂无已授权客户，请先连接客来来并接入真实渠道">
          <ElTableColumn prop="display_name" label="客户" min-width="150" />
          <ElTableColumn label="阶段" min-width="100"><template #default="{ row }">{{ row.stage_label || row.stage || '未分阶段' }}</template></ElTableColumn>
          <ElTableColumn label="来源渠道" min-width="160"><template #default="{ row }">{{ row.channel_sources?.join('、') || '未标记' }}</template></ElTableColumn>
          <ElTableColumn prop="last_message_preview" label="最近消息" min-width="220" show-overflow-tooltip />
          <ElTableColumn label="操作" width="100"><template #default="{ row }"><ElButton link type="primary" @click="openConversation(row.customer_id)">查看会话</ElButton></template></ElTableColumn>
        </ElTable>
        <p class="kellai-module__muted">展示本次已授权的最近 {{ customers.length }} 位客户；发送时使用会话中的渠道联系人编号。</p>
      </ElTabPane>
      <ElTabPane label="数据接入" name="data" lazy>
        <LocalFileAccessCard />
        <ElCard shadow="never" class="kellai-module__section">
          <template #header>企业数据接入</template>
          <p>数据库、表格与业务系统继续使用现有数据对接中心。文件授权、同步作业和知识检索保留原来的权限与执行记录。</p>
          <ElButton type="primary" @click="router.push({ name: 'business-docking' })">打开数据对接中心</ElButton>
        </ElCard>
      </ElTabPane>
      <ElTabPane label="自动化" name="automation" lazy>
        <div class="kellai-module__grid">
          <ElCard shadow="never">
            <template #header>客户沟通与内部跟进</template>
            <p>消息中心复用当前配置的 AI 模型生成摘要、意图与回复草稿，审批后可以建立跟进任务或填入发送编辑器。</p>
            <p>当前客户：{{ activeCustomer?.display_name || '尚未选择' }} · 待跟进 {{ followUpMetrics?.open || 0 }} 项</p>
            <ElButton @click="setWorkspace('messages')">处理客户消息与跟进</ElButton>
          </ElCard>
          <ElCard shadow="never">
            <template #header>外部消息自动化</template>
            <p>自动回复与定时任务由客来来统一执行。在客来来设置执行条件、渠道和发送策略，并查看运行记录。</p>
            <p class="kellai-module__muted">本模块的人工发送授权不会自动开启任何自动发送规则。</p>
            <ElButton @click="store.handleOpenKellai">打开客来来管理自动化</ElButton>
          </ElCard>
        </div>
      </ElTabPane>
    </ElTabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { ElAlert, ElButton, ElCard, ElEmpty, ElInput, ElSwitch, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
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
.kellai-module { padding: 20px; min-width: 0; height: 100%; overflow: auto; box-sizing: border-box; background: var(--el-bg-color-page, #f8fafc); }
.kellai-module__header { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; }
.kellai-module__header h1 { font-size: 18px; margin: 0; font-weight: 600; }
.kellai-module__header > div, .kellai-module__actions, .kellai-module__tags { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.kellai-module__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.kellai-module p { line-height: 1.65; font-size: 14px; }
.kellai-module__muted, .kellai-module small { color: var(--el-text-color-secondary, #64748b); font-size: 12px; overflow-wrap: anywhere; }
.kellai-module__grant { display: flex; align-items: center; gap: 12px; margin-top: 20px; }
.kellai-module__channel { padding: 14px 0; border-bottom: 1px solid var(--el-border-color-light, #e2e8f0); }
.kellai-module__channel-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.kellai-module__section { margin-top: 16px; }
.kellai-module__actions { margin: 14px 0; }
@media (max-width: 900px) { .kellai-module__grid { grid-template-columns: 1fr; } .kellai-module { padding: 12px; } }
</style>

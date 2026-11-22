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
            <p>客来来只管理外部账号连接与消息通道。业务数据、AI 任务和审批统一由 XCMAX 处理。</p>
            <ElAlert v-if="binding.requires_reauthorization" title="账号工具已升级，请重新确认授权；原发送记录保留用于核对。" type="warning" :closable="false" />
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
            <div v-for="channel in channels" :key="channel.connection_id" class="kellai-module__channel">
              <div class="kellai-module__channel-heading"><strong>{{ channel.name }}</strong><ElTag :type="channel.connected ? 'success' : 'info'">{{ !channel.enabled ? '未启用' : channel.connected ? '已连接' : '未连接' }}</ElTag></div>
              <div class="kellai-module__tags"><ElTag v-for="capability in capabilityLabels(channel)" :key="capability">{{ capability }}</ElTag></div>
              <p class="kellai-module__muted">{{ channel.capabilities.reason || receiveLabel(channel.capabilities.receive_mode) }}</p>
              <small>{{ channel.connection_id }}</small>
            </div>
            <p class="kellai-module__muted">每行对应一个明确的账号连接；收发按连接编号执行。在客来来管理凭据、回调和退出登录。</p>
          </ElCard>
        </div>
      </ElTabPane>
      <ElTabPane label="统一聊天" name="messages" lazy>
        <KellaiCustomerInbox embedded />
      </ElTabPane>
      <ElTabPane label="联系人" name="contacts" lazy>
        <ElInput v-model="contactSearch" placeholder="搜索联系人、账号或渠道" clearable aria-label="搜索联系人" />
        <ElTable :data="filteredContacts" empty-text="暂无联系人映射，请先连接客来来并接入真实渠道">
          <ElTableColumn prop="contact_name" label="联系人" min-width="150" />
          <ElTableColumn prop="channel_type" label="渠道" min-width="100" />
          <ElTableColumn prop="connection_id" label="账号连接" min-width="180" show-overflow-tooltip />
          <ElTableColumn prop="contact_id" label="外部联系人编号" min-width="180" show-overflow-tooltip />
          <ElTableColumn label="操作" width="100"><template #default="{ row }"><ElButton link type="primary" @click="openConversation(row)">查看会话</ElButton></template></ElTableColumn>
        </ElTable>
        <p class="kellai-module__muted">展示 {{ contacts.length }} 条账号与联系人映射。客户档案、销售阶段和跟进任务由 XCMAX 业务模块管理。</p>
      </ElTabPane>
    </ElTabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { ElAlert, ElButton, ElCard, ElEmpty, ElInput, ElSwitch, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
import type { KellaiChannel, KellaiContact } from '@/api/kellaiBinding'
import KellaiCustomerInbox from '@/components/im/KellaiCustomerInbox.vue'
import { KELLAI_READ_SCOPES, useKellaiStore } from '@/stores/kellai'

const store = useKellaiStore()
const { binding, channels, contacts, scopes, busy, error, channelError, statusLabel } = storeToRefs(store)
const router = useRouter()
const route = useRoute()
const areas = ['connections', 'messages', 'contacts']
function routeWorkspace(): string {
  const { workspace, source } = route.query
  if (typeof workspace === 'string' && areas.includes(workspace)) return workspace
  // Old links selected the optional WeChat source; open the authorized channel workspace instead.
  return source === 'wechat_local_db' ? 'messages' : 'connections'
}
const workspace = ref(routeWorkspace())
const requestSend = ref(false)
const contactSearch = ref('')
const filteredContacts = computed(() => contacts.value.filter(contact => `${contact.contact_name} ${contact.channel_type} ${contact.connection_id}`.toLowerCase().includes(contactSearch.value.trim().toLowerCase())))
watch(routeWorkspace, value => { workspace.value = value })
function persistWorkspace(): void { void router.replace({ query: { ...route.query, workspace: workspace.value }, hash: route.hash }) }
function setWorkspace(value: string): void { workspace.value = value; persistWorkspace() }
async function openConversation(contact: KellaiContact): Promise<void> {
  setWorkspace('messages')
  await store.selectContact(contact)
}
function authorize(): void { void store.startBinding([...KELLAI_READ_SCOPES, ...(requestSend.value ? ['messages.send'] : [])]) }
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

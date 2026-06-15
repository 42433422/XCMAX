<template>
  <div class="page-view" id="view-data-sources">
    <div class="page-content">
      <div class="page-header">
        <h2>数据来源</h2>
      </div>

      <div class="card">
        <div class="card-header">私人数据库读取助手</div>
        <p class="muted data-source-note">
          这里管理 AI 员工可读取的数据来源。市场展示为通用员工；启用具体适配器前，需要用户在本页明确选择并授权。
        </p>
        <div class="data-source-status">
          <span>员工状态：{{ statusText }}</span>
          <span>当前来源：{{ selectedSourceLabel }}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-header">选择数据来源</div>
        <div v-if="sources.length === 0" class="empty-state">暂无可用数据来源</div>
        <div v-else>
          <template v-for="(group, idx) in groupedSources" :key="idx">
            <h4 class="data-source-group-title">{{ group.label }}</h4>
            <div class="data-source-grid">
              <button
                v-for="source in group.items"
                :key="source.id"
                type="button"
                class="data-source-card"
                :class="{ active: selectedSourceId === source.id, 'is-planned': source.status !== 'available' }"
                @click="onSourceCardClick(source)"
              >
                <div class="data-source-card-badge" v-if="source.status !== 'available'">规划中</div>
                <div style="display:flex; align-items:center; gap:10px;">
                  <div
                    class="data-source-card-icon-slot"
                    :class="'is-' + (source.category || 'generic')"
                    aria-hidden="true"
                  >
                    <span
                      v-if="renderDataSourceIcon(source.icon || source.id)"
                      class="data-source-card-icon-inline"
                      v-html="renderDataSourceIcon(source.icon || source.id)"
                    />
                    <i
                      v-else
                      class="fa fa-database data-source-card-icon data-source-card-icon--fallback"
                    />
                  </div>
                  <div>
                    <div class="data-source-card-title">{{ source.label }}</div>
                    <div class="data-source-card-desc">{{ source.description || '无说明' }}</div>
                    <div class="data-source-card-meta">
                      <template v-if="source.id === WECHAT_SOURCE_ID && source.status === 'available'">
                        <span>{{ wechatAuthorized ? (wechatPollEnabled ? '已授权 · 轮询中' : '已授权') : '可用' }}</span>
                        <span v-if="!wechatAuthorized"> · 打开下方开关启用</span>
                      </template>
                      <template v-else>
                        <span>{{ source.status === 'available' ? '可用' : '规划中' }}</span>
                        <span v-if="source.requires_authorization"> · 需要授权</span>
                      </template>
                    </div>
                  </div>
                </div>
                <div
                  v-if="source.id === WECHAT_SOURCE_ID && source.status === 'available'"
                  class="data-source-card-switch-row"
                  @click.stop
                >
                  <label class="data-source-switch-label" title="启用后读取本机已解密的微信联系人与消息">
                    <span class="data-source-switch-wrap">
                      <input
                        type="checkbox"
                        :checked="wechatAuthorized"
                        :disabled="wechatSetupRunning"
                        @change="onWechatAuthToggle"
                      />
                      <span class="data-source-switch-slider" aria-hidden="true" />
                    </span>
                    <span class="data-source-switch-text">{{ wechatAuthorized ? '已启用' : '启用读取' }}</span>
                  </label>
                </div>
              </button>
            </div>
          </template>
        </div>
        <template v-if="!isWechatSourceSelected">
          <div class="form-group data-source-actions">
            <button class="btn btn-primary" type="button" :disabled="loading || isSelectedSourcePlanned" @click="refreshContacts">
              刷新联系人缓存
            </button>
            <button class="btn btn-secondary" type="button" :disabled="loading || isSelectedSourcePlanned" @click="refreshMessages">
              检查消息缓存
            </button>
          </div>
          <div v-if="isSelectedSourcePlanned" class="muted" style="margin-top:8px">该数据源还在规划中，暂时只有微信适配器可执行操作。</div>
        </template>
        <div v-if="isWechatSourceSelected" class="card data-source-wechat-controls">
          <div class="card-header">微信本地库</div>
          <div class="data-source-wechat-control-row">
            <label class="data-source-switch-label">
              <span class="data-source-switch-wrap">
                <input
                  type="checkbox"
                  :checked="wechatAuthorized"
                  :disabled="wechatSetupRunning"
                  @change="onWechatAuthToggle"
                />
                <span class="data-source-switch-slider" aria-hidden="true" />
              </span>
              启用本地库读取
            </label>
            <span class="muted data-source-wechat-control-hint">
              {{
                wechatAuthorized
                  ? '已授权：可读星标联系人、搜索、聊天记录与桌面发送'
                  : '开启后将检测本机微信目录并导入联系人（需同意授权说明）'
              }}
            </span>
            <button
              v-if="wechatAuthorized"
              class="btn btn-secondary btn-sm"
              type="button"
              :disabled="wechatSetupRunning || wechatContactSyncing"
              @click="syncWechatContacts"
            >
              {{ wechatContactSyncing ? '同步中…' : '同步联系人' }}
            </button>
          </div>
          <div v-if="wechatAuthorized" class="data-source-wechat-control-row data-source-msg-sync-row">
            <button
              class="btn btn-primary btn-sm"
              type="button"
              :disabled="wechatMsgSyncing || wechatSetupRunning"
              @click="runWechatChatHistoryWithKeyScan"
            >
              {{ wechatMsgSyncing ? '同步中…' : '扫密钥并同步聊天' }}
            </button>
            <span class="muted data-source-msg-sync-hint">
              保持微信登录：先强制扫描密钥、解密本机 message_0.db，再写入群聊消息
            </span>
            <span v-if="wechatMessageSyncLastRunAt" class="muted data-source-poll-last">
              聊天记录上次同步：{{ wechatMessageSyncLastRunAt }}
            </span>
            <span v-if="wechatMessageSyncSummary" class="data-source-msg-sync-result">
              {{ wechatMessageSyncSummary }}
            </span>
          </div>
          <div v-if="wechatAuthorized" class="data-source-wechat-control-row data-source-poll-row">
            <label class="data-source-switch-label">
              <span class="data-source-switch-wrap">
                <input v-model="wechatPollEnabled" type="checkbox" @change="onWechatPollToggle" />
                <span class="data-source-switch-slider" aria-hidden="true" />
              </span>
              定时同步（联系人+聊天记录）
            </label>
            <label class="data-source-poll-interval">
              间隔
              <select v-model="wechatPollIntervalSec" :disabled="!wechatPollEnabled" @change="onWechatPollIntervalChange">
                <option :value="30">30 秒</option>
                <option :value="60">1 分钟</option>
                <option :value="300">5 分钟</option>
                <option :value="600">10 分钟</option>
              </select>
            </label>
            <span v-if="wechatPollEnabled && wechatPollLastRunAt" class="muted data-source-poll-last">
              上次同步：{{ wechatPollLastRunAt }}
            </span>
          </div>
        </div>
        <div class="muted" style="margin-top:8px; font-size:12px">图标为本应用自制单色字形，仅用于功能区分，不代表对应品牌的官方授权。</div>
      </div>

      <div
        v-if="isWechatSourceSelected && wechatAuthorized && wechatImportNextHint"
        class="card data-source-wechat-next-hint"
        role="status"
      >
        <p>{{ wechatImportNextHint }}</p>
        <button type="button" class="btn btn-primary btn-sm" @click="goWechatBindEnterprise">
          去 Mod 管理绑定群聊
        </button>
        <button type="button" class="btn btn-secondary btn-sm" @click="wechatImportNextHint = ''">
          知道了
        </button>
      </div>

      <WechatContactsPanel v-if="isWechatSourceSelected && wechatAuthorized" ref="wechatPanelRef" />

      <div class="modal" :class="{ active: wechatConsentOpen }">
        <div class="modal-content data-source-modal data-source-wechat-consent">
          <div class="modal-header">授权读取微信本地数据库</div>
          <div class="data-source-consent-body">
            <p>即将在本机读取<strong>已授权、已解密</strong>的微信联系人及消息缓存，用于星标、搜索与 AI 上下文。不会上传云端。</p>
            <ul>
              <li>将自动检测本机微信 <code>db_storage</code> 并写入 <code>wechat-decrypt/config.json</code></li>
              <li>强制从运行中的微信扫描解密密钥（macOS 若失败需在终端用 sudo 运行扫描器）</li>
              <li>解密 message_0.db 并同步群聊聊天记录到应用库</li>
              <li>导入联系人到应用库</li>
              <li>完成后可开启定时轮询，持续同步本地库变更</li>
            </ul>
          </div>
          <div class="modal-actions">
            <button class="btn btn-secondary" type="button" :disabled="wechatSetupRunning" @click="wechatConsentOpen = false">取消</button>
            <button class="btn btn-primary" type="button" :disabled="wechatSetupRunning" @click="onWechatConsentAgree">同意并开始读取</button>
          </div>
        </div>
      </div>

      <div class="modal" :class="{ active: wechatProgressOpen }">
        <div class="modal-content data-source-modal data-source-wechat-progress">
          <div class="modal-header">正在读取本地微信数据库</div>
          <div class="data-source-progress-body">
            <div
              v-for="step in wechatProgressSteps"
              :key="step.id"
              class="data-source-progress-step"
              :class="'is-' + step.state"
            >
              <span class="data-source-progress-icon" aria-hidden="true">
                <template v-if="step.state === 'done'">✓</template>
                <template v-else-if="step.state === 'error'">!</template>
                <template v-else-if="step.state === 'active'">…</template>
                <template v-else>○</template>
              </span>
              <div>
                <div class="data-source-progress-label">{{ step.label }}</div>
                <div v-if="step.detail" class="muted data-source-progress-detail">{{ step.detail }}</div>
              </div>
            </div>
            <div v-if="wechatProgressSummary" class="data-source-progress-summary" :class="{ 'is-error': wechatProgressFailed }">
              {{ wechatProgressSummary }}
            </div>
          </div>
          <div class="modal-actions">
            <button
              v-if="wechatProgressDone"
              class="btn btn-primary"
              type="button"
              @click="closeWechatProgress"
            >
              完成
            </button>
            <button
              v-else-if="wechatProgressFailed"
              class="btn btn-secondary"
              type="button"
              @click="closeWechatProgress"
            >
              关闭
            </button>
          </div>
        </div>
      </div>

      <div v-if="!isWechatSourceSelected" class="card">
        <div class="card-header">搜索联系人</div>
        <div class="form-group data-source-search">
          <input
            v-model.trim="keyword"
            type="text"
            placeholder="输入联系人名称、备注或本地账号标识"
            @keydown.enter.prevent="searchContacts"
          />
          <button class="btn btn-primary" type="button" :disabled="loading || !keyword" @click="searchContacts">
            搜索
          </button>
        </div>
        <div v-if="contacts.length === 0" class="empty-state">暂无搜索结果</div>
        <div v-else class="data-source-results">
          <div v-for="contact in contacts" :key="`${contact.id || 'raw'}-${contact.source_user_id}`" class="data-source-result">
            <div>
              <strong>{{ contact.display_name || contact.contact_name || '-' }}</strong>
              <div class="muted">标识：{{ contact.source_user_id || '-' }} · 类型：{{ contact.contact_type === 'group' ? '群聊' : '联系人' }}</div>
            </div>
            <div class="data-source-result-actions">
              <button
                class="btn btn-secondary btn-sm"
                type="button"
                :disabled="!contact.id"
                @click="showContext(contact)"
              >
                查看上下文
              </button>
              <button class="btn btn-primary btn-sm" type="button" @click="prepareSend(contact)">发送消息</button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!isWechatSourceSelected" class="card">
        <div class="card-header">发送消息辅助</div>
        <div class="form-group">
          <label>联系人</label>
          <input v-model.trim="sendForm.contactName" type="text" placeholder="选择搜索结果或手动输入联系人名称" />
        </div>
        <div class="form-group">
          <label>消息内容</label>
          <textarea v-model.trim="sendForm.message" rows="4" placeholder="发送前请确认内容，员工只在你点击发送后执行"></textarea>
        </div>
        <button class="btn btn-primary" type="button" :disabled="loading || !sendForm.contactName || !sendForm.message" @click="sendMessage">
          确认发送
        </button>
      </div>

      <div class="modal" :class="{ active: contextModalOpen }">
        <div class="modal-content data-source-modal">
          <div class="modal-header">{{ contextTitle }}</div>
          <div class="data-source-context">
            <div v-if="contextMessages.length === 0" class="empty-state">暂无上下文</div>
            <div v-for="(msg, idx) in contextMessages" :key="idx" class="data-source-message">
              <div class="muted">{{ msg.role === 'self' ? '我' : '对方' }}</div>
              <div>{{ msg.text || msg.content || '' }}</div>
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn btn-secondary" type="button" @click="contextModalOpen = false">关闭</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import privateDbAssistantApi, { type PrivateDbContact, type PrivateDbSource } from '@/api/privateDbAssistant';
import wechatApi from '@/api/wechat';
import { appAlert } from '@/utils/appDialog';
import { dataSourceIconMarkup } from '@/utils/dataSourceIcons';
import WechatContactsPanel from './WechatContactsPanel.vue';

const WECHAT_SOURCE_ID = 'wechat_local_db';

const STORAGE_KEY = 'xcagi_private_db_assistant_source';
const WECHAT_AUTH_KEY = 'xcagi_wechat_local_db_authorized';
const WECHAT_POLL_ENABLED_KEY = 'xcagi_wechat_local_db_poll_enabled';
const WECHAT_POLL_INTERVAL_KEY = 'xcagi_wechat_local_db_poll_interval_sec';

type ProgressStepState = 'pending' | 'active' | 'done' | 'error' | 'skipped';

interface WechatProgressStep {
  id: string;
  label: string;
  detail?: string;
  state: ProgressStepState;
}

// Static catalog — augments the backend response. The backend is the authority for
// "available" status and actual operations; this catalog provides the full set of
// planned entries with categories and icons so the UI renders correctly even before
// a backend restart picks up source_catalog.py.
const STATIC_CATALOG: PrivateDbSource[] = [
  { id: 'local_message_db', label: '本地消息数据库', category: 'generic', icon: 'local_message_db', description: '通用 SQLite/SQLCipher 消息库适配器。需要用户提供数据库路径与访问凭据。', status: 'planned', requires_authorization: true },
  { id: 'wechat_local_db', label: '微信本地数据库适配器', category: 'im', icon: 'wechat', description: '读取已授权、已解密的本地联系人与消息缓存；含星标联系人、搜索、聊天记录与桌面发送通道。', status: 'planned', requires_authorization: true },
  { id: 'qq_local_db', label: 'QQ 本地数据库', category: 'im', icon: 'qq', description: 'QQ 本地消息与联系人读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'dingtalk_local_db', label: '钉钉本地数据库', category: 'im', icon: 'dingtalk', description: '钉钉本地消息与联系人读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'wework_local_db', label: '企业微信本地数据库', category: 'im', icon: 'wework', description: '企业微信本地消息与联系人读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'feishu_local_db', label: '飞书本地数据库', category: 'im', icon: 'feishu', description: '飞书本地消息读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'telegram_local_db', label: 'Telegram 本地数据库', category: 'im', icon: 'telegram', description: 'Telegram 本地消息读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'whatsapp_local_db', label: 'WhatsApp 本地数据库', category: 'im', icon: 'whatsapp', description: 'WhatsApp 本地消息读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'skype_local_db', label: 'Skype 本地数据库', category: 'im', icon: 'skype', description: 'Skype 本地消息读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'outlook_local_db', label: 'Outlook 本地邮箱', category: 'mail', icon: 'outlook', description: 'Outlook 本地邮箱读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'foxmail_local_db', label: 'Foxmail 本地邮箱', category: 'mail', icon: 'foxmail', description: 'Foxmail 本地邮箱读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'netease_mailmaster_local_db', label: '网易邮箱大师', category: 'mail', icon: 'netease_mailmaster', description: '网易邮箱大师读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'yongyou_local_db', label: '用友本地数据', category: 'erp', icon: 'yongyou', description: '用友本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'kingdee_local_db', label: '金蝶本地数据', category: 'erp', icon: 'kingdee', description: '金蝶本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'guanjiapo_local_db', label: '管家婆本地数据', category: 'erp', icon: 'guanjiapo', description: '管家婆本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'sap_local_db', label: 'SAP 本地数据', category: 'erp', icon: 'sap', description: 'SAP 本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'suda_local_db', label: '速达本地数据', category: 'erp', icon: 'suda', description: '速达本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'langchao_local_db', label: '浪潮本地数据', category: 'erp', icon: 'langchao', description: '浪潮本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'notion_local_db', label: 'Notion 本地数据', category: 'office', icon: 'notion', description: 'Notion 本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'onenote_local_db', label: 'OneNote 本地数据', category: 'office', icon: 'onenote', description: 'OneNote 本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'evernote_local_db', label: '印象笔记 / Evernote', category: 'office', icon: 'evernote', description: '印象笔记本地数据读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'wps_local_db', label: 'WPS 本地数据', category: 'office', icon: 'wps', description: 'WPS 本地文档读取（规划中）', status: 'planned', requires_authorization: true },
  { id: 'qianniu_local_db', label: '千牛(淘宝) 本地数据', category: 'ecommerce', icon: 'qianniu', description: '千牛本地客服数据（规划中）', status: 'planned', requires_authorization: true },
  { id: 'jingmai_local_db', label: '京麦(京东) 本地数据', category: 'ecommerce', icon: 'jingmai', description: '京麦本地客服数据（规划中）', status: 'planned', requires_authorization: true },
  { id: 'pdd_merchant_local_db', label: '拼多多商家', category: 'ecommerce', icon: 'pdd_merchant', description: '拼多多本地客服数据（规划中）', status: 'planned', requires_authorization: true },
];

const loading = ref(false);
const statusText = ref('未连接');
const sources = ref<PrivateDbSource[]>([]);
const route = useRoute();
const router = useRouter();
const selectedSourceId = ref(localStorage.getItem(STORAGE_KEY) || WECHAT_SOURCE_ID);
const wechatPanelRef = ref<InstanceType<typeof WechatContactsPanel> | null>(null);

const wechatAuthorized = ref(localStorage.getItem(WECHAT_AUTH_KEY) === '1');
const wechatConsentOpen = ref(false);
const wechatProgressOpen = ref(false);
const wechatSetupRunning = ref(false);
const wechatProgressDone = ref(false);
const wechatProgressFailed = ref(false);
const wechatProgressSummary = ref('');
const wechatProgressSteps = ref<WechatProgressStep[]>([]);

const wechatPollEnabled = ref(localStorage.getItem(WECHAT_POLL_ENABLED_KEY) === '1');
const wechatPollIntervalSec = ref(
  Number(localStorage.getItem(WECHAT_POLL_INTERVAL_KEY) || '60') || 60,
);
const wechatPollLastRunAt = ref('');
const wechatMessageSyncLastRunAt = ref(
  localStorage.getItem('xcagi_wechat_message_sync_last_at') || '',
);
const wechatMessageSyncSummary = ref('');
const wechatContactSyncing = ref(false);
const wechatMsgSyncing = ref(false);
const wechatImportNextHint = ref('');
let wechatPollTimer: ReturnType<typeof setInterval> | null = null;
const keyword = ref('');
const contacts = ref<PrivateDbContact[]>([]);
const contextModalOpen = ref(false);
const contextTitle = ref('上下文');
const contextMessages = ref<any[]>([]);
const sendForm = reactive({
  contactName: '',
  message: '',
});

function renderDataSourceIcon(name: string) {
  return dataSourceIconMarkup(name);
}

const selectedSourceLabel = computed(() => {
  const row = sources.value.find((s) => s.id === selectedSourceId.value);
  return row?.label || selectedSourceId.value || '未选择';
});

const groupedSources = computed(() => {
  const order = ["generic", "im", "mail", "erp", "office", "ecommerce"];
  const labels: Record<string, string> = {
    generic: "通用",
    im: "即时通讯",
    mail: "邮件",
    erp: "ERP · 财务",
    office: "办公 · 协作",
    ecommerce: "电商客服",
  };
  const groups: { label: string; items: any[] }[] = [];
  for (const cat of order) {
    const items = sources.value.filter((s) => (s.category || "generic") === cat);
    if (items.length) groups.push({ label: labels[cat], items });
  }
  return groups;
});

const isSelectedSourcePlanned = computed(() => {
  const row = sources.value.find((s) => s.id === selectedSourceId.value);
  return !row || row.status !== 'available';
});

const isWechatSourceSelected = computed(() => selectedSourceId.value === WECHAT_SOURCE_ID);

function applyRouteSourceHint() {
  const src = String(route.query.source || '').trim();
  if (!src) return;
  selectedSourceId.value = src;
  localStorage.setItem(STORAGE_KEY, src);
}

watch(() => route.query.source, applyRouteSourceHint);

function applyWechatAvailabilityFallback() {
  const idx = sources.value.findIndex((s) => s.id === WECHAT_SOURCE_ID);
  if (idx < 0) return;
  const row = sources.value[idx];
  if (row.status === 'available') return;
  sources.value = sources.value.map((entry) =>
    entry.id === WECHAT_SOURCE_ID
      ? {
          ...entry,
          status: 'available',
          capabilities: entry.capabilities || ['contacts', 'messages', 'search', 'context', 'send'],
        }
      : entry,
  );
  if (statusText.value !== '已就绪') {
    statusText.value = '已就绪';
  }
}

async function loadStatus() {
  try {
    const [status, sourceResp] = await Promise.all([
      privateDbAssistantApi.status(),
      privateDbAssistantApi.listSources(),
    ]);
    statusText.value = status?.success ? '已就绪' : '不可用';
    const backendMap = new Map<string, PrivateDbSource>(
      (Array.isArray(sourceResp.data) ? sourceResp.data : []).map((s: PrivateDbSource) => [s.id, s])
    );
    // Merge: backend is authoritative for status/capabilities; static catalog fills in
    // category, icon, and the full set of planned entries the backend may not yet serve.
    sources.value = STATIC_CATALOG.map((entry) => {
      const live = backendMap.get(entry.id);
      return live ? { ...entry, ...live, icon: entry.icon, category: entry.category } : entry;
    });
    const wechatLive = backendMap.get(WECHAT_SOURCE_ID);
    if (wechatLive?.status === 'available') {
      statusText.value = '已就绪';
    } else if (status?.success) {
      applyWechatAvailabilityFallback();
    }
    await syncWechatAuthorizedFromBackend();
  } catch (e: any) {
    statusText.value = '不可用';
    // On error, fall back to static catalog (all planned)
    sources.value = STATIC_CATALOG;
    try {
      const status = await privateDbAssistantApi.status();
      if (status?.success) {
        applyWechatAvailabilityFallback();
      }
    } catch {
      // keep planned fallback
    }
  }
}

async function persistSelectedSource(sourceId: string) {
  selectedSourceId.value = sourceId;
  localStorage.setItem(STORAGE_KEY, sourceId);
  try {
    const { api } = await import('@/api');
    await api.post('/api/preferences', {
      user_id: 'default',
      key: 'privateDbAssistantSource',
      value: sourceId,
    });
  } catch {
    // 非致命
  }
}

function markWechatAuthorized() {
  localStorage.setItem(WECHAT_AUTH_KEY, '1');
  wechatAuthorized.value = true;
  applyWechatAvailabilityFallback();
}

function clearWechatAuthorization() {
  localStorage.removeItem(WECHAT_AUTH_KEY);
  wechatAuthorized.value = false;
  wechatPollEnabled.value = false;
  localStorage.setItem(WECHAT_POLL_ENABLED_KEY, '0');
  stopWechatPollTimer();
}

function onWechatAuthToggle(ev: Event) {
  const checked = (ev.target as HTMLInputElement).checked;
  if (checked && !wechatAuthorized.value) {
    wechatConsentOpen.value = true;
    return;
  }
  if (!checked) {
    clearWechatAuthorization();
  }
}

async function syncWechatAuthorizedFromBackend() {
  try {
    const { api } = await import('@/api');
    const { resolveErpApiPath } = await import('@/utils/erpDomainPaths');
    const st = await api.get<{ contact_db_exists?: boolean }>(
      resolveErpApiPath('/api/wechat_contacts/decrypt_status'),
    );
    if (st?.contact_db_exists) {
      markWechatAuthorized();
    }
  } catch {
    // 非致命
  }
}

type WechatPipelineOptions = {
  forceKeyScan?: boolean;
  syncMessages?: boolean;
  markAuthorized?: boolean;
  showAlertOnFinish?: boolean;
};

function initWechatProgressSteps(opts: { forceKeyScan?: boolean; syncMessages?: boolean } = {}) {
  const keysLabel = opts.forceKeyScan
    ? '强制扫描解密密钥（微信需保持登录）'
    : '提取解密密钥';
  const steps: WechatProgressStep[] = [
    { id: 'toolkit', label: '定位 wechat-decrypt 工具', state: 'pending' },
    { id: 'db_dir', label: '检测微信数据目录', state: 'pending' },
    { id: 'config', label: '写入 config.json', state: 'pending' },
    { id: 'keys', label: keysLabel, state: 'pending' },
    { id: 'env', label: '应用运行时环境', state: 'pending' },
    { id: 'pycrypto', label: '解密依赖 pycryptodome', state: 'pending' },
    {
      id: 'decrypt',
      label: '同步并解密数据库（含 message_0.db）',
      state: 'pending',
    },
    { id: 'import', label: '导入联系人到应用库', state: 'pending' },
  ];
  if (opts.syncMessages !== false) {
    steps.push({
      id: 'msg_sync',
      label: '同步群聊聊天记录到应用库',
      state: 'pending',
    });
  }
  wechatProgressSteps.value = steps;
  wechatProgressDone.value = false;
  wechatProgressFailed.value = false;
  wechatProgressSummary.value = '';
}

function patchWechatProgressStep(
  stepId: string,
  state: ProgressStepState,
  detail?: string,
) {
  const idx = wechatProgressSteps.value.findIndex((s) => s.id === stepId);
  if (idx < 0) return;
  const next = { ...wechatProgressSteps.value[idx], state };
  if (detail !== undefined) next.detail = detail;
  wechatProgressSteps.value = [
    ...wechatProgressSteps.value.slice(0, idx),
    next,
    ...wechatProgressSteps.value.slice(idx + 1),
  ];
}

function mergeBackendProgressSteps(
  backendSteps: Array<{ id: string; label: string; state: string; detail?: string }>,
  opts: { syncMessages?: boolean },
) {
  const mapped = backendSteps.map((s) => ({
    id: s.id,
    label: s.label,
    detail: s.detail,
    state: mapBackendProgressState(s.state),
  }));
  if (opts.syncMessages !== false) {
    const hasMsg = mapped.some((s) => s.id === 'msg_sync');
    if (!hasMsg) {
      mapped.push({
        id: 'msg_sync',
        label: '同步群聊聊天记录到应用库',
        state: 'pending',
        detail: '',
      });
    }
  }
  wechatProgressSteps.value = mapped;
}

function mapBackendProgressState(state: string): ProgressStepState {
  if (state === 'done' || state === 'error' || state === 'skipped' || state === 'active') {
    return state;
  }
  return 'pending';
}

async function runWechatProgressPipeline(opts: WechatPipelineOptions = {}): Promise<boolean> {
  const forceKeyScan = opts.forceKeyScan === true;
  const syncMessages = opts.syncMessages !== false;
  const markAuthorized = opts.markAuthorized !== false;
  const showAlertOnFinish = opts.showAlertOnFinish === true;

  wechatSetupRunning.value = true;
  wechatMsgSyncing.value = syncMessages;
  initWechatProgressSteps({ forceKeyScan, syncMessages });
  wechatProgressOpen.value = true;
  wechatConsentOpen.value = false;
  wechatMessageSyncSummary.value = '';

  let hardFail = false;
  let summary = '';
  let autoConfigureResp: {
    success?: boolean;
    message?: string;
    imported_total?: number;
    message_db_stale?: boolean;
    keys_scan?: { needs_sudo?: boolean };
  } | null = null;

  try {
    const { wechatApi } = await import('@/api/wechat');
    const resp = await wechatApi.autoConfigure({ force_key_scan: forceKeyScan });
    autoConfigureResp = resp;

    if (Array.isArray(resp?.steps) && resp.steps.length) {
      mergeBackendProgressSteps(resp.steps, { syncMessages });
    }

    hardFail = !resp?.success;
    summary = resp?.message || '';

    if (resp?.message_db_stale) {
      hardFail = true;
      const staleHint =
        (summary || 'message_0.db 仍落后于本机微信') +
        '。请保持微信已登录，在 wechat-decrypt 目录执行：sudo ./find_all_keys_macos';
      summary = staleHint;
      patchWechatProgressStep('decrypt', 'error', staleHint);
      patchWechatProgressStep('msg_sync', 'skipped', '解密库未更新，已跳过聊天同步');
    }

    if (resp?.keys_scan?.needs_sudo && !resp?.keys_scan?.success) {
      patchWechatProgressStep(
        'keys',
        resp?.keys_scan?.used_cached_keys ? 'skipped' : 'error',
        resp?.keys_scan?.message || '需要 sudo 扫描密钥',
      );
    }

    if (resp?.keys_scan?.needs_sudo) {
      summary +=
        (summary ? ' ' : '') +
        '提示：若解密失败，请在终端对 find_all_keys_macos 使用 sudo，并保持微信已登录。';
    }

    if (!hardFail) {
      try {
        await privateDbAssistantApi.refreshSource(WECHAT_SOURCE_ID, 'messages');
      } catch {
        // 非致命
      }
      try {
        await wechatApi.ensureContactCache();
      } catch {
        // 面板侧会再试
      }
    }

    if (!hardFail && syncMessages) {
      patchWechatProgressStep('msg_sync', 'active', '正在从解密库写入群聊消息…');
      const { wechatGroupBridgeApi } = await import('@/api/wechatGroupBridge');
      try {
        const groupRes = await wechatGroupBridgeApi.syncGroups();
        if (groupRes?.success === false) {
          throw new Error(groupRes?.message || '同步聊天记录失败');
        }
        const synced = groupRes?.synced ?? 0;
        const failed = groupRes?.failed ?? 0;
        const msgSummary =
          synced > 0
            ? groupRes?.message || `已同步 ${synced} 个群聊${failed ? `，失败 ${failed}` : ''}`
            : groupRes?.message ||
              '未拉取到聊天消息（请确认 message_0.db 已解密，并在内部客服绑定群聊）';
        markWechatMessageSyncResult(msgSummary);
        patchWechatProgressStep(
          'msg_sync',
          synced > 0 ? 'done' : 'skipped',
          msgSummary,
        );
        summary = summary ? `${summary}；${msgSummary}` : msgSummary;
      } catch (syncErr: any) {
        const syncMsg = syncErr?.message || '同步聊天记录失败';
        patchWechatProgressStep('msg_sync', 'error', syncMsg);
        if (forceKeyScan) {
          hardFail = true;
          summary = syncMsg;
        } else {
          summary = summary ? `${summary}；${syncMsg}` : syncMsg;
        }
      }
    } else if (syncMessages) {
      patchWechatProgressStep('msg_sync', 'skipped', '自动配置未完成，已跳过');
    }
  } catch (e: any) {
    hardFail = true;
    summary = e?.message || '自动配置请求失败';
    wechatProgressSteps.value = wechatProgressSteps.value.map((s) =>
      s.state === 'pending' || s.state === 'active'
        ? { ...s, state: 'error' as ProgressStepState }
        : s,
    );
  }

  wechatSetupRunning.value = false;
  wechatMsgSyncing.value = false;
  wechatProgressDone.value = !hardFail;
  wechatProgressFailed.value = hardFail;
  wechatProgressSummary.value = hardFail
    ? summary || '自动配置未完成：请确认微信已登录，并检查本机是否存在微信数据目录。'
    : summary || '本地库已自动配置并完成读取，可开启下方定时轮询。';

  if (hardFail) {
    if (showAlertOnFinish) await appAlert(wechatProgressSummary.value);
    return false;
  }

  if (markAuthorized) {
    markWechatAuthorized();
    await loadStatus();
  }

  const importedTotal = Number(autoConfigureResp?.imported_total || 0);
  if (importedTotal > 0) {
    let groupCount = 0;
    try {
      const { wechatGroupBridgeApi } = await import('@/api/wechatGroupBridge');
      const groupsRes = await wechatGroupBridgeApi.listGroups('', 500);
      groupCount = Array.isArray(groupsRes?.data) ? groupsRes.data.length : 0;
    } catch {
      groupCount = 0;
    }
    wechatImportNextHint.value =
      groupCount > 0
        ? `已导入 ${importedTotal} 个联系人，其中 ${groupCount} 个群聊。下一步：在「用户 Mod 管理」为企业用户绑定负责的群。`
        : `已导入 ${importedTotal} 个联系人。下一步：在「用户 Mod 管理」为企业用户绑定微信群。`;
  }
  try {
    await wechatPanelRef.value?.reload?.();
  } catch {
    // ignore
  }
  if (showAlertOnFinish) await appAlert(wechatProgressSummary.value);
  return true;
}

async function runWechatAutoImport(): Promise<boolean> {
  return runWechatProgressPipeline({
    forceKeyScan: false,
    syncMessages: true,
    markAuthorized: true,
  });
}

function goWechatBindEnterprise() {
  router.push({ name: 'admin-entitlements', query: { focus: 'wechat' } });
}

async function onWechatConsentAgree() {
  await runWechatProgressPipeline({
    forceKeyScan: true,
    syncMessages: true,
    markAuthorized: true,
  });
}

function closeWechatProgress() {
  wechatProgressOpen.value = false;
  if (wechatAuthorized.value && !wechatPollEnabled.value) {
    wechatPollEnabled.value = false;
  }
}

function stopWechatPollTimer() {
  if (wechatPollTimer) {
    clearInterval(wechatPollTimer);
    wechatPollTimer = null;
  }
}

function markWechatMessageSyncResult(summary: string) {
  const ts = new Date().toLocaleString();
  wechatMessageSyncLastRunAt.value = ts;
  wechatMessageSyncSummary.value = summary;
  localStorage.setItem('xcagi_wechat_message_sync_last_at', ts);
}

async function runWechatChatHistoryWithKeyScan() {
  if (!wechatAuthorized.value) {
    await appAlert('请先启用微信本地库读取');
    return;
  }
  await runWechatProgressPipeline({
    forceKeyScan: true,
    syncMessages: true,
    markAuthorized: true,
    showAlertOnFinish: true,
  });
}

async function syncWechatChatHistory(
  showAlert = true,
  options: { forceKeyScan?: boolean } = {},
) {
  if (!wechatAuthorized.value) {
    if (showAlert) await appAlert('请先启用微信本地库读取');
    return false;
  }
  if (options.forceKeyScan === true) {
    return runWechatProgressPipeline({
      forceKeyScan: true,
      syncMessages: true,
      markAuthorized: true,
      showAlertOnFinish: showAlert,
    });
  }
  wechatMsgSyncing.value = true;
  wechatMessageSyncSummary.value = '';
  try {
    const { wechatGroupBridgeApi } = await import('@/api/wechatGroupBridge');
    const groupRes = await wechatGroupBridgeApi.syncGroups();
    if (groupRes?.success === false) {
      throw new Error(groupRes?.message || '同步聊天记录失败');
    }
    const synced = groupRes?.synced ?? 0;
    const failed = groupRes?.failed ?? 0;
    const summary =
      synced > 0
        ? groupRes?.message || `已同步 ${synced} 个群聊${failed ? `，失败 ${failed}` : ''}`
        : groupRes?.message || '未拉取到聊天消息';
    markWechatMessageSyncResult(summary);
    try {
      await wechatPanelRef.value?.reload?.();
    } catch {
      // ignore
    }
    if (showAlert) await appAlert(summary);
    return synced > 0;
  } catch (e: any) {
    const msg = e?.message || '同步聊天记录失败';
    wechatMessageSyncSummary.value = msg;
    if (showAlert) await appAlert(msg);
    return false;
  } finally {
    wechatMsgSyncing.value = false;
  }
}

async function syncWechatContacts() {
  if (!wechatAuthorized.value) {
    await appAlert('请先启用微信本地库读取');
    return;
  }
  wechatContactSyncing.value = true;
  try {
    await runWechatProgressPipeline({
      forceKeyScan: true,
      syncMessages: true,
      markAuthorized: true,
    });
  } finally {
    wechatContactSyncing.value = false;
  }
}

async function runWechatPollOnce() {
  if (!wechatAuthorized.value || !wechatPollEnabled.value) return;
  try {
    const { wechatApi } = await import('@/api/wechat');
    try {
      await privateDbAssistantApi.refreshSource(WECHAT_SOURCE_ID, 'contacts');
    } catch {
      await wechatApi.refreshContactCache();
    }
    await syncWechatChatHistory(false, { forceKeyScan: false });
    await wechatPanelRef.value?.reload?.();
    wechatPollLastRunAt.value = new Date().toLocaleString();
  } catch (e) {
    console.warn('微信本地库轮询失败', e);
  }
}

function startWechatPollTimer() {
  stopWechatPollTimer();
  if (!wechatPollEnabled.value || !wechatAuthorized.value) return;
  const ms = Math.max(30, wechatPollIntervalSec.value) * 1000;
  wechatPollTimer = setInterval(() => {
    void runWechatPollOnce();
  }, ms);
}

function onWechatPollToggle() {
  localStorage.setItem(WECHAT_POLL_ENABLED_KEY, wechatPollEnabled.value ? '1' : '0');
  if (wechatPollEnabled.value) {
    void runWechatPollOnce();
    startWechatPollTimer();
  } else {
    stopWechatPollTimer();
  }
}

function onWechatPollIntervalChange() {
  localStorage.setItem(WECHAT_POLL_INTERVAL_KEY, String(wechatPollIntervalSec.value));
  if (wechatPollEnabled.value) {
    startWechatPollTimer();
  }
}

async function onSourceCardClick(source: PrivateDbSource) {
  await persistSelectedSource(source.id);
  if (source.id !== WECHAT_SOURCE_ID) {
    stopWechatPollTimer();
    return;
  }
  applyWechatAvailabilityFallback();
  if (wechatAuthorized.value && wechatPollEnabled.value) {
    startWechatPollTimer();
  }
}

async function refreshContacts() {
  loading.value = true;
  try {
    const resp = await privateDbAssistantApi.refreshSource(selectedSourceId.value, 'contacts');
    if (!resp?.success) throw new Error(resp?.message || '刷新失败');
    await appAlert(resp.message || '联系人缓存已刷新');
  } catch (e: any) {
    await appAlert(`刷新失败: ${e?.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
}

async function refreshMessages() {
  loading.value = true;
  try {
    const resp = await privateDbAssistantApi.refreshSource(selectedSourceId.value, 'messages');
    if (!resp?.success) throw new Error(resp?.message || '检查失败');
    await appAlert(resp.message || '消息缓存已检查');
  } catch (e: any) {
    await appAlert(`检查失败: ${e?.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
}

async function searchContacts() {
  if (!keyword.value) return;
  loading.value = true;
  try {
    const resp = await privateDbAssistantApi.searchContacts(selectedSourceId.value, keyword.value);
    if (!resp?.success) throw new Error(resp?.message || '搜索失败');
    contacts.value = Array.isArray(resp.data) ? resp.data : [];
  } catch (e: any) {
    contacts.value = [];
    await appAlert(`搜索失败: ${e?.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
}

async function showContext(contact: PrivateDbContact) {
  if (!contact.id) return;
  loading.value = true;
  try {
    const resp = await privateDbAssistantApi.getContext(selectedSourceId.value, contact.id);
    if (!resp?.success) throw new Error(resp?.message || '读取失败');
    contextMessages.value = Array.isArray(resp.data) ? resp.data : [];
    contextTitle.value = `${contact.display_name || contact.contact_name || '联系人'} · 上下文`;
    contextModalOpen.value = true;
  } catch (e: any) {
    await appAlert(`读取上下文失败: ${e?.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
}

function prepareSend(contact: PrivateDbContact) {
  sendForm.contactName = contact.display_name || contact.contact_name || contact.source_user_id || '';
}

async function sendMessage() {
  loading.value = true;
  try {
    const resp = await privateDbAssistantApi.sendMessage(selectedSourceId.value, sendForm.contactName, sendForm.message);
    if (!resp?.success) throw new Error(resp?.message || '发送失败');
    await appAlert(resp.message || '消息已发送');
    sendForm.message = '';
  } catch (e: any) {
    await appAlert(`发送失败: ${e?.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  applyRouteSourceHint();
  try {
    const { api } = await import('@/api');
    const resp = await api.get('/api/preferences', { user_id: 'default' });
    const saved = resp?.preferences?.privateDbAssistantSource;
    if (saved) {
      selectedSourceId.value = saved;
      localStorage.setItem(STORAGE_KEY, saved);
    }
  } catch { /* 静默降级到 localStorage */ }
  await loadStatus();
  if (wechatAuthorized.value) {
    applyWechatAvailabilityFallback();
    if (wechatPollEnabled.value && isWechatSourceSelected.value) {
      startWechatPollTimer();
    }
  }
});

onBeforeUnmount(() => {
  stopWechatPollTimer();
});
</script>

<style scoped>
.data-source-note {
  margin: 0 0 12px;
  font-size: 13px;
}

.data-source-status,
.data-source-card-meta,
.data-source-result,
.data-source-result-actions,
.data-source-actions,
.data-source-search {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.data-source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.data-source-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  text-align: left;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px;
  background: #fff;
  cursor: pointer;
}

.data-source-card.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.data-source-card-title {
  font-weight: 700;
  margin-bottom: 6px;
}

.data-source-card-desc {
  color: #555;
  font-size: 13px;
  min-height: 38px;
}

.data-source-card-meta {
  margin-top: 10px;
  color: #666;
  font-size: 12px;
}

.data-source-actions {
  margin-top: 12px;
}

.data-source-search input {
  max-width: 420px;
}

.data-source-results {
  display: grid;
  gap: 10px;
}

.data-source-result {
  justify-content: space-between;
  padding: 12px;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  background: #fafafa;
}

.data-source-modal {
  max-width: 780px;
  width: calc(100vw - 32px);
}

.data-source-context {
  max-height: 50vh;
  overflow: auto;
  background: #f8f9fa;
  border-radius: 8px;
  padding: 12px;
}

.data-source-message {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff;
  white-space: pre-wrap;
  word-break: break-word;
}

.data-source-group-title {
  margin: 14px 0 6px;
  font-size: 12px;
  color: #6b7280;
  letter-spacing: .5px;
  text-transform: uppercase;
  font-weight: 600;
}

.data-source-card-icon,
.data-source-card-icon-inline :deep(.data-source-card-icon) {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: block;
}

.data-source-card-icon-slot {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  background: #f3f4f6;
  color: #475569;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.05);
}

.data-source-card-icon-slot.is-generic {
  background: linear-gradient(145deg, #f8fafc 0%, #eef2ff 100%);
  color: #4338ca;
}

.data-source-card-icon-slot.is-im {
  background: linear-gradient(145deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
}

.data-source-card-icon-slot.is-mail {
  background: linear-gradient(145deg, #eff6ff 0%, #dbeafe 100%);
  color: #1d4ed8;
}

.data-source-card-icon-slot.is-erp {
  background: linear-gradient(145deg, #fffbeb 0%, #fef3c7 100%);
  color: #b45309;
}

.data-source-card-icon-slot.is-office {
  background: linear-gradient(145deg, #faf5ff 0%, #ede9fe 100%);
  color: #7c3aed;
}

.data-source-card-icon-slot.is-ecommerce {
  background: linear-gradient(145deg, #fff7ed 0%, #ffedd5 100%);
  color: #c2410c;
}

.data-source-card.active .data-source-card-icon-slot {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.65),
    0 0 0 1px rgba(59, 130, 246, 0.18);
}

.data-source-card-icon-inline {
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 0;
}

.data-source-card-icon--fallback {
  font-size: 20px;
  line-height: 1;
}

.data-source-card.is-planned {
  opacity: .7;
}

.data-source-card-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #6b7280;
}

.data-source-card.active .data-source-card-badge {
  background: #e0e7ff;
  color: #3730a3;
}

.data-source-card-switch-row {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(59, 130, 246, 0.12);
}

.data-source-card.active .data-source-card-switch-row {
  border-top-color: rgba(59, 130, 246, 0.22);
}

.data-source-wechat-controls {
  margin-top: 12px;
}

.data-source-wechat-control-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  margin-bottom: 10px;
}

.data-source-wechat-control-row:last-child {
  margin-bottom: 0;
}

.data-source-wechat-control-hint {
  flex: 1 1 200px;
  font-size: 13px;
}

.data-source-switch-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  cursor: pointer;
  user-select: none;
}

.data-source-switch-text {
  font-size: 13px;
  font-weight: 500;
}

.data-source-switch-wrap {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
  flex-shrink: 0;
}

.data-source-switch-wrap input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.data-source-switch-slider {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: #d1d5db;
  transition: background 0.2s;
}

.data-source-switch-slider::before {
  content: '';
  position: absolute;
  height: 18px;
  width: 18px;
  left: 3px;
  top: 3px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  transition: transform 0.2s;
}

.data-source-switch-wrap input:checked + .data-source-switch-slider {
  background: #3b82f6;
}

.data-source-switch-wrap input:checked + .data-source-switch-slider::before {
  transform: translateX(20px);
}

.data-source-switch-wrap input:disabled + .data-source-switch-slider {
  opacity: 0.5;
}

.data-source-poll-row {
  padding-top: 10px;
  border-top: 1px solid #e5e7eb;
}

.data-source-poll-interval select {
  margin-left: 6px;
}

.data-source-poll-last {
  font-size: 12px;
}

.data-source-msg-sync-row {
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
  margin-top: 6px;
}

.data-source-msg-sync-hint {
  font-size: 12px;
  flex: 1 1 200px;
}

.data-source-msg-sync-result {
  font-size: 12px;
  color: #047857;
  width: 100%;
}

.data-source-consent-body {
  font-size: 14px;
  line-height: 1.55;
}

.data-source-consent-body ul {
  margin: 10px 0 0;
  padding-left: 20px;
}

.data-source-progress-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 160px;
}

.data-source-progress-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.data-source-progress-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  background: #e5e7eb;
  color: #374151;
  flex-shrink: 0;
}

.data-source-progress-step.is-active .data-source-progress-icon {
  background: #dbeafe;
  color: #1d4ed8;
}

.data-source-progress-step.is-done .data-source-progress-icon {
  background: #d1fae5;
  color: #047857;
}

.data-source-progress-step.is-error .data-source-progress-icon {
  background: #fee2e2;
  color: #b91c1c;
}

.data-source-progress-step.is-skipped .data-source-progress-icon {
  background: #fef3c7;
  color: #b45309;
}

.data-source-progress-label {
  font-weight: 600;
}

.data-source-progress-detail {
  font-size: 12px;
  margin-top: 4px;
}

.data-source-progress-summary {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #ecfdf5;
  color: #065f46;
  font-size: 13px;
}

.data-source-progress-summary.is-error {
  background: #fef2f2;
  color: #991b1b;
}

.data-source-wechat-next-hint {
  margin-top: 12px;
  padding: 12px 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.data-source-wechat-next-hint p {
  margin: 0;
  flex: 1 1 220px;
  font-size: 13px;
  color: #1e3a8a;
}
</style>

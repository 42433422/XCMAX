// AUTO-GENERATED 类型见 api-generated.ets（由 scripts/dev/gen_arkts_models.py 生成）。
// 本文件仅保留 ArkTS 特有类型（MobileEnvelope<T>、AiEmployeeProfile、ChatMessage 等）
// 和工具函数（cleanText、firstChar）。重导出 api-generated 以保持现有 import 路径不变。
export * from './api-generated';

export interface UserDto {
  id?: number;
  username?: string;
  display_name?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
  avatar_url?: string;
}

export interface MobileEnvelope<T> {
  code?: number;
  message?: string;
  success?: boolean;
  data?: T;
}

export interface MobileLoginData {
  user?: UserDto;
  session_id?: string;
  access_token?: string;
  refresh_token?: string;
  account_kind?: string;
  company_brand?: string;
  market_is_admin?: boolean;
  market_is_enterprise?: boolean;
  expires_in?: number;
}

export interface MobileMeData {
  user?: UserDto;
  permissions?: string[];
  account_kind?: string;
  company_brand?: string;
  mods?: ModSummary[];
}

export interface ModSummary {
  id?: string;
}

export interface ModIndustry {
  id?: string;
  name?: string;
}

export interface ModMenuItem {
  id?: string;
  label?: string;
  icon?: string;
  path?: string;
}

export interface WorkflowEmployeeInfo {
  id?: string;
  label?: string;
  panel_title?: string;
  panel_summary?: string;
  api_base_path?: string;
  phone_channel?: string;
  workflow_placeholder?: boolean;
  // ── duty 编制字段（对标 Android ApiModels.kt AdminMobileEmployeeInfo） ──
  yuangon_area?: string;
  is_duty_employee?: boolean;
  is_store_employee?: boolean;
  status?: string;
  employee_source?: string;
  employee_scope?: string;
}

export interface ModInfo {
  id?: string;
  name?: string;
  version?: string;
  author?: string;
  description?: string;
  primary?: boolean;
  industry?: ModIndustry;
  frontend_menu?: ModMenuItem[];
  menu?: ModMenuItem[];
  workflow_employees?: WorkflowEmployeeInfo[];
}

export interface MobileModsData {
  items?: ModInfo[];
}

export interface MobileHomeData {
  mods?: ModInfo[];
  sync?: SyncStatusData;
}

export interface SyncStatusData {
  status?: string;
  cursor?: number;
  updated_at?: string;
  error?: string;
}

export interface PairingExchangeData {
  host?: string;
  port?: number;
  api_base_url?: string;
  base_url?: string;
  hint?: string;
}

export interface ChatPayload {
  reply?: string;
  content?: string;
  message?: string;
}

export interface ChatResponseData {
  success?: boolean;
  reply?: string;
  message?: string;
  data?: ChatPayload;
}

export interface ConversationSummary {
  id: string;
  title: string;
  subtitle: string;
  badge: string;
  avatar: string;
  source: string;
  employeeKey: string;
}

// ── 超级员工（Codex/Claude）派工调用 ──
// 派工模式三态控件 → context.mode：自动(不带)/直答(chat)/多设备(code+mode_explicit)。
export interface SuperEmployeeContext {
  source?: string;
  client_surface?: string;
  target_devices?: string[];
  mode?: string;
  mode_explicit?: boolean;
}

export interface SuperEmployeeMessageBody {
  message: string;
  body: string;
  context: SuperEmployeeContext;
}

// list_messages / invoke().messages[] 里的单条消息行
export interface SuperEmployeeMessageRow {
  id?: string;
  role?: string;
  body?: string;
  kind?: string;
  status?: string;
  dispatch_request_id?: string;
  task_id?: string;
  created_at?: string;
}

export interface SuperEmployeeDispatch {
  request_id?: string;
  task_id?: string;
  status?: string;
  accepted?: boolean;
}

// POST .../{codex,claude}-super-employee/messages 的 data（invoke 返回）
export interface SuperEmployeeInvokeData {
  dispatch?: SuperEmployeeDispatch;
  assistant_message?: SuperEmployeeMessageRow;
  message?: SuperEmployeeMessageRow;
  messages?: SuperEmployeeMessageRow[];
}

// GET .../{codex,claude}-super-employee/messages 的 data
export interface SuperEmployeeMessagesData {
  messages?: SuperEmployeeMessageRow[];
}

// ── relay 离线通路：手机经云中继派发到已绑定的桌面执行端 ──
export interface RelayConfirmCodeBody {
  code: string;
}

export interface RelayDesktop {
  relay_id?: string;
  name?: string;
  online?: boolean;
}

// POST /relay/mobile/confirm-code 的 data
export interface RelayConfirmCodeData {
  relay_id?: string;
  desktop?: RelayDesktop;
}

// GET /relay/mobile/desktops 的 data
export interface RelayDesktopsData {
  items?: RelayDesktop[];
  count?: number;
}

export interface RelayTaskContext {
  source?: string;
  client_surface?: string;
  mode?: string;
  mode_explicit?: boolean;
}

export interface RelayTaskPayload {
  message: string;
  context: RelayTaskContext;
}

export interface RelayTaskCreateBody {
  relay_id: string;
  kind: string;
  payload: RelayTaskPayload;
}

// 任务回写结果：error / codex.assistant_message.body / reply（codex 字段对 claude 同样适用，relay 统一包在 codex 下）
export interface RelayTaskResult {
  error?: string;
  reply?: string;
  codex?: SuperEmployeeInvokeData;
}

export interface RelayTask {
  task_id?: string;
  status?: string;
  result?: RelayTaskResult;
}

// POST /relay/tasks 与 GET /relay/tasks/{taskId} 的 data
export interface RelayTaskData {
  task?: RelayTask;
}

// 联系人固定区条目（后端 /contacts/fixed 派生：assistant/dedicated_cs/super）
export interface FixedContactDto {
  id: string;
  kind: string;
  name: string;
  summary: string;
  avatar: string;
  route: string;
  backend: string;
}

export interface MobileFixedContactsData {
  side: string;
  top: FixedContactDto[];
  bottom: FixedContactDto[];
}

export interface AiEmployeeProfile {
  key: string;
  modId: string;
  modName: string;
  modAuthor: string;
  employeeId: string;
  name: string;
  title: string;
  summary: string;
  apiBasePath: string;
  phoneChannel: string;
  placeholder: boolean;
  avatarText: string;
}

export interface ChatMessage {
  role: string;
  text: string;
}

export function cleanText(value: string | undefined, fallback: string = ''): string {
  const text = (value || '').trim();
  return text.length > 0 ? text : fallback;
}

export function firstChar(value: string, fallback: string = 'AI'): string {
  const text = value.trim();
  if (text.length === 0) {
    return fallback;
  }
  return text.substring(0, 1);
}

// ════════════════════════════════════════════════════════════════
// 员工入岗 / 值班编制（Duty Roster）
// 对标前端 src/domain/yuangonDutyRoster.ts 与后端 duty_roster.json。
// 用于鸿蒙端展示「部门 → 子区域 → 在岗员工」组织架构。
// ════════════════════════════════════════════════════════════════

/** 编制区域定义（对标 YUANGON_AREAS）。 */
export interface DutyAreaInfo {
  id: string;
  label: string;
  ids: string[];
}

/** 在岗员工条目（由 AiEmployeeProfile + duty 字段组合）。 */
export interface DutyEmployee {
  key: string;
  employeeId: string;
  name: string;
  title: string;
  summary: string;
  areaId: string;
  apiBasePath: string;
  phoneChannel: string;
  status: string;
  isDuty: boolean;
  avatarText: string;
}

/** 区域分组（区域 + 该区域在岗员工）。 */
export interface DutyAreaGroup {
  areaId: string;
  areaLabel: string;
  plannedCount: number;
  onDutyCount: number;
  employees: DutyEmployee[];
}

/** 值班编制总览。 */
export interface DutyRosterData {
  areas: DutyAreaGroup[];
  totalPlanned: number;
  totalOnDuty: number;
}

// CI SSOT BEGIN
/**
 * 编制区域常量表（CI SSOT 生成，与前端 yuangonDutyRoster.ts YUANGON_AREAS 对齐）。
 * 后端 admin/home 返回的 duty 员工按 yuangon_area 归入这些区域。
 */
export const YUANGON_AREAS: DutyAreaInfo[] = [
  {
    id: 'site-and-marketing',
    label: '对外网站与 SEO',
    ids: ['site-content-editor', 'seo-sitemap-curator', 'flask-entry-keeper', 'marketing-site-builder']
  },
  {
    id: 'server-and-ops',
    label: '服务器与运维',
    ids: ['nginx-config-engineer', 'push-update-context-officer', 'deploy-release-officer', 'security-secrets-guard', 'log-monitor-incident', 'retention-officer', 'dbops-engineer', 'llm-ops-engineer', 'legacy-archive-curator']
  },
  {
    id: 'modstore-backend',
    label: 'MODstore 后端',
    ids: ['modstore-backend-api', 'employee-pack-curator', 'payment-billing-reconciler', 'java-payment-bridge-officer']
  },
  {
    id: 'modstore-frontend',
    label: 'MODstore 前端',
    ids: ['market-frontend-dev', 'workbench-ux-stylist']
  },
  {
    id: 'platform-core',
    label: '平台核心',
    ids: ['fhd-core-maintainer', 'vibe-coding-maintainer', 'mods-and-eskill-curator', 'change-request-auditor', 'daily-orchestrator', 'intake-dispatcher', 'task-router-officer', 'user-customer-service-officer', 'enterprise-adoption-officer', 'delivery-receipt-officer', 'mobile-android-release-officer', 'mobile-ios-release-officer', 'mobile-harmony-release-officer']
  },
  {
    id: 'quality-and-docs',
    label: '质量与文档',
    ids: ['test-qa-runner', 'doc-knowledge-curator', 'employee-interview-assistant', 'employee-pack-quality-interviewer']
  },
  {
    id: 'craft-workshop',
    label: '制作车间',
    ids: ['intent-analyst', 'employee-planner', 'artifact-generator', 'quality-validator', 'miniapp-builder', 'script-binder', 'workflow-automator', 'pack-registrar', 'sandbox-tester', 'code-validator', 'self-checker', 'host-checker', 'hex-quality-assessor']
  },
  {
    id: 'partner-ecosystem',
    label: '生态伙伴 O-B',
    ids: ['ecosystem-partner-onboard-officer', 'ecosystem-joint-catalog-officer', 'ecosystem-delivery-reporter', 'ecosystem-investor-portal-officer', 'ecosystem-revenue-share-reconciler']
  },
];
// CI SSOT END

// ════════════════════════════════════════════════════════════════
// 审批流（Approval）— 对标 Android ApprovalScreens.kt
// ════════════════════════════════════════════════════════════════

/** 审批列表项。 */
export interface ApprovalItem {
  id: string;
  title: string;
  subtitle: string;
  status: string;
  applicantName: string;
}

/** 审批详情。 */
export interface ApprovalDetail {
  id: string;
  title: string;
  requestNo: string;
  applicantName: string;
  flowName: string;
  currentNodeName: string;
  submittedAt: string;
  description: string;
  status: string;
}

// ════════════════════════════════════════════════════════════════
// 通知与公告（Notification）— 对标 Android NotificationListScreen.kt
// ════════════════════════════════════════════════════════════════

/** 通知类型。 */
export type NotificationKind = 'system' | 'announcement' | 'update' | 'alert' | 'success';

/** 通知项。 */
export interface NotificationEntry {
  id: number;
  type: NotificationKind;
  title: string;
  body: string;
  route: string;
  channel: string;
  messageId: string;
  sessionId: string;
  source: string;
  timestamp: number;
  read: boolean;
}

// ════════════════════════════════════════════════════════════════
// 客服聊天（CS Chat）— 对标 Android CsChatScreen.kt
// ════════════════════════════════════════════════════════════════

/** 客服信息。 */
export interface CsInfo {
  title: string;
  subtitle: string;
  online: boolean;
}

// ════════════════════════════════════════════════════════════════
// IM 即时通讯 — 对标 Android ImMessengerScreen.kt
// ════════════════════════════════════════════════════════════════

/** IM 消息。 */
export interface ImMessage {
  id: string;
  conversationId: number;
  senderId: number;
  content: string;
  timestamp: number;
  mine: boolean;
}

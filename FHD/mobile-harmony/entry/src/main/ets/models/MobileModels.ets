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

/** 消息页头像尺寸与位置 SSOT（对标 Android MessageAvatarLayout）。 */
export const MESSAGE_AVATAR_LAYOUT = {
  conversationAvatarSize: 48,
  conversationAvatarRadius: 14,
  conversationAvatarTextGap: 12,
  conversationRowPadding: 14,
  conversationRowMarginHorizontal: 14,
  conversationCardRadius: 14,
  conversationAvatarFontSize: 18
};

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

// ════════════════════════════════════════════════════════════════
// AI 圈子(朋友圈)— 对标 Android AiCircleScreens.kt
// 后端 /api/mobile/v1/circle/posts(app/application/ai_circle_service.py)
// ════════════════════════════════════════════════════════════════

/** 圈子评论。 */
export interface CircleComment {
  id?: number;
  author_name?: string;
  body?: string;
  created_at?: string;
}

/** 圈子动态。 */
export interface CirclePost {
  id?: number;
  author_kind?: string;
  author_user_id?: number;
  employee_id?: string;
  author_name?: string;
  author_avatar?: string;
  body?: string;
  created_at?: string;
  like_count?: number;
  liked_by_me?: boolean;
  comments?: CircleComment[];
}

/** 圈子列表数据(data.items + count)。 */
export interface CirclePostsData {
  items?: CirclePost[];
  count?: number;
}

// ════════════════════════════════════════════════════════════════
// AI 群聊 — 对标 Android AiGroupScreens.kt
// 后端 /api/mobile/v1/ai-groups(app/application/ai_group_chat_service.py)
// ════════════════════════════════════════════════════════════════

/** 群成员。 */
export interface AiGroupMember {
  employee_id?: string;
  mod_id?: string;
  name?: string;
  avatar?: string;
  summary?: string;
}

/** AI 群聊(_public_group)。 */
export interface AiGroup {
  id?: string;
  name?: string;
  department_key?: string;
  member_count?: number;
  members?: AiGroupMember[];
  is_pinned?: boolean;
  is_hidden?: boolean;
  is_followed?: boolean;
  unread_count?: number;
  created_at?: string;
  last_message_preview?: string;
  last_message_at?: string;
}

/** 群消息(_public_message)。 */
export interface AiGroupMessage {
  id?: string;
  group_id?: string;
  role?: string;
  sender_id?: string;
  sender_name?: string;
  sender_avatar?: string;
  body?: string;
  created_at?: string;
}

export interface AiGroupsData {
  groups?: AiGroup[];
}

export interface AiGroupCreateData {
  group?: AiGroup;
}

export interface AiGroupMessagesData {
  messages?: AiGroupMessage[];
}

/** post_message 返回:{group_id, messages:[新增成员回复]}。 */
export interface AiGroupPostResult {
  group_id?: string;
  messages?: AiGroupMessage[];
}

// ════════════════════════════════════════════════════════════════
// 企业模块数据(客户/发货/服务桥/钱包)— 对标 Android EnterpriseScreens.kt
// ════════════════════════════════════════════════════════════════

/** 分页信息(paginate_list)。 */
export interface PaginationInfo {
  total?: number;
  page?: number;
  per_page?: number;
  total_pages?: number;
}

/** 客户(/api/mobile/v1/customers)。 */
export interface CustomerItem {
  id?: number;
  name?: string;
  phone?: string;
}

export interface CustomersData {
  items?: CustomerItem[];
  pagination?: PaginationInfo;
}

/** 发货(/api/mobile/v1/shipments)。 */
export interface ShipmentItem {
  id?: number;
  order_number?: string;
  status?: string;
}

export interface ShipmentsData {
  items?: ShipmentItem[];
  pagination?: PaginationInfo;
}

/** 服务桥请求(ServiceRequest.to_dict)。 */
export interface ServiceBridgeRequest {
  id?: number;
  source_instance_id?: string;
  source_instance_name?: string;
  request_type?: string;
  title?: string;
  description?: string;
  priority?: string;
  status?: string;
  response?: string;
  responded_by?: string;
  responded_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ServiceBridgeData {
  items?: ServiceBridgeRequest[];
  pagination?: PaginationInfo;
}

/** 钱包余额(/api/mobile/v1/wallet/balance)。 */
export interface WalletBalanceData {
  balance?: number;
  currency?: string;
  membership_level?: string;
  experience?: number;
  byok_configured?: boolean;
  byok_count?: number;
  synced?: boolean;
  message?: string;
  market_base_url?: string;
}

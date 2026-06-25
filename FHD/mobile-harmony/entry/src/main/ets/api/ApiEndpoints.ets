// API 端点常量表。
//
// 所有 api/mobile/v1/* 路径集中于此，端点变更时只需修改本文件。
// 与 Android ApiEndpoints.kt 对齐，保持两端端点路径同步。

export class ApiEndpoints {
  static readonly BASE: string = 'api/mobile/v1';

  // 健康检查
  static readonly HEALTH: string = `${ApiEndpoints.BASE}/health`;

  // 认证
  static readonly AUTH_LOGIN: string = `${ApiEndpoints.BASE}/auth/login`;
  static readonly AUTH_LOGIN_WITH_PHONE_CODE: string = `${ApiEndpoints.BASE}/auth/login-with-phone-code`;
  static readonly AUTH_QR_CONFIRM: string = `${ApiEndpoints.BASE}/auth/qr/confirm`;
  static readonly AUTH_OIDC_EXCHANGE: string = `${ApiEndpoints.BASE}/auth/oidc/exchange`;
  static readonly AUTH_REFRESH: string = `${ApiEndpoints.BASE}/auth/refresh`;

  // 主机发现
  static readonly HOST_DISCOVER_HINT: string = `${ApiEndpoints.BASE}/host/discover-hint`;

  // 用户信息
  static readonly ME: string = `${ApiEndpoints.BASE}/me`;

  // 审批
  static readonly APPROVAL_REQUESTS: string = `${ApiEndpoints.BASE}/approval/requests`;
  static readonly APPROVAL_DETAIL: string = `api/approval/requests/{id}`;
  static readonly APPROVAL_APPROVE: string = `api/approval/requests/{id}/approve`;
  static readonly APPROVAL_REJECT: string = `api/approval/requests/{id}/reject`;

  // 客户
  static readonly CUSTOMERS: string = `${ApiEndpoints.BASE}/customers`;

  // 发货
  static readonly SHIPMENTS: string = `${ApiEndpoints.BASE}/shipments`;

  // 服务桥
  static readonly SERVICE_BRIDGE_REQUESTS: string = `${ApiEndpoints.BASE}/service-bridge/requests`;
  static readonly SERVICE_BRIDGE_REQUESTS_RESPOND: string = `${ApiEndpoints.BASE}/service-bridge/requests/{id}/respond`;

  // MOD
  static readonly MODS: string = `${ApiEndpoints.BASE}/mods`;
  static readonly PLATFORM_SHELL: string = `${ApiEndpoints.BASE}/platform-shell`;

  // 首页
  static readonly HOME: string = `${ApiEndpoints.BASE}/home`;
  static readonly ADMIN_HOME: string = `${ApiEndpoints.BASE}/admin/home`;

  // 同步
  static readonly SYNC_STATUS: string = `${ApiEndpoints.BASE}/sync/status`;
  static readonly SYNC_PULL: string = `${ApiEndpoints.BASE}/sync/pull`;
  static readonly SYNC_PUSH: string = `${ApiEndpoints.BASE}/sync/push`;
  static readonly SYNC_CONFLICTS: string = `${ApiEndpoints.BASE}/sync/conflicts`;

  // 设备
  static readonly DEVICES_REGISTER: string = `${ApiEndpoints.BASE}/devices/register`;

  // 配对
  static readonly PAIRING_EXCHANGE: string = `${ApiEndpoints.BASE}/pairing/exchange`;
  static readonly PAIRING_ISSUE: string = `${ApiEndpoints.BASE}/pairing/issue`;

  // 中继
  static readonly RELAY_MOBILE_CONFIRM: string = `${ApiEndpoints.BASE}/relay/mobile/confirm`;
  static readonly RELAY_MOBILE_CONFIRM_CODE: string = `${ApiEndpoints.BASE}/relay/mobile/confirm-code`;
  static readonly RELAY_MOBILE_DESKTOPS: string = `${ApiEndpoints.BASE}/relay/mobile/desktops`;
  static readonly RELAY_TASKS: string = `${ApiEndpoints.BASE}/relay/tasks`;
  static readonly RELAY_TASKS_DETAIL: string = `${ApiEndpoints.BASE}/relay/tasks/{taskId}`;

  // 客服
  static readonly CS_INFO: string = `${ApiEndpoints.BASE}/cs/info`;
  static readonly CS_MESSAGES: string = `${ApiEndpoints.BASE}/cs/messages`;

  // 联系人固定区(按端 SSOT 派生)
  static readonly CONTACTS_FIXED: string = `${ApiEndpoints.BASE}/contacts/fixed`;

  // 管理员
  static readonly ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES: string = `${ApiEndpoints.BASE}/admin/codex-super-employee/messages`;
  static readonly ADMIN_CLAUDE_SUPER_EMPLOYEE_MESSAGES: string = `${ApiEndpoints.BASE}/admin/claude-super-employee/messages`;

  // 会议纪要 SSOT（三级派生）
  static readonly MEETING_LEVELS: string = `${ApiEndpoints.BASE}/meetings/levels`;
  static readonly MEETING_GENERATE: string = `${ApiEndpoints.BASE}/meetings/generate-all`;
  static readonly MEETING_DETAIL: string = `${ApiEndpoints.BASE}/meetings/{id}`;

  // AI 圈子(朋友圈)
  static readonly CIRCLE_POSTS: string = `${ApiEndpoints.BASE}/circle/posts`;
  static readonly CIRCLE_POST_LIKE: string = `${ApiEndpoints.BASE}/circle/posts/{id}/like`;
  static readonly CIRCLE_POST_COMMENTS: string = `${ApiEndpoints.BASE}/circle/posts/{id}/comments`;

  // AI 群聊(对标 Android AiGroupScreens.kt)
  static readonly AI_GROUPS: string = `${ApiEndpoints.BASE}/ai-groups`;
  static readonly AI_GROUP_MESSAGES: string = `${ApiEndpoints.BASE}/ai-groups/{id}/messages`;
  static readonly AI_GROUP_MEMBERS: string = `${ApiEndpoints.BASE}/ai-groups/{id}/members`;
  static readonly AI_GROUP_MARK_READ: string = `${ApiEndpoints.BASE}/ai-groups/{id}/mark-read`;
  static readonly AI_GROUP_MARK_UNREAD: string = `${ApiEndpoints.BASE}/ai-groups/{id}/mark-unread`;

  // 钱包(我的页面余额/会员)
  static readonly WALLET_BALANCE: string = `${ApiEndpoints.BASE}/wallet/balance`;
  static readonly WALLET_OVERVIEW: string = `${ApiEndpoints.BASE}/wallet/overview`;

  // SSE 流式对话(对标 Android SseChatClient,/api/ai/chat/stream)
  static readonly AI_CHAT_STREAM: string = `api/ai/chat/stream`;
}

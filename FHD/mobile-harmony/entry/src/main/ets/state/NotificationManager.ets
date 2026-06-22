import notificationManager from '@ohos.notificationManager';
import { cleanText } from '../models/MobileModels';

// 通知管理器：对齐 Android core/push/ 模块
// - NotificationChannels：通道常量（审批/同步/系统/对话）
// - PushPayload + parse：推送载荷解析（FCM/JPush 共用）
// - NotificationManager：通道初始化、通知展示、设备注册/注销、应用内通知状态
//
// 与 Android 端差异：
// - HarmonyOS 使用 notificationManager slot type 替代 Android NotificationChannel importance
// - HarmonyOS 推送 token 由 Push Kit 提供，此处仅保留注册接口契约

export class NotificationChannels {
  static readonly APPROVAL: string = 'xcagi_approval';
  static readonly SYNC: string = 'xcagi_sync';
  static readonly SYSTEM: string = 'xcagi_system';
  static readonly CHAT: string = 'xcagi_chat';

  // 通道展示名（与 Android 端 NotificationChannels.ensure 中名称一致）
  static readonly APPROVAL_LABEL: string = '审批通知';
  static readonly SYNC_LABEL: string = '同步';
  static readonly SYSTEM_LABEL: string = '系统';
  static readonly CHAT_LABEL: string = '对话';

  // 通道 → HarmonyOS slot type 映射
  // Android IMPORTANCE_HIGH → SOCIAL_COMMUNICATION
  // Android IMPORTANCE_DEFAULT → CONTENT_INFORMATION
  // Android IMPORTANCE_LOW → OTHER_TYPES
  static slotTypeOf(channel: string): notificationManager.SlotType {
    if (channel === NotificationChannels.APPROVAL) {
      return notificationManager.SlotType.SOCIAL_COMMUNICATION;
    }
    if (channel === NotificationChannels.SYNC) {
      return notificationManager.SlotType.OTHER_TYPES;
    }
    if (channel === NotificationChannels.SYSTEM) {
      return notificationManager.SlotType.CONTENT_INFORMATION;
    }
    return notificationManager.SlotType.CONTENT_INFORMATION;
  }

  static labelOf(channel: string): string {
    if (channel === NotificationChannels.APPROVAL) return NotificationChannels.APPROVAL_LABEL;
    if (channel === NotificationChannels.SYNC) return NotificationChannels.SYNC_LABEL;
    if (channel === NotificationChannels.SYSTEM) return NotificationChannels.SYSTEM_LABEL;
    return NotificationChannels.CHAT_LABEL;
  }
}

// 推送载荷：对齐 Android PushMessageHandler.PushPayload
export interface PushPayload {
  title: string;
  body: string;
  route: string;
  channel: string;
  messageId: string;
  sessionId: string;
  source: string;
}

// 应用内通知条目（用于通知中心列表展示）
export interface NotificationEntry {
  id: number;
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

// 推送注册结果：对齐 Android PushRegisterResult
export interface PushRegisterResult {
  registered: boolean;
  token: string;
  hint: string;
}

// 解析推送 data：对齐 Android PushMessageHandler.parse
export function parsePushPayload(
  title: string | undefined,
  body: string | undefined,
  route: string | undefined,
  channel: string | undefined,
  messageId: string | undefined,
  sessionId: string | undefined,
  source: string | undefined,
): PushPayload {
  return {
    title: cleanText(title, 'XCAGI'),
    body: body || '',
    route: cleanText(route, 'xcagi://chat'),
    channel: cleanText(channel, NotificationChannels.CHAT),
    messageId: cleanText(messageId),
    sessionId: cleanText(sessionId),
    source: cleanText(source),
  };
}

// 通知管理器：单例，管理通道初始化、通知展示、应用内通知列表、推送 token 注册
export class NotificationManager {
  private static instance: NotificationManager | null = null;

  private pushToken: string = '';
  private pushProvider: string = '';
  private registered: boolean = false;
  private notifications: NotificationEntry[] = [];
  private nextId: number = 1;
  private channelsEnsured: boolean = false;

  static getInstance(): NotificationManager {
    if (NotificationManager.instance === null) {
      NotificationManager.instance = new NotificationManager();
    }
    return NotificationManager.instance;
  }

  // 通道初始化：对齐 Android NotificationChannels.ensure
  // HarmonyOS 不需要显式 createNotificationChannel，slot type 在发布时指定；
  // 这里保留方法以对齐调用契约，并标记已初始化。
  async ensureChannels(): Promise<void> {
    if (this.channelsEnsured) return;
    try {
      // HarmonyOS 通知启用状态查询
      await notificationManager.isNotificationEnabled();
      this.channelsEnsured = true;
    } catch (_err) {
      // 通知权限未授予或查询失败：不阻断业务
      this.channelsEnsured = false;
    }
  }

  // 展示通知：对齐 Android PushMessageHandler.showNotification
  async showNotification(payload: PushPayload): Promise<void> {
    await this.ensureChannels();
    // 记录到应用内通知列表
    const entry: NotificationEntry = {
      id: this.nextId++,
      title: payload.title,
      body: payload.body,
      route: payload.route,
      channel: payload.channel,
      messageId: payload.messageId,
      sessionId: payload.sessionId,
      source: payload.source,
      timestamp: new Date().getTime(),
      read: false,
    };
    this.notifications = [entry].concat(this.notifications);

    try {
      // 注：NotificationRequest.slotType 在当前 SDK 期望 @ohos.notification.SlotType，
      // 与 @ohos.notificationManager.SlotType 类型不兼容（SDK 内部模块冲突）。
      // slotType 为可选字段，此处省略以使用系统默认通道；通知发布失败已被 catch 兜底。
      const request: notificationManager.NotificationRequest = {
        id: entry.id,
        content: {
          notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
          normal: {
            title: payload.title,
            text: payload.body,
            additionalText: NotificationChannels.labelOf(payload.channel),
          },
        },
        label: payload.channel,
      };
      await notificationManager.publish(request);
    } catch (_err) {
      // 用户拒绝通知权限或发布失败：不拖垮推送回调（与 Android SecurityException 处理一致）
    }
  }

  // 注册推送 token：对齐 Android PushRegistrar.registerAll
  // HarmonyOS Push Kit token 由调用方注入（避免在此处耦合 Push Kit SDK）
  async registerToken(provider: string, token: string): Promise<PushRegisterResult> {
    const cleanProvider = cleanText(provider);
    const cleanToken = cleanText(token);
    if (cleanProvider.length === 0 || cleanToken.length === 0) {
      return { registered: false, token: '', hint: '推送 token 为空' };
    }
    this.pushProvider = cleanProvider;
    this.pushToken = cleanToken;
    this.registered = true;
    return { registered: true, token: cleanToken, hint: '' };
  }

  // 注销推送：对齐 Android PushRegistrar.unregisterAll
  unregister(): void {
    this.pushToken = '';
    this.pushProvider = '';
    this.registered = false;
  }

  isRegistered(): boolean {
    return this.registered;
  }

  getPushToken(): string {
    return this.pushToken;
  }

  getPushProvider(): string {
    return this.pushProvider;
  }

  // 获取应用内通知列表（用于通知中心页面）
  getNotifications(): NotificationEntry[] {
    return this.notifications;
  }

  // 标记已读
  markRead(id: number): void {
    this.notifications = this.notifications.map((item: NotificationEntry): NotificationEntry => {
      if (item.id === id) {
        const updated: NotificationEntry = {
          id: item.id, title: item.title, body: item.body, route: item.route,
          channel: item.channel, messageId: item.messageId, sessionId: item.sessionId,
          source: item.source, timestamp: item.timestamp, read: true
        };
        return updated;
      }
      return item;
    });
  }

  // 全部标记已读
  markAllRead(): void {
    this.notifications = this.notifications.map((item: NotificationEntry): NotificationEntry => {
      const updated: NotificationEntry = {
        id: item.id, title: item.title, body: item.body, route: item.route,
        channel: item.channel, messageId: item.messageId, sessionId: item.sessionId,
        source: item.source, timestamp: item.timestamp, read: true
      };
      return updated;
    });
  }

  // 清空通知
  clearAll(): void {
    this.notifications = [];
  }

  // 未读数
  unreadCount(): number {
    let count = 0;
    this.notifications.forEach((item: NotificationEntry) => {
      if (!item.read) count++;
    });
    return count;
  }
}

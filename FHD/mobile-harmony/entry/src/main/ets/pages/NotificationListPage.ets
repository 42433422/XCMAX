import { NotificationEntry, NotificationKind } from '../models/MobileModels';

/**
 * 通知与公告页面。
 *
 * 对标 Android NotificationListScreen.kt，通知数据为本地 mock（5 条），
 * 涵盖 system/announcement/update/alert/success 五种类型。
 * 点击通知标记已读，未读项标题加粗并显示红点。
 */
@Component
export struct NotificationListPage {
  @State notifications: NotificationEntry[] = [];
  @State readIds: number[] = [];

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.notifications = this.buildMockNotifications();
  }

  build() {
    this.NotificationArea();
  }

  @Builder
  NotificationArea() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 10 }) {
          if (this.notifications.length === 0) {
            this.EmptyCard('暂无通知', '当前没有需要展示的通知与公告。');
          } else {
            ForEach(this.notifications, (item: NotificationEntry) => {
              this.NotificationCard(item);
            }, (item: NotificationEntry) => `${item.id}`);
          }
        }
        .width('100%')
        .padding({ top: 14, bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  Header() {
    Row({ space: 12 }) {
      Text('<')
        .width(36)
        .height(36)
        .fontSize(22)
        .fontColor('#111827')
        .textAlign(TextAlign.Center)
        .onClick(() => this.onBack());
      Column({ space: 2 }) {
        Text('通知与公告')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('系统消息 · 企业公告 · 版本更新')
          .fontSize(13)
          .fontColor('#4B5563');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  NotificationCard(item: NotificationEntry) {
    Row({ space: 12 }) {
      Text(this.typeIconChar(item.type))
        .width(40)
        .height(40)
        .borderRadius(20)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.typeColor(item.type))
        .textAlign(TextAlign.Center)
        .backgroundColor(this.typeBgColor(item.type));

      Column({ space: 4 }) {
        Row() {
          Text(item.title)
            .fontSize(15)
            .fontWeight(this.isUnread(item) ? FontWeight.Bold : FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          if (this.isUnread(item)) {
            Row()
              .width(8)
              .height(8)
              .borderRadius(4)
              .backgroundColor('#DC2626');
          }
        }
        .width('100%');

        Text(item.body)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });

        Text(this.formatTime(item.timestamp))
          .fontSize(11)
          .fontColor('#9CA3AF');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.markAsRead(item.id));
  }

  @Builder
  EmptyCard(title: string, subtitle: string) {
    Column({ space: 8 }) {
      Text(title)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
      Text(subtitle)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(20)
        .textAlign(TextAlign.Center);
    }
    .width('100%')
    .padding(24)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private isUnread(item: NotificationEntry): boolean {
    if (item.read) return false;
    return this.readIds.indexOf(item.id) < 0;
  }

  private markAsRead(id: number): void {
    if (this.readIds.indexOf(id) >= 0) return;
    this.readIds = this.readIds.concat([id]);
  }

  private typeIconChar(type: NotificationKind): string {
    if (type === 'system') return '系';
    if (type === 'announcement') return '公';
    if (type === 'update') return '更';
    if (type === 'alert') return '警';
    if (type === 'success') return '成';
    return '消';
  }

  private typeColor(type: NotificationKind): string {
    if (type === 'system') return '#1D4ED8';
    if (type === 'announcement') return '#2563EB';
    if (type === 'update') return '#18A85F';
    if (type === 'alert') return '#DC2626';
    if (type === 'success') return '#166534';
    return '#4B5563';
  }

  private typeBgColor(type: NotificationKind): string {
    if (type === 'system') return '#E8F0FF';
    if (type === 'announcement') return '#E8F0FF';
    if (type === 'update') return '#E7F7EE';
    if (type === 'alert') return '#FEE2E2';
    if (type === 'success') return '#E7F7EE';
    return '#F3F4F6';
  }

  private formatTime(timestamp: number): string {
    const date = new Date(timestamp);
    const month = this.pad2(date.getMonth() + 1);
    const day = this.pad2(date.getDate());
    const hour = this.pad2(date.getHours());
    const minute = this.pad2(date.getMinutes());
    return `${month}-${day} ${hour}:${minute}`;
  }

  private pad2(value: number): string {
    return value < 10 ? `0${value}` : `${value}`;
  }

  private buildMockNotifications(): NotificationEntry[] {
    const now = new Date().getTime();
    const hour = 3600 * 1000;
    const day = 24 * hour;

    const n1: NotificationEntry = {
      id: 1,
      type: 'announcement',
      title: '欢迎使用 XCAGI 企业版',
      body: '您的企业 AI 助手已就绪。可以随时和小C助理对话，或前往 AI员工 页面查看企业智能伙伴。',
      route: '',
      channel: 'system',
      messageId: '',
      sessionId: '',
      source: 'system',
      timestamp: now - 2 * hour,
      read: false
    };
    const n2: NotificationEntry = {
      id: 2,
      type: 'system',
      title: '数据同步完成',
      body: '您的会话和 AI 员工列表已同步至最新状态。',
      route: '',
      channel: 'system',
      messageId: '',
      sessionId: '',
      source: 'system',
      timestamp: now - 5 * hour,
      read: true
    };
    const n3: NotificationEntry = {
      id: 3,
      type: 'update',
      title: '新功能：语音输入',
      body: '聊天页和客服页现已支持语音输入，点击麦克风按钮即可将语音转为文字。',
      route: '',
      channel: 'system',
      messageId: '',
      sessionId: '',
      source: 'system',
      timestamp: now - day,
      read: false
    };
    const n4: NotificationEntry = {
      id: 4,
      type: 'success',
      title: '账号配对成功',
      body: '您的移动端已成功配对企业端，可以开始使用全部功能。',
      route: '',
      channel: 'system',
      messageId: '',
      sessionId: '',
      source: 'system',
      timestamp: now - 2 * day,
      read: true
    };
    const n5: NotificationEntry = {
      id: 5,
      type: 'alert',
      title: '请及时更新应用',
      body: '检测到新版本可用，建议尽快更新以获得最新功能和安全修复。',
      route: '',
      channel: 'system',
      messageId: '',
      sessionId: '',
      source: 'system',
      timestamp: now - 3 * day,
      read: true
    };
    return [n1, n2, n3, n4, n5];
  }
}

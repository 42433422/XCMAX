import { NotificationChannels, NotificationEntry, NotificationManager } from '../state/NotificationManager';

/**
 * 通知与公告页面。
 *
 * 对标 Android NotificationListScreen.kt:通知来自真实推送/同步信号,
 * 由 NotificationManager(对齐 Android core/push/)统一管理。
 * 尚无推送到达时显示空态(诚实:不再用硬编码 mock 占位)。
 * 点击通知标记已读,未读项标题加粗并显示红点。
 */
@Component
export struct NotificationListPage {
  @State notifications: NotificationEntry[] = [];

  private manager: NotificationManager = NotificationManager.getInstance();

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.refresh();
  }

  private refresh(): void {
    this.notifications = this.manager.getNotifications();
  }

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 10 }) {
          if (this.notifications.length === 0) {
            this.EmptyCard('暂无通知', '审批、同步与系统消息会通过推送到达,届时在这里展示。');
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

      if (this.notifications.length > 0) {
        Text('全部已读')
          .fontSize(13)
          .fontColor('#1D4ED8')
          .onClick(() => {
            this.manager.markAllRead();
            this.refresh();
          });
      }
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  NotificationCard(item: NotificationEntry) {
    Row({ space: 12 }) {
      Text(this.channelIconChar(item.channel))
        .width(40)
        .height(40)
        .borderRadius(20)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.channelColor(item.channel))
        .textAlign(TextAlign.Center)
        .backgroundColor(this.channelBgColor(item.channel));

      Column({ space: 4 }) {
        Row() {
          Text(item.title)
            .fontSize(15)
            .fontWeight(item.read ? FontWeight.Medium : FontWeight.Bold)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          if (!item.read) {
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

        Row({ space: 8 }) {
          Text(NotificationChannels.labelOf(item.channel))
            .fontSize(11)
            .fontColor('#6B7280');
          Text(this.formatTime(item.timestamp))
            .fontSize(11)
            .fontColor('#9CA3AF');
        }
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
    .onClick(() => {
      this.manager.markRead(item.id);
      this.refresh();
    });
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
    .margin({ left: 14, right: 14, top: 20 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private channelIconChar(channel: string): string {
    if (channel === NotificationChannels.APPROVAL) return '审';
    if (channel === NotificationChannels.SYNC) return '同';
    if (channel === NotificationChannels.SYSTEM) return '系';
    return '话';
  }

  private channelColor(channel: string): string {
    if (channel === NotificationChannels.APPROVAL) return '#BE185D';
    if (channel === NotificationChannels.SYNC) return '#4B5563';
    if (channel === NotificationChannels.SYSTEM) return '#1D4ED8';
    return '#166534';
  }

  private channelBgColor(channel: string): string {
    if (channel === NotificationChannels.APPROVAL) return '#FCE7F3';
    if (channel === NotificationChannels.SYNC) return '#F3F4F6';
    if (channel === NotificationChannels.SYSTEM) return '#E8F0FF';
    return '#E7F7EE';
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
}

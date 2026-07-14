/**
 * 服务桥页面。
 *
 * 对标 Android BridgeScreen.kt：服务请求列表(真数据) + 发起请求。
 * 数据源:GET /api/mobile/v1/service-bridge/requests(ServiceRequest.to_dict)。
 * 「发起请求」移动端只引导到桌面端(完整表单录入在桌面端处理)。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { ServiceBridgeRequest, cleanText } from '../models/MobileModels';

@Component
export struct BridgePage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State requests: ServiceBridgeRequest[] = [];
  @State loading: boolean = false;
  @State errorMsg: string = '';

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadRequests();
  }

  private async loadRequests(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      const data = await this.api.serviceBridgeRequests();
      this.requests = data.items || [];
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  build() {
    Column() {
      this.Header();
      if (this.loading && this.requests.length === 0) {
        this.StateCard('加载中...');
      } else if (this.errorMsg.length > 0 && this.requests.length === 0) {
        this.StateCard(this.errorMsg);
      } else if (this.requests.length === 0) {
        this.StateCard('暂无服务请求');
      } else {
        Scroll() {
          Column({ space: 12 }) {
            this.SummaryCard();
            ForEach(this.requests, (req: ServiceBridgeRequest) => {
              this.RequestCard(req);
            }, (req: ServiceBridgeRequest) => (req.id !== undefined ? req.id.toString() : 'r'));
          }
          .width('100%')
          .padding({ top: 14, bottom: 24 });
        }
        .width('100%')
        .layoutWeight(1);
      }
      this.BottomActions();
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
        Text('服务桥')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('跨部门服务请求流转')
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
  StateCard(text: string) {
    Column() {
      Text(text)
        .fontSize(14)
        .fontColor('#6B7280');
    }
    .width('100%')
    .layoutWeight(1)
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center);
  }

  @Builder
  SummaryCard() {
    Row({ space: 8 }) {
      Text('服务工单')
        .fontSize(15)
        .fontColor('#374151')
        .layoutWeight(1);
      Text(`共 ${this.requests.length} 条`)
        .fontSize(13)
        .fontColor('#1D4ED8')
        .padding({ left: 10, right: 10, top: 5, bottom: 5 })
        .backgroundColor('#E8F0FF')
        .borderRadius(10);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  RequestCard(req: ServiceBridgeRequest) {
    Column({ space: 8 }) {
      Row({ space: 12 }) {
        Column({ space: 4 }) {
          Text(cleanText(req.title, '服务请求'))
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis });
          Text(`${cleanText(req.source_instance_name, cleanText(req.source_instance_id, '来源未知'))} · ${this.formatTime(req.created_at)}`)
            .fontSize(12)
            .fontColor('#6B7280')
            .maxLines(1);
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);

        Text(this.statusLabel(req.status))
          .fontSize(12)
          .fontColor(this.statusColor(req.status))
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor(this.statusBgColor(req.status))
          .borderRadius(10);
      }
      .width('100%');

      if (cleanText(req.description, '').length > 0) {
        Text(cleanText(req.description, ''))
          .width('100%')
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .lineHeight(18);
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Start)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  BottomActions() {
    Column() {
      Button('发起请求')
        .height(46)
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(12)
        .width('100%')
        .onClick(() => {
          this.showCreateDialog();
        });
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 6, bottom: 14 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  private showCreateDialog(): void {
    AlertDialog.show({
      title: '发起服务请求',
      message: '请在电脑端服务桥页面填写请求标题、目标部门与详细说明,移动端暂不支持完整表单录入。',
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '知道了',
        action: () => {}
      }
    });
  }

  private formatTime(iso: string | undefined): string {
    const value = cleanText(iso, '');
    if (value.length === 0) {
      return '';
    }
    const cleaned = value.replace('T', ' ');
    return cleaned.length >= 16 ? cleaned.substring(0, 16) : cleaned;
  }

  private statusLabel(status: string | undefined): string {
    const s = cleanText(status, '');
    if (s === 'pending') return '待处理';
    if (s === 'processing' || s === 'in_progress') return '处理中';
    if (s === 'resolved' || s === 'done' || s === 'completed') return '已完成';
    if (s === 'rejected') return '已驳回';
    return s.length > 0 ? s : '待处理';
  }

  private statusColor(status: string | undefined): string {
    const s = cleanText(status, '');
    if (s === 'pending') return '#92400E';
    if (s === 'processing' || s === 'in_progress') return '#1D4ED8';
    if (s === 'resolved' || s === 'done' || s === 'completed') return '#166534';
    if (s === 'rejected') return '#B91C1C';
    return '#4B5563';
  }

  private statusBgColor(status: string | undefined): string {
    const s = cleanText(status, '');
    if (s === 'pending') return '#FEF3C7';
    if (s === 'processing' || s === 'in_progress') return '#E8F0FF';
    if (s === 'resolved' || s === 'done' || s === 'completed') return '#E7F7EE';
    if (s === 'rejected') return '#FEE2E2';
    return '#F3F4F6';
  }
}

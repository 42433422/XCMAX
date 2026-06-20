/**
 * 服务桥页面。
 *
 * 对标 Android BridgeScreen.kt：服务请求列表 + 发起请求。
 * 本地 mock 3-5 条服务请求，每条含标题、状态、时间。
 */

interface BridgeRequest {
  requestId: string;
  title: string;
  status: string;
  timeText: string;
}

@Component
export struct BridgePage {
  @State requests: BridgeRequest[] = [
    {
      requestId: 'r1',
      title: '财务部-月度报表导出协助',
      status: 'pending',
      timeText: '今天 09:32'
    },
    {
      requestId: 'r2',
      title: '市场部-活动素材审核请求',
      status: 'processing',
      timeText: '今天 10:15'
    },
    {
      requestId: 'r3',
      title: '运维-服务器扩容评估',
      status: 'done',
      timeText: '昨天 16:40'
    },
    {
      requestId: 'r4',
      title: '行政-办公用品采购审批',
      status: 'pending',
      timeText: '昨天 14:20'
    }
  ];

  onBack: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.SummaryCard();
          ForEach(this.requests, (req: BridgeRequest) => {
            this.RequestCard(req);
          }, (req: BridgeRequest) => req.requestId);
        }
        .width('100%')
        .padding({ top: 14, bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);
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
  SummaryCard() {
    Row({ space: 8 }) {
      Text('待处理工单')
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
  RequestCard(req: BridgeRequest) {
    Row({ space: 12 }) {
      Column({ space: 4 }) {
        Text(req.title)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(req.timeText)
          .fontSize(12)
          .fontColor('#6B7280');
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
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
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
      message: '请在电脑端服务桥页面填写请求标题、目标部门与详细说明，移动端暂不支持完整表单录入。',
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

  private statusLabel(status: string): string {
    if (status === 'pending') return '待处理';
    if (status === 'processing') return '处理中';
    if (status === 'done') return '已完成';
    return status;
  }

  private statusColor(status: string): string {
    if (status === 'pending') return '#92400E';
    if (status === 'processing') return '#1D4ED8';
    if (status === 'done') return '#166534';
    return '#4B5563';
  }

  private statusBgColor(status: string): string {
    if (status === 'pending') return '#FEF3C7';
    if (status === 'processing') return '#E8F0FF';
    if (status === 'done') return '#E7F7EE';
    return '#F3F4F6';
  }
}

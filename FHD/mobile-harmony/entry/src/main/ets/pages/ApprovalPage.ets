import { MobileApiClient } from '../api/MobileApiClient';
import { ApprovalDetail, ApprovalItem } from '../models/MobileModels';

/**
 * 审批页面（列表 + 详情双模式）。
 *
 * 对标 Android ApprovalScreens.kt：
 * - 列表模式：调用 api.approvals() 加载待办审批列表。
 * - 详情模式：调用 api.approvalDetail(id) 加载详情，支持通过/驳回操作。
 *
 * 通过 @State mode 在 'list' / 'detail' 之间切换，无需路由跳转。
 */
@Component
export struct ApprovalPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State mode: string = 'list';
  @State items: ApprovalItem[] = [];
  @State detail: ApprovalDetail = {
    id: '', title: '', requestNo: '', applicantName: '',
    flowName: '', currentNodeName: '', submittedAt: '',
    description: '', status: ''
  };
  @State detailLoaded: boolean = false;
  @State loading: boolean = false;
  @State errorMsg: string = '';
  @State opinion: string = '';
  @State actionInProgress: boolean = false;

  private api: MobileApiClient = new MobileApiClient('', '');
  private currentId: number = 0;

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadList();
  }

  build() {
    Column() {
      this.Header();
      if (this.mode === 'list') {
        this.ListArea();
      } else {
        this.DetailArea();
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  // ── Header ──

  @Builder
  Header() {
    Row({ space: 12 }) {
      Text('<')
        .width(36)
        .height(36)
        .fontSize(22)
        .fontColor('#111827')
        .textAlign(TextAlign.Center)
        .onClick(() => this.handleBack());
      Column({ space: 2 }) {
        Text(this.mode === 'list' ? '审批' : (this.detailLoaded ? this.detail.title : '审批详情'))
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(this.mode === 'list' ? '待处理审批事项' : '审批详情与处理')
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

  // ── 列表模式 ──

  @Builder
  ListArea() {
    Scroll() {
      Column({ space: 10 }) {
        if (this.loading) {
          this.LoadingCard('加载中...');
        } else if (this.errorMsg.length > 0) {
          this.ErrorCard(this.errorMsg);
        } else if (this.items.length === 0) {
          this.EmptyCard('暂无待办审批', '当前没有需要您处理的审批事项。');
        } else {
          this.SectionCaption('待处理');
          ForEach(this.items, (item: ApprovalItem) => {
            this.ApprovalListCard(item);
          }, (item: ApprovalItem) => item.id);
        }
      }
      .width('100%')
      .padding({ top: 14, bottom: 24 });
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  ApprovalListCard(item: ApprovalItem) {
    Row({ space: 12 }) {
      Column({ space: 4 }) {
        Text(item.title)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(item.subtitle.length > 0 ? item.subtitle : item.applicantName)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      if (item.status.length > 0) {
        Text(this.statusLabel(item.status))
          .fontSize(12)
          .fontColor(this.statusColor(item.status))
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor(this.statusBgColor(item.status))
          .borderRadius(10);
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.openDetail(item));
  }

  // ── 详情模式 ──

  @Builder
  DetailArea() {
    Column() {
      Scroll() {
        Column({ space: 14 }) {
          if (this.loading) {
            this.LoadingCard('加载中...');
          } else if (this.errorMsg.length > 0) {
            this.ErrorCard(this.errorMsg);
          } else if (this.detailLoaded) {
            this.DetailInfoCard();
            this.DetailOpinionCard();
          }
        }
        .width('100%')
        .padding({ top: 14, bottom: 20 });
      }
      .width('100%')
      .layoutWeight(1);

      if (this.detailLoaded && this.canAct()) {
        this.DetailActions();
      }
    }
    .width('100%')
    .height('100%');
  }

  @Builder
  DetailInfoCard() {
    Column({ space: 0 }) {
      this.SectionCaption('审批信息');
      this.DetailRow('单号', this.detail.requestNo.length > 0 ? this.detail.requestNo : `#${this.detail.id}`, true);
      this.DetailRow('发起人', this.detail.applicantName, this.detail.flowName.length > 0);
      if (this.detail.flowName.length > 0) {
        this.DetailRow('流程', this.detail.flowName, this.detail.currentNodeName.length > 0);
      }
      if (this.detail.currentNodeName.length > 0) {
        this.DetailRow('当前节点', this.detail.currentNodeName, this.detail.submittedAt.length > 0);
      }
      if (this.detail.submittedAt.length > 0) {
        this.DetailRow('提交时间', this.detail.submittedAt, this.detail.description.length > 0);
      }
      if (this.detail.description.length > 0) {
        this.DetailRow('说明', this.detail.description, false);
      }
      this.DetailRow('状态', this.statusLabel(this.detail.status), false);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  DetailRow(label: string, value: string, showDivider: boolean) {
    Row({ space: 12 }) {
      Text(label)
        .width(76)
        .fontSize(14)
        .fontColor('#4B5563');
      Text(value)
        .fontSize(14)
        .fontColor('#111827')
        .maxLines(3)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ top: 10, bottom: 10 })
    .border(showDivider ? { width: { bottom: 1 }, color: '#F3F4F6' } : { width: 0 });
  }

  @Builder
  DetailOpinionCard() {
    Column({ space: 10 }) {
      this.SectionCaption('审批意见');
      TextInput({
        placeholder: '输入审批意见（可选）',
        text: this.opinion
      })
        .height(80)
        .fontSize(14)
        .fontColor('#111827')
        .placeholderColor('#7B8794')
        .backgroundColor('#F8FAFC')
        .borderRadius(10)
        .border({ width: 1, color: '#D8E0EA' })
        .padding({ left: 12, right: 12, top: 8, bottom: 8 })
        .onChange((value: string) => {
          this.opinion = value;
        });
      Text('复杂编辑请在电脑端处理')
        .fontSize(12)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  DetailActions() {
    Column({ space: 10 }) {
      Button('通过')
        .height(46)
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor(this.actionInProgress ? '#9CA3AF' : '#18A85F')
        .borderRadius(12)
        .width('100%')
        .enabled(!this.actionInProgress)
        .onClick(() => this.showConfirmDialog('approve'));
      Button('驳回')
        .height(46)
        .fontSize(15)
        .fontColor('#1D4ED8')
        .backgroundColor(this.actionInProgress ? '#F3F4F6' : '#E8F0FF')
        .borderRadius(12)
        .width('100%')
        .enabled(!this.actionInProgress)
        .onClick(() => this.showConfirmDialog('reject'));
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 6, bottom: 14 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  // ── 通用 Builder ──

  @Builder
  SectionCaption(text: string) {
    Text(text)
      .fontSize(13)
      .fontColor('#6B7280')
      .margin({ left: 14, right: 14, top: 4, bottom: 2 });
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

  @Builder
  LoadingCard(text: string) {
    Column({ space: 8 }) {
      Text(text)
        .fontSize(15)
        .fontColor('#4B5563');
    }
    .width('100%')
    .padding(24)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ErrorCard(message: string) {
    Column({ space: 8 }) {
      Text('加载失败')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#991B1B');
      Text(message)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(20)
        .textAlign(TextAlign.Center);
      Button('重试')
        .height(38)
        .fontSize(14)
        .fontColor('#1D4ED8')
        .backgroundColor('#E8F0FF')
        .borderRadius(10)
        .margin({ top: 6 })
        .onClick(() => {
          if (this.mode === 'list') {
            this.loadList();
          } else {
            this.loadDetail(this.currentId);
          }
        });
    }
    .width('100%')
    .padding(24)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  // ── 业务逻辑 ──

  private handleBack(): void {
    if (this.mode === 'detail') {
      this.mode = 'list';
      this.detailLoaded = false;
      this.detail = {
        id: '', title: '', requestNo: '', applicantName: '',
        flowName: '', currentNodeName: '', submittedAt: '',
        description: '', status: ''
      };
      this.opinion = '';
      this.errorMsg = '';
      this.loadList();
    } else {
      this.onBack();
    }
  }

  private openDetail(item: ApprovalItem): void {
    const id = parseInt(item.id, 10);
    if (!(id > 0)) return;
    this.currentId = id;
    this.mode = 'detail';
    this.detailLoaded = false;
    this.opinion = '';
    this.errorMsg = '';
    this.loadDetail(id);
  }

  private async loadList(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.items = await this.api.approvals();
    } catch (err) {
      this.errorMsg = this.errorMessage(err);
    } finally {
      this.loading = false;
    }
  }

  private async loadDetail(id: number): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.detail = await this.api.approvalDetail(id);
      this.detailLoaded = true;
    } catch (err) {
      this.errorMsg = this.errorMessage(err);
    } finally {
      this.loading = false;
    }
  }

  private showConfirmDialog(action: string): void {
    if (this.actionInProgress) return;
    const title: string = action === 'approve' ? '确认通过' : '确认驳回';
    const message: string = action === 'approve' ? '确定通过该审批？' : '确定驳回该审批？';
    AlertDialog.show({
      title: title,
      message: message,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '确定',
        action: () => {
          if (action === 'approve') {
            this.doApprove();
          } else {
            this.doReject();
          }
        }
      }
    });
  }

  private async doApprove(): Promise<void> {
    if (this.actionInProgress) return;
    this.actionInProgress = true;
    try {
      await this.api.approve(this.currentId, this.opinion);
      this.returnToList();
    } catch (err) {
      this.errorMsg = `通过失败：${this.errorMessage(err)}`;
    } finally {
      this.actionInProgress = false;
    }
  }

  private async doReject(): Promise<void> {
    if (this.actionInProgress) return;
    this.actionInProgress = true;
    try {
      await this.api.reject(this.currentId, this.opinion);
      this.returnToList();
    } catch (err) {
      this.errorMsg = `驳回失败：${this.errorMessage(err)}`;
    } finally {
      this.actionInProgress = false;
    }
  }

  private returnToList(): void {
    this.mode = 'list';
    this.detailLoaded = false;
    this.detail = {
      id: '', title: '', requestNo: '', applicantName: '',
      flowName: '', currentNodeName: '', submittedAt: '',
      description: '', status: ''
    };
    this.opinion = '';
    this.errorMsg = '';
    this.loadList();
  }

  private canAct(): boolean {
    const status = this.detail.status.toLowerCase();
    return status.indexOf('pending') >= 0 || this.detail.status.indexOf('待') >= 0;
  }

  private statusLabel(status: string): string {
    if (status.length === 0) return '';
    const lower = status.toLowerCase();
    if (lower.indexOf('pending') >= 0 || status.indexOf('待') >= 0) return '待处理';
    if (lower.indexOf('approved') >= 0 || status.indexOf('通过') >= 0) return '已通过';
    if (lower.indexOf('rejected') >= 0 || status.indexOf('驳回') >= 0) return '已驳回';
    return status;
  }

  private statusColor(status: string): string {
    const lower = status.toLowerCase();
    if (lower.indexOf('pending') >= 0 || status.indexOf('待') >= 0) return '#92400E';
    if (lower.indexOf('approved') >= 0 || status.indexOf('通过') >= 0) return '#166534';
    if (lower.indexOf('rejected') >= 0 || status.indexOf('驳回') >= 0) return '#991B1B';
    return '#4B5563';
  }

  private statusBgColor(status: string): string {
    const lower = status.toLowerCase();
    if (lower.indexOf('pending') >= 0 || status.indexOf('待') >= 0) return '#FEF3C7';
    if (lower.indexOf('approved') >= 0 || status.indexOf('通过') >= 0) return '#E7F7EE';
    if (lower.indexOf('rejected') >= 0 || status.indexOf('驳回') >= 0) return '#FEE2E2';
    return '#F3F4F6';
  }

  private errorMessage(err: object): string {
    const message = (err as Error).message;
    return message && message.length > 0 ? message : '未知错误';
  }
}

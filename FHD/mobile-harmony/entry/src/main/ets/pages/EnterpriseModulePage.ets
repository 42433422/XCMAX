/**
 * 企业模块详情页面。
 *
 * 对标 Android EnterpriseScreens.kt(ERP 客户/发货 真列表)。
 * - customer  → GET /api/mobile/v1/customers(真数据:名称/电话)
 * - shipment  → GET /api/mobile/v1/shipments(真数据:单号/状态)
 * - approval  → 跳转审批入口(ApprovalPage,真审批流)
 * - erp/inventory/analytics → 移动端无对应只读端点,诚实提示在桌面端处理。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { CustomerItem, ShipmentItem, cleanText } from '../models/MobileModels';

interface ModuleRow {
  id: string;
  title: string;
  subtitle: string;
  badge: string;
}

@Component
export struct EnterpriseModulePage {
  @Consume baseUrl: string;
  @Consume accessToken: string;
  @Prop moduleTitle: string = '';
  @Prop moduleId: string = '';

  onBack: () => void = () => {};
  onOpenFeature: (featureId: string) => void = () => {};
  onOpenApproval: () => void = () => {};

  @State rows: ModuleRow[] = [];
  @State loading: boolean = false;
  @State errorMsg: string = '';

  private api: MobileApiClient = new MobileApiClient('', '');

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadModuleData();
  }

  private hasMobileData(): boolean {
    return this.moduleId === 'customer' || this.moduleId === 'shipment';
  }

  private async loadModuleData(): Promise<void> {
    if (!this.hasMobileData()) {
      return;
    }
    this.loading = true;
    this.errorMsg = '';
    try {
      if (this.moduleId === 'customer') {
        const data = await this.api.customers(1);
        const items: CustomerItem[] = data.items || [];
        this.rows = items.map((c: CustomerItem) => {
          const row: ModuleRow = {
            id: c.id !== undefined ? c.id.toString() : 'c',
            title: cleanText(c.name, '未命名客户'),
            subtitle: cleanText(c.phone, '无联系电话'),
            badge: '客户'
          };
          return row;
        });
      } else {
        const data = await this.api.shipments(1);
        const items: ShipmentItem[] = data.items || [];
        this.rows = items.map((s: ShipmentItem) => {
          const row: ModuleRow = {
            id: s.id !== undefined ? s.id.toString() : 's',
            title: cleanText(s.order_number, s.id !== undefined ? `发货单 #${s.id}` : '发货单'),
            subtitle: '发货记录',
            badge: cleanText(s.status, '待处理')
          };
          return row;
        });
      }
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.ModuleIntroCard();
          if (this.moduleId === 'approval') {
            this.ApprovalEntryCard();
          } else if (!this.hasMobileData()) {
            this.DesktopOnlyCard();
          } else if (this.loading && this.rows.length === 0) {
            this.NoteCard('加载中...');
          } else if (this.errorMsg.length > 0 && this.rows.length === 0) {
            this.NoteCard(this.errorMsg);
          } else if (this.rows.length === 0) {
            this.NoteCard('暂无数据');
          } else {
            this.SectionCaption(`${this.moduleId === 'customer' ? '客户' : '发货'}列表 · ${this.rows.length} 条`);
            ForEach(this.rows, (item: ModuleRow) => {
              this.DataRow(item);
            }, (item: ModuleRow) => item.id);
          }
        }
        .width('100%')
        .padding({ bottom: 24 });
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
        Text(this.moduleTitle.length > 0 ? this.moduleTitle : this.moduleName())
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(this.moduleSubtitle())
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
  ModuleIntroCard() {
    Row({ space: 12 }) {
      Text(this.moduleIconText())
        .width(44)
        .height(44)
        .borderRadius(12)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(this.moduleAccentColor());
      Text(this.moduleDescription())
        .fontSize(13)
        .fontColor('#4B5563')
        .lineHeight(20)
        .layoutWeight(1);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14, top: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  SectionCaption(text: string) {
    Text(text)
      .fontSize(13)
      .fontColor('#6B7280')
      .margin({ left: 14, right: 14, top: 4, bottom: 2 });
  }

  @Builder
  DataRow(item: ModuleRow) {
    Row({ space: 12 }) {
      Column({ space: 4 }) {
        Text(item.title)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(item.subtitle)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text(item.badge)
        .fontSize(12)
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
  ApprovalEntryCard() {
    Column({ space: 10 }) {
      Text('审批流程在专属审批入口处理')
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
      Text('点击下方进入待办审批,可查看详情并通过 / 驳回。')
        .fontSize(13)
        .fontColor('#4B5563')
        .lineHeight(20);
      Button('进入待办审批')
        .width('100%')
        .height(42)
        .onClick(() => this.onOpenApproval());
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
  DesktopOnlyCard() {
    Column({ space: 8 }) {
      Text('该模块请在桌面端企业模块处理')
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
      Text('移动端目前提供客户、发货、审批的只读 / 处理能力。库存、ERP、数据分析等完整功能请在电脑端企业模块中操作。')
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(20);
    }
    .width('100%')
    .padding(20)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Start)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  NoteCard(text: string) {
    Column() {
      Text(text)
        .fontSize(14)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding(24)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private moduleName(): string {
    if (this.moduleId === 'erp') return 'ERP管理';
    if (this.moduleId === 'customer') return '客户管理';
    if (this.moduleId === 'inventory') return '库存管理';
    if (this.moduleId === 'shipment') return '发货管理';
    if (this.moduleId === 'approval') return '审批管理';
    if (this.moduleId === 'analytics') return '数据分析';
    return '企业模块';
  }

  private moduleSubtitle(): string {
    if (this.moduleId === 'customer') return '客户运营 · 真实数据';
    if (this.moduleId === 'shipment') return '发货物流 · 真实数据';
    if (this.moduleId === 'approval') return '审批流程 · 待办处理';
    return '企业模块 · 桌面端处理';
  }

  private moduleIconText(): string {
    if (this.moduleId === 'erp') return 'ERP';
    if (this.moduleId === 'customer') return '客户';
    if (this.moduleId === 'inventory') return '库存';
    if (this.moduleId === 'shipment') return '发货';
    if (this.moduleId === 'approval') return '审批';
    if (this.moduleId === 'analytics') return '分析';
    return '模块';
  }

  private moduleAccentColor(): string {
    if (this.moduleId === 'erp') return '#1D4ED8';
    if (this.moduleId === 'customer') return '#047857';
    if (this.moduleId === 'inventory') return '#B45309';
    if (this.moduleId === 'shipment') return '#7C3AED';
    if (this.moduleId === 'approval') return '#BE185D';
    if (this.moduleId === 'analytics') return '#0369A1';
    return '#4B5563';
  }

  private moduleDescription(): string {
    if (this.moduleId === 'customer') return '客户档案、联系电话与基础信息,数据来自企业端实时同步。';
    if (this.moduleId === 'shipment') return '发货单、单号与状态,数据来自企业端实时同步。';
    if (this.moduleId === 'approval') return '待办审批、流程节点、通过 / 驳回与意见填写。';
    if (this.moduleId === 'erp') return '订单、采购、财务一体化管理,完整能力在桌面端企业模块。';
    if (this.moduleId === 'inventory') return '商品库存、出入库流水、盘点与预警,完整能力在桌面端。';
    if (this.moduleId === 'analytics') return '经营看板、销售统计、趋势分析与报表导出,完整能力在桌面端。';
    return '企业模块详情,请在电脑端进行复杂操作。';
  }
}

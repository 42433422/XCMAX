/**
 * 企业模块列表页面。
 *
 * 对标 Android EnterpriseListScreen 与前端企业模块入口：
 * 展示企业核心模块卡片（ERP / 客户 / 库存 / 发货 / 审批 / 数据分析），
 * 点击模块卡片触发 onOpenModule 回调，由上层路由进入对应模块详情。
 */
@Component
export struct EnterprisePage {
  onBack: () => void = () => {};
  onOpenModule: (moduleId: string) => void = () => {};

  @State modules: EnterpriseModuleItem[] = [];

  aboutToAppear(): void {
    this.modules = this.buildModules();
  }

  build() {
    this.EnterpriseArea();
  }

  @Builder
  EnterpriseArea() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.SummaryCard();
          if (this.modules.length === 0) {
            this.EmptyCard('暂无企业模块', '企业端尚未启用任何模块，连接企业端后模块会在这里展示。');
          } else {
            ForEach(this.modules, (item: EnterpriseModuleItem) => {
              this.ModuleCard(item);
            }, (item: EnterpriseModuleItem) => item.moduleId);
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
        Text('企业模块')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('企业核心业务入口')
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
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        Text('已启用模块')
          .fontSize(15)
          .fontColor('#374151')
          .layoutWeight(1);
        Text(`${this.modules.length}`)
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .fontColor('#1D4ED8');
      }
      .width('100%');

      Text('点击模块卡片进入对应业务详情。复杂操作请在电脑端企业模块中处理。')
        .fontSize(12)
        .fontColor('#6B7280')
        .lineHeight(18);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14, top: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ModuleCard(item: EnterpriseModuleItem) {
    Row({ space: 14 }) {
      Text(item.iconText)
        .width(48)
        .height(48)
        .borderRadius(14)
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(item.accentColor);

      Column({ space: 3 }) {
        Text(item.name)
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text(item.description)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('>')
        .fontSize(20)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.onOpenModule(item.moduleId));
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

  private buildModules(): EnterpriseModuleItem[] {
    const list: EnterpriseModuleItem[] = [];
    const erp: EnterpriseModuleItem = {
      moduleId: 'erp',
      name: 'ERP管理',
      description: '订单 / 采购 / 财务一体化，企业资源计划核心入口。',
      iconText: 'ERP',
      accentColor: '#1D4ED8'
    };
    const customer: EnterpriseModuleItem = {
      moduleId: 'customer',
      name: '客户管理',
      description: '客户档案、跟进记录、分级运营与客户画像。',
      iconText: '客户',
      accentColor: '#047857'
    };
    const inventory: EnterpriseModuleItem = {
      moduleId: 'inventory',
      name: '库存管理',
      description: '商品库存、出入库流水、盘点与预警。',
      iconText: '库存',
      accentColor: '#B45309'
    };
    const shipment: EnterpriseModuleItem = {
      moduleId: 'shipment',
      name: '发货管理',
      description: '发货单、物流跟踪、签收与异常处理。',
      iconText: '发货',
      accentColor: '#7C3AED'
    };
    const approval: EnterpriseModuleItem = {
      moduleId: 'approval',
      name: '审批管理',
      description: '待办审批、流程节点、通过 / 驳回处理。',
      iconText: '审批',
      accentColor: '#BE185D'
    };
    const analytics: EnterpriseModuleItem = {
      moduleId: 'analytics',
      name: '数据分析',
      description: '经营看板、销售统计、趋势分析与报表导出。',
      iconText: '分析',
      accentColor: '#0369A1'
    };
    list.push(erp);
    list.push(customer);
    list.push(inventory);
    list.push(shipment);
    list.push(approval);
    list.push(analytics);
    return list;
  }
}

/**
 * 企业模块卡片本地数据模型。
 */
interface EnterpriseModuleItem {
  moduleId: string;
  name: string;
  description: string;
  iconText: string;
  accentColor: string;
}

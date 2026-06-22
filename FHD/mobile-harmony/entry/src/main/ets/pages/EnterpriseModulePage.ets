/**
 * 企业模块详情页面。
 *
 * 对标 Android EnterpriseModuleScreen：根据传入的 moduleId 与 moduleTitle
 * 展示该模块下的功能项列表。点击功能项触发 onOpenFeature 回调。
 *
 * 本页使用本地 mock 数据，按 moduleId 分组返回不同功能项。
 */
@Component
export struct EnterpriseModulePage {
  @Prop moduleTitle: string = '';
  @Prop moduleId: string = '';

  onBack: () => void = () => {};
  onOpenFeature: (featureId: string) => void = () => {};

  @State features: EnterpriseFeatureItem[] = [];

  aboutToAppear(): void {
    this.features = this.buildFeatures(this.moduleId);
  }

  build() {
    this.ModuleDetailArea();
  }

  @Builder
  ModuleDetailArea() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.ModuleIntroCard();
          if (this.features.length === 0) {
            this.EmptyCard('暂无功能项', '该模块尚未配置功能项，请在电脑端企业模块中开启。');
          } else {
            this.SectionCaption('功能列表');
            ForEach(this.features, (item: EnterpriseFeatureItem) => {
              this.FeatureCard(item);
            }, (item: EnterpriseFeatureItem) => item.featureId);
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
        Text(this.moduleTitle.length > 0 ? this.moduleTitle : '企业模块')
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
    Column({ space: 8 }) {
      Row({ space: 8 }) {
        Text(this.moduleIconText())
          .width(44)
          .height(44)
          .borderRadius(12)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .textAlign(TextAlign.Center)
          .backgroundColor(this.moduleAccentColor());
        Column({ space: 2 }) {
          Text(this.moduleTitle.length > 0 ? this.moduleTitle : '企业模块')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(`共 ${this.features.length} 项功能`)
            .fontSize(12)
            .fontColor('#6B7280');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      Text(this.moduleDescription())
        .fontSize(13)
        .fontColor('#4B5563')
        .lineHeight(20);
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
  FeatureCard(item: EnterpriseFeatureItem) {
    Row({ space: 12 }) {
      Column({ space: 4 }) {
        Text(item.name)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(item.description)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('>')
        .fontSize(18)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.onOpenFeature(item.featureId));
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

  private moduleSubtitle(): string {
    if (this.moduleId === 'erp') return '企业资源计划 · 功能列表';
    if (this.moduleId === 'customer') return '客户运营 · 功能列表';
    if (this.moduleId === 'inventory') return '库存管理 · 功能列表';
    if (this.moduleId === 'shipment') return '发货物流 · 功能列表';
    if (this.moduleId === 'approval') return '审批流程 · 功能列表';
    if (this.moduleId === 'analytics') return '数据分析 · 功能列表';
    return '企业模块 · 功能列表';
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
    if (this.moduleId === 'erp') return '订单、采购、财务一体化管理，支持多组织协同与单据流转。';
    if (this.moduleId === 'customer') return '客户档案、跟进记录、分级运营，构建完整客户画像。';
    if (this.moduleId === 'inventory') return '商品库存、出入库流水、盘点与预警，实时掌握库存动态。';
    if (this.moduleId === 'shipment') return '发货单管理、物流跟踪、签收确认与异常处理。';
    if (this.moduleId === 'approval') return '待办审批、流程节点查看、通过 / 驳回与意见填写。';
    if (this.moduleId === 'analytics') return '经营看板、销售统计、趋势分析与报表导出。';
    return '企业模块详情，请在电脑端进行复杂操作。';
  }

  private buildFeatures(moduleId: string): EnterpriseFeatureItem[] {
    const list: EnterpriseFeatureItem[] = [];
    if (moduleId === 'erp') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'erp-order',
        name: '订单管理',
        description: '销售订单创建、修改、查询与状态跟踪。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'erp-purchase',
        name: '采购管理',
        description: '采购订单、供应商对账与入库单据。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'erp-finance',
        name: '财务管理',
        description: '应收应付、收付款单与财务报表。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'erp-supplier',
        name: '供应商管理',
        description: '供应商档案、评级与合同管理。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    if (moduleId === 'customer') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'customer-archive',
        name: '客户档案',
        description: '客户基本信息、联系人、地址与资质。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'customer-follow',
        name: '跟进记录',
        description: '拜访记录、沟通日志与下次跟进提醒。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'customer-level',
        name: '分级运营',
        description: '客户分级、标签体系与差异化运营策略。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'customer-portrait',
        name: '客户画像',
        description: '交易行为、偏好分析与画像标签。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    if (moduleId === 'inventory') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'inventory-stock',
        name: '库存查询',
        description: '商品实时库存、可用量与占用查询。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'inventory-inout',
        name: '出入库流水',
        description: '入库、出库、调拨单据与流水记录。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'inventory-check',
        name: '盘点管理',
        description: '盘点任务、差异处理与盘点报告。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'inventory-alert',
        name: '库存预警',
        description: '最低库存、保质期与滞销预警。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    if (moduleId === 'shipment') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'shipment-order',
        name: '发货单',
        description: '发货单创建、打印与状态管理。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'shipment-tracking',
        name: '物流跟踪',
        description: '物流单号、轨迹查询与节点回传。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'shipment-sign',
        name: '签收确认',
        description: '签收回执、异常签收与拒收处理。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'shipment-exception',
        name: '异常处理',
        description: '破损、丢失、延误等异常工单。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    if (moduleId === 'approval') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'approval-todo',
        name: '待办审批',
        description: '当前用户待处理的审批事项列表。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'approval-history',
        name: '审批历史',
        description: '已处理审批记录与处理意见。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'approval-flow',
        name: '流程节点',
        description: '审批流程图、节点状态与处理人。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'approval-initiate',
        name: '发起审批',
        description: '选择流程模板并发起新的审批申请。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    if (moduleId === 'analytics') {
      const f1: EnterpriseFeatureItem = {
        featureId: 'analytics-dashboard',
        name: '经营看板',
        description: '关键经营指标实时看板与趋势。'
      };
      const f2: EnterpriseFeatureItem = {
        featureId: 'analytics-sales',
        name: '销售统计',
        description: '销售额、订单量、客户数多维统计。'
      };
      const f3: EnterpriseFeatureItem = {
        featureId: 'analytics-trend',
        name: '趋势分析',
        description: '同比环比、增长率与预测分析。'
      };
      const f4: EnterpriseFeatureItem = {
        featureId: 'analytics-report',
        name: '报表导出',
        description: '自定义报表与 Excel / PDF 导出。'
      };
      list.push(f1);
      list.push(f2);
      list.push(f3);
      list.push(f4);
      return list;
    }
    const fallback: EnterpriseFeatureItem = {
      featureId: 'unknown',
      name: '暂无功能',
      description: '该模块尚未配置功能项。'
    };
    list.push(fallback);
    return list;
  }
}

/**
 * 企业模块功能项本地数据模型。
 */
interface EnterpriseFeatureItem {
  featureId: string;
  name: string;
  description: string;
}

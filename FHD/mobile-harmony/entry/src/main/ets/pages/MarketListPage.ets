/**
 * 应用市场页面。
 *
 * 对标 Android MarketListScreen.kt：MOD 列表展示与安装。
 * 本地 mock 6 个 MOD，每个卡片含图标、名称、描述、安装按钮。
 */

interface MarketMod {
  modId: string;
  iconText: string;
  iconColor: string;
  name: string;
  description: string;
  version: string;
  installed: boolean;
}

@Component
export struct MarketListPage {
  @State mods: MarketMod[] = [
    {
      modId: 'mod-invoice-ocr',
      iconText: '票',
      iconColor: '#1D4ED8',
      name: '票据 OCR 识别',
      description: '识别发票、收据、表格截图，自动提取关键字段并归档。',
      version: 'v2.4.1',
      installed: true
    },
    {
      modId: 'mod-duty-roster',
      iconText: '岗',
      iconColor: '#BE185D',
      name: '值班编制管理',
      description: '按区域展示在岗员工，支持入岗状态与组织架构同步。',
      version: 'v1.8.0',
      installed: true
    },
    {
      modId: 'mod-approval-flow',
      iconText: '审',
      iconColor: '#7C3AED',
      name: '审批流程引擎',
      description: '多级审批流配置，支持通过、驳回、加签与委托。',
      version: 'v3.1.2',
      installed: false
    },
    {
      modId: 'mod-bridge-service',
      iconText: '桥',
      iconColor: '#047857',
      name: '服务桥接工单',
      description: '跨部门服务请求流转，支持工单分派、回复与状态追踪。',
      version: 'v1.5.3',
      installed: false
    },
    {
      modId: 'mod-neuro-bus',
      iconText: '神',
      iconColor: '#B45309',
      name: 'Neuro Bus 事件中枢',
      description: '事件发布订阅、去重、熔断、死信队列与 SLA 分层调度。',
      version: 'v4.0.0',
      installed: true
    },
    {
      modId: 'mod-market-sync',
      iconText: '市',
      iconColor: '#0369A1',
      name: '市场同步通道',
      description: '从 MODstore 拉取行业能力包，自动同步到企业端生态。',
      version: 'v2.0.6',
      installed: false
    }
  ];

  onBack: () => void = () => {};
  onOpenMod: (modId: string) => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.SummaryCard();
          ForEach(this.mods, (mod: MarketMod) => {
            this.ModCard(mod);
          }, (mod: MarketMod) => mod.modId);
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
        Text('应用市场')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('MODstore 能力包')
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
      Text('可用能力')
        .fontSize(15)
        .fontColor('#374151')
        .layoutWeight(1);
      Text(`共 ${this.mods.length} 个 MOD`)
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
  ModCard(mod: MarketMod) {
    Row({ space: 12 }) {
      Text(mod.iconText)
        .width(44)
        .height(44)
        .borderRadius(10)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(mod.iconColor);

      Column({ space: 3 }) {
        Row({ space: 8 }) {
          Text(mod.name)
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          Text(mod.version)
            .fontSize(11)
            .fontColor('#6B7280');
        }
        .width('100%');

        Text(mod.description)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .lineHeight(18);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Button(mod.installed ? '打开' : '安装')
        .height(34)
        .fontSize(13)
        .fontColor(mod.installed ? '#1D4ED8' : '#FFFFFF')
        .backgroundColor(mod.installed ? '#E8F0FF' : '#18A85F')
        .borderRadius(8)
        .onClick(() => {
          if (mod.installed) {
            this.onOpenMod(mod.modId);
          } else {
            this.installMod(mod.modId);
          }
        });
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private installMod(modId: string): void {
    const next: MarketMod[] = this.mods.map((mod: MarketMod) => {
      const updated: MarketMod = {
        modId: mod.modId,
        iconText: mod.iconText,
        iconColor: mod.iconColor,
        name: mod.name,
        description: mod.description,
        version: mod.version,
        installed: mod.modId === modId ? true : mod.installed
      };
      return updated;
    });
    this.mods = next;
  }
}

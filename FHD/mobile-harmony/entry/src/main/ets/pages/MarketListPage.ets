/**
 * 应用市场页面。
 *
 * 对标 Android MarketListScreen.kt：展示企业端已安装的 MOD 能力包(真数据)。
 * 数据源:GET /api/mobile/v1/mods(MobileApiClient.mods())。
 * 点击「打开」触发 onOpenMod(modId) → ModWebViewPage。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { ModInfo, cleanText, firstChar } from '../models/MobileModels';

const ICON_COLORS: string[] = ['#1D4ED8', '#BE185D', '#7C3AED', '#047857', '#B45309', '#0369A1'];

@Component
export struct MarketListPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State mods: ModInfo[] = [];
  @State loading: boolean = false;
  @State errorMsg: string = '';

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};
  onOpenMod: (modId: string) => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadMods();
  }

  private async loadMods(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      const data = await this.api.mods();
      this.mods = data.items || [];
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  private iconColor(mod: ModInfo): string {
    const seed = cleanText(mod.id, cleanText(mod.name, 'M'));
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
      hash = (hash + seed.charCodeAt(i)) % ICON_COLORS.length;
    }
    return ICON_COLORS[hash];
  }

  build() {
    Column() {
      this.Header();
      if (this.loading && this.mods.length === 0) {
        this.StateCard('加载中...');
      } else if (this.errorMsg.length > 0 && this.mods.length === 0) {
        this.StateCard(this.errorMsg);
      } else if (this.mods.length === 0) {
        this.StateCard('企业端尚未启用任何 MOD');
      } else {
        Scroll() {
          Column({ space: 12 }) {
            this.SummaryCard();
            ForEach(this.mods, (mod: ModInfo) => {
              this.ModCard(mod);
            }, (mod: ModInfo) => cleanText(mod.id, cleanText(mod.name, 'mod')));
          }
          .width('100%')
          .padding({ top: 14, bottom: 24 });
        }
        .width('100%')
        .layoutWeight(1);
      }
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
      Text('已启用能力')
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
  ModCard(mod: ModInfo) {
    Row({ space: 12 }) {
      Text(firstChar(cleanText(mod.name, 'M')))
        .width(44)
        .height(44)
        .borderRadius(10)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(this.iconColor(mod));

      Column({ space: 3 }) {
        Row({ space: 8 }) {
          Text(cleanText(mod.name, '未命名 MOD'))
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          Text(cleanText(mod.version, ''))
            .fontSize(11)
            .fontColor('#6B7280');
        }
        .width('100%');

        Text(cleanText(mod.description, '企业能力包'))
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .lineHeight(18);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Button('打开')
        .height(34)
        .fontSize(13)
        .fontColor('#1D4ED8')
        .backgroundColor('#E8F0FF')
        .borderRadius(8)
        .onClick(() => this.onOpenMod(cleanText(mod.id, '')));
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }
}

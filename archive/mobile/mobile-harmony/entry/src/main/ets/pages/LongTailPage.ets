/**
 * 账户钱包页面(原长尾财务)。
 *
 * 对标 Android feature/finance/LongTailScreen.kt(钱包/会员/用量)。
 * 数据源:GET /api/mobile/v1/wallet/balance(代理 market /api/wallet/overview)。
 * 展示真实余额、会员等级、BYOK 配置与同步状态;未绑定市场账号时诚实提示。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { WalletBalanceData, cleanText } from '../models/MobileModels';

@Component
export struct LongTailPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State wallet: WalletBalanceData = {};
  @State loading: boolean = false;
  @State errorMsg: string = '';

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadWallet();
  }

  private async loadWallet(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.wallet = await this.api.walletBalance();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  private balanceText(): string {
    if (this.wallet.balance === undefined || this.wallet.balance === null) {
      return '--';
    }
    return this.wallet.balance.toFixed(2);
  }

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 14 }) {
          if (this.loading) {
            this.NoteCard('加载中...');
          } else if (this.errorMsg.length > 0) {
            this.NoteCard(this.errorMsg);
          } else {
            this.BalanceCard();
            this.DetailCard();
            if (cleanText(this.wallet.message, '').length > 0) {
              this.NoteCard(cleanText(this.wallet.message, ''));
            }
          }
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 24 });
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
        Text('账户钱包')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('余额 · 会员 · 用量')
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
  BalanceCard() {
    Column({ space: 10 }) {
      Text('市场钱包余额')
        .fontSize(13)
        .fontColor('#6B7280')
        .width('100%');
      Row({ space: 4 }) {
        Text(cleanText(this.wallet.currency, 'CNY') === 'CNY' ? '¥' : cleanText(this.wallet.currency, ''))
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text(this.balanceText())
          .fontSize(32)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
      }
      .alignItems(VerticalAlign.Bottom);
      Text(this.wallet.synced ? '已与市场账号同步' : '尚未同步市场账号')
        .fontSize(12)
        .fontColor(this.wallet.synced ? '#166534' : '#92400E')
        .padding({ left: 10, right: 10, top: 5, bottom: 5 })
        .backgroundColor(this.wallet.synced ? '#E7F7EE' : '#FEF3C7')
        .borderRadius(10);
    }
    .width('100%')
    .padding(18)
    .alignItems(HorizontalAlign.Start)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  DetailCard() {
    Column({ space: 0 }) {
      this.DetailRow('会员等级', cleanText(this.wallet.membership_level, '普通用户'));
      this.DetailRow('经验值', this.wallet.experience !== undefined ? `${this.wallet.experience}` : '--');
      this.DetailRow('自有模型(BYOK)', this.wallet.byok_configured ? `已配置 ${this.wallet.byok_count !== undefined ? this.wallet.byok_count : 0} 个` : '未配置');
      this.DetailRow('结算货币', cleanText(this.wallet.currency, 'CNY'));
    }
    .width('100%')
    .padding({ left: 16, right: 16 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  DetailRow(label: string, value: string) {
    Row({ space: 12 }) {
      Text(label)
        .fontSize(14)
        .fontColor('#4B5563')
        .layoutWeight(1);
      Text(value)
        .fontSize(14)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827')
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis });
    }
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: '#F1F5F9' });
  }

  @Builder
  NoteCard(text: string) {
    Column() {
      Text(text)
        .fontSize(14)
        .fontColor('#6B7280')
        .textAlign(TextAlign.Center)
        .lineHeight(20);
    }
    .width('100%')
    .padding(20)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }
}

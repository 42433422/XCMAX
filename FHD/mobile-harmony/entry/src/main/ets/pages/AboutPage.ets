/**
 * 关于页面。
 *
 * 对标 Android feature/about/AboutScreen.kt，
 * 展示应用图标、名称、版本号及信息列表，底部提供"检查更新"入口。
 */
interface AboutInfoItem {
  label: string;
  value: string;
}

@Component
export struct AboutPage {
  @State appName: string = 'XCAGI 企业版';
  @State appVersion: string = 'v10.0.0';
  @State buildNumber: string = '20260620';
  @State officialUrl: string = 'https://xiu-ci.com';
  @State supportEmail: string = 'support@xiu-ci.com';
  @State icpRecord: string = '蜀ICP备2025xxxxxx号';

  onBack: () => void = () => {};
  onCheckUpdate: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 14 }) {
          this.AppIdentityCard();
          this.InfoListCard();
          this.CheckUpdateButton();
          this.ComplianceFooter();
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
      Text('关于')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827')
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  AppIdentityCard() {
    Column({ space: 10 }) {
      Text('XC')
        .width(72)
        .height(72)
        .borderRadius(18)
        .fontSize(26)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor('#1D4ED8');
      Text(this.appName)
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827');
      Text(this.appVersion)
        .fontSize(13)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding({ top: 24, bottom: 24, left: 16, right: 16 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  InfoListCard() {
    Column() {
      ForEach(this.infoItems(), (item: AboutInfoItem) => {
        this.InfoRow(item);
      }, (item: AboutInfoItem) => item.label);
    }
    .width('100%')
    .padding({ left: 16, right: 16 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  InfoRow(item: AboutInfoItem) {
    Row() {
      Text(item.label)
        .fontSize(15)
        .fontColor('#4B5563')
        .width(96);
      Text(item.value)
        .fontSize(15)
        .fontColor('#111827')
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1)
        .textAlign(TextAlign.End);
    }
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: '#F1F5F9' });
  }

  @Builder
  CheckUpdateButton() {
    Button('检查更新')
      .width('100%')
      .height(48)
      .fontSize(16)
      .fontWeight(FontWeight.Medium)
      .fontColor('#FFFFFF')
      .backgroundColor('#1D4ED8')
      .borderRadius(10)
      .onClick(() => this.onCheckUpdate());
  }

  @Builder
  ComplianceFooter() {
    Text(this.icpRecord)
      .fontSize(12)
      .fontColor('#9CA3AF')
      .textAlign(TextAlign.Center)
      .width('100%')
      .padding({ top: 8, bottom: 8 });
  }

  private infoItems(): AboutInfoItem[] {
    const items: AboutInfoItem[] = [
      { label: '版本', value: this.appVersion },
      { label: '构建号', value: this.buildNumber },
      { label: '官方网址', value: this.officialUrl },
      { label: '客服邮箱', value: this.supportEmail },
      { label: '备案号', value: this.icpRecord }
    ];
    return items;
  }
}

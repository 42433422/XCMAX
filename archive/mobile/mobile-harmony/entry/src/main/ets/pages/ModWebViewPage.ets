/**
 * MOD WebView 页面。
 *
 * 对标 Android feature/modhost/ModWebViewScreen.kt，
 * 接收 modId 与 modTitle，展示 MOD 加载区域。
 * 简化版使用 Text 占位，真机环境可替换为 Web 组件。
 */
@Component
export struct ModWebViewPage {
  @Prop modId: string = '';
  @Prop modTitle: string = '';

  onBack: () => void = () => {};

  build() {
    Column() {
      this.Header();
      this.WebArea();
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
      Text(this.modTitle.length > 0 ? this.modTitle : 'MOD')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827')
        .maxLines(1)
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  WebArea() {
    Column({ space: 12 }) {
      Text('MOD 加载中...')
        .fontSize(16)
        .fontColor('#4B5563');
      Text(`MOD ID: ${this.modId}`)
        .fontSize(13)
        .fontColor('#9CA3AF');
      Text('MOD WebView 需在真机环境加载')
        .fontSize(13)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .layoutWeight(1)
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center);
  }
}

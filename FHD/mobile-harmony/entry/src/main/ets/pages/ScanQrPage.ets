/**
 * 扫码页面。
 *
 * 对标 Android ScanQrScreen.kt：扫码取景框 + 相册选择 + 手电筒。
 * 简化版不调真实相机，点击取景框模拟扫码结果。
 */

@Component
export struct ScanQrPage {
  @State scanResult: string = '';
  @State flashOn: boolean = false;

  onBack: () => void = () => {};
  onScanResult: (result: string) => void = () => {};

  build() {
    Column() {
      this.Header();
      this.ScanArea();
      this.ResultArea();
      this.BottomActions();
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#0A0A0A');
  }

  @Builder
  Header() {
    Row({ space: 12 }) {
      Text('<')
        .width(36)
        .height(36)
        .fontSize(22)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .onClick(() => this.onBack());
      Column({ space: 2 }) {
        Text('扫一扫')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF');
        Text('扫描配对二维码或设备码')
          .fontSize(13)
          .fontColor('#9CA3AF');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#1A1A1A')
    .border({ width: { bottom: 1 }, color: '#2A2A2A' });
  }

  @Builder
  ScanArea() {
    Column() {
      Column() {
        // 取景框：方形 Border 描述
        Column()
          .width(220)
          .height(220)
          .border({
            width: 2,
            color: '#3370FF',
            radius: 12
          })
          .backgroundColor('#00000000')
          .onClick(() => {
            this.simulateScan();
          });

        Text('将电脑端显示的配对二维码放入框内')
          .fontSize(13)
          .fontColor('#9CA3AF')
          .margin({ top: 20 })
          .textAlign(TextAlign.Center);

        Text('点击取景框可模拟扫码')
          .fontSize(12)
          .fontColor('#6B7280')
          .margin({ top: 6 })
          .textAlign(TextAlign.Center);
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .alignItems(HorizontalAlign.Center);
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  ResultArea() {
    if (this.scanResult.length > 0) {
      Column({ space: 10 }) {
        Text('扫码结果')
          .fontSize(13)
          .fontColor('#9CA3AF');
        Text(this.scanResult)
          .width('100%')
          .fontSize(14)
          .fontColor('#FFFFFF')
          .lineHeight(20)
          .padding(12)
          .backgroundColor('#1A1A1A')
          .borderRadius(10)
          .border({ width: 1, color: '#2A2A2A' });
        Button('确认使用该结果')
          .height(40)
          .fontSize(14)
          .fontColor('#FFFFFF')
          .backgroundColor('#3370FF')
          .borderRadius(10)
          .width('100%')
          .onClick(() => {
            this.onScanResult(this.scanResult);
          });
      }
      .width('100%')
      .padding({ left: 18, right: 18, top: 6, bottom: 10 });
    }
  }

  @Builder
  BottomActions() {
    Row({ space: 16 }) {
      Column({ space: 4 }) {
        Text(this.flashOn ? '手电筒开' : '手电筒')
          .fontSize(13)
          .fontColor(this.flashOn ? '#FFD700' : '#FFFFFF');
        Text(this.flashOn ? '已开启' : '点击开启')
          .fontSize(11)
          .fontColor('#6B7280');
      }
      .alignItems(HorizontalAlign.Center)
      .width(90)
      .padding({ top: 10, bottom: 10 })
      .backgroundColor('#1A1A1A')
      .borderRadius(12)
      .border({ width: 1, color: '#2A2A2A' })
      .onClick(() => {
        this.flashOn = !this.flashOn;
      });

      Column({ space: 4 }) {
        Text('从相册选择')
          .fontSize(13)
          .fontColor('#FFFFFF');
        Text('识别图片二维码')
          .fontSize(11)
          .fontColor('#6B7280');
      }
      .alignItems(HorizontalAlign.Center)
      .layoutWeight(1)
      .padding({ top: 10, bottom: 10 })
      .backgroundColor('#1A1A1A')
      .borderRadius(12)
      .border({ width: 1, color: '#2A2A2A' })
      .onClick(() => {
        this.simulateScan();
      });
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 10, bottom: 20 });
  }

  private simulateScan(): void {
    try {
      this.scanResult = 'xcagi://pair?nonce=482913&server=119.27.178.147:5100';
    } catch (_err) {
      this.scanResult = '';
    }
  }
}

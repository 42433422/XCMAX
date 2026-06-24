/**
 * 扫码页面。
 *
 * 对标 Android ScanQrScreen.kt:用华为统一扫码服务(ScanKit)拉起系统扫码界面,
 * 真实扫描配对二维码/设备码,结果回填后由上层做配对或路由。
 * (ScanKit 真机行为需在 HarmonyOS 设备上验证。)
 */

import { scanBarcode, scanCore } from '@kit.ScanKit';
import common from '@ohos.app.ability.common';

@Component
export struct ScanQrPage {
  @State scanResult: string = '';
  @State scanning: boolean = false;
  @State errorMsg: string = '';

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
        Column()
          .width(220)
          .height(220)
          .border({ width: 2, color: '#3370FF', radius: 12 })
          .backgroundColor('#00000000')
          .onClick(() => this.startScan());

        Text('点击取景框拉起扫码,将二维码放入框内')
          .fontSize(13)
          .fontColor('#9CA3AF')
          .margin({ top: 20 })
          .textAlign(TextAlign.Center);

        if (this.errorMsg.length > 0) {
          Text(this.errorMsg)
            .fontSize(12)
            .fontColor('#F87171')
            .margin({ top: 6 })
            .textAlign(TextAlign.Center);
        }
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
    Button(this.scanning ? '扫码中...' : '开始扫描')
      .height(48)
      .width('100%')
      .fontSize(15)
      .fontColor('#FFFFFF')
      .backgroundColor('#3370FF')
      .borderRadius(12)
      .enabled(!this.scanning)
      .margin({ left: 18, right: 18, top: 10, bottom: 20 })
      .onClick(() => this.startScan());
  }

  private startScan(): void {
    if (this.scanning) {
      return;
    }
    this.scanning = true;
    this.errorMsg = '';
    const options: scanBarcode.ScanOptions = {
      scanTypes: [scanCore.ScanType.ALL],
      enableMultiMode: true,
      enableAlbum: true
    };
    try {
      const context = getContext(this) as common.Context;
      scanBarcode.startScanForResult(context, options)
        .then((result: scanBarcode.ScanResult) => {
          this.scanning = false;
          this.scanResult = result.originalValue;
        })
        .catch((err: Object) => {
          this.scanning = false;
          this.errorMsg = `扫码失败：${(err as Error).message}`;
        });
    } catch (err) {
      this.scanning = false;
      this.errorMsg = `无法拉起扫码：${(err as Error).message}`;
    }
  }
}

/**
 * 文字识别（OCR）页面。
 *
 * 对标 Android OcrScreen.kt：上传图片 + 识别结果 + 复制文本。
 * 简化版用按钮模拟上传识别，本地 mock 识别结果。
 */

@Component
export struct OcrPage {
  @State ocrText: string = '';
  @State recognizing: boolean = false;
  @State copied: boolean = false;

  onBack: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 14 }) {
          this.UploadCard();
          this.ResultCard();
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
        Text('文字识别')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('OCR 图片文字提取')
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
  UploadCard() {
    Column({ space: 12 }) {
      Row({ space: 10 }) {
        Text('识别')
          .width(40)
          .height(40)
          .borderRadius(10)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .textAlign(TextAlign.Center)
          .backgroundColor('#1D4ED8');
        Column({ space: 2 }) {
          Text('上传图片识别')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827');
          Text('调用企业端 OCR 引擎处理图片文字')
            .fontSize(13)
            .fontColor('#4B5563');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      Button(this.recognizing ? '识别中...' : '模拟上传图片并识别')
        .height(44)
        .fontSize(14)
        .fontColor('#FFFFFF')
        .backgroundColor(this.recognizing ? '#9CA3AF' : '#1D4ED8')
        .borderRadius(10)
        .width('100%')
        .enabled(!this.recognizing)
        .onClick(() => {
          this.simulateRecognize();
        });

      Text('移动端拍照上传正在接入，复杂批量识别请使用电脑端 OCR')
        .fontSize(12)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ResultCard() {
    Column({ space: 12 }) {
      Row() {
        Text('识别结果')
          .fontSize(16)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .layoutWeight(1);
        if (this.ocrText.length > 0) {
          Text(this.copied ? '已复制' : '可复制')
            .fontSize(12)
            .fontColor(this.copied ? '#166534' : '#6B7280')
            .padding({ left: 8, right: 8, top: 3, bottom: 3 })
            .backgroundColor(this.copied ? '#E7F7EE' : '#F3F4F6')
            .borderRadius(8);
        }
      }
      .width('100%');

      if (this.ocrText.length === 0) {
        Text('尚未识别到文本，请先上传图片进行识别。')
          .width('100%')
          .fontSize(14)
          .fontColor('#9CA3AF')
          .lineHeight(20)
          .padding(12)
          .backgroundColor('#F8FAFC')
          .borderRadius(10)
          .border({ width: 1, color: '#E5E7EB' });
      } else {
        Text(this.ocrText)
          .width('100%')
          .fontSize(14)
          .fontColor('#111827')
          .lineHeight(22)
          .padding(12)
          .backgroundColor('#F8FAFC')
          .borderRadius(10)
          .border({ width: 1, color: '#E5E7EB' });
      }

      if (this.ocrText.length > 0) {
        Button('复制文本')
          .height(42)
          .fontSize(14)
          .fontColor('#1D4ED8')
          .backgroundColor('#E8F0FF')
          .borderRadius(10)
          .width('100%')
          .onClick(() => {
            this.copyText();
          });
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private simulateRecognize(): void {
    this.recognizing = true;
    this.copied = false;
    try {
      this.ocrText = 'XCMAX 企业端 OCR 识别结果\n\n发票号码：20260620-00482\n开票日期：2026-06-20\n金额（含税）：￥12,800.00\n购买方：成都修茈科技有限公司\n销售方：XCAGI 智能科技\n\n备注：本识别结果由企业端 OCR 引擎生成，移动端仅做展示与复制。';
    } catch (_err) {
      this.ocrText = '';
    } finally {
      this.recognizing = false;
    }
  }

  private copyText(): void {
    try {
      this.copied = true;
    } catch (_err) {
      this.copied = false;
    }
  }
}

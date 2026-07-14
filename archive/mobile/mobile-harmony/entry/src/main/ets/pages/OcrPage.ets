/**
 * 文字识别(OCR)页面。
 *
 * 对标 Android OcrScreen.kt:选图 + 识别 + 复制。
 * 用华为 CoreVisionKit textRecognition 做真实 OCR:相册选图 → PixelMap → 识别文本。
 * 复制走系统剪贴板。(真机行为需在 HarmonyOS 设备上验证。)
 */

import { textRecognition } from '@kit.CoreVisionKit';
import image from '@ohos.multimedia.image';
import picker from '@ohos.file.picker';
import fileIo from '@ohos.file.fs';
import pasteboard from '@ohos.pasteboard';

@Component
export struct OcrPage {
  @State ocrText: string = '';
  @State recognizing: boolean = false;
  @State copied: boolean = false;
  @State errorMsg: string = '';

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
          Text('选图识别')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827');
          Text('从相册选择图片,本地 OCR 引擎提取文字')
            .fontSize(13)
            .fontColor('#4B5563');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      Button(this.recognizing ? '识别中...' : '选择图片并识别')
        .height(44)
        .fontSize(14)
        .fontColor('#FFFFFF')
        .backgroundColor(this.recognizing ? '#9CA3AF' : '#1D4ED8')
        .borderRadius(10)
        .width('100%')
        .enabled(!this.recognizing)
        .onClick(() => this.pickAndRecognize());

      if (this.errorMsg.length > 0) {
        Text(this.errorMsg)
          .fontSize(12)
          .fontColor('#B91C1C');
      }
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
        Text('尚未识别到文本,请先选择图片进行识别。')
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
          .onClick(() => this.copyText());
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private async pickAndRecognize(): Promise<void> {
    if (this.recognizing) {
      return;
    }
    this.recognizing = true;
    this.copied = false;
    this.errorMsg = '';
    try {
      const photoPicker = new picker.PhotoViewPicker();
      const selectOptions = new picker.PhotoSelectOptions();
      selectOptions.MIMEType = picker.PhotoViewMIMETypes.IMAGE_TYPE;
      selectOptions.maxSelectNumber = 1;
      const selectResult = await photoPicker.select(selectOptions);
      const uris: string[] = selectResult.photoUris;
      if (uris.length === 0) {
        this.recognizing = false;
        return;
      }
      await this.recognizeUri(uris[0]);
    } catch (err) {
      this.errorMsg = `识别失败：${(err as Error).message}`;
    } finally {
      this.recognizing = false;
    }
  }

  private async recognizeUri(uri: string): Promise<void> {
    const file = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
    const imageSource: image.ImageSource = image.createImageSource(file.fd);
    let pixelMap: image.PixelMap | null = null;
    try {
      pixelMap = await imageSource.createPixelMap();
      const visionInfo: textRecognition.VisionInfo = { pixelMap: pixelMap };
      const result: textRecognition.TextRecognitionResult = await textRecognition.recognizeText(visionInfo);
      this.ocrText = result.value.length > 0 ? result.value : '未识别到文字';
    } finally {
      if (pixelMap !== null) {
        pixelMap.release();
      }
      imageSource.release();
      fileIo.closeSync(file);
    }
  }

  private copyText(): void {
    try {
      const data = pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, this.ocrText);
      pasteboard.getSystemPasteboard().setData(data).then(() => {
        this.copied = true;
      }).catch(() => {
        this.copied = false;
      });
    } catch (_err) {
      this.copied = false;
    }
  }
}

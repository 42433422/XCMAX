import { cleanText } from '../models/MobileModels';

// 设置页面：对齐 Android feature/settings/SettingsScreen.kt
// 四大区块：安全（生物识别）/ 外观（主题模式）/ 反馈（问题反馈）/ 版本（检查更新）
@Component
export struct SettingsPage {
  @Consume biometricEnabled: boolean;
  @Consume themeMode: string;
  @Consume loading: boolean;
  @Consume companyBrand: string;
  @Consume baseUrl: string;
  @Consume relayDesktopId: string;

  onBack: () => void = () => {};
  onSetBiometric: (enabled: boolean) => void = () => {};
  onSetThemeMode: (mode: string) => void = () => {};
  onSubmitFeedback: (message: string, onDone: () => void) => void = () => {};
  onCheckForUpdate: () => void = () => {};
  onBindRelayDesktop: (code: string, onDone: (ok: boolean, msg: string) => void) => void = () => {};

  @State feedback: string = '';
  @State feedbackSubmitted: boolean = false;
  @State relayCode: string = '';
  @State relayBinding: boolean = false;
  @State relayMsg: string = '';

  build() {
    Column() {
      this.TopBar();
      Scroll() {
        Column({ space: 12 }) {
          this.SecuritySection();
          this.RelaySection();
          this.AppearanceSection();
          this.FeedbackSection();
          this.VersionSection();
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 14, bottom: 28 });
      }
      .layoutWeight(1)
      .width('100%');
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  TopBar() {
    Row({ space: 12 }) {
      Text('‹')
        .width(36)
        .height(36)
        .fontSize(22)
        .fontColor('#111827')
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.onBack();
        });
      Text('设置')
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827')
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 12, right: 18, top: 12, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  SectionCaption(text: string) {
    Text(text)
      .fontSize(13)
      .fontColor('#6B7280')
      .margin({ top: 6, bottom: 2, left: 4 });
  }

  @Builder
  SecuritySection() {
    Column() {
      this.SectionCaption('安全');
      Column() {
        Row({ space: 12 }) {
          Text('指纹')
            .width(32)
            .height(32)
            .borderRadius(8)
            .fontSize(16)
            .fontColor('#1D4ED8')
            .textAlign(TextAlign.Center)
            .backgroundColor('#E8F0FF');
          Column({ space: 2 }) {
            Text('生物识别解锁')
              .fontSize(15)
              .fontColor('#111827');
            Text(this.biometricEnabled ? '已开启' : '未开启')
              .fontSize(12)
              .fontColor('#6B7280');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
          Toggle({ type: ToggleType.Switch, isOn: this.biometricEnabled })
            .onChange((isOn: boolean) => {
              this.onSetBiometric(isOn);
            });
        }
        .width('100%')
        .padding(14);
      }
      .width('100%')
      .backgroundColor('#FFFFFF')
      .borderRadius(14)
      .border({ width: 1, color: '#E5E7EB' });
    }
    .width('100%');
  }

  @Builder
  AppearanceSection() {
    Column() {
      this.SectionCaption('外观');
      Column({ space: 10 }) {
        Row({ space: 12 }) {
          Text('调色板')
            .width(32)
            .height(32)
            .borderRadius(8)
            .fontSize(16)
            .fontColor('#7C3AED')
            .textAlign(TextAlign.Center)
            .backgroundColor('#F3E8FF');
          Column({ space: 2 }) {
            Text('主题模式')
              .fontSize(15)
              .fontColor('#111827');
            Text(this.themeLabel(this.themeMode))
              .fontSize(12)
              .fontColor('#6B7280');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 14, bottom: 4 });

        Row({ space: 8 }) {
          this.ThemeChip('跟随系统', 'system');
          this.ThemeChip('浅色', 'light');
          this.ThemeChip('深色', 'dark');
        }
        .width('100%')
        .padding({ left: 14, right: 14, bottom: 14 });
      }
      .width('100%')
      .backgroundColor('#FFFFFF')
      .borderRadius(14)
      .border({ width: 1, color: '#E5E7EB' });
    }
    .width('100%');
  }

  @Builder
  ThemeChip(label: string, mode: string) {
    Text(label)
      .height(38)
      .fontSize(14)
      .fontWeight(FontWeight.Medium)
      .fontColor(this.themeMode === mode ? '#FFFFFF' : '#374151')
      .backgroundColor(this.themeMode === mode ? '#2563EB' : '#F1F5F9')
      .borderRadius(10)
      .textAlign(TextAlign.Center)
      .layoutWeight(1)
      .onClick(() => {
        this.onSetThemeMode(mode);
      });
  }

  @Builder
  RelaySection() {
    Column() {
      this.SectionCaption('电脑执行端');
      Column({ space: 10 }) {
        Row({ space: 12 }) {
          Text('派')
            .width(32)
            .height(32)
            .borderRadius(8)
            .fontSize(16)
            .fontColor('#1D4ED8')
            .textAlign(TextAlign.Center)
            .backgroundColor('#E8F0FF');
          Column({ space: 2 }) {
            Text('绑定电脑执行端')
              .fontSize(15)
              .fontColor('#111827');
            Text(this.relayDesktopId.length > 0
              ? '已绑定，超级员工任务经云中继派到该电脑'
              : '输入电脑端显示的 6 位设备码，离线也能派工')
              .fontSize(12)
              .fontColor(this.relayDesktopId.length > 0 ? '#15803D' : '#6B7280');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
        }
        .width('100%')
        .padding(14);

        TextInput({ text: this.relayCode, placeholder: '6 位设备码' })
          .width('100%')
          .height(44)
          .fontSize(15)
          .fontColor('#111827')
          .type(InputType.Number)
          .maxLength(6)
          .backgroundColor('#F9FAFB')
          .borderRadius(10)
          .border({ width: 1, color: '#E5E7EB' })
          .padding(10)
          .onChange((value: string) => {
            this.relayCode = value;
          });

        Button(this.relayBinding ? '绑定中…' : (this.relayDesktopId.length > 0 ? '重新绑定' : '绑定'))
          .height(44)
          .width('100%')
          .fontSize(15)
          .fontColor('#FFFFFF')
          .backgroundColor(this.relayCode.trim().length === 6 && !this.relayBinding ? '#2563EB' : '#9CA3AF')
          .borderRadius(12)
          .enabled(this.relayCode.trim().length === 6 && !this.relayBinding && !this.loading)
          .onClick(() => {
            const code = this.relayCode.trim();
            if (code.length !== 6) return;
            this.relayBinding = true;
            this.relayMsg = '';
            this.onBindRelayDesktop(code, (ok: boolean, msg: string) => {
              this.relayBinding = false;
              this.relayMsg = msg;
              if (ok) {
                this.relayCode = '';
              }
            });
          });

        if (this.relayMsg.length > 0) {
          Text(this.relayMsg)
            .fontSize(12)
            .fontColor('#6B7280')
            .width('100%');
        }
      }
      .width('100%')
      .padding(14)
      .backgroundColor('#FFFFFF')
      .borderRadius(14)
      .border({ width: 1, color: '#E5E7EB' });
    }
    .width('100%');
  }

  @Builder
  FeedbackSection() {
    Column() {
      this.SectionCaption('反馈');
      Column({ space: 10 }) {
        Row({ space: 12 }) {
          Text('反馈')
            .width(32)
            .height(32)
            .borderRadius(8)
            .fontSize(16)
            .fontColor('#B45309')
            .textAlign(TextAlign.Center)
            .backgroundColor('#FEF3C7');
          Column({ space: 2 }) {
            Text('问题反馈')
              .fontSize(15)
              .fontColor('#111827');
            Text('提交后进入企业支持队列')
              .fontSize(12)
              .fontColor('#6B7280');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
        }
        .width('100%')
        .padding(14);

        TextArea({ text: this.feedback, placeholder: '描述问题或建议' })
          .width('100%')
          .height(96)
          .fontSize(14)
          .fontColor('#111827')
          .backgroundColor('#F9FAFB')
          .borderRadius(10)
          .border({ width: 1, color: '#E5E7EB' })
          .padding(10)
          .maxLength(500)
          .onChange((value: string) => {
            this.feedback = value;
          });

        Button(this.feedbackSubmitted ? '已提交，感谢反馈' : '提交反馈')
          .height(44)
          .width('100%')
          .fontSize(15)
          .fontColor('#FFFFFF')
          .backgroundColor(this.feedback.trim().length > 0 && !this.feedbackSubmitted ? '#2563EB' : '#9CA3AF')
          .borderRadius(12)
          .enabled(this.feedback.trim().length > 0 && !this.feedbackSubmitted && !this.loading)
          .onClick(() => {
            const message = this.feedback.trim();
            if (message.length === 0) return;
            this.onSubmitFeedback(message, () => {
              this.feedback = '';
              this.feedbackSubmitted = true;
            });
          });
      }
      .width('100%')
      .padding(14)
      .backgroundColor('#FFFFFF')
      .borderRadius(14)
      .border({ width: 1, color: '#E5E7EB' });
    }
    .width('100%');
  }

  @Builder
  VersionSection() {
    Column() {
      this.SectionCaption('版本');
      Column() {
        Row({ space: 12 }) {
          Text('更新')
            .width(32)
            .height(32)
            .borderRadius(8)
            .fontSize(16)
            .fontColor('#047857')
            .textAlign(TextAlign.Center)
            .backgroundColor('#D1FAE5');
          Column({ space: 2 }) {
            Text('检查更新')
              .fontSize(15)
              .fontColor('#111827');
            Text('获取企业版移动端最新构建')
              .fontSize(12)
              .fontColor('#6B7280');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
          Text('›')
            .width(24)
            .height(24)
            .fontSize(18)
            .fontColor('#9CA3AF')
            .textAlign(TextAlign.Center);
        }
        .width('100%')
        .padding(14)
        .onClick(() => {
          this.onCheckForUpdate();
        });
      }
      .width('100%')
      .backgroundColor('#FFFFFF')
      .borderRadius(14)
      .border({ width: 1, color: '#E5E7EB' });
    }
    .width('100%');
  }

  private themeLabel(mode: string): string {
    if (mode === 'dark') return '深色';
    if (mode === 'light') return '浅色';
    return '跟随系统';
  }
}

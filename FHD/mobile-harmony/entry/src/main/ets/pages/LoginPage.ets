@Component
export struct LoginPage {
  @Consume baseUrl: string;
  @Consume username: string;
  @Consume password: string;
  @Consume pairingCode: string;
  @Consume loginAccountKind: string;
  @Consume statusText: string;
  @Consume loading: boolean;

  onLogin: () => void = () => {};
  onExchangePairingCode: () => void = () => {};
  onOpenRegister: () => void = () => {};

  build() {
    this.LoginScreen();
  }

  @Builder
  LoginScreen() {
    Scroll() {
      Column({ space: 18 }) {
        Row() {
          Row({ space: 12 }) {
            Text('XC')
              .width(52)
              .height(52)
              .borderRadius(16)
              .fontSize(18)
              .fontWeight(FontWeight.Bold)
              .fontColor('#FFFFFF')
              .textAlign(TextAlign.Center)
              .backgroundColor('#101827');

            Column({ space: 4 }) {
              Text('XCAGI 企业版')
                .fontSize(24)
                .fontWeight(FontWeight.Bold)
                .fontColor('#101827');
              Text('企业 AI 员工与协同办公移动端')
                .fontSize(14)
                .fontColor('#506074');
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1);
          }
          .layoutWeight(1);

          Text(this.loading ? '连接中' : '在线')
            .fontSize(12)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.loading ? '#92400E' : '#166534')
            .padding({ left: 10, right: 10, top: 5, bottom: 5 })
            .backgroundColor(this.loading ? '#FEF3C7' : '#DCFCE7')
            .borderRadius(12);
        }
        .width('100%')
        .padding({ left: 22, right: 22, top: 28, bottom: 4 });

        Column({ space: 16 }) {
          Row() {
            Column({ space: 3 }) {
              Text('登录')
                .fontSize(21)
                .fontWeight(FontWeight.Bold)
                .fontColor('#111827');
              Text(this.loginAccountKind === 'admin' ? '管理端账号' : '企业端账号')
                .fontSize(13)
                .fontColor('#64748B');
            }
            .layoutWeight(1)
            .alignItems(HorizontalAlign.Start);

            Text(this.loginAccountKind === 'admin' ? '管理员' : '企业')
              .fontSize(12)
              .fontColor('#1D4ED8')
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .backgroundColor('#E8F0FF')
              .borderRadius(12);
          }
          .width('100%');

          Row() {
            Text('管理员账号')
              .layoutWeight(1)
              .height(38)
              .fontSize(14)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.loginAccountKind === 'admin' ? '#FFFFFF' : '#475569')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.loginAccountKind === 'admin' ? '#2563EB' : '#EEF2F7')
              .borderRadius(10)
              .onClick(() => {
                this.loginAccountKind = 'admin';
              });
            Text('企业账号')
              .layoutWeight(1)
              .height(38)
              .fontSize(14)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.loginAccountKind === 'enterprise' ? '#FFFFFF' : '#475569')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.loginAccountKind === 'enterprise' ? '#2563EB' : '#EEF2F7')
              .borderRadius(10)
              .onClick(() => {
                this.loginAccountKind = 'enterprise';
              });
          }
          .width('100%')
          .padding(4)
          .backgroundColor('#EEF2F7')
          .borderRadius(14);

          Column({ space: 8 }) {
            this.FieldLabel('服务地址');
            TextInput({ placeholder: '例如 http://192.168.1.10:17500', text: this.baseUrl })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .onChange((value: string) => {
                this.baseUrl = value;
              });
          }
          .width('100%');

          Column({ space: 8 }) {
            this.FieldLabel(this.loginAccountKind === 'admin' ? '管理员账号' : '企业账号');
            TextInput({
              placeholder: this.loginAccountKind === 'admin' ? '服务器后台管理员账号' : '企业端账号或邮箱',
              text: this.username
            })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .onChange((value: string) => {
                this.username = value;
              });
          }
          .width('100%');

          Column({ space: 8 }) {
            this.FieldLabel('密码');
            TextInput({
              placeholder: this.loginAccountKind === 'admin' ? '管理员登录密码' : '企业账号登录密码',
              text: this.password
            })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .type(InputType.Password)
              .onChange((value: string) => {
                this.password = value;
              });
          }
          .width('100%');

          Button(this.loading ? '登录中...' : (this.loginAccountKind === 'admin' ? '进入管理端' : '进入企业端'))
            .width('100%')
            .height(50)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#FFFFFF')
            .backgroundColor(this.loading ? '#94A3B8' : '#2563EB')
            .borderRadius(12)
            .enabled(!this.loading)
            .onClick(() => {
              this.onLogin();
            });

          Row({ space: 4 }) {
            Text('还没有账号？')
              .fontSize(13)
              .fontColor('#64748B');
            Text('注册新账号')
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor('#1D4ED8')
              .onClick(() => this.onOpenRegister());
          }
          .width('100%')
          .justifyContent(FlexAlign.Center);

          Row({ space: 8 }) {
            Text(this.statusText.indexOf('失败') >= 0 ? '!' : 'i')
              .width(22)
              .height(22)
              .borderRadius(11)
              .fontSize(12)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.statusText.indexOf('失败') >= 0 ? '#B91C1C' : '#1D4ED8')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.statusText.indexOf('失败') >= 0 ? '#FEE2E2' : '#E8F0FF');
            Text(this.statusText)
              .layoutWeight(1)
              .fontSize(13)
              .fontColor(this.statusText.indexOf('失败') >= 0 ? '#B91C1C' : '#35506B')
              .maxLines(3);
          }
          .width('100%')
          .padding({ left: 12, right: 12, top: 10, bottom: 10 })
          .backgroundColor(this.statusText.indexOf('失败') >= 0 ? '#FFF1F2' : '#F8FAFC')
          .borderRadius(12)
          .border({ width: 1, color: this.statusText.indexOf('失败') >= 0 ? '#FECACA' : '#E2E8F0' });
        }
        .width('100%')
        .padding(18)
        .margin({ left: 18, right: 18 })
        .backgroundColor('#FFFFFF')
        .borderRadius(18)
        .border({ width: 1, color: '#DDE5EF' });

        Column({ space: 12 }) {
          Row() {
            Text('桌面绑定')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor('#111827')
              .layoutWeight(1);
            Text('可选')
              .fontSize(12)
              .fontColor('#64748B')
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .backgroundColor('#F1F5F9')
              .borderRadius(10);
          }
          .width('100%');

          Row({ space: 10 }) {
            TextInput({ placeholder: '输入绑定码', text: this.pairingCode })
              .height(46)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .layoutWeight(1)
              .onChange((value: string) => {
                this.pairingCode = value;
              });
            Button('绑定')
              .height(46)
              .fontSize(15)
              .fontColor('#1D4ED8')
              .backgroundColor('#E8F0FF')
              .borderRadius(12)
              .padding({ left: 18, right: 18 })
              .enabled(!this.loading)
              .onClick(() => {
                this.onExchangePairingCode();
              });
          }
          .width('100%');
        }
        .width('100%')
        .padding(16)
        .margin({ left: 18, right: 18, bottom: 24 })
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#DDE5EF' });
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start);
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F3F6FA');
  }

  @Builder
  FieldLabel(label: string) {
    Text(label)
      .fontSize(13)
      .fontColor('#111827')
      .fontWeight(FontWeight.Medium)
      .width('100%');
  }
}

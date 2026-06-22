/**
 * 注册页面。
 *
 * 对标 Android feature/auth/RegisterScreen.kt，
 * 提供用户名、密码、确认密码、企业名称表单，提交后触发 onSuccess。
 */
@Component
export struct RegisterPage {
  @State username: string = '';
  @State password: string = '';
  @State confirmPassword: string = '';
  @State enterpriseName: string = '';
  @State error: string = '';

  onBack: () => void = () => {};
  onSuccess: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 16 }) {
          this.FormCard();
          this.LoginLink();
        }
        .width('100%')
        .padding({ left: 18, right: 18, top: 18, bottom: 24 });
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
      Text('注册')
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
  FormCard() {
    Column({ space: 14 }) {
      this.FieldLabel('用户名');
      TextInput({ placeholder: '请输入用户名', text: this.username })
        .height(48)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#9CA3AF')
        .backgroundColor('#FFFFFF')
        .borderRadius(10)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 14, right: 14 })
        .onChange((value: string) => {
          this.username = value;
        });

      this.FieldLabel('密码');
      TextInput({ placeholder: '请输入密码', text: this.password })
        .height(48)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#9CA3AF')
        .backgroundColor('#FFFFFF')
        .borderRadius(10)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 14, right: 14 })
        .type(InputType.Password)
        .onChange((value: string) => {
          this.password = value;
        });

      this.FieldLabel('确认密码');
      TextInput({ placeholder: '请再次输入密码', text: this.confirmPassword })
        .height(48)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#9CA3AF')
        .backgroundColor('#FFFFFF')
        .borderRadius(10)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 14, right: 14 })
        .type(InputType.Password)
        .onChange((value: string) => {
          this.confirmPassword = value;
        });

      this.FieldLabel('企业名称');
      TextInput({ placeholder: '请输入企业名称', text: this.enterpriseName })
        .height(48)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#9CA3AF')
        .backgroundColor('#FFFFFF')
        .borderRadius(10)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 14, right: 14 })
        .onChange((value: string) => {
          this.enterpriseName = value;
        });

      if (this.error.length > 0) {
        Text(this.error)
          .fontSize(13)
          .fontColor('#B91C1C')
          .width('100%')
          .padding({ left: 4, right: 4 });
      }

      Button('注册')
        .width('100%')
        .height(48)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#FFFFFF')
        .backgroundColor(this.canSubmit() ? '#1D4ED8' : '#9CA3AF')
        .borderRadius(10)
        .enabled(this.canSubmit())
        .onClick(() => this.handleSubmit());
    }
    .width('100%')
    .padding(18)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  FieldLabel(label: string) {
    Text(label)
      .fontSize(13)
      .fontColor('#111827')
      .fontWeight(FontWeight.Medium)
      .width('100%');
  }

  @Builder
  LoginLink() {
    Row() {
      Text('已有账号？')
        .fontSize(14)
        .fontColor('#6B7280');
      Text('去登录')
        .fontSize(14)
        .fontColor('#1D4ED8')
        .fontWeight(FontWeight.Medium)
        .onClick(() => this.onBack());
    }
    .width('100%')
    .justifyContent(FlexAlign.Center);
  }

  private canSubmit(): boolean {
    return this.username.trim().length > 0
      && this.password.trim().length > 0
      && this.confirmPassword.trim().length > 0
      && this.enterpriseName.trim().length > 0;
  }

  private handleSubmit(): void {
    if (this.password !== this.confirmPassword) {
      this.error = '两次输入的密码不一致';
      return;
    }
    if (this.password.trim().length < 6) {
      this.error = '密码长度至少 6 位';
      return;
    }
    this.error = '';
    this.onSuccess();
  }
}

import { MobileApiClient } from '../api/MobileApiClient';
import { ChatMessage, CsInfo } from '../models/MobileModels';

/**
 * 客服聊天页面。
 *
 * 对标 Android CsChatScreen.kt，鸿蒙版简化为 HTTP 模式：
 * 进入页面拉取客服信息与历史消息，发送消息走 csSend 接口。
 */
@Component
export struct CsChatPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State messages: ChatMessage[] = [];
  @State input: string = '';
  @State loading: boolean = false;
  @State csTitle: string = '专属客服';
  @State csSubtitle: string = '在线';
  @State csOnline: boolean = true;

  private api: MobileApiClient = new MobileApiClient('');

  onBack: () => void = () => {};

  async aboutToAppear(): Promise<void> {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    await this.loadCsInfo();
    await this.loadCsMessages();
  }

  private async loadCsInfo(): Promise<void> {
    try {
      const info: CsInfo = await this.api.csInfo();
      this.csTitle = info.title.length > 0 ? info.title : '专属客服';
      this.csSubtitle = info.subtitle.length > 0 ? info.subtitle : (info.online ? '在线' : '离线');
      this.csOnline = info.online;
    } catch (_err) {
      this.csTitle = '专属客服';
      this.csSubtitle = '在线';
      this.csOnline = true;
    }
  }

  private async loadCsMessages(): Promise<void> {
    try {
      const list: ChatMessage[] = await this.api.csMessages();
      this.messages = list;
    } catch (_err) {
      this.messages = [];
    }
  }

  private async sendCsMessage(): Promise<void> {
    const text: string = this.input.trim();
    if (text.length === 0 || this.loading) {
      return;
    }
    const userMsg: ChatMessage = { role: 'user', text: text };
    this.messages = this.messages.concat([userMsg]);
    this.input = '';
    this.loading = true;
    try {
      const response = await this.api.csSend(text);
      const reply: string = (response.reply !== undefined && response.reply.length > 0)
        ? response.reply
        : (response.message !== undefined && response.message.length > 0 ? response.message : '客服已收到您的消息，稍后会回复。');
      const csMsg: ChatMessage = { role: 'assistant', text: reply };
      this.messages = this.messages.concat([csMsg]);
    } catch (_err) {
      const errMsg: ChatMessage = { role: 'assistant', text: '消息发送失败，请稍后重试。' };
      this.messages = this.messages.concat([errMsg]);
    } finally {
      this.loading = false;
    }
  }

  build() {
    this.CsChatArea();
  }

  @Builder
  CsChatArea() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          if (this.messages.length === 0) {
            this.EmptyHint();
          } else {
            ForEach(this.messages, (message: ChatMessage, index: number) => {
              this.ChatBubble(message, index);
            }, (_message: ChatMessage, index: number) => `${index}`);
          }
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 16 });
      }
      .width('100%')
      .layoutWeight(1);

      this.InputBar();
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
        Text(this.csTitle)
          .fontSize(18)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Row({ space: 6 }) {
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.csOnline ? '#18A85F' : '#9CA3AF');
          Text(this.csSubtitle)
            .fontSize(12)
            .fontColor(this.csOnline ? '#18A85F' : '#6B7280')
            .maxLines(1);
        }
        .alignItems(VerticalAlign.Center);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 12, right: 14, top: 10, bottom: 10 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  EmptyHint() {
    Column({ space: 6 }) {
      Text('正在连接客服...')
        .fontSize(15)
        .fontColor('#6B7280');
      Text('客服上线后会尽快回复您')
        .fontSize(12)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding({ top: 48, bottom: 48 })
    .alignItems(HorizontalAlign.Center);
  }

  @Builder
  ChatBubble(message: ChatMessage, index: number) {
    Row() {
      if (message.role === 'user') {
        Blank()
          .layoutWeight(1);
        Text(message.text)
          .fontSize(15)
          .fontColor('#FFFFFF')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#18A85F')
          .borderRadius(12)
          .constraintSize({ maxWidth: '78%' });
      } else {
        Text(message.text)
          .fontSize(15)
          .fontColor('#111827')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#FFFFFF')
          .borderRadius(12)
          .border({ width: 1, color: '#E5E7EB' })
          .constraintSize({ maxWidth: '78%' });
        Blank()
          .layoutWeight(1);
      }
    }
    .width('100%')
    .padding({ top: index === 0 ? 0 : 2 });
  }

  @Builder
  InputBar() {
    Row({ space: 10 }) {
      TextInput({ placeholder: '发送消息', text: this.input })
        .height(44)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#6B7280')
        .backgroundColor('#FFFFFF')
        .borderRadius(20)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 16, right: 16 })
        .layoutWeight(1)
        .onChange((value: string) => {
          this.input = value;
        });
      Button(this.loading ? '...' : '发送')
        .height(44)
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(20)
        .padding({ left: 20, right: 20 })
        .enabled(!this.loading && this.input.trim().length > 0)
        .onClick(() => this.sendCsMessage());
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }
}

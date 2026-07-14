import { ImMessage } from '../models/MobileModels';
import { ImWebSocketClient, ImInbound, ImConnStatus } from '../api/ImWebSocketClient';

/**
 * IM 即时通讯页面。
 *
 * 对标 Android core/im/ImWebSocketClient.kt:用真实 WebSocket(/ws/im?session_id=)
 * 接收实时消息,含重连退避与心跳;发送为 V0 本地回显(完整发送走 IM 会话 HTTP 流程)。
 */
@Component
export struct ImMessengerPage {
  @Consume baseUrl: string;
  @Consume sessionId: string;

  @State peerIdText: string = '';
  @State conversationId: number = -1;
  @State draft: string = '';
  @State messages: ImMessage[] = [];
  @State error: string = '';
  @State connStatus: ImConnStatus = 'idle';

  private wsClient: ImWebSocketClient | null = null;

  onBack: () => void = () => {};

  aboutToDisappear(): void {
    this.teardownWs();
  }

  private teardownWs(): void {
    if (this.wsClient !== null) {
      this.wsClient.disconnect();
      this.wsClient = null;
    }
  }

  private connStatusLabel(): string {
    if (this.connStatus === 'open') return '实时已连接';
    if (this.connStatus === 'connecting') return '连接中...';
    if (this.connStatus === 'reconnecting') return '重连中...';
    if (this.connStatus === 'closed') return '已断开';
    return '未连接';
  }

  private openConversation(): void {
    const peer: string = this.peerIdText.trim();
    if (peer.length === 0) {
      this.error = '请输入对方用户 ID';
      return;
    }
    this.conversationId = Number(peer);
    this.messages = [];
    this.error = '';
    // 建立真实 WebSocket 连接,接收实时消息
    this.teardownWs();
    const client = new ImWebSocketClient(this.baseUrl, this.sessionId);
    this.wsClient = client;
    client.connect(
      (inbound: ImInbound) => { this.onInbound(inbound); },
      (status: ImConnStatus) => { this.connStatus = status; }
    );
  }

  private onInbound(inbound: ImInbound): void {
    const m = inbound.message;
    if (!m) {
      return;
    }
    const content: string = (m.content !== undefined && m.content.length > 0)
      ? m.content : (m.body !== undefined ? m.body : '');
    if (content.length === 0) {
      return;
    }
    const msg: ImMessage = {
      id: m.id !== undefined ? `${m.id}` : `${Date.now()}`,
      conversationId: m.conversation_id !== undefined ? m.conversation_id : this.conversationId,
      senderId: m.sender_id !== undefined ? m.sender_id : 0,
      content: content,
      timestamp: Date.now(),
      mine: false
    };
    this.messages = this.messages.concat([msg]);
  }

  private sendMessage(): void {
    const text: string = this.draft.trim();
    if (text.length === 0 || this.conversationId < 0) {
      return;
    }
    const msg: ImMessage = {
      id: `${Date.now()}`,
      conversationId: this.conversationId,
      senderId: 0,
      content: text,
      timestamp: Date.now(),
      mine: true
    };
    this.messages = this.messages.concat([msg]);
    this.draft = '';
  }

  private closeConversation(): void {
    this.teardownWs();
    this.connStatus = 'idle';
    this.conversationId = -1;
    this.messages = [];
    this.draft = '';
    this.peerIdText = '';
    this.error = '';
  }

  build() {
    this.ImArea();
  }

  @Builder
  ImArea() {
    Column() {
      this.Header();
      if (this.conversationId < 0) {
        this.NewConversationArea();
      } else {
        this.ConversationArea();
      }
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
        Text('IM 消息')
          .fontSize(18)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text(this.conversationId < 0 ? '发起即时直聊' : `会话 #${this.conversationId} · ${this.connStatusLabel()}`)
          .fontSize(12)
          .fontColor(this.connStatus === 'open' ? '#166534' : '#4B5563')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      if (this.conversationId >= 0) {
        Text('关闭')
          .fontSize(13)
          .fontColor('#1D4ED8')
          .padding({ left: 10, right: 10, top: 6, bottom: 6 })
          .backgroundColor('#E8F0FF')
          .borderRadius(10)
          .onClick(() => this.closeConversation());
      }
    }
    .width('100%')
    .padding({ left: 12, right: 14, top: 10, bottom: 10 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  NewConversationArea() {
    Scroll() {
      Column({ space: 12 }) {
        this.NewConversationCard();
        if (this.error.length > 0) {
          this.ErrorText();
        }
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 16, bottom: 16 });
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  NewConversationCard() {
    Column({ space: 12 }) {
      Row({ space: 10 }) {
        Text('👤')
          .width(34)
          .height(34)
          .borderRadius(17)
          .fontSize(16)
          .textAlign(TextAlign.Center)
          .backgroundColor('#E8F0FF');
        Column({ space: 2 }) {
          Text('对方用户')
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827');
          Text('输入企业用户 ID 后发起直聊')
            .fontSize(12)
            .fontColor('#4B5563');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      TextInput({ placeholder: '用户 ID', text: this.peerIdText })
        .height(44)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#6B7280')
        .backgroundColor('#FFFFFF')
        .borderRadius(12)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 14, right: 14 })
        .type(InputType.Number)
        .onChange((value: string) => {
          const digits: string = value.replace(/[^0-9]/g, '').substring(0, 10);
          this.peerIdText = digits;
        });

      Button('打开会话')
        .height(44)
        .width('100%')
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(12)
        .enabled(this.peerIdText.trim().length > 0)
        .onClick(() => this.openConversation());
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ConversationArea() {
    Column() {
      Scroll() {
        Column({ space: 10 }) {
          if (this.messages.length === 0) {
            this.EmptyConversationHint();
          } else {
            ForEach(this.messages, (message: ImMessage) => {
              this.ImMessageBubble(message);
            }, (message: ImMessage) => message.id);
          }
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 16 });
      }
      .width('100%')
      .layoutWeight(1);

      if (this.error.length > 0) {
        this.ErrorText();
      }
      this.InputBar();
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  EmptyConversationHint() {
    Column({ space: 6 }) {
      Text('💬')
        .width(52)
        .height(52)
        .borderRadius(16)
        .fontSize(24)
        .textAlign(TextAlign.Center)
        .backgroundColor('#F3F4F6');
      Text('暂无消息')
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
      Text('发出第一条消息后会显示在这里')
        .fontSize(12)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding({ top: 48, bottom: 48 })
    .alignItems(HorizontalAlign.Center);
  }

  @Builder
  ImMessageBubble(message: ImMessage) {
    Row() {
      if (message.mine) {
        Blank()
          .layoutWeight(1);
        Column({ space: 2 }) {
          Text(`用户 ${message.senderId}`)
            .fontSize(11)
            .fontColor('#D1FAE5')
            .maxLines(1);
          Text(message.content)
            .fontSize(15)
            .fontColor('#FFFFFF')
            .lineHeight(22);
        }
        .padding({ left: 12, right: 12, top: 9, bottom: 9 })
        .backgroundColor('#18A85F')
        .borderRadius(12)
        .constraintSize({ maxWidth: '78%' })
        .alignItems(HorizontalAlign.End);
      } else {
        Column({ space: 2 }) {
          Text(`用户 ${message.senderId}`)
            .fontSize(11)
            .fontColor('#6B7280')
            .maxLines(1);
          Text(message.content)
            .fontSize(15)
            .fontColor('#111827')
            .lineHeight(22);
        }
        .padding({ left: 12, right: 12, top: 9, bottom: 9 })
        .backgroundColor('#FFFFFF')
        .borderRadius(12)
        .border({ width: 1, color: '#E5E7EB' })
        .constraintSize({ maxWidth: '78%' })
        .alignItems(HorizontalAlign.Start);
        Blank()
          .layoutWeight(1);
      }
    }
    .width('100%');
  }

  @Builder
  InputBar() {
    Row({ space: 10 }) {
      TextInput({ placeholder: '输入消息', text: this.draft })
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
          this.draft = value;
        });
      Button('发送')
        .height(44)
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(20)
        .padding({ left: 20, right: 20 })
        .enabled(this.draft.trim().length > 0)
        .onClick(() => this.sendMessage());
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  @Builder
  ErrorText() {
    Text(this.error)
      .fontSize(12)
      .fontColor('#B91C1C')
      .padding({ left: 14, right: 14, top: 4, bottom: 4 });
  }
}

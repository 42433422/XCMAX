import { ChatMessage } from '../models/MobileModels';

const TAB_MESSAGES = 0;
const TAB_CONTACTS = 1;
const TAB_DISCOVER = 2;
const TAB_PROFILE = 3;

@Component
export struct ChatPage {
  @Consume activeConversationId: string;
  @Consume activeConversationTitle: string;
  @Consume activeEmployeeKey: string;
  @Consume messages: ChatMessage[];
  @Consume chatInput: string;
  @Consume loading: boolean;
  @Consume selectedTab: number;
  @Consume selectedEmployeeKey: string;

  onSendChatMessage: () => void = () => {};

  build() {
    this.ChatArea();
  }

  @Builder
  ChatArea() {
    Column() {
      Row({ space: 10 }) {
        Text('<')
          .width(36)
          .height(36)
          .fontSize(22)
          .fontColor('#111827')
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.activeConversationId = '';
            this.activeEmployeeKey = '';
          });

        Column({ space: 2 }) {
          Text(this.activeConversationTitle)
            .fontSize(18)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(this.activeEmployeeKey.length > 0 ? '企业端已安装员工' : '固定服务入口')
            .fontSize(12)
            .fontColor('#4B5563');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);

        Text('i')
          .width(34)
          .height(34)
          .borderRadius(17)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor('#1D4ED8')
          .textAlign(TextAlign.Center)
          .backgroundColor('#E8F0FF')
          .onClick(() => {
            if (this.activeEmployeeKey.length > 0) {
              this.selectedEmployeeKey = this.activeEmployeeKey;
              this.selectedTab = TAB_CONTACTS;
              this.activeConversationId = '';
            } else {
              this.selectedTab = TAB_PROFILE;
              this.activeConversationId = '';
            }
          });
      }
      .width('100%')
      .padding({ left: 12, right: 14, top: 8, bottom: 8 })
      .backgroundColor('#FFFFFF')
      .border({ width: { bottom: 1 }, color: '#E5E7EB' });

      Scroll() {
        Column({ space: 12 }) {
          ForEach(this.messages, (message: ChatMessage, index: number) => {
            this.ChatBubble(message, index);
          }, (_message: ChatMessage, index: number) => `${index}`);
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 16 });
      }
      .width('100%')
      .layoutWeight(1);

      Column({ space: 8 }) {
        Row({ space: 8 }) {
          this.ModeChip('快速', true);
          this.ModeChip('深度', false);
          this.ModeChip('识图', false);
        }
        .width('100%');

        Row({ space: 10 }) {
          TextInput({ placeholder: '发送消息', text: this.chatInput })
            .height(44)
            .fontSize(15)
            .fontColor('#111827')
            .placeholderColor('#6B7280')
            .backgroundColor('#FFFFFF')
            .borderRadius(12)
            .padding({ left: 14, right: 14 })
            .layoutWeight(1)
            .onChange((value: string) => {
              this.chatInput = value;
            });
          Button(this.loading ? '...' : '发送')
            .height(44)
            .fontSize(15)
            .fontColor('#FFFFFF')
            .backgroundColor('#2563EB')
            .borderRadius(12)
            .padding({ left: 18, right: 18 })
            .enabled(!this.loading)
            .onClick(() => {
              this.onSendChatMessage();
            });
        }
        .width('100%');
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 12 })
      .backgroundColor('#F4F6F8')
      .border({ width: { top: 1 }, color: '#E5E7EB' });
    }
    .width('100%')
    .layoutWeight(1);
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
          .borderRadius(14)
          .constraintSize({ maxWidth: '78%' });
      } else {
        Text(message.text)
          .fontSize(15)
          .fontColor('#111827')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#FFFFFF')
          .borderRadius(14)
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
  ModeChip(label: string, active: boolean) {
    Text(label)
      .fontSize(12)
      .fontColor(active ? '#1D4ED8' : '#4B5563')
      .padding({ left: 10, right: 10, top: 5, bottom: 5 })
      .backgroundColor(active ? '#E8F0FF' : '#FFFFFF')
      .borderRadius(10)
      .border({ width: 1, color: active ? '#C7D7FE' : '#E5E7EB' });
  }
}

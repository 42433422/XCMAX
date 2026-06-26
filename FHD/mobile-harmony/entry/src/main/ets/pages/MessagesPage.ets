import { ConversationSummary, MESSAGE_AVATAR_LAYOUT } from '../models/MobileModels';
import { ChatPage } from './ChatPage';

@Component
export struct MessagesPage {
  @Consume activeConversationId: string;
  @Consume conversations: ConversationSummary[];

  onOpenConversation: (item: ConversationSummary) => void = () => {};
  onSendChatMessage: () => void = () => {};
  onOpenOverlay: (name: string) => void = () => {};

  build() {
    this.MessageArea();
  }

  @Builder
  MessageArea() {
    if (this.activeConversationId.length > 0) {
      ChatPage({ onSendChatMessage: () => this.onSendChatMessage() });
    } else {
      Scroll() {
        Column({ space: 10 }) {
          Row() {
            Text('消息')
              .fontSize(24)
              .fontWeight(FontWeight.Bold)
              .fontColor('#111827')
              .layoutWeight(1);
            Text(`${this.conversations.length} 个会话`)
              .fontSize(13)
              .fontColor('#4B5563');
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 18 });

          this.GroupChatEntry();

          ForEach(this.conversations, (item: ConversationSummary) => {
            this.ConversationRow(item);
          }, (item: ConversationSummary) => item.id);
        }
        .width('100%')
        .padding({ bottom: 18 });
      }
      .width('100%')
      .layoutWeight(1);
    }
  }

  @Builder
  GroupChatEntry() {
    Row({ space: 12 }) {
      Text('群')
        .width(48)
        .height(48)
        .borderRadius(14)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor('#7C3AED');
      Column({ space: 4 }) {
        Text('AI 群聊')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text('多位 AI 员工在群里协作,可 @ 点名')
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
      Text('>')
        .fontSize(18)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding(14)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.onOpenOverlay('aigroups'));
  }

  @Builder
  ConversationRow(item: ConversationSummary) {
    Row({ space: MESSAGE_AVATAR_LAYOUT.conversationAvatarTextGap }) {
      this.Avatar(item.avatar, item.id === 'assistant' ? '#18A85F' : '#1D4ED8');

      Column({ space: 5 }) {
        Row({ space: 8 }) {
          Text(item.title)
            .fontSize(17)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          Text(item.badge)
            .fontSize(12)
            .fontColor('#166534')
            .padding({ left: 8, right: 8, top: 3, bottom: 3 })
            .backgroundColor('#E7F7EE')
            .borderRadius(9);
        }
        .width('100%');

        Text(item.subtitle)
          .fontSize(14)
          .fontColor('#374151')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });

        Text(item.source === 'fixed' ? '固定入口' : item.source)
          .fontSize(12)
          .fontColor('#1D4ED8')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(MESSAGE_AVATAR_LAYOUT.conversationRowPadding)
    .margin({
      left: MESSAGE_AVATAR_LAYOUT.conversationRowMarginHorizontal,
      right: MESSAGE_AVATAR_LAYOUT.conversationRowMarginHorizontal
    })
    .backgroundColor('#FFFFFF')
    .borderRadius(MESSAGE_AVATAR_LAYOUT.conversationCardRadius)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => {
      this.onOpenConversation(item);
    });
  }

  @Builder
  Avatar(text: string, color: string) {
    Text(text)
      .width(MESSAGE_AVATAR_LAYOUT.conversationAvatarSize)
      .height(MESSAGE_AVATAR_LAYOUT.conversationAvatarSize)
      .borderRadius(MESSAGE_AVATAR_LAYOUT.conversationAvatarRadius)
      .fontSize(MESSAGE_AVATAR_LAYOUT.conversationAvatarFontSize)
      .fontWeight(FontWeight.Bold)
      .fontColor('#FFFFFF')
      .textAlign(TextAlign.Center)
      .backgroundColor(color);
  }
}

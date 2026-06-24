import { ConversationSummary } from '../models/MobileModels';
import { ChatPage } from './ChatPage';

@Component
export struct MessagesPage {
  @Consume activeConversationId: string;
  @Consume conversations: ConversationSummary[];
  @State searchQuery: string = '';

  onOpenConversation: (item: ConversationSummary) => void = () => {};
  onSendChatMessage: () => void = () => {};

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

          TextInput({ placeholder: '搜索会话', text: this.searchQuery })
            .height(40)
            .fontSize(15)
            .fontColor('#111827')
            .placeholderColor('#6B7280')
            .backgroundColor('#FFFFFF')
            .borderRadius(12)
            .border({ width: 1, color: '#E5E7EB' })
            .padding({ left: 14, right: 14 })
            .margin({ left: 14, right: 14 })
            .onChange((value: string) => {
              this.searchQuery = value;
            });

          ForEach(this.filtered(), (item: ConversationSummary) => {
            this.ConversationRow(item);
          }, (item: ConversationSummary) => item.id);

          if (this.filtered().length === 0) {
            Text(this.searchQuery.trim().length > 0 ? '没有匹配的会话' : '暂无会话')
              .fontSize(14)
              .fontColor('#9CA3AF')
              .margin({ top: 28 });
          }
        }
        .width('100%')
        .padding({ bottom: 18 });
      }
      .width('100%')
      .layoutWeight(1);
    }
  }

  @Builder
  ConversationRow(item: ConversationSummary) {
    Row({ space: 12 }) {
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
    .padding(14)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => {
      this.onOpenConversation(item);
    });
  }

  // 按标题/副标题大小写不敏感过滤会话（对齐 Android ConversationListScreen 搜索）。
  private filtered(): ConversationSummary[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (q.length === 0) {
      return this.conversations;
    }
    const out: ConversationSummary[] = [];
    for (const item of this.conversations) {
      if (item.title.toLowerCase().includes(q) || item.subtitle.toLowerCase().includes(q)) {
        out.push(item);
      }
    }
    return out;
  }

  @Builder
  Avatar(text: string, color: string) {
    Text(text)
      .width(48)
      .height(48)
      .borderRadius(14)
      .fontSize(18)
      .fontWeight(FontWeight.Bold)
      .fontColor('#FFFFFF')
      .textAlign(TextAlign.Center)
      .backgroundColor(color);
  }
}

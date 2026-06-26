/**
 * AI 群聊会话页面。
 *
 * 对标 Android AiGroupScreens.kt(群聊):群成员各回一条;@了具体成员则只有 TA 回复。
 * 数据源:GET/POST /api/mobile/v1/ai-groups/{id}/messages。
 * 支持从候选员工名录里邀请成员入群(POST /ai-groups/{id}/members)。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { AiGroupCandidate, AiGroupMessage, AiGroupPostResult, cleanText, firstChar } from '../models/MobileModels';

@Component
export struct AiGroupChatPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;
  @Consume displayName: string;

  @Prop groupId: string = '';
  @Prop groupName: string = '';

  @State messages: AiGroupMessage[] = [];
  @State input: string = '';
  @State loading: boolean = false;
  @State sending: boolean = false;
  @State errorMsg: string = '';
  @State showInvite: boolean = false;
  @State candidates: AiGroupCandidate[] = [];
  @State loadingCandidates: boolean = false;

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadMessages();
  }

  private async loadMessages(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.messages = await this.api.aiGroupMessages(this.groupId);
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  private async sendMessage(): Promise<void> {
    const text = this.input.trim();
    if (text.length === 0 || this.sending) {
      return;
    }
    this.input = '';
    this.sending = true;
    // 本地先回显我的消息
    const mine: AiGroupMessage = {
      id: `local-${new Date().getTime()}`, group_id: this.groupId, role: 'user',
      sender_name: cleanText(this.displayName, '我'), body: text, created_at: ''
    };
    this.messages = this.messages.concat([mine]);
    try {
      const result: AiGroupPostResult = await this.api.sendAiGroupMessage(
        this.groupId, text, cleanText(this.displayName, '我'), []);
      const replies: AiGroupMessage[] = result.messages || [];
      this.messages = this.messages.concat(replies);
    } catch (err) {
      const errMsg: AiGroupMessage = {
        id: `err-${new Date().getTime()}`, group_id: this.groupId, role: 'ai',
        sender_name: '系统', body: `发送失败：${cleanText((err as Error).message, '请稍后重试')}`, created_at: ''
      };
      this.messages = this.messages.concat([errMsg]);
    } finally {
      this.sending = false;
    }
  }

  private toggleInvite(): void {
    this.showInvite = !this.showInvite;
    if (this.showInvite && this.candidates.length === 0 && !this.loadingCandidates) {
      this.loadCandidates();
    }
  }

  private async loadCandidates(): Promise<void> {
    this.loadingCandidates = true;
    try {
      this.candidates = await this.api.aiGroupCandidates();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载候选员工失败');
    } finally {
      this.loadingCandidates = false;
    }
  }

  private async inviteMember(candidate: AiGroupCandidate): Promise<void> {
    this.showInvite = false;
    const name = cleanText(candidate.name, 'AI 员工');
    try {
      await this.api.addAiGroupMember(
        this.groupId,
        cleanText(candidate.employee_id, ''),
        cleanText(candidate.mod_id, ''),
        name,
        cleanText(candidate.avatar, ''),
        cleanText(candidate.summary, ''));
      const note: AiGroupMessage = {
        id: `sys-${new Date().getTime()}`, group_id: this.groupId, role: 'ai',
        sender_name: '系统', body: `已邀请「${name}」入群`, created_at: ''
      };
      this.messages = this.messages.concat([note]);
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '邀请失败');
    }
  }

  private isMine(message: AiGroupMessage): boolean {
    return cleanText(message.role, 'ai') === 'user';
  }

  build() {
    Column() {
      this.Header();
      if (this.showInvite) {
        this.InvitePanel();
      }
      Scroll() {
        Column({ space: 10 }) {
          if (this.loading && this.messages.length === 0) {
            this.Hint('加载中...');
          } else if (this.messages.length === 0) {
            this.Hint('群里还没有消息，发一条开始协作吧');
          } else {
            ForEach(this.messages, (message: AiGroupMessage, index: number) => {
              this.MessageBubble(message, index);
            }, (message: AiGroupMessage, index: number) => cleanText(message.id, `${index}`));
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
        Text(cleanText(this.groupName, 'AI 群聊'))
          .fontSize(18)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text('群成员会各自回复，@成员可单独点名')
          .fontSize(12)
          .fontColor('#6B7280')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('邀请')
        .fontSize(14)
        .fontColor('#1D4ED8')
        .onClick(() => { this.toggleInvite(); });
    }
    .width('100%')
    .padding({ left: 12, right: 14, top: 10, bottom: 10 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  InvitePanel() {
    Column({ space: 0 }) {
      Text('邀请员工入群（含超级员工）')
        .fontSize(13)
        .fontColor('#6B7280')
        .width('100%')
        .padding({ left: 16, top: 10, bottom: 6 });
      Scroll() {
        Column({ space: 0 }) {
          if (this.loadingCandidates && this.candidates.length === 0) {
            Text('加载中...')
              .fontSize(13)
              .fontColor('#9CA3AF')
              .padding(16);
          } else if (this.candidates.length === 0) {
            Text('暂无可邀请的员工')
              .fontSize(13)
              .fontColor('#9CA3AF')
              .padding(16);
          } else {
            ForEach(this.candidates, (candidate: AiGroupCandidate) => {
              this.CandidateRow(candidate);
            }, (candidate: AiGroupCandidate) => cleanText(candidate.employee_id, cleanText(candidate.name, '')));
          }
        }
        .width('100%');
      }
      .width('100%')
      .height(180);
    }
    .width('100%')
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  CandidateRow(candidate: AiGroupCandidate) {
    Row({ space: 10 }) {
      Text(firstChar(cleanText(candidate.name, 'AI')))
        .width(32)
        .height(32)
        .borderRadius(16)
        .fontSize(13)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(candidate.is_super === true ? '#7C3AED' : '#1D4ED8');
      Text(cleanText(candidate.name, 'AI 员工'))
        .fontSize(14)
        .fontColor('#111827')
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis });
      if (candidate.is_super === true) {
        Text('超级员工')
          .fontSize(11)
          .fontColor('#7C3AED')
          .backgroundColor('#F3E8FF')
          .borderRadius(8)
          .padding({ left: 8, right: 8, top: 2, bottom: 2 });
      }
      Blank().layoutWeight(1);
      Text('邀请')
        .fontSize(13)
        .fontColor('#1D4ED8');
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 10, bottom: 10 })
    .onClick(() => this.inviteMember(candidate));
  }

  @Builder
  Hint(text: string) {
    Column() {
      Text(text)
        .fontSize(14)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding({ top: 48, bottom: 48 })
    .alignItems(HorizontalAlign.Center);
  }

  @Builder
  MessageBubble(message: AiGroupMessage, index: number) {
    if (this.isMine(message)) {
      Row() {
        Blank().layoutWeight(1);
        Text(cleanText(message.body, ''))
          .fontSize(15)
          .fontColor('#FFFFFF')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#18A85F')
          .borderRadius(12)
          .constraintSize({ maxWidth: '78%' });
      }
      .width('100%')
      .padding({ top: index === 0 ? 0 : 2 });
    } else {
      Row({ space: 8 }) {
        Text(firstChar(cleanText(message.sender_name, 'AI')))
          .width(36)
          .height(36)
          .borderRadius(18)
          .fontSize(14)
          .fontColor('#FFFFFF')
          .textAlign(TextAlign.Center)
          .backgroundColor('#7C3AED');
        Column({ space: 3 }) {
          Text(cleanText(message.sender_name, 'AI 员工'))
            .fontSize(12)
            .fontColor('#6B7280');
          Text(cleanText(message.body, ''))
            .fontSize(15)
            .fontColor('#111827')
            .lineHeight(22)
            .padding({ left: 14, right: 14, top: 10, bottom: 10 })
            .backgroundColor('#FFFFFF')
            .borderRadius(12)
            .border({ width: 1, color: '#E5E7EB' })
            .constraintSize({ maxWidth: '82%' });
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)
      .padding({ top: index === 0 ? 0 : 2 });
    }
  }

  @Builder
  InputBar() {
    Row({ space: 10 }) {
      TextInput({ placeholder: '在群里发消息', text: this.input })
        .height(44)
        .fontSize(15)
        .fontColor('#111827')
        .placeholderColor('#6B7280')
        .backgroundColor('#FFFFFF')
        .borderRadius(20)
        .border({ width: 1, color: '#E5E7EB' })
        .padding({ left: 16, right: 16 })
        .layoutWeight(1)
        .onChange((value: string) => { this.input = value; });
      Button(this.sending ? '...' : '发送')
        .height(44)
        .fontSize(15)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(20)
        .padding({ left: 20, right: 20 })
        .enabled(!this.sending && this.input.trim().length > 0)
        .onClick(() => this.sendMessage());
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }
}

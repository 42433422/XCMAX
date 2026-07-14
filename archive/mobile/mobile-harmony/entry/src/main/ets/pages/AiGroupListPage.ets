/**
 * AI 群聊列表页面。
 *
 * 对标 Android AiGroupScreens.kt:首次进入后端自动按 6 个部门种出 6 个群。
 * 数据源:GET /api/mobile/v1/ai-groups;POST 创建自定义群。
 * 点击群 → onOpenGroup(id, name) → AiGroupChatPage。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { AiGroup, cleanText, firstChar } from '../models/MobileModels';

@Component
export struct AiGroupListPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State groups: AiGroup[] = [];
  @State loading: boolean = false;
  @State errorMsg: string = '';
  @State creating: boolean = false;
  @State showCreate: boolean = false;
  @State newName: string = '';

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};
  onOpenGroup: (groupId: string, groupName: string) => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadGroups();
  }

  private async loadGroups(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.groups = await this.api.aiGroups();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  private async createGroup(): Promise<void> {
    const name = this.newName.trim();
    if (name.length === 0 || this.creating) {
      return;
    }
    this.creating = true;
    try {
      await this.api.createAiGroup(name);
      this.newName = '';
      this.showCreate = false;
      await this.loadGroups();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '创建失败');
    } finally {
      this.creating = false;
    }
  }

  build() {
    Column() {
      this.Header();
      if (this.showCreate) {
        this.CreatePanel();
      }
      if (this.loading && this.groups.length === 0) {
        this.StateCard('加载中...');
      } else if (this.errorMsg.length > 0 && this.groups.length === 0) {
        this.StateCard(this.errorMsg);
      } else if (this.groups.length === 0) {
        this.StateCard('暂无群聊');
      } else {
        Scroll() {
          Column({ space: 10 }) {
            ForEach(this.groups, (group: AiGroup) => {
              this.GroupCard(group);
            }, (group: AiGroup) => cleanText(group.id, 'g'));
          }
          .width('100%')
          .padding({ top: 12, bottom: 24 });
        }
        .width('100%')
        .layoutWeight(1);
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
        Text('AI 群聊')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('多位 AI 员工在群里协作')
          .fontSize(13)
          .fontColor('#4B5563');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text(this.showCreate ? '取消' : '+ 建群')
        .fontSize(14)
        .fontColor('#1D4ED8')
        .onClick(() => { this.showCreate = !this.showCreate; });
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  CreatePanel() {
    Row({ space: 10 }) {
      TextInput({ placeholder: '群名称', text: this.newName })
        .height(40)
        .fontSize(14)
        .layoutWeight(1)
        .onChange((value: string) => { this.newName = value; });
      Button(this.creating ? '...' : '创建')
        .height(40)
        .fontSize(14)
        .enabled(!this.creating && this.newName.trim().length > 0)
        .onClick(() => this.createGroup());
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 10, bottom: 10 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  StateCard(text: string) {
    Column() {
      Text(text)
        .fontSize(14)
        .fontColor('#6B7280');
    }
    .width('100%')
    .layoutWeight(1)
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center);
  }

  @Builder
  GroupCard(group: AiGroup) {
    Row({ space: 12 }) {
      Text(firstChar(cleanText(group.name, '群')))
        .width(46)
        .height(46)
        .borderRadius(12)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor('#7C3AED');

      Column({ space: 4 }) {
        Row({ space: 8 }) {
          Text(cleanText(group.name, 'AI 群聊'))
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          if (group.unread_count !== undefined && group.unread_count > 0) {
            Text(`${group.unread_count}`)
              .fontSize(11)
              .fontColor('#FFFFFF')
              .padding({ left: 7, right: 7, top: 2, bottom: 2 })
              .backgroundColor('#DC2626')
              .borderRadius(9);
          }
        }
        .width('100%');

        Text(cleanText(group.last_message_preview, `${group.member_count !== undefined ? group.member_count : 0} 位成员`))
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
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.onOpenGroup(cleanText(group.id, ''), cleanText(group.name, 'AI 群聊')));
  }
}

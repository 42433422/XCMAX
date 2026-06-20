import { ConversationSummary } from '../models/MobileModels';
import { MessagesPage } from './MessagesPage';
import { ContactsPage } from './ContactsPage';
import { DiscoverPage } from './DiscoverPage';
import { ProfilePage } from './ProfilePage';

const TAB_MESSAGES = 0;
const TAB_CONTACTS = 1;
const TAB_DISCOVER = 2;
const TAB_PROFILE = 3;

@Component
export struct MainShell {
  @Consume selectedTab: number;
  @Consume companyBrand: string;
  @Consume displayName: string;
  @Consume accountKind: string;
  @Consume activeConversationId: string;

  onOpenConversation: (item: ConversationSummary) => void = () => {};
  onSendChatMessage: () => void = () => {};
  onStartEmployeeChat: (employeeKey: string) => void = () => {};
  onRefreshHome: () => void = () => {};
  onLogout: () => void = () => {};
  onOpenSettings: () => void = () => {};
  onOpenDutyRoster: () => void = () => {};

  build() {
    this.MainShell();
  }

  @Builder
  MainShell() {
    Column() {
      this.TopBar();

      if (this.selectedTab === TAB_MESSAGES) {
        MessagesPage({
          onOpenConversation: (item: ConversationSummary) => this.onOpenConversation(item),
          onSendChatMessage: () => this.onSendChatMessage()
        });
      } else if (this.selectedTab === TAB_CONTACTS) {
        ContactsPage({
          onStartEmployeeChat: (employeeKey: string) => this.onStartEmployeeChat(employeeKey)
        });
      } else if (this.selectedTab === TAB_DISCOVER) {
        DiscoverPage({
          onOpenDutyRoster: () => this.onOpenDutyRoster()
        });
      } else {
        ProfilePage({
          onRefreshHome: () => this.onRefreshHome(),
          onLogout: () => this.onLogout(),
          onOpenSettings: () => this.onOpenSettings()
        });
      }

      this.BottomNav();
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  TopBar() {
    Row({ space: 12 }) {
      Column({ space: 2 }) {
        Text(this.companyBrand)
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(`${this.displayName} · ${this.accountKind === 'enterprise' ? '企业账号' : this.accountKind}`)
          .fontSize(13)
          .fontColor('#374151')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('i')
        .width(36)
        .height(36)
        .borderRadius(18)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#1D4ED8')
        .textAlign(TextAlign.Center)
        .backgroundColor('#E8F0FF')
        .border({ width: 1, color: '#C7D7FE' })
        .onClick(() => {
          this.selectedTab = TAB_PROFILE;
        });
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  BottomNav() {
    Row() {
      this.NavItem('消息', TAB_MESSAGES);
      this.NavItem('通讯录', TAB_CONTACTS);
      this.NavItem('探索', TAB_DISCOVER);
      this.NavItem('我的', TAB_PROFILE);
    }
    .width('100%')
    .height(62)
    .padding({ left: 8, right: 8 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  @Builder
  NavItem(label: string, tab: number) {
    Column({ space: 4 }) {
      Text(this.navGlyph(tab))
        .fontSize(18)
        .fontColor(this.selectedTab === tab ? '#18A85F' : '#4B5563')
        .fontWeight(this.selectedTab === tab ? FontWeight.Bold : FontWeight.Regular);
      Text(label)
        .fontSize(12)
        .fontColor(this.selectedTab === tab ? '#18A85F' : '#4B5563');
    }
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .layoutWeight(1)
    .height('100%')
    .onClick(() => {
      this.selectedTab = tab;
      this.activeConversationId = '';
    });
  }

  private navGlyph(tab: number): string {
    if (tab === TAB_MESSAGES) {
      return 'M';
    }
    if (tab === TAB_CONTACTS) {
      return 'A';
    }
    if (tab === TAB_DISCOVER) {
      return 'O';
    }
    return 'U';
  }
}

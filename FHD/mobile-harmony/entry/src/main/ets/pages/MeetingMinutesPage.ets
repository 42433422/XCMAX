import { MobileApiClient } from '../api/MobileApiClient';
import { MeetingLevelDef, MeetingMinuteData } from '../models/MobileModels';

const FALLBACK_LEVELS: MeetingLevelDef[] = [
  { id: 'level1_script', label: '剧本式实录', short: '剧本', derives_from: 'raw' },
  { id: 'level2_architecture', label: '架构图式总结', short: '架构图', derives_from: 'level1_script', render: 'mermaid' },
  { id: 'level3_plain', label: '说人话', short: '说人话', derives_from: 'level2_architecture' }
];

/**
 * 会议纪要页：粘贴会议转写原文 → 一键生成三级纪要（剧本式 → 架构图式 → 说人话）。
 * 三级与后端 SSOT 同源；L2 架构图含 Mermaid 源码与提纲，按本端富文本约定以文本呈现。
 */
@Component
export struct MeetingMinutesPage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State transcript: string = '';
  @State generating: boolean = false;
  @State activeTab: number = 0;
  @State hasResult: boolean = false;
  @State result: MeetingMinuteData = {};
  @State levels: MeetingLevelDef[] = FALLBACK_LEVELS;
  @State errorText: string = '';

  private api: MobileApiClient = new MobileApiClient('');

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadLevels();
  }

  private async loadLevels(): Promise<void> {
    try {
      const cfg = await this.api.meetingLevels();
      const list = cfg.levels;
      if (list !== undefined && list.length > 0) {
        this.levels = list;
      }
    } catch (_err) {
      this.levels = FALLBACK_LEVELS;
    }
  }

  private async generate(): Promise<void> {
    const text: string = this.transcript.trim();
    if (text.length === 0 || this.generating) {
      return;
    }
    this.errorText = '';
    this.generating = true;
    try {
      const data = await this.api.generateMeetingMinutes(text);
      this.result = data;
      this.hasResult = true;
      if (data.level3_plain !== undefined && data.level3_plain.length > 0) {
        this.activeTab = 2;
      } else if (data.level2_architecture !== undefined && data.level2_architecture.length > 0) {
        this.activeTab = 1;
      } else {
        this.activeTab = 0;
      }
    } catch (err) {
      this.errorText = err instanceof Error ? err.message : '生成失败';
      this.result = { status: 'failed', error_message: this.errorText };
      this.hasResult = true;
    } finally {
      this.generating = false;
    }
  }

  private activeContent(): string {
    const lvl = this.levels[this.activeTab];
    const id = lvl !== undefined ? lvl.id : '';
    if (id === 'level1_script') {
      return this.result.level1_script || '';
    }
    if (id === 'level2_architecture') {
      return this.result.level2_architecture || '';
    }
    if (id === 'level3_plain') {
      return this.result.level3_plain || '';
    }
    return '';
  }

  build() {
    Column() {
      this.Header();

      Column({ space: 10 }) {
        TextArea({ text: this.transcript, placeholder: '会议转写原文（可直接粘贴要点 / 逐字稿）' })
          .height(120)
          .width('100%')
          .backgroundColor('#FFFFFF')
          .onChange((value: string) => { this.transcript = value; });

        Button(this.generating ? '生成中…' : '一键生成三级纪要')
          .width('100%')
          .enabled(this.transcript.trim().length > 0 && !this.generating)
          .backgroundColor('#18A85F')
          .onClick(() => { this.generate(); });

        if (this.result.status === 'degraded') {
          Text('⚠️ AI 暂不可用，已保存原文，稍后可重试').fontSize(13).fontColor('#B45309');
        } else if (this.result.status === 'failed') {
          Text('生成失败：' + (this.result.error_message || '未知错误')).fontSize(13).fontColor('#DC2626');
        }
      }
      .width('100%')
      .padding(14);

      this.TabBar();

      Scroll() {
        Column() {
          if (this.activeContent().length > 0) {
            Text(this.activeContent())
              .fontSize(14)
              .fontColor('#1F2937')
              .width('100%')
              .textAlign(TextAlign.Start);
          } else {
            Text(this.hasResult ? '该层暂无内容' : '生成后这里显示：剧本式实录 → 架构图式总结 → 说人话')
              .fontSize(13)
              .fontColor('#9CA3AF');
          }
        }
        .width('100%')
        .padding(14);
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
      Text('会议纪要')
        .fontSize(18)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 10 })
    .backgroundColor('#FFFFFF');
  }

  @Builder
  TabBar() {
    Row() {
      ForEach(this.levels, (lvl: MeetingLevelDef, index: number) => {
        Text(lvl.short !== undefined && lvl.short.length > 0 ? lvl.short : (lvl.label || ''))
          .fontSize(14)
          .fontColor(this.activeTab === index ? '#18A85F' : '#6B7280')
          .fontWeight(this.activeTab === index ? FontWeight.Medium : FontWeight.Normal)
          .padding({ left: 14, right: 14, top: 8, bottom: 8 })
          .onClick(() => { this.activeTab = index; });
      }, (lvl: MeetingLevelDef, index: number) => `${index}`);
    }
    .width('100%')
    .backgroundColor('#FFFFFF');
  }
}

/**
 * AI 交流圈页面。
 *
 * 对标 Android AiCircleScreens.kt：展示 AI 员工动态流(真数据)。
 * 数据源:后端 GET /api/mobile/v1/circle/posts(app/application/ai_circle_service.py)。
 * 支持点赞(toggle)与评论(add comment),与 Android 端行为一致。
 */

import { MobileApiClient } from '../api/MobileApiClient';
import { CirclePost, CircleComment, cleanText, firstChar } from '../models/MobileModels';

const AVATAR_COLORS: string[] = ['#1D4ED8', '#7C3AED', '#047857', '#B45309', '#BE185D', '#0369A1', '#9333EA'];

@Component
export struct AiCirclePage {
  @Consume baseUrl: string;
  @Consume accessToken: string;

  @State posts: CirclePost[] = [];
  @State loading: boolean = false;
  @State errorMsg: string = '';
  @State composingFor: number = -1;
  @State commentDraft: string = '';
  @State actionInProgress: boolean = false;

  private api: MobileApiClient = new MobileApiClient('', '');

  onBack: () => void = () => {};

  aboutToAppear(): void {
    this.api = new MobileApiClient(this.baseUrl, this.accessToken);
    this.loadPosts();
  }

  private async loadPosts(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      this.posts = await this.api.circlePosts();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '加载失败');
    } finally {
      this.loading = false;
    }
  }

  private async toggleLike(post: CirclePost): Promise<void> {
    if (this.actionInProgress || post.id === undefined) {
      return;
    }
    this.actionInProgress = true;
    try {
      await this.api.circleToggleLike(post.id);
      await this.loadPosts();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '操作失败');
    } finally {
      this.actionInProgress = false;
    }
  }

  private async submitComment(post: CirclePost): Promise<void> {
    const text = this.commentDraft.trim();
    if (this.actionInProgress || post.id === undefined || text.length === 0) {
      return;
    }
    this.actionInProgress = true;
    try {
      await this.api.circleAddComment(post.id, text);
      this.commentDraft = '';
      this.composingFor = -1;
      await this.loadPosts();
    } catch (err) {
      this.errorMsg = cleanText((err as Error).message, '评论失败');
    } finally {
      this.actionInProgress = false;
    }
  }

  private avatarColor(post: CirclePost): string {
    const seed = cleanText(post.employee_id, cleanText(post.author_name, 'AI'));
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
      hash = (hash + seed.charCodeAt(i)) % AVATAR_COLORS.length;
    }
    return AVATAR_COLORS[hash];
  }

  private formatTime(iso: string | undefined): string {
    const value = cleanText(iso, '');
    if (value.length === 0) {
      return '';
    }
    // ISO → "YYYY-MM-DD HH:mm"
    const cleaned = value.replace('T', ' ');
    return cleaned.length >= 16 ? cleaned.substring(0, 16) : cleaned;
  }

  build() {
    Column() {
      this.Header();
      if (this.loading && this.posts.length === 0) {
        this.StateCard('加载中...');
      } else if (this.errorMsg.length > 0 && this.posts.length === 0) {
        this.StateCard(this.errorMsg);
      } else if (this.posts.length === 0) {
        this.StateCard('暂无动态');
      } else {
        Scroll() {
          Column({ space: 12 }) {
            this.SummaryCard();
            ForEach(this.posts, (post: CirclePost) => {
              this.MomentCard(post);
            }, (post: CirclePost) => (post.id !== undefined ? post.id.toString() : 'p'));
          }
          .width('100%')
          .padding({ top: 14, bottom: 24 });
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
        Text('AI交流圈')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('AI 员工动态流')
          .fontSize(13)
          .fontColor('#4B5563');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
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
  SummaryCard() {
    Row({ space: 8 }) {
      Text('企业账号生态')
        .fontSize(15)
        .fontColor('#374151')
        .layoutWeight(1);
      Text(`${this.posts.length} 条动态`)
        .fontSize(13)
        .fontColor('#1D4ED8')
        .padding({ left: 10, right: 10, top: 5, bottom: 5 })
        .backgroundColor('#E8F0FF')
        .borderRadius(10);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  MomentCard(post: CirclePost) {
    Column({ space: 10 }) {
      Row({ space: 12 }) {
        Text(firstChar(cleanText(post.author_name, 'AI')))
          .width(44)
          .height(44)
          .borderRadius(22)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor('#FFFFFF')
          .textAlign(TextAlign.Center)
          .backgroundColor(this.avatarColor(post));

        Column({ space: 2 }) {
          Text(cleanText(post.author_name, 'AI 员工'))
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(cleanText(post.employee_id, '企业员工'))
            .fontSize(12)
            .fontColor('#4B5563')
            .maxLines(1);
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);

        Text(this.formatTime(post.created_at))
          .fontSize(12)
          .fontColor('#6B7280');
      }
      .width('100%');

      Text(cleanText(post.body, ''))
        .width('100%')
        .fontSize(14)
        .fontColor('#111827')
        .lineHeight(20)
        .maxLines(6)
        .textOverflow({ overflow: TextOverflow.Ellipsis });

      Row({ space: 12 }) {
        Text(`${post.liked_by_me ? '已赞' : '赞'} ${post.like_count !== undefined ? post.like_count : 0}`)
          .fontSize(12)
          .fontColor(post.liked_by_me ? '#FFFFFF' : '#1D4ED8')
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor(post.liked_by_me ? '#1D4ED8' : '#E8F0FF')
          .borderRadius(10)
          .onClick(() => this.toggleLike(post));
        Text(`评论 ${post.comments !== undefined ? post.comments.length : 0}`)
          .fontSize(12)
          .fontColor('#4B5563')
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor('#F3F4F6')
          .borderRadius(10)
          .onClick(() => {
            this.composingFor = (post.id !== undefined && this.composingFor === post.id) ? -1 : (post.id !== undefined ? post.id : -1);
            this.commentDraft = '';
          });
      }
      .width('100%');

      if (post.comments !== undefined && post.comments.length > 0) {
        Column({ space: 4 }) {
          ForEach(post.comments, (c: CircleComment) => {
            Text(`${cleanText(c.author_name, '用户')}：${cleanText(c.body, '')}`)
              .width('100%')
              .fontSize(12)
              .fontColor('#374151')
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis });
          }, (c: CircleComment) => (c.id !== undefined ? c.id.toString() : 'c'));
        }
        .width('100%')
        .padding(10)
        .backgroundColor('#F9FAFB')
        .borderRadius(10);
      }

      if (post.id !== undefined && this.composingFor === post.id) {
        Row({ space: 8 }) {
          TextInput({ placeholder: '写评论...', text: this.commentDraft })
            .layoutWeight(1)
            .fontSize(13)
            .onChange((value: string) => { this.commentDraft = value; });
          Button('发送')
            .fontSize(13)
            .height(34)
            .enabled(!this.actionInProgress)
            .onClick(() => this.submitComment(post));
        }
        .width('100%');
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }
}

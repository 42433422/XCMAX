import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/pinned_ids.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../chat/chat_screen.dart';
import '../circle/ai_circle_screen.dart';

class FixedPartnerProfileScreen extends StatelessWidget {
  const FixedPartnerProfileScreen({
    super.key,
    required this.kind,
    this.repositoryConversation,
    this.repository,
  });

  final FixedPartnerKind kind;
  final ConversationItem? repositoryConversation;
  final MobileRepository? repository;

  @override
  Widget build(BuildContext context) {
    final spec = FixedPartnerProfileSpec.fromKind(kind);
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _FixedPartnerProfileTopBar(
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 28),
                children: [
                  _FixedPartnerHeader(spec: spec),
                  const SizedBox(height: 10),
                  _PlainCell(
                    title: '伙伴资料',
                    subtitle: spec.summary,
                    showArrow: false,
                  ),
                  const SizedBox(height: 10),
                  _CirclePreview(
                    spec: spec,
                    onTap: () => _openCircle(context),
                  ),
                  const SizedBox(height: 10),
                  _PlainCell(
                    title: '基础功能',
                    subtitle: spec.abilityLabels.join('、'),
                    showArrow: false,
                  ),
                  const SizedBox(height: 10),
                  _PlainCell(
                    title: '来源',
                    subtitle: spec.source,
                    showArrow: false,
                  ),
                  const SizedBox(height: 12),
                  _ActionRow(
                    text: '发消息',
                    icon: Icons.chat,
                    onTap: () => _openChat(context, spec),
                  ),
                  const SizedBox(height: 8),
                  _ActionRow(
                    text: '进入 AI 交流圈',
                    icon: Icons.forum,
                    onTap: () => _openCircle(context),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openChat(BuildContext context, FixedPartnerProfileSpec spec) {
    final conversation = repositoryConversation ?? spec.conversation;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChatScreen(
          conversation: conversation,
          initialMessages: const [],
          repository: repository,
        ),
      ),
    );
  }

  void _openCircle(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => AiCircleScreen(repository: repository)),
    );
  }
}

enum FixedPartnerKind { assistant, customerService, codex, cursor, claude }

class FixedPartnerProfileSpec {
  const FixedPartnerProfileSpec({
    required this.kind,
    required this.name,
    required this.alias,
    required this.accountId,
    required this.summary,
    required this.source,
    required this.abilityLabels,
    required this.circleLabels,
    required this.avatarFallback,
    required this.avatarColor,
    required this.conversation,
  });

  final FixedPartnerKind kind;
  final String name;
  final String alias;
  final String accountId;
  final String summary;
  final String source;
  final List<String> abilityLabels;
  final List<String> circleLabels;
  final AppAvatarFallback avatarFallback;
  final Color avatarColor;
  final ConversationItem conversation;

  static FixedPartnerProfileSpec fromKind(FixedPartnerKind kind) {
    switch (kind) {
      case FixedPartnerKind.codex:
        return _spec(
          kind: kind,
          id: PinnedIds.codex,
          type: ConversationType.pinnedCodex,
          name: '超级员工-Codex',
          alias: '全设备协同 · 排比派工',
          accountId: 'XCAGI-CODEX',
          summary: '把开发、测试、打包、提交类任务派发到在线的 Codex 工作设备协同完成；普通问题可直接对话。',
          source: 'XCAGI 超级员工 · Codex 通道',
          abilityLabels: const ['多设备派工', '开发任务', '测试验证', '打包提交'],
          circleLabels: const ['派工', '协同', '开发'],
          avatarFallback: AppAvatarFallback.codex,
          avatarColor: AppTheme.textPrimary,
        );
      case FixedPartnerKind.cursor:
        return _spec(
          kind: kind,
          id: PinnedIds.cursor,
          type: ConversationType.pinnedCursor,
          name: '超级员工-Cursor',
          alias: '全设备协同 · Agent 派工',
          accountId: 'XCAGI-CURSOR',
          summary:
              '与 Codex/Claude 同构的超级员工，把任务派发到在线 Cursor Agent 工作设备；派工不可用时回退本机 Cursor CLI 直答。',
          source: 'XCAGI 超级员工 · Cursor 通道',
          abilityLabels: const ['多设备派工', '开发任务', 'Agent 直答', '本地 CLI'],
          circleLabels: const ['派工', '协同', '开发'],
          avatarFallback: AppAvatarFallback.cursor,
          avatarColor: AppTheme.brand,
        );
      case FixedPartnerKind.claude:
        return _spec(
          kind: kind,
          id: PinnedIds.claude,
          type: ConversationType.pinnedClaude,
          name: '超级员工-Claude',
          alias: '全设备协同 · 排比派工',
          accountId: 'XCAGI-CLAUDE',
          summary: '与 Codex 同构的超级员工，把任务派发到在线 Claude 工作设备；派工不可用时回退本机 Claude 直答。',
          source: 'XCAGI 超级员工 · Claude 通道',
          abilityLabels: const ['多设备派工', '开发任务', '测试验证', '本地直答'],
          circleLabels: const ['派工', '协同', '开发'],
          avatarFallback: AppAvatarFallback.claude,
          avatarColor: AppTheme.momentAccent,
        );
      case FixedPartnerKind.assistant:
        return _spec(
          kind: kind,
          id: PinnedIds.assistant,
          type: ConversationType.pinnedAssistant,
          name: '小C助理',
          alias: '企业智能助手',
          accountId: 'XCAGI-AI-C',
          summary: '负责智能对话、快速分析、识图入口和企业协同问答。',
          source: 'XCAGI 企业版内置伙伴',
          abilityLabels: const ['智能对话', '快速模式', '深度分析', '拍照识图'],
          circleLabels: const ['对话', '分析', '识图'],
          avatarFallback: AppAvatarFallback.assistant,
          avatarColor: AppTheme.brand,
        );
      case FixedPartnerKind.customerService:
        return _spec(
          kind: kind,
          id: PinnedIds.cs,
          type: ConversationType.pinnedCs,
          name: '专属客服',
          alias: '企业服务顾问',
          accountId: 'XCAGI-CS',
          summary: '用于企业服务接待、问题反馈、订单跟进与人工协同支持。',
          source: '企业服务通道',
          abilityLabels: const ['服务咨询', '进度跟进', '问题反馈', '人工协同'],
          circleLabels: const ['服务', '协同', '反馈'],
          avatarFallback: AppAvatarFallback.customerService,
          avatarColor: AppTheme.success,
        );
    }
  }

  static FixedPartnerKind? kindForConversation(ConversationItem conversation) {
    switch (conversation.type) {
      case ConversationType.pinnedAssistant:
        return FixedPartnerKind.assistant;
      case ConversationType.pinnedCs:
        return FixedPartnerKind.customerService;
      case ConversationType.pinnedCodex:
        return FixedPartnerKind.codex;
      case ConversationType.pinnedCursor:
        return FixedPartnerKind.cursor;
      case ConversationType.pinnedClaude:
        return FixedPartnerKind.claude;
      case ConversationType.pinnedTrae:
      case ConversationType.aiTask:
      case ConversationType.systemNotification:
        return null;
    }
  }

  static FixedPartnerProfileSpec _spec({
    required FixedPartnerKind kind,
    required String id,
    required ConversationType type,
    required String name,
    required String alias,
    required String accountId,
    required String summary,
    required String source,
    required List<String> abilityLabels,
    required List<String> circleLabels,
    required AppAvatarFallback avatarFallback,
    required Color avatarColor,
  }) {
    return FixedPartnerProfileSpec(
      kind: kind,
      name: name,
      alias: alias,
      accountId: accountId,
      summary: summary,
      source: source,
      abilityLabels: abilityLabels,
      circleLabels: circleLabels,
      avatarFallback: avatarFallback,
      avatarColor: avatarColor,
      conversation: ConversationItem(
        id: id,
        type: type,
        title: name,
        subtitle: alias,
        timestampText: '',
        isPinned: true,
      ),
    );
  }
}

class _FixedPartnerProfileTopBar extends StatelessWidget {
  const _FixedPartnerProfileTopBar({required this.onBack});

  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 64,
      color: colors.surface,
      child: Row(
        children: [
          IconButton(
            onPressed: onBack,
            icon: const Icon(Icons.arrow_back, size: 24),
            tooltip: '返回',
            color: colors.textPrimary,
          ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: IconButton(
              onPressed: () {},
              icon: const Icon(Icons.more_horiz),
              tooltip: '更多',
              color: colors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

class _FixedPartnerHeader extends StatelessWidget {
  const _FixedPartnerHeader({required this.spec});

  final FixedPartnerProfileSpec spec;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.fromLTRB(28, 34, 24, 34),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppAvatar(
            fallback: spec.avatarFallback,
            size: 76,
            borderRadius: BorderRadius.circular(8),
            contentDescription: spec.name,
          ),
          const SizedBox(width: 18),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  spec.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 22,
                    height: 1.27,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  '昵称：${spec.alias}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(context),
                ),
                const SizedBox(height: 6),
                Text(
                  'AI号：${spec.accountId}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(context),
                ),
                const SizedBox(height: 6),
                Text(
                  '来源：${spec.source}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textSecondary,
                    fontSize: 13,
                    height: 1.31,
                    letterSpacing: 0,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PlainCell extends StatelessWidget {
  const _PlainCell({
    required this.title,
    required this.subtitle,
    required this.showArrow,
  });

  final String title;
  final String subtitle;
  final bool showArrow;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 17,
                    height: 1.29,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
                if (subtitle.trim().isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (showArrow)
            Icon(
              Icons.chevron_right,
              size: 20,
              color: colors.textTertiary,
            ),
        ],
      ),
    );
  }
}

class _CirclePreview extends StatelessWidget {
  const _CirclePreview({
    required this.spec,
    required this.onTap,
  });

  final FixedPartnerProfileSpec spec;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final labels = spec.circleLabels.take(3).toList(growable: false);
    final colors = AppTheme.colors(context);
    final accent = _resolvePartnerColor(context, spec.avatarColor);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          child: Column(
            children: [
              Row(
                children: [
                  Icon(
                    Icons.forum,
                    size: 20,
                    color: colors.momentAccent,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'AI交流圈',
                          style: TextStyle(
                            color: colors.textPrimary,
                            fontSize: 17,
                            height: 1.29,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '进入交流圈 · 查看 ${spec.name} 的动态与能力更新',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: colors.textSecondary,
                            fontSize: 13,
                            height: 1.31,
                            letterSpacing: 0,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Icon(
                    Icons.chevron_right,
                    size: 20,
                    color: colors.textTertiary,
                  ),
                ],
              ),
              if (labels.isNotEmpty) ...[
                const SizedBox(height: 12),
                Row(
                  children: [
                    const SizedBox(width: 30),
                    for (final label in labels) ...[
                      Container(
                        width: 44,
                        height: 44,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: accent.withValues(alpha: 0.16),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          label.length > 2 ? label.substring(0, 2) : label,
                          style: TextStyle(
                            color: accent,
                            fontSize: 11,
                            height: 1.27,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 0,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({
    required this.text,
    required this.icon,
    required this.onTap,
  });

  final String text;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 22, color: colors.brand),
              const SizedBox(width: 10),
              Text(
                text,
                style: TextStyle(
                  color: colors.brand,
                  fontSize: 17,
                  height: 1.29,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

TextStyle _bodyStyle(BuildContext context) {
  final colors = AppTheme.colors(context);
  return TextStyle(
    color: colors.textSecondary,
    fontSize: 15,
    height: 1.4,
    letterSpacing: 0,
  );
}

Color _resolvePartnerColor(BuildContext context, Color color) {
  final colors = AppTheme.colors(context);
  return switch (color) {
    AppTheme.brand => colors.brand,
    AppTheme.success => colors.success,
    AppTheme.momentAccent => colors.momentAccent,
    AppTheme.textPrimary => colors.textPrimary,
    _ => color,
  };
}

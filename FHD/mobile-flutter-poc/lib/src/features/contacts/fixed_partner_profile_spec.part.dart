part of 'fixed_partner_profile_screen.dart';

enum FixedPartnerKind {
  assistant,
  customerService,
  codex,
  cursor,
  claude,
  trae,
}

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
      case FixedPartnerKind.trae:
        return _spec(
          kind: kind,
          id: PinnedIds.trae,
          type: ConversationType.pinnedTrae,
          name: '超级员工-Trae',
          alias: '全设备协同 · IDE 执行端',
          accountId: 'XCAGI-TRAE',
          summary:
              '与 Codex/Cursor/Claude 同构的超级员工，把任务派发到在线 Trae 工作设备；派工不可用时回退本机 Trae CLI 直答，兼顾 IDE 执行端、备用额度与补位协作。',
          source: 'XCAGI 超级员工 · Trae 通道',
          abilityLabels: const ['多设备派工', 'IDE 执行', '补位协作', '本地 CLI'],
          circleLabels: const ['派工', '协同', '开发'],
          avatarFallback: AppAvatarFallback.trae,
          avatarColor: AppTheme.success,
        );
      case FixedPartnerKind.assistant:
        return _spec(
          kind: kind,
          id: PinnedIds.assistant,
          type: ConversationType.pinnedAssistant,
          name: '小C助理',
          alias: 'AI助手',
          accountId: 'XCAGI-AI-C',
          summary: '负责智能对话、快速分析、识图入口和团队协同问答。',
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
          alias: '服务顾问',
          accountId: 'XCAGI-CS',
          summary: '用于服务接待、问题反馈、订单跟进与人工协同支持。',
          source: '服务通道',
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
        return FixedPartnerKind.trae;
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

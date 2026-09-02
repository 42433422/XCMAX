import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/pinned_ids.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../chat/chat_screen.dart';
import '../circle/ai_circle_screen.dart';
part 'fixed_partner_profile_spec.part.dart';
part 'fixed_partner_profile_widgets.part.dart';

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
                  _CirclePreview(spec: spec, onTap: () => _openCircle(context)),
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

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_chat_ui/flutter_chat_ui.dart' hide ChatMessage;
import 'package:flutter_chat_core/flutter_chat_core.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../data/offline/mobile_offline_store.dart';
import '../../models/conversation.dart';
import '../../policy/mobile_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
import '../../theme/app_icons.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../contacts/employee_profile_screen.dart';
import '../contacts/fixed_partner_profile_screen.dart';
import '../devtools/branch_detail_screen.dart';
import '../devtools/diff_viewer_screen.dart';
import '../devtools/timeline_screen.dart';
import '../tools/ocr_screen.dart';
import '../voice/voice_input_sheet.dart';

// 按职责拆分为 part 文件：state 状态类分层（helpers/messaging/actions）与各 UI 组件组。
part 'chat_screen_state_helpers.part.dart';
part 'chat_screen_state_messaging.part.dart';
part 'chat_screen_state_actions.part.dart';
part 'chat_screen_bubble.part.dart';
part 'chat_screen_widgets.part.dart';
part 'chat_screen_composer.part.dart';
part 'chat_screen_employee_tools.part.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.conversation,
    required this.initialMessages,
    this.repository,
  });

  final ConversationItem conversation;
  final List<ChatMessage> initialMessages;
  final MobileRepository? repository;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends _ChatStateActions {
  @override
  void initState() {
    super.initState();
    _messages = [...widget.initialMessages];
    _syncFlyerChat();
    _repository = widget.repository ?? MobileRepositoryScope.maybeRead(context);
    _employeeRef = _parseEmployeeConversationRef(widget.conversation.id);
    _loadRemoteMessages();
    _loadUserAvatar();
    _loadEmployeeProfile();
  }

  @override
  void dispose() {
    _flyerChatController.dispose();
    _controller.dispose();
    super.dispose();
  }

  Widget _buildEmptyChat(BuildContext context) {
    return const SizedBox.shrink();
  }

  Widget _buildFlyerTextMessage(
    BuildContext context,
    TextMessage message,
    int index, {
    required bool isSentByMe,
    MessageGroupStatus? groupStatus,
  }) {
    final originalIndex =
        _messages.indexWhere((item) => item.id == message.id);
    if (originalIndex < 0) return const SizedBox.shrink();
    final original = _messages[originalIndex];
    final isActiveRelay = _sending &&
        _activeAssistantId == original.id &&
        _activeRelayProgress != null;
    final toolCalls = _toolCallsFor(original);
    return MessageBubble(
      message: original,
      conversation: widget.conversation,
      showAvatar: _showAvatarAt(originalIndex),
      userAvatarUrl: _userAvatarSource,
      aiAvatarUrl: _employeeProfile?.avatarUrl,
      aiContentDescription: _resolvedTitle,
      hasEmployeeProfile: _employeeProfile != null,
      relayProgress: isActiveRelay ? _activeRelayProgress : null,
      cancellingRelay: _cancellingRelay,
      onCancelRelay: _cancellingRelay ? null : () => _stopChat(),
      onReply: () => setState(() => _replyTo = original),
      onDelete: () => _deleteMessageAt(originalIndex),
      onResend: original.status == ChatDeliveryStatus.failed
          ? _resendLastChat
          : null,
      toolCalls: toolCalls,
      onShowTimeline: toolCalls.isEmpty
          ? null
          : () => _openTimelineForMessage(original),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final activeGitBranches = _activeGitBranches();
    final activeGitBranch = _currentGitBranch(activeGitBranches);
    final employeeProfile = _employeeProfile;
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: _resolvedTitle,
              height: 48,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: () => _showMessage('视频通话功能即将上线'),
                  icon: const Icon(AppIcons.video, size: 22),
                  tooltip: '视频',
                  color: colors.textPrimary,
                ),
                IconButton(
                  onPressed: _openProfileOrTools,
                  icon: const Icon(AppIcons.more, size: 22),
                  tooltip: '更多',
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: Chat(
                chatController: _flyerChatController,
                currentUserId: _flyerMeId,
                resolveUser: _resolveFlyerUser,
                backgroundColor: Colors.transparent,
                // 发送仍走现有链路：输入区由外层 Column 提供。
                onMessageSend: (_) {},
                builders: Builders(
                  textMessageBuilder: _buildFlyerTextMessage,
                  emptyChatListBuilder: _buildEmptyChat,
                  // 与微信/Telegram 一致：消息从底部向上生长。
                  chatAnimatedListBuilder: (context, itemBuilder) =>
                      ChatAnimatedList(itemBuilder: itemBuilder, reversed: true),
                  // 输入区由外层 Column 提供，Chat 只负责消息列表。
                  composerBuilder: (context) => const SizedBox.shrink(),
                ),
              ),
            ),
            _Composer(
              controller: _controller,
              onSend: _send,
              onStop: _stopChat,
              busy: _sending,
              topContent: _composerTopContent(
                activeGitBranches,
                activeGitBranch,
              ),
              showTools: _showToolPanel,
              onToggleTools: () =>
                  setState(() => _showToolPanel = !_showToolPanel),
              onVoice: _startVoiceInput,
              toolActions: _toolActions(),
            ),
          ],
        ),
      ),
    );
  }
}

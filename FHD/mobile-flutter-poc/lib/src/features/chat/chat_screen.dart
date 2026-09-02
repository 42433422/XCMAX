import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/mobile_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
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
    _repository = widget.repository ?? MobileRepositoryScope.maybeRead(context);
    _employeeRef = _parseEmployeeConversationRef(widget.conversation.id);
    _loadRemoteMessages();
    _loadUserAvatar();
    _loadEmployeeProfile();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
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
                  icon: const Icon(Icons.videocam_outlined, size: 22),
                  tooltip: '视频',
                  color: colors.textPrimary,
                ),
                IconButton(
                  onPressed: _openProfileOrTools,
                  icon: const Icon(Icons.more_horiz, size: 22),
                  tooltip: '更多',
                  color: colors.textPrimary,
                ),
              ],
            ),
            if (_loadingRemoteMessages)
              LinearProgressIndicator(
                minHeight: 2,
                color: colors.brand,
                backgroundColor: colors.surfaceHigh,
              ),
            Expanded(
              child: _messages.isEmpty
                  ? const SizedBox.expand()
                  : ListView.builder(
                      reverse: true,
                      padding: const EdgeInsets.fromLTRB(14, 4, 14, 20),
                      itemBuilder: (context, index) {
                        final originalIndex = _messages.length - index - 1;
                        final message = _messages[originalIndex];
                        final isActiveRelay = _sending &&
                            _activeAssistantId == message.id &&
                            _activeRelayProgress != null;
                        final toolCalls = _toolCallsFor(message);
                        return MessageBubble(
                          message: message,
                          conversation: widget.conversation,
                          showAvatar: _showAvatarAt(originalIndex),
                          userAvatarUrl: _userAvatarSource,
                          aiAvatarUrl: employeeProfile?.avatarUrl,
                          aiContentDescription: _resolvedTitle,
                          hasEmployeeProfile: employeeProfile != null,
                          relayProgress:
                              isActiveRelay ? _activeRelayProgress : null,
                          cancellingRelay: _cancellingRelay,
                          onCancelRelay:
                              _cancellingRelay ? null : () => _stopChat(),
                          onReply: () => setState(() => _replyTo = message),
                          onDelete: () => _deleteMessageAt(originalIndex),
                          onResend: message.status == ChatDeliveryStatus.failed
                              ? _resendLastChat
                              : null,
                          toolCalls: toolCalls,
                          onShowTimeline: toolCalls.isEmpty
                              ? null
                              : () => _openTimelineForMessage(message),
                        );
                      },
                      itemCount: _messages.length,
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

part of 'chat_screen.dart';

// 消息气泡与内嵌 mini timeline 组件。
String _formatBubbleTimeText(String rawText) {
  final raw = rawText.trim();
  if (raw.isEmpty) return '';

  DateTime? parsed;
  final numeric = int.tryParse(raw);
  if (numeric != null && numeric > 0) {
    final millis = numeric <= 9999999999 ? numeric * 1000 : numeric;
    parsed = DateTime.fromMillisecondsSinceEpoch(millis);
  } else {
    parsed = DateTime.tryParse(raw)?.toLocal();
  }
  if (parsed == null) return raw;

  final now = DateTime.now();
  final sameDay = now.year == parsed.year &&
      now.month == parsed.month &&
      now.day == parsed.day;
  final hour = parsed.hour.toString().padLeft(2, '0');
  final minute = parsed.minute.toString().padLeft(2, '0');
  if (sameDay) return '$hour:$minute';
  return '${parsed.month}/${parsed.day} $hour:$minute';
}

// Long model answers use the existing native text widgets; only fenced code
// receives a scrollable monospace surface, never an HTML or WebView renderer.
class _ChatRichBody extends StatelessWidget {
  const _ChatRichBody({
    required this.text,
    required this.style,
    required this.codeBackground,
  });

  final String text;
  final TextStyle style;
  final Color codeBackground;

  static final RegExp _fencedCode = RegExp(r'```[^\r\n`]*\r?\n([\s\S]*?)```');

  @override
  Widget build(BuildContext context) {
    final matches = _fencedCode.allMatches(text).toList();
    if (matches.isEmpty) return Text(text, style: style);

    final blocks = <Widget>[];
    var cursor = 0;
    for (final match in matches) {
      if (match.start > cursor) {
        blocks.add(Text(text.substring(cursor, match.start), style: style));
      }
      final source = match.group(1) ?? '';
      blocks.add(
        Container(
          constraints: BoxConstraints(
            maxWidth: min(520.0, MediaQuery.sizeOf(context).width * 0.76),
          ),
          margin: const EdgeInsets.symmetric(vertical: 6),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: codeBackground,
            borderRadius: BorderRadius.circular(8),
          ),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: SelectableText(
              source,
              style: style.copyWith(
                fontFamily: 'monospace',
                fontSize: 13,
                height: 1.5,
              ),
            ),
          ),
        ),
      );
      cursor = match.end;
    }
    if (cursor < text.length) {
      blocks.add(Text(text.substring(cursor), style: style));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: blocks,
    );
  }
}

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    required this.conversation,
    required this.showAvatar,
    required this.userAvatarUrl,
    required this.aiAvatarUrl,
    required this.aiContentDescription,
    required this.hasEmployeeProfile,
    required this.onReply,
    required this.onDelete,
    this.onResend,
    this.relayProgress,
    this.cancellingRelay = false,
    this.onCancelRelay,
    this.toolCalls = const <Map<String, Object?>>[],
    this.onShowTimeline,
  });

  final ChatMessage message;
  final ConversationItem conversation;
  final bool showAvatar;
  final String userAvatarUrl;
  final String? aiAvatarUrl;
  final String aiContentDescription;
  final bool hasEmployeeProfile;
  final VoidCallback onReply;
  final VoidCallback onDelete;
  final VoidCallback? onResend;
  final RelayTaskProgress? relayProgress;
  final bool cancellingRelay;
  final VoidCallback? onCancelRelay;
  final List<Map<String, Object?>> toolCalls;
  final VoidCallback? onShowTimeline;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    if (message.role == ChatRole.system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Text(
            message.body,
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          ),
        ),
      );
    }

    final isUser = message.role == ChatRole.user;
    final fallback = isUser
        ? AppAvatarFallback.user
        : chatAvatarFallback(
            conversationId: conversation.id,
            hasEmployeeProfile: hasEmployeeProfile,
          );
    final fixedAssistantAvatar = conversation.type.usesPinnedAvatar;
    final avatar = AppAvatar(
      imageSource: isUser
          ? userAvatarUrl
          : fixedAssistantAvatar
              ? null
              : aiAvatarUrl,
      fallback: fallback,
      size: MessageAvatarLayout.bubbleAvatarSize,
      borderRadius: MessageAvatarLayout.bubbleAvatarRadius,
      contentDescription: isUser ? '我' : aiContentDescription,
    );
    final bubbleColor = isUser ? colors.chatUserBubble : colors.surface;
    final textColor = isUser ? colors.chatUserBubbleText : colors.textPrimary;
    final visibleBody = message.status == ChatDeliveryStatus.sending
        ? '${message.body}\u200B▌'
        : message.body;
    final quote = message.quote?.trim() ?? '';
    final timeText = _formatBubbleTimeText(message.timeText);
    final showTimestamp =
        message.status != ChatDeliveryStatus.sending && timeText.isNotEmpty;

    return Padding(
      padding: EdgeInsets.only(
        top: showAvatar
            ? MessageAvatarLayout.bubbleTopPaddingWithAvatar
            : MessageAvatarLayout.bubbleTopPaddingWithoutAvatar,
        bottom: MessageAvatarLayout.bubbleTopPaddingWithoutAvatar,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          if (!isUser) ...[
            if (showAvatar) ...[
              avatar,
              const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
            ] else
              const SizedBox(
                width: MessageAvatarLayout.bubbleAvatarReservedWidth,
              ),
          ],
          Flexible(
            child: Column(
              crossAxisAlignment:
                  isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                _MessageActionMenu(
                  text: message.body,
                  onReply: onReply,
                  onDelete: onDelete,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                      maxWidth: min(
                        isUser ? 420.0 : 620.0,
                        MediaQuery.sizeOf(context).width * (isUser ? 0.84 : 0.92),
                      ),
                    ),
                    child: Material(
                      key: ValueKey('chat_bubble_${message.id}'),
                      color: bubbleColor,
                      elevation: 0,
                      borderRadius: BorderRadius.only(
                        topLeft: Radius.circular(isUser ? 12 : 4),
                        topRight: Radius.circular(isUser ? 4 : 12),
                        bottomLeft: const Radius.circular(12),
                        bottomRight: const Radius.circular(12),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (quote.isNotEmpty) ...[
                              Container(
                                constraints: const BoxConstraints(
                                  maxWidth: 236,
                                ),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 6,
                                ),
                                decoration: BoxDecoration(
                                  color: (isUser
                                          ? Colors.white
                                          : colors.textPrimary)
                                      .withValues(alpha: 0.06),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Text(
                                  quote,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    color: isUser
                                        ? colors.chatUserBubbleText.withValues(
                                            alpha: 0.8,
                                          )
                                        : colors.textSecondary,
                                    fontSize: 12,
                                    height: 1.33,
                                    letterSpacing: 0,
                                  ),
                                ),
                              ),
                              const SizedBox(height: 6),
                            ],
                            if (relayProgress != null) ...[
                              _RelayProgressCard(
                                progress: relayProgress!,
                                cancelling: cancellingRelay,
                                onCancel: onCancelRelay,
                              ),
                              const SizedBox(height: 8),
                            ],
                            // Parsing fenced blocks on each new frame scales with
                            // the full reply length. Defer rich formatting for huge
                            // in-flight replies, then restore it on the final status.
                            if (message.status == ChatDeliveryStatus.sending &&
                                message.body.length > 16384)
                              Text(
                                visibleBody,
                                style: TextStyle(
                                  color: textColor,
                                  fontSize: 15,
                                  height: 1.4,
                                  letterSpacing: 0,
                                ),
                              )
                            else _ChatRichBody(
                              text: visibleBody,
                              codeBackground: colors.surfaceHigh,
                              style: TextStyle(
                                color: textColor,
                                fontSize: 15,
                                height: 1.4,
                                letterSpacing: 0,
                              ),
                            ),
                            if (toolCalls.isNotEmpty &&
                                onShowTimeline != null) ...[
                              const SizedBox(height: 10),
                              _MiniTimeline(
                                calls: toolCalls,
                                onTap: onShowTimeline!,
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                if ([ChatDeliveryStatus.failed, ChatDeliveryStatus.pending].contains(message.status) ||
                    showTimestamp)
                  Padding(
                    padding: const EdgeInsets.only(top: 3, left: 4, right: 4),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if ([ChatDeliveryStatus.failed, ChatDeliveryStatus.pending].contains(message.status)) ...[
                          Semantics(
                            liveRegion: true,
                            excludeSemantics: true,
                            label: '原任务回执未核实，请先核对真实状态，不要重复提交',
                            child: Text(
                              message.status == ChatDeliveryStatus.pending ? '结果待核对' : '结果未确认',
                              style: TextStyle(
                                color: colors.danger,
                                fontSize: 12,
                                height: 1.27,
                                fontWeight: FontWeight.w500,
                                letterSpacing: 0,
                              ),
                            ),
                          ),
                          if (onResend != null) ...[
                            const SizedBox(width: 8),
                            TextButton(
                              onPressed: onResend,
                              style: TextButton.styleFrom(
                                foregroundColor: colors.brand,
                                minimumSize: const Size(48, 44),
                                tapTargetSize: MaterialTapTargetSize.padded,
                                padding: const EdgeInsets.symmetric(horizontal: 6),
                              ),
                              child: const Text('核对结果'),
                            ),
                          ],
                        ] else
                          Text(
                            timeText,
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 11,
                              height: 1.27,
                              fontWeight: FontWeight.w500,
                              letterSpacing: 0,
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          if (isUser) ...[
            if (showAvatar) ...[
              const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
              avatar,
            ] else
              const SizedBox(
                width: MessageAvatarLayout.bubbleAvatarReservedWidth,
              ),
          ],
        ],
      ),
    );
  }
}

/// Assistant 气泡底部嵌入的 dev-loop mini timeline：4 图标水平排列 + 连接线，
/// 点击跳转 TimelineScreen 查看完整调用详情。
class _MiniTimeline extends StatelessWidget {
  const _MiniTimeline({required this.calls, required this.onTap});

  final List<Map<String, Object?>> calls;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: colors.surfaceHigh.withValues(alpha: 0.5),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: colors.divider.withValues(alpha: 0.6),
            width: 0.5,
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text(
              '闭环',
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 10,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(child: _buildNodes(colors)),
            const SizedBox(width: 6),
            Icon(Icons.chevron_right, size: 14, color: colors.textTertiary),
          ],
        ),
      ),
    );
  }

  Widget _buildNodes(XcagiThemeColors colors) {
    final children = <Widget>[];
    for (var i = 0; i < calls.length; i++) {
      final call = calls[i];
      children.add(_MiniTimelineNode(call: call, colors: colors));
      if (i < calls.length - 1) {
        children.add(
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(top: 10.5, left: 2, right: 2),
              child: _MiniTimelineConnector(
                colors: colors,
                success: _callSuccess(call),
              ),
            ),
          ),
        );
      }
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }

  /// 已完成的步骤（success 为 null）按成功处理；只有显式 success=false 才视为失败。
  bool _callSuccess(Map<String, Object?> call) {
    final v = call['success'];
    if (v is bool) return v;
    return true;
  }
}

class _MiniTimelineNode extends StatelessWidget {
  const _MiniTimelineNode({required this.call, required this.colors});

  final Map<String, Object?> call;
  final XcagiThemeColors colors;

  @override
  Widget build(BuildContext context) {
    final icon = _iconFor(call['icon'] ?? '');
    final success = call['success'] != false;
    final color = success ? colors.success : colors.danger;
    final label = _shortLabel(call['label'] as String? ?? '');
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 22,
          height: 22,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, size: 13, color: color),
        ),
        const SizedBox(height: 3),
        SizedBox(
          width: 22,
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 9,
              height: 1.0,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
        ),
      ],
    );
  }

  String _shortLabel(String raw) {
    if (raw.isEmpty) return raw;
    if (raw.startsWith('创建分支')) return '分支';
    if (raw.startsWith('验证')) return '验证';
    if (raw.startsWith('推送')) return '推送';
    if (raw.contains('CLI')) return 'CLI';
    if (raw.contains('执行')) return '执行';
    if (raw.length <= 2) return raw;
    return raw.substring(0, 2);
  }

  IconData _iconFor(Object? icon) {
    switch (icon) {
      case 'branch':
        return Icons.call_split;
      case 'check':
        return Icons.check_circle_outline;
      case 'upload':
        return Icons.cloud_upload_outlined;
      case 'terminal':
      default:
        return Icons.terminal;
    }
  }
}

class _MiniTimelineConnector extends StatelessWidget {
  const _MiniTimelineConnector({required this.colors, required this.success});

  final XcagiThemeColors colors;
  final bool success;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 1,
      color: success
          ? colors.success.withValues(alpha: 0.5)
          : colors.divider.withValues(alpha: 0.7),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../voice/voice_input_sheet.dart';

class CsChatScreen extends StatefulWidget {
  const CsChatScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<CsChatScreen> createState() => _CsChatScreenState();
}

class _CsChatScreenState extends State<CsChatScreen> {
  late final MobileRepository _repository;
  late Future<void> _future;
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  var _messages = <CsMessage>[];
  CsInfo? _info;
  var _streaming = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '专属客服',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              titleWidget: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '专属客服',
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 17,
                      height: 1.29,
                      fontWeight: FontWeight.w500,
                      letterSpacing: 0,
                    ),
                  ),
                  if (_info != null)
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: _info!.online
                                ? colors.weChatOnline
                                : colors.textTertiary,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          _info!.online
                              ? _info!.name.ifEmpty('客服在线')
                              : _info!.name.ifEmpty('客服离线'),
                          style: TextStyle(
                            color: _info!.online
                                ? colors.weChatOnline
                                : colors.textTertiary,
                            fontSize: 12,
                            height: 1.2,
                            letterSpacing: 0,
                          ),
                        ),
                      ],
                    ),
                ],
              ),
              actions: [
                AppAvatar(
                  imageSource: _info?.avatar,
                  fallback: AppAvatarFallback.customerService,
                  size: 34,
                  borderRadius: BorderRadius.circular(17),
                  contentDescription: '专属客服',
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<void>(
                future: _future,
                builder: (context, snapshot) {
                  final loading =
                      snapshot.connectionState == ConnectionState.waiting;
                  return Column(
                    children: [
                      Expanded(
                        child: loading
                            ? Center(
                                child: CircularProgressIndicator(
                                  color: colors.brand,
                                ),
                              )
                            : _messages.isEmpty
                                ? _CsEmptyState(error: _error)
                                : ListView.separated(
                                    controller: _scrollController,
                                    padding: const EdgeInsets.fromLTRB(
                                      14,
                                      12,
                                      14,
                                      16,
                                    ),
                                    itemCount: _messages.length,
                                    separatorBuilder: (_, __) =>
                                        const SizedBox(height: 7),
                                    itemBuilder: (context, index) => _CsBubble(
                                      message: _messages[index],
                                      streaming: _streaming &&
                                          index == _messages.length - 1,
                                      onDelete: () => setState(
                                        () => _messages = [..._messages]
                                          ..removeAt(index),
                                      ),
                                      onReply: () {
                                        final quote = _messages[index].body;
                                        _controller.text =
                                            '引用「${quote.take(60)}」\n${_controller.text}';
                                        _controller.selection =
                                            TextSelection.collapsed(
                                          offset: _controller.text.length,
                                        );
                                      },
                                    ),
                                  ),
                      ),
                      _CsInputBar(
                        controller: _controller,
                        streaming: _streaming,
                        onSend: _send,
                        onStop: () => setState(() => _streaming = false),
                        onVoice: _startVoiceInput,
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait<Object>([
        _repository.loadCsInfo().catchError((_) => const CsInfo(
              available: false,
              name: '专属客服',
              online: false,
            )),
        _repository.loadCsMessages(),
      ]);
      if (!mounted) return;
      setState(() {
        _info = results[0] as CsInfo;
        _messages = results[1] as List<CsMessage>;
        _error = null;
      });
      _scrollToBottom();
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _streaming) return;
    _controller.clear();
    final local = CsMessage(
      messageId: 'local_user_${DateTime.now().microsecondsSinceEpoch}',
      sender: 'user',
      body: text,
      timestamp: '刚刚',
    );
    setState(() {
      _messages = [..._messages, local];
      _streaming = true;
    });
    _scrollToBottom();

    try {
      final response = await _repository.sendCsMessage(text);
      if (!mounted) return;
      if (response.reply.trim().isNotEmpty) {
        setState(() {
          _messages = [
            ..._messages,
            CsMessage(
              messageId: '${response.messageId.ifEmpty('local')}_cs',
              sender: 'cs',
              body: response.reply,
              timestamp: response.timestamp.ifEmpty('刚刚'),
            ),
          ];
        });
      } else {
        final fresh = await _repository.loadCsMessages();
        if (!mounted) return;
        setState(() => _messages = fresh);
      }
    } catch (error) {
      if (mounted) _showSnack(error.toString());
    } finally {
      if (mounted) {
        setState(() => _streaming = false);
        _scrollToBottom();
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  void _showSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  void _insertVoiceText(String text) {
    final recognized = text.trim();
    if (recognized.isEmpty) return;
    final current = _controller.text.trim();
    _controller.text = current.isEmpty ? recognized : '$current $recognized';
    _controller.selection = TextSelection.collapsed(
      offset: _controller.text.length,
    );
  }

  void _startVoiceInput() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.colors(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(VoiceInputDesign.sheetTopCornerRadius),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      builder: (context) => VoiceInputSheet(onResult: _insertVoiceText),
    );
  }
}

class _CsEmptyState extends StatelessWidget {
  const _CsEmptyState({this.error});

  final String? error;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.support_agent,
              size: 48,
              color: colors.textTertiary,
            ),
            const SizedBox(height: 14),
            Text(
              error == null ? '向专属客服提问' : '客服消息暂时无法加载',
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 15,
                height: 1.4,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              error == null ? '客服上线后会尽快回复您' : error!,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textTertiary,
                fontSize: 13,
                height: 1.31,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CsBubble extends StatelessWidget {
  const _CsBubble({
    required this.message,
    required this.streaming,
    required this.onReply,
    required this.onDelete,
  });

  final CsMessage message;
  final bool streaming;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final isUser = message.isUser;
    final bubble = GestureDetector(
      onLongPressStart: (details) =>
          _showActions(context, details.globalPosition),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 260),
        child: Material(
          key: ValueKey('cs_bubble_${message.messageId}'),
          color: isUser ? colors.weChatGreen : colors.surface,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(8),
            topRight: const Radius.circular(8),
            bottomLeft: Radius.circular(isUser ? 8 : 2),
            bottomRight: Radius.circular(isUser ? 2 : 8),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: Text(
                    message.body,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 15,
                      height: 1.4,
                      letterSpacing: 0,
                    ),
                  ),
                ),
                if (streaming)
                  Padding(
                    padding: const EdgeInsets.only(left: 2),
                    child: Text(
                      '|',
                      style: TextStyle(
                        color: colors.brand,
                        fontSize: 15,
                        height: 1.4,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );

    return Row(
      mainAxisAlignment:
          isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!isUser) ...[
          AppAvatar(
            fallback: AppAvatarFallback.customerService,
            size: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            borderRadius: BorderRadius.circular(
              MessageAvatarLayout.customerServiceBubbleAvatarSize / 2,
            ),
            contentDescription: '客服',
          ),
          const SizedBox(
              width: MessageAvatarLayout.customerServiceBubbleAvatarGap),
        ],
        bubble,
        if (isUser) ...[
          const SizedBox(
              width: MessageAvatarLayout.customerServiceBubbleAvatarGap),
          Container(
            width: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            height: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: colors.divider,
              shape: BoxShape.circle,
            ),
            child: Text(
              '我',
              style: TextStyle(
                color: colors.surface,
                fontSize: 14,
                height: 1,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ],
    );
  }

  Future<void> _showActions(BuildContext context, Offset position) async {
    final selected = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        position.dx,
        position.dy,
      ),
      items: const [
        PopupMenuItem(value: 'copy', child: Text('复制')),
        PopupMenuItem(value: 'reply', child: Text('引用')),
        PopupMenuItem(value: 'delete', child: Text('删除')),
      ],
    );
    if (!context.mounted) return;
    switch (selected) {
      case 'copy':
        await Clipboard.setData(ClipboardData(text: message.body));
        if (!context.mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已复制')),
        );
        break;
      case 'reply':
        onReply();
        break;
      case 'delete':
        onDelete();
        break;
    }
  }
}

class _CsInputBar extends StatelessWidget {
  const _CsInputBar({
    required this.controller,
    required this.streaming,
    required this.onSend,
    required this.onStop,
    required this.onVoice,
  });

  final TextEditingController controller;
  final bool streaming;
  final VoidCallback onSend;
  final VoidCallback onStop;
  final VoidCallback onVoice;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('cs_input_bar_surface'),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colors.weChatDivider, width: 0.5),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _CsCircleIconButton(
              onPressed: onVoice,
              icon: Icons.mic,
              tooltip: '语音',
              foregroundColor: colors.textSecondary,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Container(
                constraints: const BoxConstraints(minHeight: 36),
                padding: const EdgeInsets.symmetric(horizontal: 10),
                decoration: BoxDecoration(
                  color: colors.weChatInputBg,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: colors.weChatDivider, width: 0.5),
                ),
                alignment: Alignment.center,
                child: TextField(
                  controller: controller,
                  maxLines: 1,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => onSend(),
                  decoration: InputDecoration(
                    isCollapsed: true,
                    border: InputBorder.none,
                    hintText: '输入消息...',
                    hintStyle: TextStyle(
                      color: colors.textTertiary,
                      fontSize: 15,
                      height: 1.4,
                      letterSpacing: 0,
                    ),
                  ),
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 15,
                    height: 1.4,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 6),
            _CsCircleIconButton(
              onPressed: streaming ? onStop : onSend,
              icon: streaming ? Icons.close : Icons.send,
              tooltip: streaming ? '停止' : '发送',
              backgroundColor: streaming ? colors.danger : colors.brand,
              foregroundColor: colors.surface,
            ),
          ],
        ),
      ),
    );
  }
}

class _CsCircleIconButton extends StatelessWidget {
  const _CsCircleIconButton({
    required this.onPressed,
    required this.icon,
    required this.tooltip,
    this.backgroundColor = Colors.transparent,
    required this.foregroundColor,
  });

  final VoidCallback onPressed;
  final IconData icon;
  final String tooltip;
  final Color backgroundColor;
  final Color foregroundColor;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: Material(
          color: backgroundColor,
          shape: const CircleBorder(),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onPressed,
            customBorder: const CircleBorder(),
            child: SizedBox.square(
              dimension: 36,
              child: Icon(icon, size: 22, color: foregroundColor),
            ),
          ),
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}

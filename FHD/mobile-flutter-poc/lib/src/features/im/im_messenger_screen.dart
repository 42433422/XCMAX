import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class ImMessengerScreen extends StatefulWidget {
  const ImMessengerScreen({
    super.key,
    this.repository,
    this.initialConversationId,
    this.initialMessages,
  });

  final MobileRepository? repository;
  final int? initialConversationId;
  final List<ImMessage>? initialMessages;

  @override
  State<ImMessengerScreen> createState() => _ImMessengerScreenState();
}

class _ImMessengerScreenState extends State<ImMessengerScreen> {
  late final MobileRepository _repository;
  final _peerController = TextEditingController();
  final _draftController = TextEditingController();
  var _conversationId = 0;
  var _messages = const <ImMessage>[];
  var _error = '';
  var _working = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _conversationId = widget.initialConversationId ?? 0;
    _messages = widget.initialMessages ?? const <ImMessage>[];
    if (_conversationId > 0 && widget.initialMessages == null) {
      _reloadMessages();
    }
  }

  @override
  void dispose() {
    _peerController.dispose();
    _draftController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: 'IM 消息',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: _conversationId <= 0
                  ? _buildNewConversation()
                  : _buildConversation(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNewConversation() {
    return ListView(
      padding: const EdgeInsets.only(bottom: 96),
      children: [
        const WeSectionCaption('新会话'),
        WeCellGroup(
          children: [
            const WeCell(
              title: '对方用户',
              subtitle: '输入企业用户 ID 后发起直聊',
              icon: Icons.person_search,
              showArrow: false,
              showDivider: false,
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: WeField(
                controller: _peerController,
                placeholder: '用户 ID',
                keyboardType: TextInputType.number,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(10),
                ],
                onChanged: (_) => setState(() {}),
              ),
            ),
            WeBlockButton(
              text: _working ? '打开中' : '打开会话',
              enabled: !_working && _peerController.text.trim().isNotEmpty,
              onPressed: _openDirect,
            ),
            const SizedBox(height: 16),
          ],
        ),
        if (_error.trim().isNotEmpty) _ErrorText(_error),
      ],
    );
  }

  Widget _buildConversation() {
    final colors = AppTheme.colors(context);
    return Column(
      children: [
        Container(
          color: colors.surface,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: colors.brandContainer,
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.chat_bubble_outline,
                  color: colors.brand,
                  size: 20,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '会话 #$_conversationId',
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 16,
                        height: 1.38,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0,
                      ),
                    ),
                    Text(
                      'WebSocket 已连接，消息实时同步',
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 12,
                        height: 1.33,
                        letterSpacing: 0,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            color: colors.brand,
            onRefresh: _reloadMessages,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              children: [
                if (_messages.isEmpty)
                  const _EmptyConversationHint()
                else
                  for (final message in _messages)
                    _MessageBubble(
                      message,
                      onReply: () {
                        final current = _draftController.text;
                        _draftController.text =
                            '引用「${message.body.take(60)}」\n$current';
                        _draftController.selection = TextSelection.collapsed(
                          offset: _draftController.text.length,
                        );
                      },
                      onDelete: () => setState(
                        () => _messages = _messages
                            .where((candidate) => candidate.id != message.id)
                            .toList(growable: false),
                      ),
                    ),
                if (_error.trim().isNotEmpty) _ErrorText(_error),
              ],
            ),
          ),
        ),
        Container(
          key: const ValueKey('im_input_bar_surface'),
          color: colors.surface,
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
          child: SafeArea(
            top: false,
            child: Row(
              children: [
                Expanded(
                  child: WeField(
                    controller: _draftController,
                    placeholder: '输入消息',
                    singleLine: false,
                    maxLength: 1000,
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _working ? null : _send,
                  icon: Icon(Icons.send, color: colors.brand),
                  tooltip: '发送',
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _openDirect() async {
    final peerId = int.tryParse(_peerController.text.trim()) ?? 0;
    setState(() {
      _working = true;
      _error = '';
    });
    try {
      final id = await _repository.openImDirect(peerId);
      if (!mounted) return;
      setState(() => _conversationId = id);
      await _reloadMessages();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _reloadMessages() async {
    if (_conversationId <= 0) return;
    try {
      final messages = await _repository.loadImMessages(_conversationId);
      if (mounted) {
        setState(() {
          _messages = messages;
          _error = '';
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _send() async {
    final body = _draftController.text.trim();
    if (body.isEmpty || _conversationId <= 0) return;
    setState(() {
      _working = true;
      _error = '';
    });
    try {
      final message = await _repository.sendImMessage(
        conversationId: _conversationId,
        body: body,
      );
      if (!mounted) return;
      setState(() {
        _messages = [..._messages, message];
        _draftController.clear();
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }
}

class _EmptyConversationHint extends StatelessWidget {
  const _EmptyConversationHint();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 64),
      child: Column(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: colors.surfaceHigh,
              borderRadius: BorderRadius.circular(16),
            ),
            alignment: Alignment.center,
            child: Icon(
              Icons.chat_bubble_outline,
              color: colors.textSecondary,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '暂无消息',
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 16,
              height: 1.38,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
          Text(
            '发出第一条消息后会显示在这里',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 13,
              height: 1.38,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble(
    this.message, {
    required this.onReply,
    required this.onDelete,
  });

  final ImMessage message;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final maxBubbleWidth = MediaQuery.sizeOf(context).width * 0.78;
    return Align(
      alignment: message.mine ? Alignment.centerRight : Alignment.centerLeft,
      child: GestureDetector(
        onLongPressStart: (details) => _showActions(
          context,
          details.globalPosition,
        ),
        child: Container(
          key: ValueKey('im_bubble_${message.id}'),
          constraints: BoxConstraints(maxWidth: maxBubbleWidth),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: message.mine ? colors.brand : colors.surfaceHigh,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: message.mine
                ? CrossAxisAlignment.end
                : CrossAxisAlignment.start,
            children: [
              Text(
                '用户 ${message.senderUserId}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: message.mine
                      ? Theme.of(context)
                          .colorScheme
                          .onPrimary
                          .withValues(alpha: 0.72)
                      : colors.textTertiary,
                  fontSize: 11,
                  height: 1.27,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
              Text(
                message.body,
                style: TextStyle(
                  color: message.mine
                      ? Theme.of(context).colorScheme.onPrimary
                      : colors.textPrimary,
                  fontSize: 15,
                  height: 1.4,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
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

class _ErrorText extends StatelessWidget {
  const _ErrorText(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text(
        text,
        style: TextStyle(
          color: colors.danger,
          fontSize: 13,
          height: 1.38,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension on String {
  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}

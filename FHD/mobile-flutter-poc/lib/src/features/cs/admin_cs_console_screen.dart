import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';

class AdminCsConsoleScreen extends StatefulWidget {
  const AdminCsConsoleScreen({
    super.key,
    this.repository,
    this.initialInbox,
  });

  final MobileRepository? repository;
  final List<AdminCsInboxItem>? initialInbox;

  @override
  State<AdminCsConsoleScreen> createState() => _AdminCsConsoleScreenState();
}

class _AdminCsConsoleScreenState extends State<AdminCsConsoleScreen> {
  late final MobileRepository _repository;
  late Future<List<AdminCsInboxItem>> _inboxFuture;
  AdminCsInboxItem? _selected;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _inboxFuture = _loadInbox();
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    if (selected != null) {
      return _AdminCsConversationScreen(
        repository: _repository,
        conversation: selected,
        onBack: () => setState(() => _selected = null),
      );
    }

    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '客户客服',
              showBack: Navigator.of(context).canPop(),
              onBack: Navigator.of(context).canPop()
                  ? () => Navigator.of(context).maybePop()
                  : null,
              actions: [
                IconButton(
                  onPressed: _refreshInbox,
                  icon: const Icon(Icons.refresh),
                  color: colors.textPrimary,
                  tooltip: '刷新',
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<List<AdminCsInboxItem>>(
                future: _inboxFuture,
                builder: (context, snapshot) {
                  final loading =
                      snapshot.connectionState == ConnectionState.waiting;
                  final items =
                      snapshot.data ?? widget.initialInbox ?? const [];
                  if (loading && items.isEmpty) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refreshInbox,
                    child: items.isEmpty
                        ? _AdminCsEmptyInbox()
                        : ListView.separated(
                            physics: const AlwaysScrollableScrollPhysics(),
                            itemCount: items.length,
                            separatorBuilder: (_, __) => Divider(
                              height: 0.5,
                              thickness: 0.5,
                              indent:
                                  MessageAvatarLayout.conversationDividerStart,
                              color:
                                  Theme.of(context).colorScheme.outlineVariant,
                            ),
                            itemBuilder: (context, index) {
                              final item = items[index];
                              return _AdminCsInboxRow(
                                item: item,
                                onTap: () => setState(() => _selected = item),
                              );
                            },
                          ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<List<AdminCsInboxItem>> _loadInbox() async {
    return widget.initialInbox ?? _repository.loadAdminCsInbox();
  }

  Future<void> _refreshInbox() async {
    final future = _repository.loadAdminCsInbox();
    setState(() => _inboxFuture = future);
    await future;
  }
}

class _AdminCsInboxRow extends StatelessWidget {
  const _AdminCsInboxRow({
    required this.item,
    required this.onTap,
  });

  final AdminCsInboxItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final name = item.customerName.ifEmpty('客户');
    final time = item.lastMessageAt.replaceAll('T', ' ').take(19);
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            _CustomerAvatar(name: name),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 16,
                      height: 1.3,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                  if (time.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      time,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textTertiary,
                        fontSize: 13,
                        height: 1.31,
                        letterSpacing: 0,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (item.unreadCount > 0)
              Container(
                constraints: const BoxConstraints(minWidth: 22, minHeight: 22),
                padding: const EdgeInsets.symmetric(horizontal: 6),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: colors.danger,
                  borderRadius: BorderRadius.circular(11),
                ),
                child: Text(
                  '${item.unreadCount}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    height: 1,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _AdminCsEmptyInbox extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        SizedBox(height: MediaQuery.sizeOf(context).height * 0.24),
        Icon(Icons.support_agent, size: 48, color: colors.textTertiary),
        const SizedBox(height: 14),
        Text(
          '暂无客户咨询',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: colors.textSecondary,
            fontSize: 15,
            height: 1.4,
            letterSpacing: 0,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          '客户在「专属客服」发起咨询后会出现在这里',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: colors.textTertiary,
            fontSize: 13,
            height: 1.31,
            letterSpacing: 0,
          ),
        ),
      ],
    );
  }
}

class _AdminCsConversationScreen extends StatefulWidget {
  const _AdminCsConversationScreen({
    required this.repository,
    required this.conversation,
    required this.onBack,
  });

  final MobileRepository repository;
  final AdminCsInboxItem conversation;
  final VoidCallback onBack;

  @override
  State<_AdminCsConversationScreen> createState() =>
      _AdminCsConversationScreenState();
}

class _AdminCsConversationScreenState
    extends State<_AdminCsConversationScreen> {
  late Future<List<AdminCsMessage>> _messagesFuture;
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  var _messages = <AdminCsMessage>[];
  var _sending = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _messagesFuture = _loadMessages();
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
    final customerName = widget.conversation.customerName.ifEmpty('客户');
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: customerName,
              showBack: true,
              onBack: widget.onBack,
              actions: [
                IconButton(
                  onPressed: _refreshMessages,
                  icon: const Icon(Icons.refresh),
                  color: colors.textPrimary,
                  tooltip: '刷新',
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<List<AdminCsMessage>>(
                future: _messagesFuture,
                builder: (context, snapshot) {
                  final loading =
                      snapshot.connectionState == ConnectionState.waiting &&
                          _messages.isEmpty;
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
                                ? _AdminCsEmptyMessages(error: _error)
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
                                    itemBuilder: (context, index) =>
                                        _AdminCsBubble(
                                      message: _messages[index],
                                    ),
                                  ),
                      ),
                      _AdminCsInputBar(
                        controller: _controller,
                        sending: _sending,
                        onSend: _send,
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

  Future<List<AdminCsMessage>> _loadMessages() async {
    try {
      final messages = await widget.repository.loadAdminCsMessages(
        widget.conversation.conversationId,
      );
      if (mounted) {
        setState(() {
          _messages = messages;
          _error = null;
        });
        _scrollToBottom();
      }
      return messages;
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
      return const [];
    }
  }

  Future<void> _refreshMessages() async {
    final future = _loadMessages();
    setState(() => _messagesFuture = future);
    await future;
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;
    _controller.clear();
    final local = AdminCsMessage(
      messageId: 'local_admin_${DateTime.now().microsecondsSinceEpoch}',
      fromCustomer: false,
      senderName: '客服',
      body: text,
      timestamp: '刚刚',
    );
    setState(() {
      _sending = true;
      _messages = [..._messages, local];
    });
    _scrollToBottom();

    try {
      await widget.repository.replyAdminCs(
        conversationId: widget.conversation.conversationId,
        body: text,
      );
      await _refreshMessages();
    } catch (error) {
      if (mounted) _showSnack(error.toString());
    } finally {
      if (mounted) setState(() => _sending = false);
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
}

class _AdminCsEmptyMessages extends StatelessWidget {
  const _AdminCsEmptyMessages({this.error});

  final String? error;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          error == null ? '暂无消息' : error!,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: colors.textTertiary,
            fontSize: 14,
            height: 1.36,
            letterSpacing: 0,
          ),
        ),
      ),
    );
  }
}

class _AdminCsBubble extends StatelessWidget {
  const _AdminCsBubble({required this.message});

  final AdminCsMessage message;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final mine = !message.fromCustomer;
    final bubble = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 260),
      child: Material(
        color: mine ? colors.weChatGreen : colors.surface,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(8),
          topRight: const Radius.circular(8),
          bottomLeft: Radius.circular(mine ? 8 : 2),
          bottomRight: Radius.circular(mine ? 2 : 8),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
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
      ),
    );

    return Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!mine) ...[
          _CustomerAvatar(name: message.senderName.ifEmpty('客户'), size: 36),
          const SizedBox(
            width: MessageAvatarLayout.customerServiceBubbleAvatarGap,
          ),
        ],
        bubble,
        if (mine) ...[
          const SizedBox(
            width: MessageAvatarLayout.customerServiceBubbleAvatarGap,
          ),
          AppAvatar(
            fallback: AppAvatarFallback.customerService,
            size: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            borderRadius: BorderRadius.circular(
              MessageAvatarLayout.customerServiceBubbleAvatarSize / 2,
            ),
            contentDescription: '客服',
          ),
        ],
      ],
    );
  }
}

class _AdminCsInputBar extends StatelessWidget {
  const _AdminCsInputBar({
    required this.controller,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colors.weChatDivider, width: 0.5),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                onChanged: (_) {},
                decoration: InputDecoration(
                  hintText: '以企业专属客服身份回复...',
                  isDense: true,
                  filled: true,
                  fillColor: colors.weChatInputBg,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide(color: colors.weChatDivider),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide(color: colors.weChatDivider),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: sending ? null : onSend,
              icon: const Icon(Icons.send),
              tooltip: '发送',
              style: IconButton.styleFrom(
                backgroundColor: colors.brand,
                foregroundColor: Colors.white,
                disabledBackgroundColor: colors.divider,
                disabledForegroundColor: colors.textTertiary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CustomerAvatar extends StatelessWidget {
  const _CustomerAvatar({
    required this.name,
    this.size = 44,
  });

  final String name;
  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final clean = name.trim();
    final letter = clean.isEmpty ? '客' : clean.substring(0, 1);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.brand,
        borderRadius: BorderRadius.circular(size >= 40 ? 8 : size / 2),
      ),
      child: Text(
        letter,
        style: TextStyle(
          color: Colors.white,
          fontSize: size >= 40 ? 18 : 14,
          height: 1,
          fontWeight: FontWeight.w700,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension _AdminCsStringExt on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int count) {
    if (length <= count) return this;
    return substring(0, count);
  }
}

// part 文件：客服会话详情屏、消息气泡与空态。

part of 'admin_cs_console_screen.dart';

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
                                            message: _messages[index]),
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

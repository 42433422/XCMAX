import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../im/im_websocket_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
part 'im_messenger_widgets.part.dart';

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
  var _wsConnected = false;
  StreamSubscription<Map<String, Object?>>? _wsSubscription;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _conversationId = widget.initialConversationId ?? 0;
    _messages = widget.initialMessages ?? const <ImMessage>[];
    if (_conversationId > 0) {
      if (widget.initialMessages == null) {
        _reloadMessages();
      }
      _attachWebSocket();
    }
  }

  @override
  void dispose() {
    _wsSubscription?.cancel();
    _repository.disconnectImWebSocket();
    _peerController.dispose();
    _draftController.dispose();
    super.dispose();
  }

  Future<void> _attachWebSocket() async {
    _wsSubscription?.cancel();
    _wsSubscription = _repository.imWebSocketEvents.listen(_onWebSocketEvent);
    await _repository.connectImWebSocket();
    if (!mounted) return;
    setState(() => _wsConnected = _repository.imWebSocketConnected);
    Future<void>.delayed(const Duration(milliseconds: 400), () {
      if (!mounted) return;
      setState(() => _wsConnected = _repository.imWebSocketConnected);
    });
  }

  void _onWebSocketEvent(Map<String, Object?> event) {
    final parsed = ImWebSocketClient.parseMessageEvent(event);
    if (parsed == null || parsed.conversationId != _conversationId) return;
    if (_messages.any((message) => message.id == parsed.messageId)) return;
    if (!mounted) return;
    setState(() {
      _messages = [
        ..._messages,
        ImMessage(
          id: parsed.messageId,
          senderUserId: parsed.senderUserId,
          body: parsed.body,
          createdAt: '刚刚',
        ),
      ];
      _wsConnected = _repository.imWebSocketConnected;
    });
  }

  String get _wsStatusText {
    if (_wsConnected) return 'WebSocket 已连接，消息实时同步';
    if (_conversationId > 0) return '正在连接 WebSocket…';
    return 'WebSocket 未连接';
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
              subtitle: '输入用户 ID 后发起直聊',
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
                      _wsStatusText,
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
      await _attachWebSocket();
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

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_api.dart' show MobileApiException;
import '../../api/mobile_session_store.dart' show MobileSessionData;
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../im/im_websocket_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../../policy/mobile_error_policy.dart';
part 'im_messenger_widgets.part.dart';

/// IM 实时通道状态文案：只在握手真正成功后才显示“已连接”。
String imWsStatusText(
  ImWsConnectionState state, {
  required bool conversationOpen,
  bool attached = true,
}) {
  switch (state) {
    case ImWsConnectionState.connected:
      return 'WebSocket 已连接，消息实时同步';
    case ImWsConnectionState.connecting:
      return '正在连接 WebSocket…';
    case ImWsConnectionState.reconnecting:
      return 'WebSocket 已断开，正在重连…（新消息需下拉刷新）';
    case ImWsConnectionState.disconnected:
      if (conversationOpen && !attached) return '正在连接 WebSocket…';
      return conversationOpen ? 'WebSocket 未连接，新消息需下拉刷新' : 'WebSocket 未连接';
  }
}

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

class _ImMessengerScreenState extends State<ImMessengerScreen>
    with WidgetsBindingObserver {
  late final MobileRepository _repository;
  final _peerController = TextEditingController();
  final _draftController = TextEditingController();
  var _conversationId = 0;
  var _messages = const <ImMessage>[];
  var _error = '';
  var _working = false;
  var _wsState = ImWsConnectionState.disconnected;
  var _wsAttached = false;
  StreamSubscription<Map<String, Object?>>? _wsSubscription;
  StreamSubscription<ImWsConnectionState>? _wsStateSubscription;
  StreamSubscription<MobileSessionData>? _sessionSubscription;
  int _authGeneration = 0;
  int _requestEpoch = 0;
  bool _foreground = true;
  bool _invalidated = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    WidgetsBinding.instance.addObserver(this);
    _authGeneration = _repository.client.authGeneration;
    _sessionSubscription = _repository.client.sessionChanges.listen((_) {
      if (_authGeneration != _repository.client.authGeneration) _invalidateSession();
    });
    _conversationId = widget.initialConversationId ?? 0;
    _messages = widget.initialMessages ?? const <ImMessage>[];
    if (_conversationId > 0) {
      if (widget.initialMessages == null) {
        _reloadMessages();
      }
      _attachWebSocket();
    }
  }

  void _invalidateSession() {
    if (_invalidated) return;
    _invalidated = true;
    _requestEpoch++;
    _repository.disconnectImWebSocket();
    if (mounted) {
      setState(() {
        _messages = const <ImMessage>[];
        _conversationId = 0;
        _wsState = ImWsConnectionState.disconnected;
        _error = '账号已切换，请重新打开会话';
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final foreground = state == AppLifecycleState.resumed;
    if (foreground == _foreground) return;
    _foreground = foreground;
    _requestEpoch++;
    if (!_foreground) {
      _repository.disconnectImWebSocket();
      if (mounted) setState(() => _wsState = ImWsConnectionState.disconnected);
    } else if (!_invalidated && _conversationId > 0) {
      unawaited(_attachWebSocket());
      unawaited(_reloadMessages());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _requestEpoch++;
    _sessionSubscription?.cancel();
    _wsSubscription?.cancel();
    _wsStateSubscription?.cancel();
    _repository.disconnectImWebSocket();
    _peerController.dispose();
    _draftController.dispose();
    super.dispose();
  }

  Future<void> _attachWebSocket() async {
    if (_invalidated || !_foreground || _conversationId <= 0 ||
        _authGeneration != _repository.client.authGeneration) {
      return;
    }
    final epoch = _requestEpoch;
    _wsSubscription?.cancel();
    _wsSubscription = _repository.imWebSocketEvents.listen(_onWebSocketEvent);
    _wsStateSubscription?.cancel();
    _wsStateSubscription = _repository.imWebSocketStates.listen((state) {
      if (!mounted || _invalidated || !_foreground ||
          _authGeneration != _repository.client.authGeneration) {
        return;
      }
      setState(() => _wsState = state);
      // Missed frames and acknowledgements are resolved from server truth.
      // Never recover by re-sending the last outbound message.
      if (state == ImWsConnectionState.connected && _conversationId > 0) {
        unawaited(_reloadMessages());
      }
    });
    await _repository.connectImWebSocket();
    if (!mounted || _invalidated || !_foreground ||
        epoch != _requestEpoch ||
        _authGeneration != _repository.client.authGeneration) {
      return;
    }
    setState(() {
      _wsAttached = true;
      _wsState = _repository.imWebSocketState;
    });
  }

  void _onWebSocketEvent(Map<String, Object?> event) {
    final parsed = ImWebSocketClient.parseMessageEvent(event);
    if (parsed == null || parsed.conversationId != _conversationId ||
        _invalidated || !_foreground ||
        _authGeneration != _repository.client.authGeneration) {
      return;
    }
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
      _wsState = _repository.imWebSocketState;
    });
  }

  String get _wsStatusText => imWsStatusText(
        _wsState,
        conversationOpen: _conversationId > 0,
        attached: _wsAttached,
      );

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
      if (mounted) setState(() => _error = mobileErrorText(error));
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _reloadMessages() async {
    if (_conversationId <= 0 || _invalidated || !_foreground) return;
    final conversationId = _conversationId;
    final epoch = _requestEpoch;
    final idsBeforeRead = _messages.map((message) => message.id).toSet();
    try {
      final messages = await _repository.loadImMessages(conversationId);
      if (!mounted || _invalidated || !_foreground ||
          conversationId != _conversationId || epoch != _requestEpoch ||
          _authGeneration != _repository.client.authGeneration) {
        return;
      }
      setState(() {
        // Server snapshot wins. Only preserve new live frames that arrived
        // after the GET began; stale/deleted cached messages must not survive.
        final merged = <int, ImMessage>{
          for (final message in messages) message.id: message,
          for (final message in _messages)
            if (!idsBeforeRead.contains(message.id)) message.id: message,
        };
        _messages = merged.values.toList()..sort((a, b) => a.id.compareTo(b.id));
        _error = '';
      });
    } catch (error) {
      if (!mounted || _invalidated || epoch != _requestEpoch) return;
      if (error is MobileApiException &&
          (error.statusCode == 401 || error.statusCode == 403)) {
        _invalidateSession();
      } else {
        setState(() => _error = mobileErrorText(error));
      }
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
      if (mounted) setState(() => _error = mobileErrorText(error));
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }
}

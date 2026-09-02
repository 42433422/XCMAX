import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../voice/voice_input_sheet.dart';

part 'cs_chat_screen_widgets.part.dart';
part 'cs_chat_screen_input.part.dart';

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
        _repository.loadCsInfo().catchError(
              (_) =>
                  const CsInfo(available: false, name: '专属客服', online: false),
            ),
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

  Future<void> _startVoiceInput() async {
    final granted = await const AndroidRecordAudioPermission().ensureGranted();
    if (!mounted) return;
    if (!granted) {
      _showSnack('需要麦克风权限才能使用语音输入');
      return;
    }
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

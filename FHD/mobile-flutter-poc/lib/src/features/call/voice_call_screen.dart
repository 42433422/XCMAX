import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';

/// 通话方式选择：语音可用，视频暂未解锁。
Future<void> showCallOptionsSheet(
  BuildContext context, {
  required VoidCallback onVoice,
}) {
  final colors = AppTheme.colors(context);
  final textTheme = Theme.of(context).textTheme;
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: colors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (sheetContext) => SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(height: 8),
          Container(
            width: 38,
            height: 4,
            decoration: BoxDecoration(
              color: colors.divider,
              borderRadius: BorderRadius.circular(999),
            ),
          ),
          const SizedBox(height: 8),
          ListTile(
            key: const ValueKey('call_option_voice'),
            leading: Icon(Icons.call, color: colors.brand),
            title: Text(
              '语音通话',
              style: textTheme.bodyLarge?.copyWith(color: colors.textPrimary),
            ),
            onTap: () {
              Navigator.of(sheetContext).pop();
              onVoice();
            },
          ),
          ListTile(
            key: const ValueKey('call_option_video'),
            enabled: false,
            leading: Icon(
              Icons.videocam_off_outlined,
              color: colors.textTertiary.withValues(alpha: 0.6),
            ),
            title: Row(
              children: [
                Text(
                  '视频通话',
                  style: textTheme.bodyLarge?.copyWith(
                    color: colors.textTertiary.withValues(alpha: 0.7),
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
                  decoration: BoxDecoration(
                    color: colors.divider,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '未解锁',
                    style: textTheme.labelSmall?.copyWith(
                      color: colors.textTertiary,
                      fontSize: 10,
                    ),
                  ),
                ),
              ],
            ),
            onTap: null,
          ),
          const SizedBox(height: 8),
        ],
      ),
    ),
  );
}

enum _CallStage { connecting, listening, thinking, speaking, muted, ended }

/// AI 语音通话：说话 → 识别 → 对话回复 → 朗读，循环往复。
///
/// 交互取自成熟语音代理的「半双工轮次」做法（Pipecat 的
/// transport → VAD → STT → LLM → TTS 管线），在本机简化实现：
/// 系统语音识别出完整一句话后提交现有对话接口，再把回复交给系统 TTS 朗读。
class VoiceCallScreen extends StatefulWidget {
  const VoiceCallScreen({
    super.key,
    required this.conversation,
    required this.repository,
    required this.title,
    this.avatarUrl,
  });

  final ConversationItem conversation;
  final MobileRepository repository;
  final String title;
  final String? avatarUrl;

  @override
  State<VoiceCallScreen> createState() => _VoiceCallScreenState();
}

class _VoiceCallScreenState extends State<VoiceCallScreen> {
  final SpeechToText _speech = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  Timer? _ticker;

  _CallStage _stage = _CallStage.connecting;
  bool _speechReady = false;
  bool _muted = false;
  bool _speakerOn = true;
  bool _handlingTurn = false;
  int _seconds = 0;
  String _heardText = '';
  String _replyText = '';
  String _errorText = '';

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || _stage == _CallStage.ended) return;
      setState(() => _seconds += 1);
    });
    _prepare();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _speech.cancel();
    _tts.stop();
    super.dispose();
  }

  Future<void> _prepare() async {
    try {
      await _tts.setLanguage('zh-CN');
      await _tts.setSpeechRate(0.95);
      await _tts.setVolume(1.0);
      await _tts.awaitSpeakCompletion(true);
    } catch (_) {
      // 系统缺少中文语音时仍保留文字字幕与对话能力。
    }
    final ready = await _speech.initialize(
      onError: _onSpeechError,
      onStatus: _onSpeechStatus,
    );
    if (!mounted) return;
    setState(() {
      _speechReady = ready;
      if (!ready) {
        _errorText = '语音识别不可用，请允许麦克风与语音识别权限后重试';
        _stage = _CallStage.ended;
      }
    });
    if (ready) await _startListening();
  }

  Future<void> _startListening() async {
    if (!_speechReady || _handlingTurn || _muted) return;
    setState(() {
      _stage = _CallStage.listening;
      _errorText = '';
    });
    await _speech.listen(
      onResult: _onSpeechResult,
      listenFor: const Duration(seconds: 30),
      pauseFor: const Duration(seconds: 3),
      localeId: 'zh_CN',
      partialResults: true,
      cancelOnError: true,
    );
  }

  void _onSpeechResult(SpeechRecognitionResult result) {
    final text = result.recognizedWords.trim();
    if (text.isEmpty) return;
    setState(() => _heardText = text);
    if (result.finalResult && !_handlingTurn) {
      unawaited(_handleUtterance(text));
    }
  }

  void _onSpeechError(SpeechRecognitionError error) {
    if (!mounted || _stage == _CallStage.ended) return;
    // no-speech 属正常停顿，继续听即可。
    if (error.errorMsg == 'error_no_speech' || error.errorMsg == 'error_speech_timeout') {
      if (!_muted) unawaited(_startListening());
      return;
    }
    setState(() => _errorText = '没有听清，请再说一遍');
    if (!_muted) unawaited(_startListening());
  }

  void _onSpeechStatus(String status) {
    if (!mounted) return;
    if (status == 'done' && _stage == _CallStage.listening && !_muted) {
      unawaited(_startListening());
    }
  }

  Future<void> _handleUtterance(String text) async {
    _handlingTurn = true;
    await _speech.stop();
    if (!mounted) return;
    setState(() => _stage = _CallStage.thinking);
    try {
      final message = await widget.repository.sendMessage(
        conversation: widget.conversation,
        body: text,
      );
      final reply = message.body.trim();
      _replyText = reply.isEmpty ? '我在。' : reply;
      if (!mounted) return;
      setState(() {
        _stage = _CallStage.speaking;
        _errorText = '';
      });
      await _speak(_replyText);
    } catch (error) {
      if (!mounted) return;
      setState(() => _errorText = mobileErrorText(error, fallback: '通话暂时不可用'));
    } finally {
      _handlingTurn = false;
      if (mounted && _stage != _CallStage.ended && !_muted) {
        await _startListening();
      }
    }
  }

  Future<void> _speak(String text) async {
    if (text.isEmpty) return;
    try {
      await _tts.setVolume(_speakerOn ? 1.0 : 0.4);
      await _tts.speak(text);
    } catch (_) {
      // 朗读失败不影响字幕与下一轮对话。
    }
  }

  Future<void> _toggleMute() async {
    if (_muted) {
      setState(() => _muted = false);
      await _startListening();
      return;
    }
    await _speech.cancel();
    await _tts.stop();
    setState(() {
      _muted = true;
      _stage = _CallStage.muted;
    });
  }

  Future<void> _toggleSpeaker() async {
    setState(() => _speakerOn = !_speakerOn);
    await _tts.setVolume(_speakerOn ? 1.0 : 0.4).catchError((_) {});
  }

  Future<void> _hangUp() async {
    _ticker?.cancel();
    await _speech.cancel();
    await _tts.stop();
    if (!mounted) return;
    setState(() => _stage = _CallStage.ended);
    Navigator.of(context).maybePop();
  }

  String get _statusText {
    switch (_stage) {
      case _CallStage.connecting:
        return '正在接通…';
      case _CallStage.listening:
        return '正在聆听…';
      case _CallStage.thinking:
        return '正在思考…';
      case _CallStage.speaking:
        return '正在说话…';
      case _CallStage.muted:
        return '已静音';
      case _CallStage.ended:
        return _errorText.isEmpty ? '通话已结束' : _errorText;
    }
  }

  String get _durationText {
    final minutes = (_seconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (_seconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Scaffold(
      backgroundColor: const Color(0xFF121317),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
              child: Row(
                children: [
                  IconButton(
                    onPressed: _hangUp,
                    icon: const Icon(Icons.keyboard_arrow_down, size: 28),
                    color: Colors.white70,
                    tooltip: '收起',
                  ),
                  const Spacer(),
                  Text(
                    '语音通话',
                    style: textTheme.titleSmall?.copyWith(color: Colors.white70),
                  ),
                  const Spacer(),
                  const SizedBox(width: 48),
                ],
              ),
            ),
            const Spacer(),
            Semantics(
              label: '${widget.title} 头像',
              child: AppAvatar(
                imageSource: widget.avatarUrl,
                fallback: AppAvatarFallback.aiEmployee,
                size: 108,
                borderRadius: BorderRadius.circular(54),
                contentDescription: widget.title,
              ),
            ),
            const SizedBox(height: 18),
            Text(
              widget.title,
              style: textTheme.headlineSmall?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              _durationText,
              style: textTheme.bodySmall?.copyWith(color: Colors.white54),
            ),
            const SizedBox(height: 14),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (_stage == _CallStage.thinking ||
                    _stage == _CallStage.speaking ||
                    _stage == _CallStage.listening)
                  SizedBox.square(
                    dimension: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: colors.brand,
                    ),
                  ),
                if (_stage == _CallStage.thinking ||
                    _stage == _CallStage.speaking ||
                    _stage == _CallStage.listening)
                  const SizedBox(width: 8),
                Text(
                  _statusText,
                  style: textTheme.bodyMedium?.copyWith(color: Colors.white70),
                ),
              ],
            ),
            const SizedBox(height: 22),
            Expanded(
              flex: 2,
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 28),
                child: Column(
                  children: [
                    if (_heardText.isNotEmpty)
                      _CaptionRow(
                        label: '你',
                        text: _heardText,
                        color: Colors.white60,
                      ),
                    if (_replyText.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      _CaptionRow(
                        label: widget.title,
                        text: _replyText,
                        color: Colors.white,
                      ),
                    ],
                    if (_errorText.isNotEmpty && _stage != _CallStage.ended)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(
                          _errorText,
                          textAlign: TextAlign.center,
                          style: textTheme.bodySmall?.copyWith(
                            color: colors.warning,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(32, 8, 32, 28),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _CallControl(
                    key: const ValueKey('call_mute_button'),
                    icon: _muted ? Icons.mic_off : Icons.mic,
                    label: _muted ? '取消静音' : '静音',
                    active: _muted,
                    onTap: _toggleMute,
                  ),
                  _CallControl(
                    key: const ValueKey('call_hangup_button'),
                    icon: Icons.call_end,
                    label: '挂断',
                    danger: true,
                    onTap: _hangUp,
                  ),
                  _CallControl(
                    key: const ValueKey('call_speaker_button'),
                    icon: _speakerOn ? Icons.volume_up : Icons.volume_down,
                    label: '免提',
                    active: _speakerOn,
                    onTap: _toggleSpeaker,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CaptionRow extends StatelessWidget {
  const _CaptionRow({
    required this.label,
    required this.text,
    required this.color,
  });

  final String label;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: textTheme.labelSmall?.copyWith(color: Colors.white38),
        ),
        const SizedBox(height: 4),
        Text(
          text,
          style: textTheme.bodyMedium?.copyWith(
            color: color,
            height: 1.45,
          ),
        ),
      ],
    );
  }
}

class _CallControl extends StatelessWidget {
  const _CallControl({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.danger = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final background = danger
        ? colors.danger
        : active
            ? Colors.white.withValues(alpha: 0.22)
            : Colors.white.withValues(alpha: 0.10);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: background,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: SizedBox.square(
              dimension: 62,
              child: Icon(icon, color: Colors.white, size: 26),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          label,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: Colors.white60),
        ),
      ],
    );
  }
}

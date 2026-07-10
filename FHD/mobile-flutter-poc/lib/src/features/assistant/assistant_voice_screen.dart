import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../data/mobile_repository.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../platform/assistant_native_bridge.dart';
import '../../theme/app_theme.dart';
import 'assistant_visuals.dart';

enum _VoiceConversationState { idle, listening, thinking, speaking, error }

class AssistantVoiceScreen extends StatefulWidget {
  const AssistantVoiceScreen({
    super.key,
    required this.repository,
    this.nativeBridge = const AssistantNativeBridge(),
  });

  final MobileRepository repository;
  final AssistantNativeBridge nativeBridge;

  @override
  State<AssistantVoiceScreen> createState() => _AssistantVoiceScreenState();
}

class _AssistantVoiceScreenState extends State<AssistantVoiceScreen>
    with SingleTickerProviderStateMixin {
  final _speech = SpeechToText();
  late final AnimationController _pulse;
  var _state = _VoiceConversationState.idle;
  String _heard = '';
  String _answer = '点一下开始说话';
  String _error = '';
  double _level = 0.15;
  bool _nativeRecognitionActive = false;

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _speech.cancel();
    widget.nativeBridge.stopSpeech();
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final listening = _state == _VoiceConversationState.listening;
    final busy = _state == _VoiceConversationState.thinking;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: AssistantBackdrop(
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              AssistantTopBar(
                title: '和小C说话',
                onBack: () => Navigator.of(context).maybePop(),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(22, 10, 22, 28),
                  child: Column(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 7,
                        ),
                        decoration: BoxDecoration(
                          color: (_state == _VoiceConversationState.error
                                  ? assistantRose
                                  : assistantIndigo)
                              .withValues(alpha: 0.09),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 7,
                              height: 7,
                              decoration: BoxDecoration(
                                color: _state == _VoiceConversationState.error
                                    ? assistantRose
                                    : listening
                                        ? assistantMint
                                        : assistantIndigo,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 7),
                            Text(
                              _stateLabel,
                              style: TextStyle(
                                color: colors.textSecondary,
                                fontSize: 11.5,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const Spacer(),
                      AnimatedBuilder(
                        animation: _pulse,
                        builder: (context, child) => Container(
                          width: 216 + (listening ? _pulse.value * 14 : 0),
                          height: 216 + (listening ? _pulse.value * 14 : 0),
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: RadialGradient(
                              colors: [
                                assistantIndigo.withValues(
                                  alpha:
                                      listening ? 0.18 + _level * 0.08 : 0.12,
                                ),
                                assistantBlue.withValues(alpha: 0.05),
                                Colors.transparent,
                              ],
                              stops: const [0.22, 0.68, 1],
                            ),
                          ),
                          alignment: Alignment.center,
                          child: Container(
                            width: 156,
                            height: 156,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: colors.surface.withValues(alpha: 0.72),
                              border: Border.all(
                                color: Colors.white.withValues(alpha: 0.86),
                                width: 1.4,
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color:
                                      assistantIndigo.withValues(alpha: 0.14),
                                  blurRadius: 30,
                                  offset: const Offset(0, 12),
                                ),
                              ],
                            ),
                            alignment: Alignment.center,
                            child: child,
                          ),
                        ),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: listening
                                  ? const [Color(0xFFEF6883), Color(0xFFE44F70)]
                                  : const [assistantIndigo, assistantBlue],
                            ),
                            boxShadow: [
                              BoxShadow(
                                color: (listening
                                        ? assistantRose
                                        : assistantIndigo)
                                    .withValues(alpha: 0.32),
                                blurRadius: 22,
                                offset: const Offset(0, 9),
                              ),
                            ],
                          ),
                          child: Material(
                            color: Colors.transparent,
                            shape: const CircleBorder(),
                            child: InkWell(
                              customBorder: const CircleBorder(),
                              onTap: busy ? null : _primaryAction,
                              child: SizedBox.square(
                                dimension: 96,
                                child: Icon(
                                  busy
                                      ? Icons.more_horiz_rounded
                                      : listening
                                          ? Icons.stop_rounded
                                          : _state ==
                                                  _VoiceConversationState
                                                      .speaking
                                              ? Icons.mic_rounded
                                              : Icons.mic_none_rounded,
                                  color: Colors.white,
                                  size: 38,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      if (_heard.isNotEmpty) ...[
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 13,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: assistantIndigo.withValues(alpha: 0.07),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            '你说 · $_heard',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 12,
                              height: 1.5,
                            ),
                          ),
                        ),
                        const SizedBox(height: 13),
                      ],
                      Container(
                        width: double.infinity,
                        constraints: const BoxConstraints(minHeight: 104),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 16,
                        ),
                        decoration: assistantSurfaceDecoration(
                          context,
                          radius: 22,
                        ),
                        child: busy
                            ? const Center(child: CircularProgressIndicator())
                            : Column(
                                mainAxisSize: MainAxisSize.min,
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Text(
                                    _error.isNotEmpty ? _error : _answer,
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                      color: _error.isNotEmpty
                                          ? assistantRose
                                          : colors.textPrimary,
                                      fontSize: 15,
                                      fontWeight: FontWeight.w600,
                                      height: 1.45,
                                    ),
                                  ),
                                  if (_state == _VoiceConversationState.idle &&
                                      _error.isEmpty) ...[
                                    const SizedBox(height: 6),
                                    Text(
                                      '小C会边听边整理，回答时也能随时打断',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                        color: colors.textSecondary,
                                        fontSize: 11.5,
                                        height: 1.45,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                      ),
                      const Spacer(),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.touch_app_outlined,
                              size: 14, color: colors.textSecondary),
                          const SizedBox(width: 6),
                          Text(
                            _state == _VoiceConversationState.speaking
                                ? '轻点麦克风，立即打断并继续说'
                                : '轻点开始说话 · 回答时也可随时打断',
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String get _stateLabel => switch (_state) {
        _VoiceConversationState.listening => '正在听你说',
        _VoiceConversationState.thinking => '小C正在思考',
        _VoiceConversationState.speaking => '小C正在回答',
        _VoiceConversationState.error => '没有听清',
        _ => '自然语音 · 可随时打断',
      };

  Future<void> _primaryAction() async {
    if (_state == _VoiceConversationState.listening) {
      await _speech.stop();
      return;
    }
    await widget.nativeBridge.stopSpeech();
    await _startListening();
  }

  Future<void> _startListening() async {
    final granted = await const AndroidRecordAudioPermission().ensureGranted();
    if (!granted) {
      if (mounted) {
        setState(() {
          _state = _VoiceConversationState.error;
          _error = '需要麦克风权限才能开始语音对话';
        });
      }
      return;
    }
    setState(() {
      _state = _VoiceConversationState.listening;
      _heard = '';
      _error = '';
      _level = 0.15;
    });
    final ready = await _speech.initialize(
      onStatus: _handleStatus,
      onError: _handleError,
    );
    if (!ready || !mounted) {
      setState(() {
        _state = _VoiceConversationState.error;
        _error = '系统语音识别暂不可用';
      });
      return;
    }
    await _speech.listen(
      onResult: _handleResult,
      onSoundLevelChange: (level) {
        if (mounted && _state == _VoiceConversationState.listening) {
          setState(() => _level = (level.abs() / 10).clamp(0.15, 1.0));
        }
      },
      listenOptions: SpeechListenOptions(
        listenMode: ListenMode.dictation,
        partialResults: true,
        cancelOnError: false,
        listenFor: const Duration(minutes: 3),
        pauseFor: const Duration(seconds: 3),
      ),
    );
  }

  void _handleResult(SpeechRecognitionResult result) {
    if (!mounted) return;
    setState(() => _heard = result.recognizedWords.trim());
    if (result.finalResult && _heard.isNotEmpty) _submit(_heard);
  }

  void _handleStatus(String status) {
    if (!mounted || status == 'listening') return;
    if ((status == 'done' || status == 'notListening') &&
        _state == _VoiceConversationState.listening &&
        _heard.isNotEmpty) {
      _submit(_heard);
    }
  }

  void _handleError(SpeechRecognitionError error) {
    if (!mounted) return;
    if (error.permanent) {
      _startNativeRecognition();
      return;
    }
    setState(() {
      _state = _VoiceConversationState.error;
      _error = '没有听清，点一下重试';
    });
  }

  Future<void> _startNativeRecognition() async {
    if (_nativeRecognitionActive || !mounted) return;
    _nativeRecognitionActive = true;
    await _speech.cancel();
    if (!mounted) return;
    setState(() {
      _state = _VoiceConversationState.listening;
      _error = '';
      _answer = '正在打开系统语音识别…';
    });
    try {
      final text = await widget.nativeBridge.recognizeSpeech();
      if (!mounted) return;
      if (text.isEmpty) {
        setState(() {
          _state = _VoiceConversationState.error;
          _error = '没有听清，点一下重试';
        });
        return;
      }
      setState(() {
        _heard = text;
        _state = _VoiceConversationState.listening;
      });
      await _submit(text);
    } catch (_) {
      if (mounted) {
        setState(() {
          _state = _VoiceConversationState.error;
          _error = '系统语音识别不可用，请在手机设置中启用语音服务';
        });
      }
    } finally {
      _nativeRecognitionActive = false;
    }
  }

  Future<void> _submit(String text) async {
    if (_state != _VoiceConversationState.listening) return;
    setState(() {
      _state = _VoiceConversationState.thinking;
      _error = '';
    });
    await _speech.stop();
    if (!mounted) return;
    try {
      final answer = await widget.repository.streamAssistantMessage(body: text);
      if (!mounted) return;
      setState(() {
        _answer = answer;
        _state = _VoiceConversationState.speaking;
      });
      try {
        final audio = await widget.repository.synthesizeAssistantSpeech(answer);
        await widget.nativeBridge.playBase64Audio(audio);
      } catch (_) {
        await widget.nativeBridge.speakText(answer);
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _state = _VoiceConversationState.error;
          _error = error.toString();
        });
      }
    }
  }
}

import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../theme/app_theme.dart';

enum _SpeechUiState { idle, listening, processing, error }

class VoiceInputDesign {
  static const sheetTopCornerRadius = 28.0;
  static const sheetHorizontalPadding = 20.0;
  static const sheetTopPadding = 6.0;
  static const sheetBottomPadding = 28.0;
  static const cardCornerRadius = 22.0;
  static const cardVerticalPadding = 18.0;
  static const micOuterSize = 92.0;
  static const micInnerSize = 64.0;
  static const micIconSize = 30.0;
  static const waveformHeight = 42.0;
  static const waveformBarWidth = 4.0;
  static const waveformBarGap = 5.0;
  static const actionHeight = 48.0;
  static const dragHandleWidth = 42.0;
  static const dragHandleHeight = 5.0;
  static const dragHandleCornerRadius = 999.0;
  static const previewMinHeight = 42.0;
  static const previewCornerRadius = 16.0;
  static const pulseExpansion = 30.0;
  static const pulseMaxAlpha = 0.15;
  static const pulseDurationMs = 1320;
  static const pulseSecondDelayMs = 520;

  static const waveformWeights = <double>[
    0.36,
    0.52,
    0.78,
    1,
    0.72,
    0.9,
    0.6,
    0.42,
  ];

  @visibleForTesting
  static Map<String, double> dimensionTokensForTest() {
    return {
      'sheetTopCornerRadius': sheetTopCornerRadius,
      'sheetHorizontalPadding': sheetHorizontalPadding,
      'sheetTopPadding': sheetTopPadding,
      'sheetBottomPadding': sheetBottomPadding,
      'cardCornerRadius': cardCornerRadius,
      'cardVerticalPadding': cardVerticalPadding,
      'micOuterSize': micOuterSize,
      'micInnerSize': micInnerSize,
      'micIconSize': micIconSize,
      'waveformHeight': waveformHeight,
      'waveformBarWidth': waveformBarWidth,
      'waveformBarGap': waveformBarGap,
      'actionHeight': actionHeight,
      'dragHandleWidth': dragHandleWidth,
      'dragHandleHeight': dragHandleHeight,
      'dragHandleCornerRadius': dragHandleCornerRadius,
      'previewMinHeight': previewMinHeight,
      'previewCornerRadius': previewCornerRadius,
      'pulseExpansion': pulseExpansion,
      'pulseMaxAlpha': pulseMaxAlpha,
      'pulseDurationMs': pulseDurationMs.toDouble(),
      'pulseSecondDelayMs': pulseSecondDelayMs.toDouble(),
    };
  }

  @visibleForTesting
  static List<double> waveformWeightsForTest() {
    return List.unmodifiable(waveformWeights);
  }
}

class VoiceInputSheet extends StatefulWidget {
  const VoiceInputSheet({super.key, required this.onResult});

  final ValueChanged<String> onResult;

  @override
  State<VoiceInputSheet> createState() => _VoiceInputSheetState();
}

class _VoiceInputSheetState extends State<VoiceInputSheet> {
  final _speech = SpeechToText();
  var _state = _SpeechUiState.idle;
  var _partial = '';
  var _final = '';
  var _errorText = '';
  var _soundLevel = 0.16;

  bool get _hasResult => _final.trim().isNotEmpty;
  String get _recognizedText => _final.trim().isNotEmpty ? _final : _partial;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _startListening());
  }

  @override
  void dispose() {
    _speech.cancel();
    super.dispose();
  }

  Future<void> _startListening() async {
    setState(() {
      _state = _SpeechUiState.listening;
      _partial = '';
      _final = '';
      _errorText = '';
      _soundLevel = 0.16;
    });
    try {
      final available = await _speech.initialize(
        onStatus: _handleStatus,
        onError: _handleError,
      );
      if (!mounted) return;
      if (!available) {
        setState(() {
          _state = _SpeechUiState.error;
          _errorText = '没听清';
        });
        return;
      }
      await _speech.listen(
        onResult: _handleResult,
        onSoundLevelChange: (level) {
          if (!mounted || _state != _SpeechUiState.listening) return;
          setState(() => _soundLevel = (level / 10).abs().clamp(0.16, 1.0));
        },
        listenOptions: SpeechListenOptions(
          listenMode: ListenMode.dictation,
          partialResults: true,
          cancelOnError: false,
        ),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _SpeechUiState.error;
        _errorText = '没听清';
      });
    }
  }

  void _handleResult(SpeechRecognitionResult result) {
    if (!mounted) return;
    final words = result.recognizedWords.trim();
    setState(() {
      if (result.finalResult) {
        _final = words;
        _state = words.isEmpty ? _SpeechUiState.error : _SpeechUiState.idle;
        if (words.isEmpty) _errorText = '没听清';
      } else {
        _partial = words;
      }
    });
  }

  void _handleStatus(String status) {
    if (!mounted) return;
    if (status == 'listening') {
      setState(() => _state = _SpeechUiState.listening);
      return;
    }
    if (status == 'done' || status == 'notListening') {
      setState(() {
        if (_hasResult) {
          _state = _SpeechUiState.idle;
        } else if (_partial.trim().isNotEmpty) {
          _final = _partial.trim();
          _state = _SpeechUiState.idle;
        } else if (_state == _SpeechUiState.processing) {
          _state = _SpeechUiState.error;
          _errorText = '没听清';
        }
      });
    }
  }

  void _handleError(SpeechRecognitionError error) {
    if (!mounted) return;
    setState(() {
      _state = _SpeechUiState.error;
      _errorText = _voiceErrorText(error.errorMsg);
    });
  }

  Future<void> _primaryAction() async {
    if (_hasResult) {
      widget.onResult(_final.trim());
      if (mounted) Navigator.of(context).pop();
      return;
    }
    if (_state == _SpeechUiState.error) {
      await _startListening();
      return;
    }
    if (_state == _SpeechUiState.processing) return;
    setState(() => _state = _SpeechUiState.processing);
    try {
      await _speech.stop();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _SpeechUiState.error;
        _errorText = '没听清';
      });
    }
  }

  void _cancel() {
    _speech.cancel();
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final palette = _VoicePalette.of(context, _state);
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.only(
          left: VoiceInputDesign.sheetHorizontalPadding,
          right: VoiceInputDesign.sheetHorizontalPadding,
          top: VoiceInputDesign.sheetTopPadding,
          bottom: MediaQuery.of(context).viewInsets.bottom +
              VoiceInputDesign.sheetBottomPadding,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: VoiceInputDesign.dragHandleWidth,
                height: VoiceInputDesign.dragHandleHeight,
                margin: const EdgeInsets.only(bottom: 16),
                decoration: BoxDecoration(
                  color: colors.divider.withValues(alpha: 0.72),
                  borderRadius: BorderRadius.circular(
                    VoiceInputDesign.dragHandleCornerRadius,
                  ),
                ),
              ),
            ),
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '语音输入',
                        style: TextStyle(
                          color: colors.textPrimary,
                          fontSize: 17,
                          height: 1.29,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0,
                        ),
                      ),
                      const SizedBox(height: 6),
                      _VoiceStatusPill(
                        text: _voiceStatusLabel(_state, _errorText, _hasResult),
                        palette: palette,
                      ),
                    ],
                  ),
                ),
                IconButton(
                  onPressed: _cancel,
                  icon: const Icon(Icons.close),
                  tooltip: '关闭',
                ),
              ],
            ),
            const SizedBox(height: 18),
            _VoiceListeningCard(
              state: _state,
              level: _soundLevel,
              preview: _recognizedText,
              statusText: _voiceStatusLabel(_state, _errorText, _hasResult),
              palette: palette,
              weights: VoiceInputDesign.waveformWeights,
            ),
            const SizedBox(height: 18),
            Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: VoiceInputDesign.actionHeight,
                    child: TextButton(
                      onPressed: _cancel,
                      child: const Text('取消'),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: SizedBox(
                    height: VoiceInputDesign.actionHeight,
                    child: FilledButton.icon(
                      onPressed: _state == _SpeechUiState.processing
                          ? null
                          : _primaryAction,
                      icon: Icon(
                        _hasResult
                            ? Icons.check
                            : _state == _SpeechUiState.error
                                ? Icons.refresh
                                : Icons.mic,
                        size: 18,
                      ),
                      label: Text(_voicePrimaryLabel(_state, _hasResult)),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

part 'voice_input_sheet_widgets.part.dart';

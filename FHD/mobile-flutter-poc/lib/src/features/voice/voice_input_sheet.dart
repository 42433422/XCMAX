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
                        text: _voiceStatusLabel(
                          _state,
                          _errorText,
                          _hasResult,
                        ),
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

class _VoiceStatusPill extends StatelessWidget {
  const _VoiceStatusPill({required this.text, required this.palette});

  final String text;
  final _VoicePalette palette;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: palette.statusBackground,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: palette.statusForeground,
          fontSize: 12,
          height: 1.34,
          fontWeight: FontWeight.w500,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _VoiceListeningCard extends StatelessWidget {
  const _VoiceListeningCard({
    required this.state,
    required this.level,
    required this.preview,
    required this.statusText,
    required this.palette,
    required this.weights,
  });

  final _SpeechUiState state;
  final double level;
  final String preview;
  final String statusText;
  final _VoicePalette palette;
  final List<double> weights;

  @override
  Widget build(BuildContext context) {
    final isListening = state == _SpeechUiState.listening;
    final displayText = preview.trim().isEmpty ? statusText : preview.trim();
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: XcagiSpacing.lg,
        vertical: VoiceInputDesign.cardVerticalPadding,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceHigh.withValues(alpha: 0.62),
        border: Border.all(color: colors.divider.withValues(alpha: 0.78)),
        borderRadius: BorderRadius.circular(VoiceInputDesign.cardCornerRadius),
      ),
      child: Column(
        children: [
          Row(
            children: [
              SizedBox(
                width: VoiceInputDesign.micOuterSize,
                height: VoiceInputDesign.micOuterSize,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    if (isListening) _VoicePulseRings(color: palette.pulse),
                    Container(
                      width: VoiceInputDesign.micInnerSize,
                      height: VoiceInputDesign.micInnerSize,
                      decoration: BoxDecoration(
                        color: colors.surface,
                        shape: BoxShape.circle,
                      ),
                      alignment: Alignment.center,
                      child: Icon(
                        Icons.mic,
                        size: VoiceInputDesign.micIconSize,
                        color: state == _SpeechUiState.error
                            ? colors.danger
                            : colors.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 18),
              Expanded(
                child: SizedBox(
                  height: VoiceInputDesign.waveformHeight,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      for (var index = 0; index < weights.length; index++) ...[
                        Container(
                          width: VoiceInputDesign.waveformBarWidth,
                          height: 8 +
                              (level.clamp(0.16, 1.0) * 30 * weights[index]),
                          decoration: BoxDecoration(
                            color: palette.waveform.withValues(
                              alpha: 0.34 + weights[index] * 0.42,
                            ),
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                        if (index < weights.length - 1)
                          const SizedBox(
                            width: VoiceInputDesign.waveformBarGap,
                          ),
                      ],
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(
              minHeight: VoiceInputDesign.previewMinHeight,
            ),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: BorderRadius.circular(
                VoiceInputDesign.previewCornerRadius,
              ),
            ),
            child: Text(
              displayText,
              style: TextStyle(
                color: preview.trim().isEmpty
                    ? palette.previewPlaceholder
                    : colors.textPrimary,
                fontSize: 14,
                height: 1.43,
                letterSpacing: 0,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _VoicePalette {
  const _VoicePalette({
    required this.statusBackground,
    required this.statusForeground,
    required this.pulse,
    required this.waveform,
    required this.previewPlaceholder,
  });

  final Color statusBackground;
  final Color statusForeground;
  final Color pulse;
  final Color waveform;
  final Color previewPlaceholder;

  static _VoicePalette of(BuildContext context, _SpeechUiState state) {
    final colors = AppTheme.colors(context);
    switch (state) {
      case _SpeechUiState.listening:
        return _VoicePalette(
          statusBackground: colors.success.withValues(alpha: 0.10),
          statusForeground: colors.success,
          pulse: colors.success,
          waveform: colors.textPrimary,
          previewPlaceholder: colors.textSecondary,
        );
      case _SpeechUiState.processing:
        return _VoicePalette(
          statusBackground: colors.brand.withValues(alpha: 0.10),
          statusForeground: colors.brand,
          pulse: colors.textTertiary,
          waveform: colors.textPrimary,
          previewPlaceholder: colors.textSecondary,
        );
      case _SpeechUiState.error:
        return _VoicePalette(
          statusBackground: colors.danger.withValues(alpha: 0.13),
          statusForeground: colors.danger,
          pulse: colors.textTertiary,
          waveform: colors.danger,
          previewPlaceholder: colors.danger,
        );
      case _SpeechUiState.idle:
        return _VoicePalette(
          statusBackground: colors.surfaceHigh,
          statusForeground: colors.textSecondary,
          pulse: colors.textTertiary,
          waveform: colors.textPrimary,
          previewPlaceholder: colors.textSecondary,
        );
    }
  }
}

class _VoicePulseRings extends StatefulWidget {
  const _VoicePulseRings({required this.color});

  final Color color;

  @override
  State<_VoicePulseRings> createState() => _VoicePulseRingsState();
}

class _VoicePulseRingsState extends State<_VoicePulseRings>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: VoiceInputDesign.pulseDurationMs),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Stack(
          alignment: Alignment.center,
          children: [
            _VoicePulseRing(color: widget.color, progress: _progress(0)),
            _VoicePulseRing(
              color: widget.color,
              progress: _progress(VoiceInputDesign.pulseSecondDelayMs),
            ),
          ],
        );
      },
    );
  }

  double _progress(int delayMs) {
    final elapsed = _controller.value * VoiceInputDesign.pulseDurationMs;
    final shifted =
        (elapsed - delayMs) % VoiceInputDesign.pulseDurationMs.toDouble();
    return (shifted / VoiceInputDesign.pulseDurationMs).clamp(0.0, 1.0);
  }
}

class _VoicePulseRing extends StatelessWidget {
  const _VoicePulseRing({required this.color, required this.progress});

  final Color color;
  final double progress;

  @override
  Widget build(BuildContext context) {
    final size = VoiceInputDesign.micInnerSize +
        VoiceInputDesign.pulseExpansion * progress;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withValues(
          alpha: (1 - progress) * VoiceInputDesign.pulseMaxAlpha,
        ),
        shape: BoxShape.circle,
      ),
    );
  }
}

String _voiceStatusLabel(
  _SpeechUiState state,
  String errorText,
  bool hasResult,
) {
  if (hasResult) return '识别完成';
  switch (state) {
    case _SpeechUiState.listening:
      return '正在听';
    case _SpeechUiState.processing:
      return '识别中';
    case _SpeechUiState.error:
      return errorText.trim().isEmpty ? '没听清' : errorText.trim();
    case _SpeechUiState.idle:
      return '语音输入';
  }
}

String _voicePrimaryLabel(_SpeechUiState state, bool hasResult) {
  if (hasResult) return '插入';
  switch (state) {
    case _SpeechUiState.error:
      return '重试';
    case _SpeechUiState.processing:
      return '识别中';
    case _SpeechUiState.idle:
    case _SpeechUiState.listening:
      return '完成';
  }
}

String _voiceErrorText(String errorMsg) {
  final lower = errorMsg.toLowerCase();
  if (lower.contains('network')) return '网络异常';
  if (lower.contains('permission')) return '需要麦克风权限才能使用语音输入';
  return '没听清';
}

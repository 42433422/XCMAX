// part 文件：语音输入面板的视觉组件与文案工具。

part of 'voice_input_sheet.dart';

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

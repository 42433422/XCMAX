import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/voice/voice_input_sheet.dart';

void main() {
  test('voice input keeps the Flutter geometry contract', () {
    expect(VoiceInputDesign.dimensionTokensForTest(), {
      'sheetTopCornerRadius': 28.0,
      'sheetHorizontalPadding': 20.0,
      'sheetTopPadding': 6.0,
      'sheetBottomPadding': 28.0,
      'cardCornerRadius': 22.0,
      'cardVerticalPadding': 18.0,
      'micOuterSize': 92.0,
      'micInnerSize': 64.0,
      'micIconSize': 30.0,
      'waveformHeight': 42.0,
      'waveformBarWidth': 4.0,
      'waveformBarGap': 5.0,
      'actionHeight': 48.0,
      'dragHandleWidth': 42.0,
      'dragHandleHeight': 5.0,
      'dragHandleCornerRadius': 999.0,
      'previewMinHeight': 42.0,
      'previewCornerRadius': 16.0,
      'pulseExpansion': 30.0,
      'pulseMaxAlpha': 0.15,
      'pulseDurationMs': 1320.0,
      'pulseSecondDelayMs': 520.0,
    });
    expect(VoiceInputDesign.waveformWeightsForTest(), [
      0.36,
      0.52,
      0.78,
      1.0,
      0.72,
      0.9,
      0.6,
      0.42,
    ]);
  });
}

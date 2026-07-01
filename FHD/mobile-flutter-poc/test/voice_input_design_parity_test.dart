import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/voice/voice_input_sheet.dart';

void main() {
  test('VoiceInputDesign dimensions mirror Android source', () {
    expect(
      VoiceInputDesign.dimensionTokensForTest(),
      _androidVoiceInputDimensions(),
      reason: 'Flutter voice input geometry must mirror Android.',
    );
  });

  test('VoiceInputDesign waveform weights mirror Android source', () {
    expect(
      VoiceInputDesign.waveformWeightsForTest(),
      _androidVoiceInputWaveformWeights(),
      reason: 'Flutter voice waveform bars must mirror Android.',
    );
  });
}

Map<String, double> _androidVoiceInputDimensions() {
  final source = _androidVoiceInputDesignSource();
  final tokens = {
    for (final match in RegExp(
      r'val\s+(\w+)\s*=\s*(\d+(?:\.\d+)?)\.dp',
    ).allMatches(source))
      match.group(1)!: double.parse(match.group(2)!),
  };
  final sheetSource = _androidVoiceInputSheetSource();
  tokens['pulseExpansion'] = _requiredDouble(
    RegExp(r'micInnerSize\.value\s*\+\s*(\d+(?:\.\d+)?)f\s*\*\s*p'),
    sheetSource,
    'pulse expansion',
  );
  tokens['pulseMaxAlpha'] = _requiredDouble(
    RegExp(r'\(1f\s*-\s*p\)\s*\*\s*(\d+(?:\.\d+)?)f'),
    sheetSource,
    'pulse max alpha',
  );
  tokens['pulseDurationMs'] = _requiredDouble(
    RegExp(r'tween\((\d+)'),
    sheetSource,
    'pulse duration',
  );
  final delays = RegExp(
    r'listOf\(\s*0,\s*(\d+)\s*\)\.forEach',
  ).firstMatch(sheetSource);
  if (delays == null) {
    throw StateError('Android VoicePulse second delay not found');
  }
  tokens['pulseSecondDelayMs'] = double.parse(delays.group(1)!);
  return tokens;
}

List<double> _androidVoiceInputWaveformWeights() {
  final source = _androidVoiceInputDesignSource();
  final block = RegExp(
    r'waveformWeights\s*=\s*listOf\(([^)]*)\)',
  ).firstMatch(source);
  if (block == null) {
    throw StateError('Android VoiceInputDesign waveformWeights not found');
  }
  return RegExp(r'(\d+(?:\.\d+)?)f?')
      .allMatches(block.group(1)!)
      .map((match) => double.parse(match.group(1)!))
      .toList(growable: false);
}

String _androidVoiceInputDesignSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/speech/VoiceInputDesign.kt',
  ).readAsStringSync();
}

String _androidVoiceInputSheetSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/speech/VoiceInputSheet.kt',
  ).readAsStringSync();
}

double _requiredDouble(RegExp pattern, String source, String label) {
  final match = pattern.firstMatch(source);
  if (match == null) throw StateError('Android $label not found');
  return double.parse(match.group(1)!);
}

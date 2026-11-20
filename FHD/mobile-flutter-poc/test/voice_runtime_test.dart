import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/call/voice_call_screen.dart';
import 'package:xcagi_flutter_poc/src/features/voice/voice_input_sheet.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/platform/speech_recognition_support.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

const _conversation = ConversationItem(
  id: 'voice-test',
  type: ConversationType.pinnedAssistant,
  title: '小C',
  subtitle: '',
  timestampText: '',
);

class _VoiceChannels {
  static const speech = MethodChannel('plugin.csdcorp.com/speech_to_text');
  static const tts = MethodChannel('flutter_tts');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final speechCalls = <String>[];
  final ttsCalls = <String>[];
  String? failSpeechMethod;
  bool ready = true;
  bool failTtsStop = false;
  Completer<bool>? delayedInitialization;

  void install() {
    messenger.setMockMethodCallHandler(tts, (call) async {
      ttsCalls.add(call.method);
      if (failTtsStop && call.method == 'stop') {
        throw PlatformException(code: 'service_unavailable');
      }
      return 1;
    });
    messenger.setMockMethodCallHandler(speech, (call) async {
      speechCalls.add(call.method);
      if (call.method == failSpeechMethod) throw MissingPluginException();
      if (call.method == 'initialize') {
        return delayedInitialization?.future ?? ready;
      }
      return call.method == 'listen' ? true : null;
    });
  }

  Future<void> emit(String method, Object value) async {
    await messenger.handlePlatformMessage(
      speech.name,
      const StandardMethodCodec().encodeMethodCall(MethodCall(method, value)),
      (_) {},
    );
  }

  void dispose() {
    messenger.setMockMethodCallHandler(speech, null);
    messenger.setMockMethodCallHandler(tts, null);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late _VoiceChannels channels;
  setUp(() {
    channels = _VoiceChannels()..install();
  });
  tearDown(() {
    channels.dispose();
    debugSpeechOperatingSystemOverride = null;
  });

  Future<void> openCall(WidgetTester tester) async {
    final repository = MobileRepository();
    addTearDown(repository.dispose);
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(
        body: Builder(builder: (context) {
          return TextButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => VoiceCallScreen(
                conversation: _conversation,
                repository: repository,
                title: '小C',
                speech: SpeechToText.withMethodChannel(),
              ),
            )),
            child: const Text('文字聊天'),
          );
        }),
      ),
    ));
    await tester.tap(find.text('文字聊天'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  Future<void> openInput(
    WidgetTester tester, {
    required ValueChanged<String> onResult,
  }) async {
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: Builder(builder: (context) {
        return TextButton(
          onPressed: () => showModalBottomSheet<void>(
            context: context,
            isScrollControlled: true,
            builder: (_) => VoiceInputSheet(
              onResult: onResult,
              speech: SpeechToText.withMethodChannel(),
            ),
          ),
          child: const Text('文字输入'),
        );
      })),
    ));
    await tester.tap(find.text('文字输入'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  testWidgets('HarmonyOS call option is disabled with a text-chat explanation',
      (tester) async {
    debugSpeechOperatingSystemOverride = 'ohos';
    var started = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Builder(builder: (context) {
        return TextButton(
          onPressed: () =>
              showCallOptionsSheet(context, onVoice: () => started = true),
          child: const Text('通话'),
        );
      })),
    ));
    await tester.tap(find.text('通话'));
    await tester.pumpAndSettle();
    final option = find.byKey(const ValueKey('call_option_voice'));
    expect(tester.widget<ListTile>(option).enabled, isFalse);
    expect(find.text(unsupportedSpeechRecognitionMessage!), findsOneWidget);
    await tester.tap(option);
    expect(started, isFalse);
    expect(channels.speechCalls, isEmpty);
  });

  testWidgets('HarmonyOS shared dictation entry keeps text input available',
      (tester) async {
    debugSpeechOperatingSystemOverride = 'ohos';
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Builder(builder: (context) {
        return TextButton(
          onPressed: () => showVoiceInputSheet(context, onResult: (_) {
            fail('Unsupported recognition must not return fabricated text');
          }),
          child: const Text('语音输入'),
        );
      })),
    ));
    await tester.tap(find.text('语音输入'));
    await tester.pumpAndSettle();
    expect(find.byType(VoiceInputSheet), findsNothing);
    expect(find.text(unsupportedSpeechRecognitionMessage!), findsOneWidget);
    expect(channels.speechCalls, isEmpty);
  });

  testWidgets('direct HarmonyOS call performs no native audio operations',
      (tester) async {
    debugSpeechOperatingSystemOverride = 'ohos';
    await openCall(tester);
    expect(find.text(unsupportedSpeechRecognitionMessage!), findsOneWidget);
    await tester.tap(find.text('返回文字聊天'));
    await tester.pumpAndSettle();
    expect(find.byType(VoiceCallScreen), findsNothing);
    expect(find.text('文字聊天'), findsOneWidget);
    expect(channels.speechCalls, isEmpty);
    expect(channels.ttsCalls, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('direct HarmonyOS dictation performs no recognition operations',
      (tester) async {
    debugSpeechOperatingSystemOverride = 'ohos';
    await openInput(tester, onResult: (_) => fail('No recognition adapter'));
    expect(find.text(unsupportedSpeechRecognitionMessage!), findsOneWidget);
    expect(find.text('重试'), findsNothing);
    await tester.tap(find.text('返回文字输入'));
    await tester.pumpAndSettle();
    expect(find.byType(VoiceInputSheet), findsNothing);
    expect(channels.speechCalls, isEmpty);
    expect(tester.takeException(), isNull);
  });

  for (final failure in ['initialize', 'unavailable', 'listen']) {
    testWidgets('$failure ends the call with a usable exit', (tester) async {
      channels.failSpeechMethod = failure;
      channels.ready = failure != 'unavailable';
      channels.failTtsStop = true;
      await openCall(tester);
      expect(tester.takeException(), isNull);
      expect(find.text('正在接通…'), findsNothing);
      expect(find.text(speechRecognitionUnavailableMessage), findsOneWidget);
      await tester.tap(find.text('返回文字聊天'));
      await tester.pumpAndSettle();
      expect(find.byType(VoiceCallScreen), findsNothing);
      expect(find.text('文字聊天'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  for (final operatingSystem in ['android', 'ios']) {
    testWidgets('$operatingSystem retains native call recognition',
        (tester) async {
      debugSpeechOperatingSystemOverride = operatingSystem;
      await openCall(tester);
      expect(
          channels.speechCalls, containsAllInOrder(['initialize', 'listen']));
      expect(find.text('正在聆听…'), findsOneWidget);
      expect(find.text('返回文字聊天'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('call_hangup_button')));
      await tester.pumpAndSettle();
      expect(find.byType(VoiceCallScreen), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('$operatingSystem dictation inserts actual recognized text',
        (tester) async {
      debugSpeechOperatingSystemOverride = operatingSystem;
      var result = '';
      await openInput(tester, onResult: (text) => result = text);
      expect(
          channels.speechCalls, containsAllInOrder(['initialize', 'listen']));
      final words = SpeechRecognitionResult.init(
        [const SpeechRecognitionWords('请查看今日订单', null, 1.0)],
        ResultType.finalResult,
      );
      await channels.emit('textRecognition', jsonEncode(words.toJson()));
      await tester.pump();
      await tester.tap(find.text('插入'));
      await tester.pumpAndSettle();
      expect(result, '请查看今日订单');
      expect(find.byType(VoiceInputSheet), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('recognition completing after hangup never starts listening',
      (tester) async {
    final initialized = channels.delayedInitialization = Completer<bool>();
    await openCall(tester);
    await tester.tap(find.byKey(const ValueKey('call_hangup_button')));
    await tester.pumpAndSettle();
    initialized.complete(true);
    await tester.pump();
    expect(channels.speechCalls, isNot(contains('listen')));
    expect(tester.takeException(), isNull);
  });

  testWidgets('permanent recognition errors stop instead of restarting forever',
      (tester) async {
    await openCall(tester);
    final listenCount = channels.speechCalls.where((c) => c == 'listen').length;
    await channels.emit('notifyError',
        jsonEncode({'errorMsg': 'error_permission', 'permanent': true}));
    await tester.pump();
    expect(find.text(speechRecognitionUnavailableMessage), findsOneWidget);
    expect(
        channels.speechCalls.where((c) => c == 'listen').length, listenCount);
    await tester.tap(find.text('返回文字聊天'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}

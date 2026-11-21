import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const preferences = MethodChannel('plugins.flutter.io/shared_preferences');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  Future<void> Function()? onTaskStore;

  setUp(() {
    onTaskStore = null;
    messenger.setMockMethodCallHandler(preferences, (call) async {
      if (call.method == 'getAll') return <String, Object>{};
      if (call.method == 'setString' &&
          '${call.arguments['key']}'.contains('.relay.e2ee.task.')) {
        await onTaskStore?.call();
      }
      return true;
    });
  });
  tearDown(() => messenger.setMockMethodCallHandler(preferences, null));

  for (final phase in ['public-key', 'seal', 'remember-task']) {
    test('account switch during relay $phase cannot POST the old intent', () async {
      final http = _DispatchRecorder();
      final api = _PreflightApi(http);
      addTearDown(api.dispose);
      var reached = false;
      Future<void> switchAccount() async {
        reached = true;
        final generation = api.beginLoginAttempt();
        await api.saveSession(const MobileSessionData(
            userId: 2, accessToken: 'account-B', username: 'B'),
            authGeneration: generation);
      }

      if (phase == 'public-key') api.onPublicKey = switchAccount;
      if (phase == 'remember-task') onTaskStore = switchAccount;
      final payload = <String, Object?>{'message': 'execute once'};
      if (phase == 'seal') {
        payload['serialization'] = _DuringSerialization(() {
          reached = true;
          api.beginLoginAttempt();
        });
      }
      await expectLater(api.relayCreateTask(relayId: 'scope-$phase', kind: 'codex.invoke',
          payload: payload, clientRequestId: 'original-intent'),
          throwsA(isA<MobileApiException>().having((error) => error.statusCode, 'status', 409)));
      expect(reached, isTrue);
      expect(http.methods, isEmpty);
    });
  }

  test('account switch while resolving LAN base cannot POST the old intent', () async {
    final http = _DispatchRecorder();
    final api = _PreflightApi(http);
    addTearDown(api.dispose);
    api.onBase = () async {
      final generation = api.beginLoginAttempt();
      await api.saveSession(const MobileSessionData(userId: 2, accessToken: 'account-B'),
          authGeneration: generation);
    };
    await expectLater(api.postSuperEmployeeMessage('codex', 'execute once',
        conversationId: 'original-conversation', idempotencyKey: 'original-intent'),
        throwsA(isA<MobileApiException>().having((error) => error.statusCode, 'status', 409)));
    expect(http.methods, isEmpty);
  });
}

class _PreflightApi extends MobileApiClient {
  _PreflightApi(HttpClient http) : super(httpClient: http,
      config: const MobileApiConfig(baseUrl: 'https://same-server.invalid/'),
      sessionStore: MemoryMobileSessionStore(const MobileSessionData(
          userId: 1, accessToken: 'account-A', username: 'A')));

  Future<void> Function()? onBase;
  Future<void> Function()? onPublicKey;

  @override
  Future<String> resolveSessionBaseUrl() async {
    final callback = onBase;
    onBase = null;
    await callback?.call();
    return 'https://same-server.invalid/';
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayDesktops() async {
    await onPublicKey?.call();
    return MobileEnvelope(success: true, message: '', raw: {}, data: {
      'items': [
        for (final phase in ['public-key', 'seal', 'remember-task'])
          {'relay_id': 'scope-$phase',
            'public_key': 'B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw='},
      ],
    });
  }
}

class _DuringSerialization {
  _DuringSerialization(this.onSerialize);
  final void Function() onSerialize;
  Map<String, Object?> toJson() {
    onSerialize();
    return {'serialized': true};
  }
}

class _DispatchRecorder implements HttpClient {
  final methods = <String>[];
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    methods.add(method);
    throw StateError('The stale intent must never open an HTTP request');
  }
  @override
  void close({bool force = false}) {}
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('xcagi/credential_cipher');
  const password = 'synthetic-audit-password';
  const encrypted = 'enc:v1:synthetic-ciphertext';
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  for (final available in [true, false]) {
    test(
        'a plaintext cipher-prefix password is encrypted or cleared ($available)',
        () async {
      const prefixedPassword = 'enc:v1:literal-user-password';
      var encryptionCalls = 0;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'decrypt') return prefixedPassword;
        encryptionCalls++;
        expect(call.arguments['plain'], prefixedPassword);
        if (!available) throw PlatformException(code: 'unavailable');
        return encrypted;
      });
      final directory =
          await Directory.systemTemp.createTemp('xcagi-cipher-test-');
      addTearDown(() => directory.delete(recursive: true));
      final file = File('${directory.path}/session.json');
      final api = MobileApiClient(
          sessionStore: FileMobileSessionStore(filePath: file.path));
      await api.saveLoginPreferences(
          username: 'audit',
          password: prefixedPassword,
          rememberPassword: true,
          autoLogin: true);
      expect(encryptionCalls, 1);
      expect(await file.readAsString(), isNot(contains(prefixedPassword)));
      final decoded = await api.loadSession();
      expect(decoded.canAutoLogin, available);
      if (available) {
        expect(decoded.savedPassword, prefixedPassword);
        await api.saveSession(decoded.copyWith(themeMode: 'dark'));
        expect(encryptionCalls, 2);
        expect(await file.readAsString(), isNot(contains(prefixedPassword)));
      } else {
        expect(decoded.savedPassword, isEmpty);
        expect(decoded.rememberPassword, isFalse);
      }
    });
  }

  for (final failure in ['null', 'plaintext', 'empty-cipher', 'error']) {
    test('credential encryption $failure clears saved password and auto login',
        () async {
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (failure == 'error') throw PlatformException(code: 'unavailable');
        if (failure == 'empty-cipher') return 'enc:v1:';
        return failure == 'null' ? null : password;
      });
      final directory =
          await Directory.systemTemp.createTemp('xcagi-cipher-test-');
      addTearDown(() => directory.delete(recursive: true));
      final file = File('${directory.path}/session.json');
      final api = MobileApiClient(
          sessionStore: FileMobileSessionStore(filePath: file.path));
      await api.saveLoginPreferences(
          username: 'audit',
          password: password,
          rememberPassword: true,
          autoLogin: true);
      final raw = await file.readAsString();
      expect(raw, isNot(contains(password)));
      final session = await api.loadSession();
      expect(session.savedPassword, isEmpty);
      expect(session.rememberPassword, isFalse);
      expect(session.autoLogin, isFalse);
    });
  }

  test('encrypted credentials remain encrypted when a decoded session is saved',
      () async {
    messenger.setMockMethodCallHandler(channel,
        (call) async => call.method == 'encrypt' ? encrypted : password);
    final directory =
        await Directory.systemTemp.createTemp('xcagi-cipher-test-');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}/session.json');
    final store = FileMobileSessionStore(filePath: file.path);
    final api = MobileApiClient(sessionStore: store);
    await api.saveLoginPreferences(
        username: 'audit',
        password: password,
        rememberPassword: true,
        autoLogin: true);
    final decoded = await api.loadSession();
    expect(decoded.savedPassword, password);
    expect(decoded.canAutoLogin, isTrue);
    await api.saveSession(decoded.copyWith(themeMode: 'dark'));
    expect((await store.load()).savedPassword, encrypted);
    expect(await file.readAsString(), isNot(contains(password)));
    expect((await api.loadSession()).savedPassword, password);
  });
}

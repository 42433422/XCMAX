import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

void main() {
  const qr = '{"v":3,"kind":"xcagi_relay_pairing",'
      '"relay_id":"relay-12345678","code":"345678"}';

  for (final transition in ['logout', 'switch', 'same-account-login']) {
    test('failed pairing rollback cannot undo $transition', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final http = HttpClient();
      addTearDown(() => http.close(force: true));
      addTearDown(() => server.close(force: true));
      final base = 'http://127.0.0.1:${server.port}/';
      final binding = Completer<void>();
      final release = Completer<void>();
      final subscription = server.listen((request) async {
        request.response.headers.contentType = ContentType.json;
        if (request.uri.path.endsWith('/pairing/exchange')) {
          request.response.write(jsonEncode({
            'success': true,
            'data': {
              'api_base_url': base,
              'relay_id': 'relay-new',
            }
          }));
        } else {
          binding.complete();
          await release.future;
          request.response
              .write(jsonEncode({'success': false, 'message': 'expired'}));
        }
        await request.response.close();
      });
      addTearDown(subscription.cancel);
      final store = MemoryMobileSessionStore(const MobileSessionData(
          accessToken: 'access-A', username: 'account-A', userId: 1));
      final api = MobileApiClient(
          config: MobileApiConfig(baseUrl: base),
          sessionStore: store,
          httpClient: http);
      final repository = MobileRepository(client: api);
      final result = expectLater(
          repository.exchangePairingCode(jsonEncode({
            'v': 2,
            'nonce': 'legacy-nonce-123',
            'api_base_url': base,
          })),
          throwsA(anyOf(
              isA<MobileApiException>(), isA<MobileRepositoryException>())));
      await binding.future;
      if (transition == 'logout') {
        await api.clearActiveAuth();
      } else {
        final account = transition == 'switch' ? 'B' : 'A';
        await api.persistLoginSession({
          'access_token': 'access-$account',
          'user': {'id': account == 'A' ? 1 : 2, 'username': 'account-$account'}
        },
            fallbackUsername: 'account-$account',
            fallbackAccountKind: 'enterprise');
        await api.saveLocalSettings(themeMode: 'dark');
      }
      release.complete();
      await result;
      final saved = await store.load();
      expect(
          saved.accessToken,
          transition == 'logout'
              ? ''
              : transition == 'switch'
                  ? 'access-B'
                  : 'access-A');
      if (transition != 'logout') expect(saved.themeMode, 'dark');
    });
  }

  for (final input in <String>[
    qr,
    '345678',
    qr.replaceFirst(
        '}',
        ',"api_base_url":"https://attacker.example/",'
            '"relay_base_url":"https://attacker.example/"}'),
  ]) {
    test(
        'signed-in phone binds ${input == '345678' ? 'device code' : input == qr ? 'QR' : 'QR without trusting its origins'}',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final httpClient = HttpClient();
      addTearDown(() => httpClient.close(force: true));
      addTearDown(() => server.close(force: true));
      final requestDone = server.first.then((request) async {
        expect(request.uri.path, '/api/mobile/v1/relay/mobile/bind-account');
        expect(request.headers.value(HttpHeaders.authorizationHeader),
            'Bearer signed-in-token');
        final body = jsonDecode(await utf8.decoder.bind(request).join());
        expect(body, {
          'relay_id': input == '345678' ? '' : 'relay-12345678',
          'pairing_code': '345678',
        });
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'success': true,
            'data': {'relay_id': 'relay-12345678'},
          }),
        );
        await request.response.close();
      });
      final store = MemoryMobileSessionStore(
        const MobileSessionData(
          accessToken: 'signed-in-token',
          username: 'test-user',
          serverMode: 'lan',
          fhdHost: '192.168.1.9:17500',
        ),
      );
      final repository = MobileRepository(
        client: MobileApiClient(
          config: MobileApiConfig(
            baseUrl: 'http://${server.address.address}:${server.port}/',
          ),
          sessionStore: store,
          httpClient: httpClient,
        ),
      );

      await repository.exchangePairingCode(input);
      await requestDone;
      expect((await store.load()).relayDesktopId, 'relay-12345678');
    });
  }

  test('relay QR requires mobile login', () async {
    final repository = MobileRepository(
      client: MobileApiClient(sessionStore: MemoryMobileSessionStore()),
    );
    await expectLater(
      repository.exchangePairingCode(qr),
      throwsA(
        isA<MobileRepositoryException>().having(
          (error) => error.message,
          'message',
          contains('请先登录账号'),
        ),
      ),
    );
  });

  test('trusted legacy exchange restores session when account bind rejects',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));
    final base = 'http://${server.address.address}:${server.port}/';
    var exchanges = 0;
    var bindings = 0;
    final listening = server.listen((request) async {
      request.response.headers.contentType = ContentType.json;
      if (request.uri.path == '/api/mobile/v1/pairing/exchange') {
        exchanges++;
        request.response.write(jsonEncode({
          'success': true,
          'data': {
            'api_base_url': base,
            'relay_id': 'relay-legacy-1',
            'relay': {'relay_id': 'relay-legacy-1', 'pairing_code': '345678'},
          },
        }));
      } else {
        bindings++;
        expect(request.uri.path, '/api/mobile/v1/relay/mobile/bind-account');
        expect(request.headers.value(HttpHeaders.authorizationHeader),
            'Bearer signed-in-token');
        expect(jsonDecode(await utf8.decoder.bind(request).join()), {
          'relay_id': 'relay-legacy-1',
          'pairing_code': '345678',
        });
        request.response.write(jsonEncode({
          'success': false,
          'message': 'expired code',
        }));
      }
      await request.response.close();
    });
    addTearDown(listening.cancel);
    const previous = MobileSessionData(
      accessToken: 'signed-in-token',
      username: 'test-user',
      fhdHost: 'original.local:17500',
      relayDesktopId: 'relay-original',
      serverMode: 'lan',
      setupComplete: true,
    );
    final store = MemoryMobileSessionStore(previous);
    final repository = MobileRepository(
      client: MobileApiClient(
        config: MobileApiConfig(baseUrl: base),
        sessionStore: store,
        httpClient: httpClient,
      ),
    );
    final qr = jsonEncode({
      'v': 2,
      'nonce': 'legacy-nonce-123',
      'api_base_url': base,
    });

    await expectLater(
      repository.exchangePairingCode(qr),
      throwsA(isA<MobileRepositoryException>()),
    );
    expect(exchanges, 1);
    expect(bindings, 1);
    final restored = await store.load();
    expect(restored.accessToken, previous.accessToken);
    expect(restored.fhdHost, previous.fhdHost);
    expect(restored.relayDesktopId, previous.relayDesktopId);
    expect(restored.setupComplete, previous.setupComplete);
  });
}

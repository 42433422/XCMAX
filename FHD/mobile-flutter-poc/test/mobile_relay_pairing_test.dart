import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

void main() {
  const qr = '{"v":3,"kind":"xcagi_relay_pairing",'
      '"relay_id":"relay-12345678","code":"345678"}';

  for (final input in <String>[qr, '345678']) {
    test('signed-in phone binds ${input == qr ? 'QR' : 'device code'}',
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
          'relay_id': input == qr ? 'relay-12345678' : '',
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

  test('legacy LAN exchange restores session when cloud bind rejects',
      () async {
    final desktop = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final cloud = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => desktop.close(force: true));
    addTearDown(() => cloud.close(force: true));
    final desktopBase = 'http://${desktop.address.address}:${desktop.port}/';
    final cloudBase = 'http://${cloud.address.address}:${cloud.port}/';
    final desktopDone = desktop.first.then((request) async {
      expect(request.uri.path, '/api/mobile/v1/pairing/exchange');
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'success': true,
        'data': {
          'api_base_url': desktopBase,
          'relay_id': 'relay-legacy-1',
          'relay': {'relay_id': 'relay-legacy-1', 'pairing_code': '345678'},
        },
      }));
      await request.response.close();
    });
    final cloudDone = cloud.first.then((request) async {
      expect(request.uri.path, '/api/mobile/v1/relay/mobile/bind-account');
      expect(request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer signed-in-token');
      expect(jsonDecode(await utf8.decoder.bind(request).join()), {
        'relay_id': 'relay-legacy-1',
        'pairing_code': '345678',
      });
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'success': false,
        'message': 'expired code',
      }));
      await request.response.close();
    });
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
        config: MobileApiConfig(baseUrl: cloudBase),
        sessionStore: store,
        httpClient: httpClient,
      ),
    );
    final qr = jsonEncode({
      'v': 2,
      'nonce': 'legacy-nonce-123',
      'api_base_url': desktopBase,
    });

    await expectLater(
      repository.exchangePairingCode(qr),
      throwsA(isA<MobileRepositoryException>()),
    );
    await desktopDone;
    await cloudDone;
    final restored = await store.load();
    expect(restored.accessToken, previous.accessToken);
    expect(restored.fhdHost, previous.fhdHost);
    expect(restored.relayDesktopId, previous.relayDesktopId);
    expect(restored.setupComplete, previous.setupComplete);
  });
}

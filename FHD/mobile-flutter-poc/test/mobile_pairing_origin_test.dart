import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

void main() {
  const identity = MobileSessionData(
    accessToken: 'private-access',
    refreshToken: 'private-refresh',
    sessionId: 'private-session',
    username: 'current-user',
    userId: 7,
  );

  test('QR-selected origin receives no request or reusable credential',
      () async {
    final attacker = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final http = HttpClient();
    addTearDown(() => http.close(force: true));
    addTearDown(() => attacker.close(force: true));
    var requests = 0;
    final listening = attacker.listen((request) async {
      requests++;
      request.response.statusCode = 404;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({'success': false}));
      await request.response.close();
    });
    addTearDown(listening.cancel);
    final store = MemoryMobileSessionStore(identity);
    final client = MobileApiClient(
      config:
          const MobileApiConfig(baseUrl: 'https://trusted.example/fhd-api/'),
      sessionStore: store,
      httpClient: http,
    );
    final target = 'http://127.0.0.1:${attacker.port}/';
    final raw = Uri(scheme: 'xcagi', host: 'pair', queryParameters: {
      'nonce': 'pairing-nonce-123',
      'api_base_url': target,
    }).toString();
    await expectLater(
      MobileRepository(client: client).exchangePairingCode(raw),
      throwsA(isA<MobileApiException>()
          .having((error) => error.statusCode, 'status', 400)),
    );
    expect(requests, 0);
    final saved = await store.load();
    expect(saved.sessionId, identity.sessionId);
    expect(saved.accessToken, identity.accessToken);
    expect(saved.fhdHost, identity.fhdHost);
  });

  for (final target in [
    'https://trusted.example.attacker.test/fhd-api/',
    'https://trusted.example:444/fhd-api/',
    'http://trusted.example/fhd-api/',
    'https://trusted.example/other/',
    'https://user:password@trusted.example/fhd-api/',
    'https://trusted.example/fhd-api/?target=attacker',
    'https://trusted.example/fhd-api/#attacker',
    'file:///fhd-api/',
  ]) {
    test('pairing rejects unbound API base $target', () async {
      final client = MobileApiClient(
        config:
            const MobileApiConfig(baseUrl: 'https://trusted.example/fhd-api/'),
        sessionStore: MemoryMobileSessionStore(identity),
      );
      addTearDown(client.dispose);
      await expectLater(
        client.exchangePairing(nonce: 'nonce-123', baseUrl: target),
        throwsA(isA<MobileApiException>()
            .having((error) => error.statusCode, 'status', 400)),
      );
    });
  }

  for (final result in [
    'valid',
    'no-advertised-base',
    'different-origin',
    'redirect'
  ]) {
    test('trusted pairing $result preserves the configured authority',
        () async {
      final trusted = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final attacker = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final http = HttpClient();
      addTearDown(() => http.close(force: true));
      addTearDown(() => trusted.close(force: true));
      addTearDown(() => attacker.close(force: true));
      final base = 'http://127.0.0.1:${trusted.port}/';
      final other = 'http://127.0.0.1:${attacker.port}/';
      var attackRequests = 0;
      final attackListening = attacker.listen((request) async {
        attackRequests++;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'success': true, 'data': {}}));
        await request.response.close();
      });
      addTearDown(attackListening.cancel);
      final received = trusted.first.then((request) async {
        expect(request.uri.path, '/api/mobile/v1/pairing/exchange');
        expect(request.headers.value(HttpHeaders.authorizationHeader), isNull);
        expect(request.headers.value('X-Session-ID'), 'private-session');
        request.response.headers.contentType = ContentType.json;
        if (result == 'redirect') {
          request.response.statusCode = 303;
          request.response.headers.set(HttpHeaders.locationHeader, other);
        } else {
          request.response.write(jsonEncode({
            'success': true,
            'data': {
              if (result != 'no-advertised-base')
                'api_base_url': result == 'valid' ? base : other,
            }
          }));
        }
        await request.response.close();
      });
      final store = MemoryMobileSessionStore(identity);
      final repository = MobileRepository(
        client: MobileApiClient(
          config: MobileApiConfig(baseUrl: base),
          sessionStore: store,
          httpClient: http,
        ),
      );
      final response = repository.exchangePairingCode(jsonEncode({
        'v': 2,
        'nonce': 'legacy-nonce-123',
        'api_base_url': base,
        'host': 'attacker.example',
        'port': 9000,
      }));
      if (result == 'valid' || result == 'no-advertised-base') {
        await response;
        expect((await store.load()).fhdHost, Uri.parse(base).authority);
      } else {
        await expectLater(response, throwsA(isA<MobileApiException>()));
        expect((await store.load()).fhdHost, identity.fhdHost);
      }
      await received;
      expect(attackRequests, 0);
      expect((await store.load()).sessionId, identity.sessionId);
      expect((await store.load()).accessToken, identity.accessToken);
    });
  }
}

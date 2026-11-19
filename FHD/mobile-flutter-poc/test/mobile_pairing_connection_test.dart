import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

const _identity = MobileSessionData(
  accessToken: 'private-access',
  sessionId: 'private-session',
  username: 'current-user',
  userId: 7,
);

void main() {
  for (final scenario in ['http', 'old-local', 'https']) {
    test('legacy pairing retains the complete trusted $scenario API base',
        () async {
      final trusted = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final old = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final http = HttpClient();
      final recorder = _HttpsRecorder(http, trusted.port);
      addTearDown(() => http.close(force: true));
      addTearDown(() => trusted.close(force: true));
      addTearDown(() => old.close(force: true));
      final base = scenario == 'https'
          ? 'https://trusted.example:8443/fhd-api/'
          : 'http://127.0.0.1:${trusted.port}/fhd-api/';
      final oldBase = 'http://127.0.0.1:${old.port}/old-api/';
      var oldRequests = 0;
      final stale = old.listen((request) async {
        oldRequests++;
        request.response.statusCode = 500;
        await request.response.close();
      });
      addTearDown(stale.cancel);
      final paths = <String>[];
      final sessions = <String, String?>{};
      final serving = trusted.listen((request) async {
        final path = request.uri.path;
        paths.add(path);
        sessions[path] = request.headers.value('X-Session-ID');
        request.response.headers.contentType = ContentType.json;
        request.response.statusCode = path.startsWith('/fhd-api/') ? 200 : 404;
        request.response.write(jsonEncode({
          'success': true,
          'data': path.endsWith('/pairing/exchange')
              ? {
                  'api_base_url': base,
                  if (scenario != 'old-local') 'local_base_url': oldBase,
                }
              : <String, Object?>{},
        }));
        await request.response.close();
      });
      addTearDown(serving.cancel);
      final store = MemoryMobileSessionStore(_identity.copyWith(
        localBaseUrl: scenario == 'old-local' ? oldBase : '',
      ));
      final client = MobileApiClient(
        config: MobileApiConfig(baseUrl: base),
        sessionStore: store,
        httpClient: scenario == 'https' ? recorder : http,
      );
      await MobileRepository(client: client).exchangePairingCode(jsonEncode({
        'v': 2,
        'nonce': 'legacy-nonce-123',
        'api_base_url': scenario == 'http' ? '$base//' : base,
        'local_base_url': oldBase,
      }));
      expect((await store.load()).localBaseUrl, base);
      expect(await client.resolveSessionBaseUrl(), base);
      await client.getJson('/api/mobile/v1/private-check');
      expect(paths, [
        '/fhd-api/api/mobile/v1/pairing/exchange',
        '/fhd-api/api/health',
        '/fhd-api/api/mobile/v1/private-check',
      ]);
      expect(sessions['/fhd-api/api/health'], isNull);
      expect(
          sessions['/fhd-api/api/mobile/v1/private-check'], 'private-session');
      expect(oldRequests, 0);
      expect((await store.load()).serverMode, 'lan');
      expect((await store.load()).accessToken, _identity.accessToken);
      if (scenario == 'https') {
        expect(recorder.uris.map((uri) => uri.scheme), everyElement('https'));
        expect(recorder.uris.map((uri) => uri.authority),
            everyElement('trusted.example:8443'));
      }
    });
  }

  for (final redirect in [false, true]) {
    test('LAN health preserves the complete base (redirect=$redirect)',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final http = HttpClient();
      addTearDown(() => http.close(force: true));
      addTearDown(() => server.close(force: true));
      final base = 'http://127.0.0.1:${server.port}/fhd-api/';
      final paths = <String>[];
      final serving = server.listen((request) async {
        paths.add(request.uri.path);
        request.response.statusCode = 200;
        if (redirect && request.uri.path == '/fhd-api/api/health') {
          request.response.statusCode = 302;
          request.response.headers
              .set(HttpHeaders.locationHeader, '/other-service/api/health');
        }
        await request.response.close();
      });
      addTearDown(serving.cancel);
      final store = MemoryMobileSessionStore(_identity.copyWith(
        fhdHost: '127.0.0.1:${server.port}',
        localBaseUrl: base,
        serverMode: 'lan',
      ));
      final client = MobileApiClient(
        config: MobileApiConfig(baseUrl: base),
        sessionStore: store,
        httpClient: http,
      );
      expect(await client.preferCloudIfLanUnreachable(), redirect);
      expect(paths, ['/fhd-api/api/health']);
      expect((await store.load()).serverMode, redirect ? 'cloud' : 'lan');
      if (!redirect) expect(await client.resolveSessionBaseUrl(), base);
    });
  }
}

// Capture the requested HTTPS URI before routing to a real loopback HTTP server.
// This verifies scheme persistence; it does not substitute for TLS acceptance.
class _HttpsRecorder implements HttpClient {
  _HttpsRecorder(this.delegate, this.port);
  final HttpClient delegate;
  final int port;
  final uris = <Uri>[];

  @override
  Future<HttpClientRequest> openUrl(String method, Uri uri) {
    uris.add(uri);
    return delegate.openUrl(
        method, uri.replace(scheme: 'http', host: '127.0.0.1', port: port));
  }

  @override
  void close({bool force = false}) => delegate.close(force: force);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

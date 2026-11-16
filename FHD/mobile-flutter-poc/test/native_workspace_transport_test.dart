import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';

void main() {
  late HttpServer server;
  late HttpClient http;
  late MobileApiClient api;
  late String base;
  setUp(() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    base = 'http://127.0.0.1:${server.port}/';
    http = HttpClient();
    api = MobileApiClient(
        config: MobileApiConfig(baseUrl: base),
        httpClient: http,
        sessionStore: MemoryMobileSessionStore(
            MobileSessionData.empty.copyWith(userId: 1, accessToken: 'owned')));
  });
  tearDown(() async {
    api.dispose();
    http.close(force: true);
    await server.close(force: true);
  });
  test('native writes use original body and credentials without changing base',
      () async {
    server.listen((request) async {
      expect(request.uri.path, '/api/mod/owned/products/update');
      expect(request.headers.value('authorization'), 'Bearer owned');
      expect(
          jsonDecode(await utf8.decodeStream(request)), {'id': 1, 'price': 12});
      request.response.headers.contentType = ContentType.json;
      request.response.write('{"success":true}');
      await request.response.close();
    });
    final response = await api.workspaceRequest('api/mod/owned/products/update',
        method: 'POST',
        body: {'id': 1, 'price': 12},
        expectedGeneration: api.authGeneration,
        expectedBase: base);
    expect(response['success'], true);
  });
  test('changed account and foreign URLs fail before sending a write',
      () async {
    final generation = api.authGeneration;
    await api.clearActiveAuth();
    expect(
        () => api.workspaceRequest('api/products/update',
            method: 'POST',
            body: {'id': 1},
            expectedGeneration: generation,
            expectedBase: base),
        throwsStateError);
    for (final path in [
      'https://attacker/api',
      '//attacker/api',
      'api/../../outside'
    ]) {
      expect(
          () => api.workspaceRequest(path,
              expectedGeneration: api.authGeneration, expectedBase: base),
          throwsArgumentError);
    }
  });
  test('late response after backend change is discarded', () async {
    final arrived = Completer<void>(), release = Completer<void>();
    server.listen((request) async {
      await request.drain<void>();
      arrived.complete();
      await release.future;
      request.response.headers.contentType = ContentType.json;
      request.response.write('{"success":true,"data":"old-account"}');
      await request.response.close();
    });
    final pending = api.workspaceRequest('api/products/list',
        expectedGeneration: api.authGeneration, expectedBase: base);
    final check = expectLater(
        pending,
        throwsA(isA<MobileApiException>()
            .having((e) => e.statusCode, 'status', 409)));
    await arrived.future;
    await api.saveSession((await api.loadSession())
        .copyWith(serverMode: 'lan', localBaseUrl: 'http://127.0.0.1:1/'));
    release.complete();
    await check;
  });
  test('export rejects redirects and login HTML instead of sharing them',
      () async {
    var redirects = true;
    server.listen((request) async {
      await request.drain<void>();
      if (redirects) {
        request.response.statusCode = 302;
        request.response.headers
            .set('location', 'https://attacker.invalid/file');
      } else {
        request.response.headers.contentType = ContentType.html;
        request.response.write('<html>login</html>');
      }
      await request.response.close();
    });
    Future<List<int>> download() =>
        api.workspaceFileRequest('api/products/export.xlsx',
            expectedGeneration: api.authGeneration, expectedBase: base);
    await expectLater(
        download(),
        throwsA(isA<MobileApiException>()
            .having((e) => e.statusCode, 'status', 302)));
    redirects = false;
    await expectLater(download(), throwsStateError);
  });
}

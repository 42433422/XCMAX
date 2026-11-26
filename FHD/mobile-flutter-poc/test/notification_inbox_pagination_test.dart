import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

Future<void> _reply(HttpRequest request, List<int> ids,
    {int? next, bool success = true}) async {
  request.response.headers.contentType = ContentType.json;
  request.response.write(jsonEncode({
    'success': success,
    'message': success ? '' : 'page rejected',
    'data': {
      'notifications': [
        for (final id in ids)
          {'id': id, 'title': 'notification $id', 'is_read': id.isEven},
      ],
      'next_before_id': next,
    },
  }));
  await request.response.close();
}

void main() {
  late HttpServer server;
  late HttpClient http;
  late MobileApiClient api;
  late MobileRepository repository;

  setUp(() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    http = HttpClient();
    api = MobileApiClient(
      config: MobileApiConfig(baseUrl: 'http://127.0.0.1:${server.port}/'),
      httpClient: http,
      sessionStore: MemoryMobileSessionStore(
          MobileSessionData.empty.copyWith(userId: 1, accessToken: 'owned')),
    );
    repository = MobileRepository(client: api);
  });
  tearDown(() async {
    await repository.dispose();
    api.dispose();
    http.close(force: true);
    await server.close(force: true);
  });

  test('inbox follows the server cursor beyond the first 50 notifications',
      () async {
    final cursors = <String?>[];
    server.listen((request) async {
      expect(request.uri.path, '/api/mobile/v1/notifications/inbox');
      expect(request.headers.value('authorization'), 'Bearer owned');
      expect(request.uri.queryParameters['limit'], '50');
      final cursor = request.uri.queryParameters['before_id'];
      cursors.add(cursor);
      if (cursor == null) {
        await _reply(request, List.generate(50, (index) => 51 - index),
            next: 2);
      } else {
        expect(cursor, '2');
        await _reply(request, [1]);
      }
    });
    final items = await repository.loadNotificationInbox();
    expect(cursors, [null, '2']);
    expect(
        items.map((item) => item.id), List.generate(51, (index) => 51 - index));
    expect(items.last.title, 'notification 1');
    expect(items.first.isRead, false);
    expect(items[1].isRead, true);
  });

  test('failed later page does not return a truncated successful inbox',
      () async {
    var requests = 0;
    server.listen((request) async {
      requests++;
      await _reply(request, requests == 1 ? [3, 2] : [],
          next: requests == 1 ? 2 : null, success: requests == 1);
    });
    await expectLater(
        repository.loadNotificationInbox(),
        throwsA(isA<MobileRepositoryException>()
            .having((error) => error.message, 'message', 'page rejected')));
    expect(requests, 2);
  });

  for (final invalidCursor in [0, 2, 3]) {
    test('non-progressing cursor $invalidCursor fails without looping',
        () async {
      var requests = 0;
      server.listen((request) async {
        requests++;
        await _reply(request, requests == 1 ? [3, 2] : [1],
            next: requests == 1 ? 2 : invalidCursor);
      });
      await expectLater(
          repository.loadNotificationInbox(),
          throwsA(isA<MobileRepositoryException>()
              .having((error) => error.message, 'message', contains('分页游标'))));
      expect(requests, 2);
    });
  }

  test('account revocation while a later page waits discards the entire inbox',
      () async {
    final arrived = Completer<void>(), release = Completer<void>();
    server.listen((request) async {
      if (request.uri.queryParameters['before_id'] == null) {
        await _reply(request, [3, 2], next: 2);
      } else {
        arrived.complete();
        await release.future;
        await _reply(request, [1]);
      }
    });
    final pending = repository.loadNotificationInbox();
    final rejected = expectLater(
        pending,
        throwsA(isA<MobileApiException>()
            .having((error) => error.statusCode, 'status', 409)));
    await arrived.future.timeout(const Duration(seconds: 3));
    await api.clearActiveAuth();
    release.complete();
    await rejected;
  });
}

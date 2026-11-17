import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/im/im_websocket_client.dart';

class AuthApi extends MobileApiClient {
  int cleared = 0;
  int disposed = 0;
  @override
  Future<void> clearActiveAuth() async {
    cleared++;
  }

  @override
  void dispose() {
    disposed++;
    super.dispose();
  }
}

class AuthSocket extends ImWebSocketClient {
  final failures = StreamController<void>.broadcast();
  int disposed = 0;
  @override
  Stream<void> get authFailures => failures.stream;
  @override
  void dispose() {
    disposed++;
    failures.close();
    super.dispose();
  }
}

class BorrowedHttpClient implements HttpClient {
  int closes = 0;
  @override
  void close({bool force = false}) {
    closes++;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('disposal detaches auth listener and preserves borrowed resources',
      () async {
    final api = AuthApi();
    final socket = AuthSocket();
    final repository = MobileRepository(client: api, imWebSocket: socket);
    socket.failures.add(null);
    await Future<void>.delayed(Duration.zero);
    expect(api.cleared, 1);
    await repository.dispose();
    await repository.dispose();
    socket.failures.add(null);
    await Future<void>.delayed(Duration.zero);
    expect(api.cleared, 1);
    expect(api.disposed, 0);
    expect(socket.disposed, 0);
    api.dispose();
    socket.dispose();
  });

  test('owned repository closes websocket streams and API changes', () async {
    final repository = MobileRepository();
    final socketDone = Completer<void>();
    final apiDone = Completer<void>();
    repository.imWebSocketStates.listen((_) {}, onDone: socketDone.complete);
    repository.client.sessionChanges.listen((_) {}, onDone: apiDone.complete);
    await Future<void>.delayed(Duration.zero);
    await repository.dispose();
    await Future.wait([socketDone.future, apiDone.future]);
  });

  test('API disposal leaves injected HTTP client open', () {
    final http = BorrowedHttpClient();
    final api = MobileApiClient(httpClient: http);
    api.dispose();
    api.dispose();
    expect(http.closes, 0);
    http.close();
  });
}

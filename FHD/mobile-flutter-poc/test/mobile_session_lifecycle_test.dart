import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';

const _accountA = MobileSessionData(
  accessToken: 'access-A',
  refreshToken: 'refresh-A',
  sessionId: 'session-A',
  userId: 1,
  username: 'account-A',
);

Future<void> _reply(HttpRequest request, int status,
    [Map<String, Object?> data = const {}]) async {
  request.response.statusCode = status;
  request.response.headers.contentType = ContentType.json;
  request.response.write(jsonEncode({'success': status == 200, 'data': data}));
  await request.response.close();
}

Future<void> _login(MobileApiClient api, String account) async {
  await api.persistLoginSession({
    'access_token': 'access-$account',
    'refresh_token': 'refresh-$account',
    'session_id': 'session-$account',
    'user': {'id': account == 'A' ? 1 : 2, 'username': 'account-$account'},
  }, fallbackUsername: 'account-$account', fallbackAccountKind: 'enterprise');
}

Future<({MobileApiClient api, HttpServer server, MobileSessionStore store})>
    _fixture({MobileSessionStore? store}) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  final http = HttpClient();
  addTearDown(() => http.close(force: true));
  addTearDown(() => server.close(force: true));
  final sessions = store ?? MemoryMobileSessionStore(_accountA);
  final api = MobileApiClient(
    config: MobileApiConfig(baseUrl: 'http://127.0.0.1:${server.port}/'),
    httpClient: http,
    sessionStore: sessions,
  );
  return (api: api, server: server, store: sessions);
}

void main() {
  final mutations = <String, Future<void> Function(MobileApiClient)>{
    'profile': (api) =>
        api.saveLocalProfile(displayName: 'old', avatarSource: 'old'),
    'settings': (api) => api.saveLocalSettings(themeMode: 'dark'),
    'legal': (api) => api.saveLegalAcceptedVersion('old'),
    'setup': (api) => api.saveSetupComplete(true),
    'push': (api) => api.saveFcmToken('old'),
    'LAN': (api) => api.saveAutoLanProbe(true),
    'sync': (api) => api.saveSyncState(syncCursor: 42),
    'wallet': (api) => api.saveWalletBalanceJson('{"old":true}'),
    'mods': (api) => api.cacheModInfos([
          {'id': 'old'}
        ]),
    'relay': (api) => api.persistRelayBindingMeta('old', {}),
  };
  for (final entry in mutations.entries) {
    test('late ${entry.key} read cannot restore logged out credentials',
        () async {
      final store = _SlowReadStore();
      final api = MobileApiClient(sessionStore: store);
      store.delayNextRead = true;
      final mutation = entry.value(api);
      await store.readStarted.future;
      final logout = api.clearActiveAuth();
      store.releaseRead.complete();
      await logout;
      await mutation;
      expect((await store.load()).hasAuth, isFalse);
      expect((await api.loadSession()).hasAuth, isFalse);
    });
  }

  for (final transition in ['logout', 'switch', 'same-account-login']) {
    test('old session snapshot cannot undo $transition', () async {
      final api =
          MobileApiClient(sessionStore: MemoryMobileSessionStore(_accountA));
      final generation = api.authGeneration;
      final previous = await api.loadSession();
      if (transition == 'logout') {
        await api.clearActiveAuth();
      } else {
        await _login(api, transition == 'switch' ? 'B' : 'A');
      }
      await api.saveSession(previous.copyWith(themeMode: 'old'),
          authGeneration: generation);
      final saved = await api.sessionStore.load();
      expect(saved.themeMode, isNot('old'));
      expect(
          saved.accessToken,
          transition == 'logout'
              ? ''
              : transition == 'switch'
                  ? 'access-B'
                  : 'access-A');
    });
  }

  test('an unowned stale public snapshot cannot replace another account',
      () async {
    final api =
        MobileApiClient(sessionStore: MemoryMobileSessionStore(_accountA));
    final previous = await api.loadSession();
    await _login(api, 'B');
    await api.saveSession(previous);
    expect((await api.sessionStore.load()).accessToken, 'access-B');
  });

  for (final account in ['A', 'B']) {
    test('login $account keeps only the matching account private cache',
        () async {
      final api = MobileApiClient(
          sessionStore: MemoryMobileSessionStore(_accountA.copyWith(
        walletBalanceJson: '{"owner":"A"}',
        cachedModInfos: [
          {'id': 'private-A'}
        ],
        cachedChatMessages: {
          'chat-A': [
            {'body': 'private-A'}
          ]
        },
        relayDesktopId: 'relay-A',
        localAvatarSource: 'avatar-A',
        themeMode: 'dark',
      )));
      await _login(api, account);
      final saved = await api.loadSession();
      expect(saved.walletBalanceJson.isNotEmpty, account == 'A');
      expect(saved.cachedChatMessages.isNotEmpty, account == 'A');
      expect(saved.cachedModInfos.isNotEmpty, account == 'A');
      expect(saved.relayDesktopId.isNotEmpty, account == 'A');
      expect(saved.localAvatarSource.isNotEmpty, account == 'A');
      expect(saved.themeMode, 'dark');
    });
  }

  test('late forced reload cannot replace a refreshed memory snapshot',
      () async {
    final store = _SlowReadStore();
    final fixture = await _fixture(store: store);
    await fixture.api.loadSession();
    store.delayNextRead = true;
    final reload = fixture.api.loadSession(forceReload: true);
    await store.readStarted.future;
    final subscription = fixture.server.listen((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        await _reply(request, 200, {'access_token': 'refreshed-A'});
      } else {
        await _reply(
            request,
            request.headers.value(HttpHeaders.authorizationHeader) ==
                    'Bearer refreshed-A'
                ? 200
                : 401);
      }
    });
    addTearDown(subscription.cancel);
    await fixture.api.getJson('protected');
    store.releaseRead.complete();
    expect((await reload).accessToken, 'refreshed-A');
    expect((await fixture.api.loadSession()).accessToken, 'refreshed-A');
  });

  for (final phone in [false, true]) {
    for (final transition in ['logout', 'switch']) {
      test('late ${phone ? "phone" : "password"} login cannot undo $transition',
          () async {
        final fixture = await _fixture();
        final repository = MobileRepository(client: fixture.api);
        final arrived = Completer<void>();
        final release = Completer<void>();
        final subscription = fixture.server.listen((request) async {
          arrived.complete();
          await release.future;
          await _reply(request, 200, {
            'access_token': 'late-A',
            'refresh_token': 'late-refresh-A',
            'user': {'id': 1, 'username': 'account-A'},
          });
        });
        addTearDown(subscription.cancel);
        final result = expectLater(
            phone
                ? repository.loginWithPhoneCode(
                    phone: '13800000000', code: '123456')
                : repository.login(
                    username: 'account-A',
                    password: 'synthetic',
                    adminMode: false),
            throwsA(isA<MobileApiException>()));
        await arrived.future;
        if (transition == 'logout') {
          await fixture.api.clearActiveAuth();
        } else {
          await _login(fixture.api, 'B');
        }
        release.complete();
        await result;
        expect((await fixture.store.load()).accessToken,
            transition == 'logout' ? '' : 'access-B');
      });
    }
  }

  test('a newer login attempt completes while the older response is pending',
      () async {
    final fixture = await _fixture();
    final repository = MobileRepository(client: fixture.api);
    final arrived = Completer<void>();
    final release = Completer<void>();
    final subscription = fixture.server.listen((request) async {
      final payload = jsonDecode(await utf8.decodeStream(request)) as Map;
      if (payload['username'] == 'account-A') {
        arrived.complete();
        await release.future;
      }
      final account = payload['username'] == 'account-A' ? 'A' : 'B';
      await _reply(request, 200, {
        'access_token': 'access-$account',
        'user': {'id': account == 'A' ? 1 : 2, 'username': 'account-$account'}
      });
    });
    addTearDown(subscription.cancel);
    final old = expectLater(
        repository.login(
            username: 'account-A', password: 'synthetic', adminMode: false),
        throwsA(isA<MobileApiException>()));
    await arrived.future;
    await repository.login(
        username: 'account-B', password: 'synthetic', adminMode: false);
    release.complete();
    await old;
    expect((await fixture.store.load()).accessToken, 'access-B');
  });

  test('pairing auth replacement clears credentials omitted by the new account',
      () async {
    final store = MemoryMobileSessionStore(_accountA.copyWith(
        marketAccessToken: 'market-A', marketRefreshToken: 'market-refresh-A'));
    final api = MobileApiClient(sessionStore: store);
    await api.persistPairingSession({'access_token': 'access-B'});
    final saved = await store.load();
    expect(saved.accessToken, 'access-B');
    expect(saved.refreshToken, isEmpty);
    expect(saved.sessionId, isEmpty);
    expect(saved.marketAccessToken, isEmpty);
    expect(saved.marketRefreshToken, isEmpty);
    expect(saved.userId, 0);
    expect(saved.username, isNot('account-A'));
  });

  test('a protected response issued during login cannot cross its commit',
      () async {
    final fixture = await _fixture();
    final repository = MobileRepository(client: fixture.api);
    final loginArrived = Completer<void>(), loginRelease = Completer<void>();
    final readArrived = Completer<void>(), readRelease = Completer<void>();
    final subscription = fixture.server.listen((request) async {
      if (request.uri.path.endsWith('/auth/login')) {
        loginArrived.complete();
        await loginRelease.future;
        await _reply(request, 200, {
          'access_token': 'access-B',
          'user': {'id': 2, 'username': 'account-B'}
        });
      } else {
        expect(request.headers.value(HttpHeaders.authorizationHeader),
            'Bearer access-A');
        readArrived.complete();
        await readRelease.future;
        await _reply(request, 200, {'owner': 'A'});
      }
    });
    addTearDown(subscription.cancel);
    final login = repository.login(
        username: 'account-B', password: 'synthetic', adminMode: false);
    await loginArrived.future;
    final oldRead = expectLater(
        fixture.api.getJson('protected'), throwsA(isA<MobileApiException>()));
    await readArrived.future;
    loginRelease.complete();
    await login;
    readRelease.complete();
    await oldRead;
    expect((await fixture.store.load()).accessToken, 'access-B');
  });

  for (final snapshot in [false, true]) {
    test(
        'queued ${snapshot ? "snapshot" : "settings"} cannot undo a token refresh',
        () async {
      final store = _SlowRefreshStore();
      final fixture = await _fixture(store: store);
      final previous = await fixture.api.loadSession();
      final subscription = fixture.server.listen((request) async {
        if (request.uri.path.endsWith('/auth/refresh')) {
          await _reply(request, 200,
              {'access_token': 'refreshed-A', 'refresh_token': 'rotated-A'});
        } else {
          await _reply(
              request,
              request.headers.value(HttpHeaders.authorizationHeader) ==
                      'Bearer refreshed-A'
                  ? 200
                  : 401);
        }
      });
      addTearDown(subscription.cancel);
      final refreshing = fixture.api.getJson('protected');
      await store.writeStarted.future;
      final saving = snapshot
          ? fixture.api.saveSession(previous.copyWith(themeMode: 'stale'))
          : fixture.api.saveLocalSettings(themeMode: 'dark');
      store.releaseWrite.complete();
      await Future.wait([refreshing, saving]);
      final saved = await store.load();
      expect(saved.accessToken, 'refreshed-A');
      expect(saved.refreshToken, 'rotated-A');
      expect(saved.themeMode, snapshot ? '' : 'dark');
    });
  }

  for (final outcome in [200, 401]) {
    for (final transition in ['logout', 'switch', 'same-account-login']) {
      test('late refresh $outcome cannot mutate $transition', () async {
        final fixture = await _fixture();
        final arrived = Completer<void>();
        final release = Completer<void>();
        var protectedRequests = 0;
        final subscription = fixture.server.listen((request) async {
          if (request.uri.path.endsWith('/auth/refresh')) {
            arrived.complete();
            await release.future;
            await _reply(request, outcome, {
              'access_token': 'refreshed-A',
              'refresh_token': 'rotated-A',
            });
          } else {
            protectedRequests++;
            await _reply(request, 401);
          }
        });
        addTearDown(subscription.cancel);
        final result = expectLater(fixture.api.getJson('protected'),
            throwsA(isA<MobileApiException>()));
        await arrived.future.timeout(const Duration(seconds: 3));
        if (transition == 'logout') {
          await fixture.api.clearActiveAuth();
        } else {
          await _login(fixture.api, transition == 'switch' ? 'B' : 'A');
        }
        release.complete();
        await result;
        final saved = await fixture.store.load();
        expect(
            saved.accessToken,
            transition == 'logout'
                ? ''
                : transition == 'switch'
                    ? 'access-B'
                    : 'access-A');
        expect(
            saved.refreshToken,
            transition == 'logout'
                ? ''
                : transition == 'switch'
                    ? 'refresh-B'
                    : 'refresh-A');
        expect(
            (await fixture.api.loadSession()).accessToken, saved.accessToken);
        expect(protectedRequests, 1,
            reason: 'Do not replay an old account action.');
      });
    }
  }

  test('late protected 401 does not refresh the new account', () async {
    final fixture = await _fixture();
    final arrived = Completer<void>();
    final release = Completer<void>();
    var refreshes = 0;
    final subscription = fixture.server.listen((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        refreshes++;
      } else {
        arrived.complete();
        await release.future;
      }
      await _reply(request, 401);
    });
    addTearDown(subscription.cancel);
    final result = expectLater(
        fixture.api.getJson('protected'), throwsA(isA<MobileApiException>()));
    await arrived.future;
    await _login(fixture.api, 'B');
    release.complete();
    await result;
    expect(refreshes, 0);
    expect((await fixture.store.load()).accessToken, 'access-B');
  });

  test('new account refresh does not wait for the previous account flight',
      () async {
    final fixture = await _fixture();
    final oldArrived = Completer<void>();
    final oldRelease = Completer<void>();
    var refreshes = 0;
    final subscription = fixture.server.listen((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        refreshes++;
        final payload = jsonDecode(await utf8.decodeStream(request)) as Map;
        if (payload['refresh_token'] == 'refresh-A') {
          oldArrived.complete();
          await oldRelease.future;
          await _reply(request, 200, {'access_token': 'refreshed-A'});
        } else {
          await _reply(request, 200, {'access_token': 'refreshed-B'});
        }
      } else {
        await _reply(
            request,
            request.headers.value(HttpHeaders.authorizationHeader) ==
                    'Bearer refreshed-B'
                ? 200
                : 401);
      }
    });
    addTearDown(subscription.cancel);
    final oldResult = expectLater(
        fixture.api.getJson('protected'), throwsA(isA<MobileApiException>()));
    await oldArrived.future;
    await _login(fixture.api, 'B');
    final next = await fixture.api
        .getJson('protected')
        .timeout(const Duration(seconds: 3));
    expect(next['success'], isTrue);
    expect((await fixture.store.load()).accessToken, 'refreshed-B');
    oldRelease.complete();
    await oldResult;
    expect(refreshes, 2);
    expect((await fixture.store.load()).accessToken, 'refreshed-B');
  });

  test('normal simultaneous 401 requests share refresh and retry successfully',
      () async {
    final fixture = await _fixture();
    var refreshes = 0;
    final subscription = fixture.server.listen((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        refreshes++;
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await _reply(request, 200, {
          'access_token': 'refreshed-A',
          'refresh_token': 'rotated-A',
        });
      } else {
        await _reply(
            request,
            request.headers.value(HttpHeaders.authorizationHeader) ==
                    'Bearer refreshed-A'
                ? 200
                : 401);
      }
    });
    addTearDown(subscription.cancel);
    final results = await Future.wait([
      fixture.api.getJson('protected'),
      fixture.api.getJson('protected'),
    ]);
    expect(results.every((value) => value['success'] == true), isTrue);
    expect(refreshes, 1);
    expect((await fixture.store.load()).refreshToken, 'rotated-A');
  });

  test(
      'logout is the last durable write when refresh persistence already began',
      () async {
    final store = _SlowRefreshStore();
    final fixture = await _fixture(store: store);
    final subscription = fixture.server.listen((request) async {
      await _reply(
          request,
          request.uri.path.endsWith('/auth/refresh') ? 200 : 401,
          {'access_token': 'refreshed-A'});
    });
    addTearDown(subscription.cancel);
    final result = expectLater(
        fixture.api.getJson('protected'), throwsA(isA<MobileApiException>()));
    await store.writeStarted.future;
    final logout = fixture.api.clearActiveAuth();
    final postLogout = fixture.api.loadSession();
    store.releaseWrite.complete();
    await logout;
    await result;
    expect((await postLogout).hasAuth, isFalse);
    expect((await store.load()).hasAuth, isFalse);
    expect((await fixture.api.loadSession()).hasAuth, isFalse);
  });

  test('login without refresh tokens never inherits the previous credentials',
      () async {
    final fixture = await _fixture();
    await fixture.api.persistLoginSession({
      'access_token': 'access-B',
      'user': {'id': 2, 'username': 'account-B'},
    }, fallbackUsername: 'account-B', fallbackAccountKind: 'enterprise');
    final saved = await fixture.store.load();
    expect(saved.accessToken, 'access-B');
    expect(saved.refreshToken, isEmpty);
    expect(saved.sessionId, isEmpty);
    expect(saved.marketAccessToken, isEmpty);
    expect(saved.marketRefreshToken, isEmpty);
  });

  test('LAN probe has a total deadline even while response bytes keep arriving',
      () async {
    final fixture = await _fixture();
    Timer? trickle;
    addTearDown(() => trickle?.cancel());
    final subscription = fixture.server.listen((request) async {
      request.response.statusCode = 200;
      request.response.write(' ');
      await request.response.flush();
      trickle = Timer.periodic(const Duration(milliseconds: 50), (timer) {
        try {
          request.response.write(' ');
          unawaited(request.response.flush().catchError((Object _) {}));
        } catch (_) {
          timer.cancel();
        }
      });
    });
    addTearDown(subscription.cancel);
    final elapsed = Stopwatch()..start();
    final ok = await fixture.api
        .probeLanHealth('127.0.0.1:${fixture.server.port}')
        .timeout(const Duration(seconds: 2));
    expect(ok, isFalse);
    expect(elapsed.elapsedMilliseconds, lessThan(1900));
  });

  for (final status in [200, 503]) {
    test('LAN probe returns the completed response status $status', () async {
      final fixture = await _fixture();
      final subscription =
          fixture.server.listen((request) => _reply(request, status));
      addTearDown(subscription.cancel);
      expect(
          await fixture.api.probeLanHealth('127.0.0.1:${fixture.server.port}'),
          status == 200);
    });
  }
}

class _SlowRefreshStore extends MemoryMobileSessionStore {
  _SlowRefreshStore() : super(_accountA);
  final writeStarted = Completer<void>();
  final releaseWrite = Completer<void>();

  @override
  Future<void> save(MobileSessionData data) async {
    if (data.accessToken == 'refreshed-A' && !writeStarted.isCompleted) {
      writeStarted.complete();
      await releaseWrite.future;
    }
    await super.save(data);
  }
}

class _SlowReadStore extends MemoryMobileSessionStore {
  _SlowReadStore() : super(_accountA);
  var delayNextRead = false;
  final readStarted = Completer<void>();
  final releaseRead = Completer<void>();

  @override
  Future<MobileSessionData> load() async {
    final snapshot = await super.load();
    if (delayNextRead) {
      delayNextRead = false;
      readStarted.complete();
      await releaseRead.future;
    }
    return snapshot;
  }
}

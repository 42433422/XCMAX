import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/policy/android_runtime_policy.dart';
import 'package:xcagi_flutter_poc/src/platform/credential_cipher.dart';

void main() {
  setUp(AndroidProductSkuConfig.resetRemoteSku);

  test('FileMobileSessionStore persists Android-equivalent auth fields',
      () async {
    final file = File(
      '${Directory.systemTemp.path}/xcagi_session_store_test.json',
    );
    if (file.existsSync()) file.deleteSync();
    addTearDown(() {
      if (file.existsSync()) file.deleteSync();
    });

    final store = FileMobileSessionStore(filePath: file.path);
    await store.save(
      const MobileSessionData(
        accessToken: 'fhd-access',
        refreshToken: 'fhd-refresh',
        sessionId: 'session-1',
        username: 'admin',
        accountKind: 'admin',
        userId: 1,
        marketAccessToken: 'market-access',
        marketRefreshToken: 'market-refresh',
        localAvatarSource: '/data/user/0/app/files/avatar.jpg',
        fhdHost: '192.168.31.8:5112',
        serverMode: 'lan',
        relayDesktopId: 'relay-1',
        relayBaseUrl: 'https://xiu-ci.com/fhd-api',
        localBaseUrl: 'http://192.168.31.8:5112/fhd-api',
        relaySessionToken: 'relay-session',
        relayAccountId: 'account-1',
        relayTenantId: 'tenant-1',
        relayPairedAt: '2026-07-01T00:00:00Z',
        fcmToken: 'fcm-1',
        autoLanProbe: true,
        syncCursor: 42,
        lastSyncAt: '2026-07-01T01:00:00Z',
        autoSync: false,
        setupComplete: true,
        legalAcceptedVersion: 'legal-2026',
        themeMode: 'dark',
        biometricEnabled: true,
        savedUsername: 'remembered',
        savedPassword: 'encrypted-or-local-secret',
        rememberPassword: true,
        autoLogin: true,
        walletBalanceJson: '{"balance":12.5}',
        inflightRelayTasks: {'pinned:codex': 'task-1'},
        cachedChatMessages: {
          'pinned:codex': [
            {
              'id': 'cache-1',
              'conversation_id': 'pinned:codex',
              'role': 'assistant',
              'body': '已完成',
            },
          ],
        },
        cachedModInfos: [
          {
            'id': 'avatar-mod',
            'name': '头像生成',
            'workflow_employees': [
              {
                'id': 'avatar-generation-employee',
                'label': '头像生成员工',
              },
            ],
          },
        ],
      ),
    );

    final loaded = await store.load();
    expect(loaded.accessToken, 'fhd-access');
    expect(loaded.refreshToken, 'fhd-refresh');
    expect(loaded.sessionId, 'session-1');
    expect(loaded.username, 'admin');
    expect(loaded.accountKind, 'admin');
    expect(loaded.userId, 1);
    expect(loaded.marketAccessToken, 'market-access');
    expect(loaded.marketRefreshToken, 'market-refresh');
    expect(loaded.localAvatarSource, '/data/user/0/app/files/avatar.jpg');
    expect(loaded.fhdHost, '192.168.31.8:5112');
    expect(loaded.serverMode, 'lan');
    expect(loaded.relayDesktopId, 'relay-1');
    expect(loaded.relayBaseUrl, 'https://xiu-ci.com/fhd-api');
    expect(loaded.localBaseUrl, 'http://192.168.31.8:5112/fhd-api');
    expect(loaded.relaySessionToken, 'relay-session');
    expect(loaded.relayAccountId, 'account-1');
    expect(loaded.relayTenantId, 'tenant-1');
    expect(loaded.relayPairedAt, '2026-07-01T00:00:00Z');
    expect(loaded.fcmToken, 'fcm-1');
    expect(loaded.autoLanProbe, isTrue);
    expect(loaded.syncCursor, 42);
    expect(loaded.lastSyncAt, '2026-07-01T01:00:00Z');
    expect(loaded.autoSync, isFalse);
    expect(loaded.setupComplete, isTrue);
    expect(loaded.legalAcceptedVersion, 'legal-2026');
    expect(loaded.themeMode, 'dark');
    expect(loaded.biometricEnabled, isTrue);
    expect(loaded.savedUsername, 'remembered');
    expect(loaded.savedPassword, 'encrypted-or-local-secret');
    expect(loaded.rememberPassword, isTrue);
    expect(loaded.autoLogin, isTrue);
    expect(loaded.walletBalanceJson, '{"balance":12.5}');
    expect(loaded.androidServerModeLabel, '服务器中继 · 电脑执行端');
    expect(loaded.inflightRelayTasks['pinned:codex'], 'task-1');
    expect(loaded.cachedChatMessages['pinned:codex']?.single['body'], '已完成');
    expect(loaded.cachedModInfos.single['id'], 'avatar-mod');
    expect(
      (loaded.cachedModInfos.single['workflow_employees'] as List).single['id'],
      'avatar-generation-employee',
    );
  });

  test('MobileSessionData mirrors Android server mode label priority', () {
    expect(MobileSessionData.empty.androidServerModeLabel, '远程同步可用');
    expect(
      const MobileSessionData(serverMode: 'lan').androidServerModeLabel,
      '本地连通待启',
    );
    expect(
      const MobileSessionData(fhdHost: '10.0.0.2:5112').androidServerModeLabel,
      'Agent 控制 · 10.0.0.2:5112',
    );
    expect(
      const MobileSessionData(
        fhdHost: '10.0.0.2:5112',
        relayDesktopId: 'relay-1',
      ).androidServerModeLabel,
      '服务器中继 · 电脑执行端',
    );
  });

  test('MobileApiClient saves login response into session store', () async {
    final store = MemoryMobileSessionStore();
    final client = MobileApiClient(sessionStore: store);

    await client.persistLoginSession(
      const {
        'access_token': 'access-from-login',
        'refresh_token': 'refresh-from-login',
        'session_id': 'session-from-login',
        'account_kind': 'admin',
        'market_access_token': 'market-from-login',
        'market_refresh_token': 'market-refresh-from-login',
        'user': {
          'id': 1,
          'username': 'admin',
          'display_name': 'Administrator',
        },
      },
      fallbackUsername: 'fallback',
      fallbackAccountKind: 'enterprise',
    );

    final saved = await store.load();
    expect(saved.accessToken, 'access-from-login');
    expect(saved.refreshToken, 'refresh-from-login');
    expect(saved.sessionId, 'session-from-login');
    expect(saved.username, 'admin');
    expect(saved.accountKind, 'admin');
    expect(saved.userId, 1);
    expect(saved.marketAccessToken, 'market-from-login');
    expect(saved.marketRefreshToken, 'market-refresh-from-login');
    expect(saved.setupComplete, isFalse);
    expect(saved.serverMode, 'cloud');
  });

  test('MobileApiClient login server mode follows Android AuthRoutingPolicy',
      () async {
    Future<String> persistWith({
      required String remoteSku,
      required String previousMode,
    }) async {
      AndroidProductSkuConfig.setRemoteSku(remoteSku);
      final store = MemoryMobileSessionStore(
        MobileSessionData(
          fhdHost: '192.168.31.8:17500',
          serverMode: previousMode,
        ),
      );
      final client = MobileApiClient(sessionStore: store);

      await client.persistLoginSession(
        const {
          'access_token': 'access-from-login',
          'account_kind': 'enterprise',
          'user': {
            'id': 1,
            'username': 'admin',
          },
        },
        fallbackUsername: 'fallback',
        fallbackAccountKind: 'enterprise',
      );

      return (await store.load()).serverMode;
    }

    expect(
      await persistWith(remoteSku: '', previousMode: 'lan'),
      'lan',
      reason: 'Enterprise build with configured host mirrors Android LAN mode.',
    );
    expect(
      await persistWith(remoteSku: '', previousMode: ' CLOUD '),
      'cloud',
      reason: 'Android preserves explicit cloud mode for enterprise login.',
    );
    expect(
      await persistWith(remoteSku: 'personal', previousMode: 'lan'),
      'cloud',
      reason: 'Remote personal SKU must not reuse an old enterprise LAN host.',
    );
  });

  test('MobileApiClient persists Android local auth and settings flags',
      () async {
    final store = MemoryMobileSessionStore();
    final client = MobileApiClient(sessionStore: store);

    await client.saveLoginPreferences(
      username: 'admin',
      password: 'secret',
      rememberPassword: true,
      autoLogin: true,
    );
    await client.saveLocalSettings(
      themeMode: 'dark',
      biometricEnabled: true,
    );
    await client.saveLegalAcceptedVersion('legal-2026');
    await client.saveFcmToken(' fcm-1 ');
    await client.saveAutoLanProbe(true);
    await client.saveSyncState(
      syncCursor: 9,
      lastSyncAt: ' 2026-07-01T02:00:00Z ',
      autoSync: false,
    );
    await client.saveWalletBalanceJson(' {"balance":88} ');

    var saved = await store.load();
    expect(saved.savedUsername, 'admin');
    expect(saved.savedPassword, 'secret');
    expect(saved.rememberPassword, isTrue);
    expect(saved.autoLogin, isTrue);
    expect(saved.themeMode, 'dark');
    expect(saved.biometricEnabled, isTrue);
    expect(saved.legalAcceptedVersion, 'legal-2026');
    expect(saved.fcmToken, 'fcm-1');
    expect(saved.autoLanProbe, isTrue);
    expect(saved.syncCursor, 9);
    expect(saved.lastSyncAt, '2026-07-01T02:00:00Z');
    expect(saved.autoSync, isFalse);
    expect(saved.walletBalanceJson, '{"balance":88}');

    await client.saveLoginPreferences(
      username: 'admin',
      password: 'secret',
      rememberPassword: false,
      autoLogin: false,
    );
    await client.saveLocalSettings(biometricEnabled: false);
    await client.saveAutoLanProbe(false);
    await client.saveSyncState(syncCursor: -1, autoSync: true);
    await client.saveWalletBalanceJson('');

    saved = await store.load();
    expect(saved.savedUsername, '');
    expect(saved.savedPassword, '');
    expect(saved.rememberPassword, isFalse);
    expect(saved.autoLogin, isFalse);
    expect(saved.themeMode, 'dark');
    expect(saved.biometricEnabled, isFalse);
    expect(saved.autoLanProbe, isFalse);
    expect(saved.syncCursor, 0);
    expect(saved.autoSync, isTrue);
    expect(saved.walletBalanceJson, '');
  });

  test(
      'MobileApiClient stores remembered password like Android CredentialCipher',
      () async {
    final store = MemoryMobileSessionStore();
    final client = MobileApiClient(
      sessionStore: store,
      credentialCipher: const _FakeCredentialCipher(),
    );

    await client.saveLoginPreferences(
      username: 'admin',
      password: 'secret',
      rememberPassword: true,
      autoLogin: true,
    );

    var raw = await store.load();
    expect(raw.savedPassword, 'enc:v1:secret');
    expect(raw.savedPassword, isNot('secret'));

    var session = await client.loadSession();
    expect(session.savedPassword, 'secret');
    expect(session.savedUsername, 'admin');
    expect(session.canAutoLoginForAndroid, isTrue);

    await client.saveLocalSettings(themeMode: 'dark');
    raw = await store.load();
    expect(raw.savedPassword, 'enc:v1:secret');
    session = await client.loadSession();
    expect(session.savedPassword, 'secret');
    expect(session.themeMode, 'dark');

    await store.save(
      const MobileSessionData(
        savedUsername: 'legacy-admin',
        savedPassword: 'legacy-secret',
        rememberPassword: true,
        autoLogin: true,
      ),
    );
    session = await client.loadSession();
    expect(session.savedPassword, 'legacy-secret');
    expect(session.canAutoLoginForAndroid, isTrue);
  });

  test('MobileApiClient clearActiveAuth mirrors Android logout semantics',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accessToken: 'access',
        refreshToken: 'refresh',
        sessionId: 'session',
        username: 'admin',
        accountKind: 'admin',
        userId: 7,
        marketAccessToken: 'market',
        marketRefreshToken: 'market-refresh',
        fhdHost: '192.168.31.8:5112',
        serverMode: 'lan',
        relayDesktopId: 'relay-1',
        relayBaseUrl: 'https://xiu-ci.com/fhd-api',
        localBaseUrl: 'http://192.168.31.8:5112/fhd-api',
        relaySessionToken: 'relay-session',
        relayAccountId: 'account-1',
        relayTenantId: 'tenant-1',
        relayPairedAt: '2026-07-01T00:00:00Z',
        setupComplete: true,
        savedUsername: 'remembered',
        savedPassword: 'secret',
        rememberPassword: true,
        autoLogin: true,
        walletBalanceJson: '{"balance":12.5}',
        inflightRelayTasks: {'pinned:codex': 'task-1'},
        cachedChatMessages: {
          'pinned:codex': [
            {'id': 'cache-1', 'body': '清理'},
          ],
        },
        conversationListStates: {
          'pinned:codex': {
            'last_message_preview': '我: 清理',
            'last_message_at': 1782769513391,
          },
        },
      ),
    );
    final client = MobileApiClient(sessionStore: store);

    await client.clearActiveAuth();

    final saved = await store.load();
    expect(saved.accessToken, '');
    expect(saved.refreshToken, '');
    expect(saved.sessionId, '');
    expect(saved.username, '');
    expect(saved.accountKind, '');
    expect(saved.userId, 0);
    expect(saved.marketAccessToken, '');
    expect(saved.marketRefreshToken, '');
    expect(saved.fhdHost, '192.168.31.8:5112');
    expect(saved.serverMode, 'lan');
    expect(saved.relayDesktopId, '');
    expect(saved.relayBaseUrl, '');
    expect(saved.localBaseUrl, '');
    expect(saved.relaySessionToken, '');
    expect(saved.relayAccountId, '');
    expect(saved.relayTenantId, '');
    expect(saved.relayPairedAt, '');
    expect(saved.setupComplete, isFalse);
    expect(saved.savedUsername, 'remembered');
    expect(saved.savedPassword, 'secret');
    expect(saved.rememberPassword, isTrue);
    expect(saved.autoLogin, isFalse);
    expect(saved.walletBalanceJson, '');
    expect(saved.inflightRelayTasks, isEmpty);
    expect(saved.cachedChatMessages, isEmpty);
    expect(saved.conversationListStates, isEmpty);
  });

  test('MobileApiClient persists Android pairing and relay metadata', () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        relayDesktopId: 'old-relay',
        inflightRelayTasks: {'pinned:codex': 'task-1'},
      ),
    );
    final client = MobileApiClient(sessionStore: store);

    await client.persistPairingSession(
      const {
        'api_base_url': 'http://192.168.31.8:5112/fhd-api',
        'access_token': 'access-from-pair',
        'refresh_token': 'refresh-from-pair',
        'session_token': 'session-from-pair',
        'account_kind': 'enterprise',
        'relay_base_url': 'https://xiu-ci.com/fhd-api',
        'local_base_url': 'http://192.168.31.8:5112/fhd-api',
        'account_id': 'account-1',
        'tenant_id': 'tenant-1',
        'paired_at': '2026-07-01T00:00:00Z',
        'user': {'id': 9, 'username': 'mobile-admin'},
      },
      clearRelayDesktop: true,
    );

    var saved = await store.load();
    expect(saved.accessToken, 'access-from-pair');
    expect(saved.sessionId, 'session-from-pair');
    expect(saved.username, 'mobile-admin');
    expect(saved.accountKind, 'enterprise');
    expect(saved.fhdHost, '192.168.31.8:5112');
    expect(saved.serverMode, 'lan');
    expect(saved.relayDesktopId, '');
    expect(saved.inflightRelayTasks, isEmpty);
    expect(saved.androidServerModeLabel, 'Agent 控制 · 192.168.31.8:5112');

    await client.persistRelayBindingMeta('relay-new', const {
      'relay_base_url': 'https://xiu-ci.com/fhd-api',
      'session_token': 'relay-session',
      'desktop': {
        'local_base_url': 'http://192.168.31.8:5112/fhd-api',
        'paired_at': '2026-07-01T00:01:00Z',
      },
    });

    saved = await store.load();
    expect(saved.relayDesktopId, 'relay-new');
    expect(saved.relaySessionToken, 'relay-session');
    expect(saved.relayPairedAt, '2026-07-01T00:01:00Z');
    expect(saved.androidServerModeLabel, '服务器中继 · 电脑执行端');
  });

  test('MobileRepository cachedMe restores Android username and local avatar',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        username: 'admin',
        accountKind: 'admin',
        userId: 1,
        localAvatarSource: '/data/user/0/app/files/avatar.jpg',
      ),
    );
    final repository = MobileRepository(
      client: MobileApiClient(sessionStore: store),
    );

    final me = await repository.cachedMe();

    expect(me.displayName, 'admin');
    expect(me.accountKindLabel, '管理员账号');
    expect(me.avatarSource, '/data/user/0/app/files/avatar.jpg');
  });

  test(
      'MobileRepository deletes one cached chat message like Android ts delete',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        cachedChatMessages: {
          'pinned:codex': [
            {
              'id': 'cache-1',
              'conversation_id': 'pinned:codex',
              'role': 'user',
              'body': '保留',
              'ts': 101,
            },
            {
              'id': 'cache-2',
              'conversation_id': 'pinned:codex',
              'role': 'assistant',
              'body': '删除',
              'ts': 202,
            },
          ],
        },
      ),
    );
    final repository = MobileRepository(
      client: MobileApiClient(sessionStore: store),
    );

    await repository.deleteCachedChatMessage(
      conversationId: 'pinned:codex',
      message: const ChatMessage(
        id: 'cache-2',
        conversationId: 'pinned:codex',
        role: ChatRole.assistant,
        body: '删除',
        timeText: '刚刚',
        cacheTimestampMs: 202,
      ),
    );

    final cached = (await store.load()).cachedChatMessages['pinned:codex'];
    expect(cached, hasLength(1));
    expect(cached?.single['body'], '保留');
  });

  test('MobileRepository ignores cached chat delete without Android ts',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        cachedChatMessages: {
          'pinned:assistant': [
            {
              'id': 'cache-plain-1',
              'conversation_id': 'pinned:assistant',
              'role': 'assistant',
              'body': '不要猜删',
              'ts': 303,
            },
          ],
        },
      ),
    );
    final repository = MobileRepository(
      client: MobileApiClient(sessionStore: store),
    );

    await repository.deleteCachedChatMessage(
      conversationId: 'pinned:assistant',
      message: const ChatMessage(
        id: 'cache-plain-1',
        conversationId: 'pinned:assistant',
        role: ChatRole.assistant,
        body: '不要猜删',
        timeText: '刚刚',
      ),
    );

    final cached = (await store.load()).cachedChatMessages['pinned:assistant'];
    expect(cached, hasLength(1));
    expect(cached?.single['body'], '不要猜删');
  });

  test('MobileRepository loads cached normal chat like Android loadCachedChat',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        cachedChatMessages: {
          'pinned:assistant': [
            {
              'id': 'cache-plain-1',
              'conversation_id': 'pinned:assistant',
              'role': 'user',
              'body': '昨天说到哪了',
              'ts': 101,
            },
            {
              'id': 'cache-plain-2',
              'conversation_id': 'pinned:assistant',
              'role': 'assistant',
              'body': '继续处理回访记录',
              'ts': 202,
            },
          ],
        },
      ),
    );
    final repository = MobileRepository(
      client: MobileApiClient(sessionStore: store),
    );

    final messages = await repository.loadInitialMessages(
      const ConversationItem(
        id: 'pinned:assistant',
        type: ConversationType.pinnedAssistant,
        title: '小C助理',
        subtitle: '',
        timestampText: '',
      ),
    );

    expect(messages, hasLength(2));
    expect(messages.first.role, ChatRole.user);
    expect(messages.first.body, '昨天说到哪了');
    expect(messages.last.role, ChatRole.assistant);
    expect(messages.last.body, '继续处理回访记录');
  });

  test('MobileRepository does not cache super employee reply after stop',
      () async {
    final store = MemoryMobileSessionStore();
    final repository = MobileRepository(
      client: _CancelAwareSuperEmployeeApi(store),
    );
    var cancelled = true;

    await expectLater(
      repository.streamMessage(
        conversation: const ConversationItem(
          id: 'pinned:codex',
          type: ConversationType.pinnedCodex,
          title: '超级员工-Codex',
          subtitle: '',
          timestampText: '',
        ),
        body: '继续',
        isCancelled: () => cancelled,
      ),
      throwsA(anything),
    );

    final cached = (await store.load()).cachedChatMessages['pinned:codex'];
    expect(cached, hasLength(1));
    expect(cached?.single['role'], 'user');
    expect(cached?.single['body'], '继续');

    final state = (await store.load()).conversationListStates['pinned:codex'];
    expect(state?['last_message_preview'], '我: 继续');
    expect(state?['last_message_at'], isA<int>());

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: true,
    );
    final codex = conversations.singleWhere(
      (item) => item.id == 'pinned:codex',
    );
    expect(codex.subtitle, '我: 继续');
    expect(codex.timestampMs, greaterThan(0));
    expect(codex.timestampText, isNotEmpty);
  });

  test('MobileRepository caches normal chat like Android streamChat', () async {
    final store = MemoryMobileSessionStore();
    final repository = MobileRepository(client: _PlainChatCacheApi(store));

    final reply = await repository.streamMessage(
      conversation: const ConversationItem(
        id: 'pinned:assistant',
        type: ConversationType.pinnedAssistant,
        title: '小C助理',
        subtitle: '',
        timestampText: '',
      ),
      body: '你好',
    );

    expect(reply, '普通回复');
    final session = await store.load();
    final cached = session.cachedChatMessages['pinned:assistant'];
    expect(cached, hasLength(2));
    expect(cached?[0]['role'], 'user');
    expect(cached?[0]['body'], '你好');
    expect(cached?[1]['role'], 'assistant');
    expect(cached?[1]['body'], '普通回复');
    final state = session.conversationListStates['pinned:assistant'];
    expect(state?['last_message_preview'], '普通回复');
    expect(state?['last_message_at'], isA<int>());

    final conversations = await repository.loadCachedConversations(
      adminMode: false,
      enterpriseMode: true,
    );
    final assistant = conversations.singleWhere(
      (item) => item.id == 'pinned:assistant',
    );
    expect(assistant.subtitle, '普通回复');
  });

  test('MobileRepository enterprise conversations parse Android mobile mods',
      () async {
    final store = MemoryMobileSessionStore();
    final repository =
        MobileRepository(client: _EnterpriseModsApi(store: store));

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: true,
    );

    expect(conversations.map((item) => item.id), contains('pinned:codex'));
    expect(conversations.map((item) => item.id), contains('pinned:cs'));
    final cs = conversations.singleWhere((item) => item.id == 'pinned:cs');
    expect(cs.title, '专属客服');
    expect(cs.subtitle, '您好，我是您的专属客服');
    expect(
      conversations.map((item) => item.id),
      contains('employee:avatar-mod:avatar-generation-employee'),
    );
    final employee = conversations.singleWhere(
      (item) => item.id == 'employee:avatar-mod:avatar-generation-employee',
    );
    expect(employee.title, '头像生成员工');
    expect(employee.subtitle, '给 AI 员工生成头像');
    expect(employee.avatarUrl, 'https://cdn.example.com/avatar.png');
    expect(employee.badgeText, '已安装');
    expect(employee.badgeColor, 0xFF3370FF);
    expect((await store.load()).cachedModInfos.single['id'], 'avatar-mod');
  });

  test(
      'MobileRepository conversations use Android cached mod infos on refresh failure',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accountKind: 'enterprise',
        cachedModInfos: [
          {
            'id': 'cached-avatar-mod',
            'name': '缓存头像包',
            'version': '1.0.0',
            'description': '离线缓存',
            'author': 'XC',
            'workflow_employees': [
              {
                'id': 'cached-avatar-employee',
                'label': '缓存头像员工',
                'panel_summary': '来自缓存的员工资料',
                'phone_channel': 'mobile-chat',
              },
            ],
          },
        ],
      ),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: true,
    );

    expect(conversations.map((item) => item.id), contains('pinned:codex'));
    final employee = conversations.singleWhere(
      (item) => item.id == 'employee:cached-avatar-mod:cached-avatar-employee',
    );
    expect(employee.title, '缓存头像员工');
    expect(employee.subtitle, '来自缓存的员工资料');
  });

  test('MobileRepository cached conversations mirror Android Room first paint',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accountKind: 'enterprise',
        cachedModInfos: [
          {
            'id': 'cached-avatar-mod',
            'name': '缓存头像包',
            'workflow_employees': [
              {
                'id': 'cached-avatar-employee',
                'label': '缓存头像员工',
                'panel_summary': '来自缓存的员工资料',
                'phone_channel': 'mobile-chat',
              },
            ],
          },
        ],
        conversationListStates: {
          'employee:cached-avatar-mod:cached-avatar-employee': {
            'last_message_preview': '我: 先看缓存',
            'last_message_at': 1719820800000,
          },
        },
      ),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final conversations = await repository.loadCachedConversations(
      adminMode: false,
      enterpriseMode: true,
    );

    final employee = conversations.singleWhere(
      (item) => item.id == 'employee:cached-avatar-mod:cached-avatar-employee',
    );
    expect(employee.title, '缓存头像员工');
    expect(employee.subtitle, '我: 先看缓存');
    expect(employee.timestampMs, 1719820800000);
    expect(employee.badgeText, '已安装');
    expect(employee.badgeColor, 0xFF3370FF);
  });

  test('MobileRepository admin conversations use Android admin badge color',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accountKind: 'admin',
        cachedModInfos: [
          {
            'id': 'admin-duty',
            'name': '管理端 AI 员工',
            'workflow_employees': [
              {
                'id': 'site-content-editor',
                'label': '静态站内容编辑员',
                'panel_summary': '维护静态站内容',
                'phone_channel': 'admin-duty',
              },
            ],
          },
        ],
      ),
    );
    final repository =
        MobileRepository(client: MobileApiClient(sessionStore: store));

    final conversations = await repository.loadCachedConversations(
      adminMode: true,
      enterpriseMode: true,
    );

    expect(conversations.map((item) => item.id), isNot(contains('pinned:cs')));
    final customerService = conversations.singleWhere(
      (item) =>
          item.id ==
          'employee:admin-duty-employees:user-customer-service-officer',
    );
    expect(customerService.title, '客户客服');
    expect(customerService.subtitle, '查看并回复企业客户的客服消息');
    expect(customerService.type, ConversationType.aiTask);
    expect(conversations.indexOf(customerService), 5);
    final employee = conversations.singleWhere(
      (item) => item.id == 'employee:admin-duty-employees:site-content-editor',
    );
    expect(employee.badgeText, '管理端');
    expect(employee.badgeColor, 0xFFED7B2F);
  });

  test('MobileRepository timestamps mirror Android cross-year format',
      () async {
    final now = DateTime.now();
    final previousYear = now.year - 1;
    final timestampMs = DateTime(previousYear, 1, 2).millisecondsSinceEpoch;
    final expectedYear = (previousYear % 100).toString().padLeft(2, '0');
    final store = MemoryMobileSessionStore(
      MobileSessionData(
        accountKind: 'enterprise',
        conversationListStates: {
          'pinned:codex': {
            'last_message_preview': '我: 继续',
            'last_message_at': timestampMs,
          },
        },
      ),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: true,
    );

    final codex = conversations.singleWhere(
      (item) => item.id == 'pinned:codex',
    );
    expect(codex.subtitle, '我: 继续');
    expect(codex.timestampText, '$expectedYear/1/2');
  });

  test('MobileRepository fixed conversations do not use fake preview seeds',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(accountKind: 'enterprise'),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: true,
    );

    final codex = conversations.singleWhere(
      (item) => item.id == 'pinned:codex',
    );
    expect(codex.subtitle, '全设备协同');
    expect(codex.timestampText, isEmpty);
    expect(codex.timestampMs, 0);
  });

  test(
      'MobileRepository AI employees use Android cached mod infos on refresh failure',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accountKind: 'enterprise',
        cachedModInfos: [
          {
            'id': 'cached-avatar-mod',
            'name': '缓存头像包',
            'workflow_employees': [
              {
                'id': 'cached-avatar-employee',
                'label': '缓存头像员工',
                'panel_summary': '来自缓存的员工资料',
                'phone_channel': 'mobile-chat',
              },
            ],
          },
        ],
      ),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final employees = await repository.loadAiEmployees();

    expect(employees.single.employeeId, 'cached-avatar-employee');
    expect(employees.single.name, '缓存头像员工');
    expect(employees.single.summary, '来自缓存的员工资料');
  });

  test('MobileRepository AI employee page uses Android admin mode source',
      () async {
    final api = _EmployeeSourceApi(accountKind: 'admin_portal');
    final repository = MobileRepository(client: api);

    final employees = await repository.loadAiEmployees();

    expect(api.adminHomeCalls, 1);
    expect(api.mobileModsCalls, 0);
    expect(employees.map((employee) => employee.employeeId),
        contains('site-content-editor'));
  });

  test('MobileRepository normalizes cached customer service employee identity',
      () async {
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        accountKind: 'admin',
        cachedModInfos: [
          {
            'id': 'admin-duty',
            'workflow_employees': [
              {
                'id': 'user-customer-service-officer',
                'label': '用户客服员工',
                'panel_title': '用户客服员工',
                'panel_summary': '面向终端用户的客服 AI 员工',
                'phone_channel': 'admin-duty',
              },
            ],
          },
        ],
      ),
    );
    final repository = MobileRepository(client: _FailingModsApi(store: store));

    final conversations = await repository.loadCachedConversations(
      adminMode: true,
      enterpriseMode: true,
    );
    final customerService = conversations.singleWhere(
      (item) =>
          item.id ==
          'employee:admin-duty-employees:user-customer-service-officer',
    );
    final employees = await repository.loadAiEmployees();
    final customerServiceProfile = employees.singleWhere(
      (employee) => employee.employeeId == 'user-customer-service-officer',
    );

    expect(customerService.title, '客户客服');
    expect(customerService.subtitle, '查看并回复企业客户的客服消息');
    expect(customerServiceProfile.name, '客户客服');
    expect(customerServiceProfile.title, '客户客服');
    expect(customerServiceProfile.summary, '查看并回复企业客户的客服消息');
  });

  test('MobileRepository AI employee page uses Android mobile mods source',
      () async {
    final api = _EmployeeSourceApi(accountKind: 'enterprise');
    final repository = MobileRepository(client: api);

    final employees = await repository.loadAiEmployees();

    expect(api.adminHomeCalls, 0);
    expect(api.mobileModsCalls, 1);
    expect(employees.single.employeeId, 'avatar-generation-employee');
    expect(employees.single.name, '头像生成员工');
  });

  test('MobileRepository personal conversations keep Android fixed assistant',
      () async {
    final repository = MobileRepository(client: _EnterpriseModsApi());

    final conversations = await repository.loadConversations(
      adminMode: false,
      enterpriseMode: false,
    );

    expect(conversations.map((item) => item.id), ['pinned:assistant']);
  });
}

class _CancelAwareSuperEmployeeApi extends MobileApiClient {
  _CancelAwareSuperEmployeeApi(MobileSessionStore store)
      : super(sessionStore: store);

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayDesktops() async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {'items': []},
      raw: {'items': []},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> postSuperEmployeeMessage(
    String tool,
    String body,
  ) async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {'reply': '最终回复'},
      raw: {'reply': '最终回复'},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {'items': []},
      raw: {
        'success': true,
        'data': {'items': []}
      },
    );
  }
}

class _PlainChatCacheApi extends MobileApiClient {
  _PlainChatCacheApi(MobileSessionStore store) : super(sessionStore: store);

  @override
  Future<String> streamChat(
    String message, {
    String? sessionId,
    int userId = 0,
    List<Map<String, String>> recentMessages = const [],
    void Function(String token)? onToken,
  }) async {
    onToken?.call('普通');
    onToken?.call('回复');
    return '普通回复';
  }
}

class _EnterpriseModsApi extends MobileApiClient {
  _EnterpriseModsApi({MobileSessionStore? store})
      : super(sessionStore: store ?? MemoryMobileSessionStore());

  @override
  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {
        'data': {
          'items': [
            {
              'id': 'avatar-mod',
              'name': '头像生成',
              'version': '1.0.0',
              'description': '头像员工包',
              'author': 'XC',
              'workflow_employees': [
                {
                  'id': 'avatar-generation-employee',
                  'label': '头像生成员工',
                  'panel_summary': '给 AI 员工生成头像',
                  'api_base_path': '/api/avatar',
                  'phone_channel': 'mobile',
                  'market_avatar': 'https://cdn.example.com/avatar.png',
                },
              ],
            },
          ],
        },
      },
      raw: {
        'success': true,
        'data': {
          'items': [],
        },
      },
    );
  }
}

class _FailingModsApi extends MobileApiClient {
  _FailingModsApi({required MobileSessionStore store})
      : super(sessionStore: store);

  @override
  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: false,
      message: 'offline',
      data: {},
      raw: {'success': false, 'message': 'offline'},
    );
  }
}

class _EmployeeSourceApi extends _EnterpriseModsApi {
  _EmployeeSourceApi({required this.accountKind});

  final String accountKind;
  var adminHomeCalls = 0;
  var mobileModsCalls = 0;

  @override
  Future<MobileSessionData> loadSession() async {
    return MobileSessionData(accountKind: accountKind);
  }

  @override
  Future<MobileEnvelope<AdminMobileHomeData>> adminHome() async {
    adminHomeCalls += 1;
    return MobileEnvelope<AdminMobileHomeData>(
      success: true,
      message: '',
      data: AdminMobileHomeData.empty(),
      raw: const {'success': true},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    mobileModsCalls += 1;
    return super.mobileMods();
  }
}

class _FakeCredentialCipher extends AndroidCredentialCipher {
  const _FakeCredentialCipher();

  @override
  Future<String> encrypt(String plain) async {
    if (plain.isEmpty) return '';
    return 'enc:v1:$plain';
  }

  @override
  Future<String> decrypt(String stored) async {
    if (stored.isEmpty) return '';
    if (!stored.startsWith('enc:v1:')) return stored;
    return stored.substring('enc:v1:'.length);
  }
}

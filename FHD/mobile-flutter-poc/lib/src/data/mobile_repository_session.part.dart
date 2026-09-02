part of 'mobile_repository.dart';

abstract class _RepoSessionBase extends _RepoRootBase {
  _RepoSessionBase({
    MobileApiClient? client,
    ImWebSocketClient? imWebSocket,
  }) : super(client: client, imWebSocket: imWebSocket);

  Future<MobileMeData> loadMe() async {
    final response = await _client.me();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('账号信息加载失败'));
    }
    return MobileMeData.fromJson(response.data ?? const <String, Object?>{});
  }

  Future<MobileMeData> cachedMe() async {
    final session = await _client.loadSession();
    if (!session.hasIdentity) {
      return MobileMeData.adminFallback(avatarUrl: session.localAvatarSource);
    }
    final username = session.username.ifEmpty('admin');
    return MobileMeData(
      user: MobileUserData(
        id: session.userId,
        username: username,
        displayName: username,
        email: '',
        role: session.accountKind.ifEmpty('admin'),
        isActive: true,
        avatarUrl: session.localAvatarSource.trim().isEmpty
            ? null
            : session.localAvatarSource.trim(),
      ),
      permissions: const [],
      accountKind: session.accountKind.ifEmpty('admin'),
      companyBrand: '',
      modIds: const [],
    );
  }

  Future<List<ConversationItem>> loadConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) async {
    final conversationStates = Map<String, _ConversationListState>.of(
      _emptyConversationStates,
    )..addAll(await _loadConversationListStates(_client));
    final fixed = _fixedConversationItems(
      showCodex: enterpriseMode || adminMode,
      showCursor: enterpriseMode || adminMode,
      showClaude: enterpriseMode || adminMode,
      showTrae: enterpriseMode || adminMode,
      showCustomerService: enterpriseMode && !adminMode,
      states: conversationStates,
    );

    if (!adminMode && !enterpriseMode) return _sortConversationItems(fixed);

    final mods = await _loadModInfosOrCache(adminMode: adminMode);
    return _sortConversationItems([
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: adminMode ? null : '已安装',
        badgeColor: adminMode ? null : _badgeInstalledColor,
        states: conversationStates,
      ),
    ]);
  }

  Future<List<ConversationItem>> loadCachedConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) async {
    final conversationStates = await _loadConversationListStates(_client);
    final fixed = _fixedConversationItems(
      showCodex: enterpriseMode || adminMode,
      showCursor: enterpriseMode || adminMode,
      showClaude: enterpriseMode || adminMode,
      showTrae: enterpriseMode || adminMode,
      showCustomerService: enterpriseMode && !adminMode,
      states: conversationStates,
    );

    if (!adminMode && !enterpriseMode) return _sortConversationItems(fixed);

    final mods = await _loadCachedModInfos(adminMode: adminMode);
    return _sortConversationItems([
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: adminMode ? null : '已安装',
        badgeColor: adminMode ? null : _badgeInstalledColor,
        states: conversationStates,
      ),
    ]);
  }

  Future<List<ModInfo>> loadModInfos({bool adminMode = false}) async {
    if (adminMode) {
      final response = await _client.adminHome();
      if (!response.success) {
        throw MobileRepositoryException(response.message.ifEmpty('移动数据加载失败'));
      }

      final home = response.data ?? AdminMobileHomeData.empty();
      final mods = [_normalizeAdminDutyMod(home.toAdminModInfo())];
      await _cacheModInfos(mods);
      return mods;
    }

    final response = await _client.mobileMods();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('AI 员工同步失败'));
    }
    final mods = _parseModInfos(response.data ?? const <String, Object?>{});
    await _cacheModInfos(mods);
    return mods;
  }

  Future<List<ModInfo>> _loadModInfosOrCache({required bool adminMode}) async {
    try {
      return await loadModInfos(adminMode: adminMode);
    } catch (_) {
      return _loadCachedModInfos(adminMode: adminMode);
    }
  }

  Future<List<ModInfo>> _loadCachedModInfos({required bool adminMode}) async {
    final session = await _client.loadSession();
    final mods = session.cachedModInfos
        .map(ModInfo.fromJson)
        .where((mod) => mod.id.trim().isNotEmpty || mod.name.trim().isNotEmpty)
        .toList(growable: false);
    if (adminMode) {
      return mods.map(_normalizeAdminDutyMod).toList(growable: false);
    }
    return mods;
  }

  Future<void> _cacheModInfos(List<ModInfo> mods) async {
    if (mods.isEmpty) return;
    try {
      await _client.cacheModInfos(
        mods.map(_modInfoToCacheJson).toList(growable: false),
      );
    } catch (_) {
      // Cache write failure must not block the live Flutter UI.
    }
  }

}

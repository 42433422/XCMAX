part of 'mobile_repository.dart';

/// 企业端员工列表直接消费统一员工目录（与桌面端员工工作台、信息页同源），
/// 不再从 mod 编制里二次筛选。
ModInfo? _enterpriseDirectoryMod(List<Map<String, Object?>> rows) {
  final employees = <WorkflowEmployeeInfo>[];
  for (final row in rows) {
    final packId = (row['pack_id'] ?? '').toString().trim();
    if (packId.isEmpty) continue;
    final label = (row['label'] ?? packId).toString().trim().ifEmpty(packId);
    // 与桌面端一致：按通讯录顺序从头像池取图，避免整列撞图。
    final avatarIndex = employees.length % employeeAvatarPool.length;
    employees.add(
      WorkflowEmployeeInfo(
        id: packId,
        label: label,
        panelTitle: label,
        panelSummary: (row['description'] ?? '').toString().trim(),
        apiBasePath:
            row['prompt_only'] == true ? '' : '/api/admin/employees/$packId',
        phoneChannel: 'admin-duty',
        workflowPlaceholder: false,
        profileSource: (row['runtime_kind'] ?? 'employee_pack').toString(),
        marketConnected: false,
        marketPkgId: '',
        marketName: '',
        marketDescription: '',
        marketVersion: '',
        marketAuthor: '',
        marketIndustry: '',
        marketMaterialCategory: '',
        marketLicenseScope: '',
        marketSecurityLevel: '',
        marketAvatar: employeeAvatarPool[avatarIndex],
      ),
    );
  }
  if (employees.isEmpty) return null;
  return ModInfo(
    id: adminDutyModId,
    name: '企业员工',
    version: 'local',
    description: '${employees.length} 位 AI 员工，来自统一员工目录。',
    author: 'XCAGI',
    primary: true,
    industry: const ModIndustry(id: '企业', name: '企业'),
    avatarUrl: null,
    frontendMenu: const [],
    workflowEmployees: employees,
  );
}

abstract class _RepoSessionBase extends _RepoRootBase {
  _RepoSessionBase({super.client, super.imWebSocket});

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
    final conversationStates =
        Map<String, _ConversationListState>.of(_emptyConversationStates)
          ..addAll(
            await _loadConversationListStates(
              _client,
              openStore: openOfflineStore,
            ),
          );
    final fixed = _fixedConversationItems(
      showCodex: adminMode,
      showCursor: adminMode,
      showClaude: adminMode,
      showTrae: adminMode,
      showCustomerService: enterpriseMode && !adminMode,
      states: conversationStates,
    );

    if (!adminMode && !enterpriseMode) return _sortConversationItems(fixed);

    final mods = await _loadModInfosOrCache(adminMode: adminMode);
    return _sortConversationItems([
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: null,
        badgeColor: null,
        states: conversationStates,
      ),
    ]);
  }

  Future<List<ConversationItem>> loadCachedConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) async {
    final conversationStates = await _loadConversationListStates(
      _client,
      openStore: openOfflineStore,
    );
    final fixed = _fixedConversationItems(
      showCodex: adminMode,
      showCursor: adminMode,
      showClaude: adminMode,
      showTrae: adminMode,
      showCustomerService: enterpriseMode && !adminMode,
      states: conversationStates,
    );

    if (!adminMode && !enterpriseMode) return _sortConversationItems(fixed);

    final mods = await _loadCachedModInfos(adminMode: adminMode);
    return _sortConversationItems([
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: null,
        badgeColor: null,
        states: conversationStates,
      ),
    ]);
  }

  Future<List<ModInfo>> loadModInfos({bool adminMode = false}) async {
    final generation = _client.authGeneration;
    final session = await _client.loadSession();
    final base = await _client.resolveSessionBaseUrl();
    Future<void> requireScope() async {
      final current = await _client.loadSession();
      final currentBase = await _client.resolveSessionBaseUrl();
      if (generation != _client.authGeneration ||
          base != currentBase ||
          current.serverMode != session.serverMode ||
          current.fhdHost != session.fhdHost ||
          current.localBaseUrl != session.localBaseUrl) {
        throw const MobileApiException(
            statusCode: 409, message: '账号或连接已切换，请重新加载员工目录', body: {});
      }
    }

    Future<void> cache(List<ModInfo> mods) async {
      await requireScope();
      try {
        await _client.cacheModInfos(
            mods.map(_modInfoToCacheJson).toList(growable: false),
            authGeneration: generation,
            expectedSession: session,
            expectedBaseUrl: base);
      } catch (_) {/* A disk failure must not block the live directory. */}
      await requireScope();
    }

    await requireScope();
    if (adminMode) {
      final response = await _client.adminHome();
      if (!response.success) {
        throw MobileRepositoryException(response.message.ifEmpty('移动数据加载失败'));
      }

      final home = response.data ?? AdminMobileHomeData.empty();
      final mods = [_normalizeAdminDutyMod(home.toAdminModInfo())];
      await cache(mods);
      return mods;
    }

    MobileEnvelope<List<Map<String, Object?>>>? directory;
    try {
      directory = await _client.employeeDirectory();
    } on MobileApiException catch (error) {
      if (error.statusCode == 401 || error.statusCode == 403) rethrow;
      directory = null;
    } catch (_) {
      directory = null;
    }
    if (directory != null && directory.success) {
      final mod = _enterpriseDirectoryMod(
        directory.data ?? const <Map<String, Object?>>[],
      );
      final mods = mod == null ? <ModInfo>[] : [mod];
      await cache(mods);
      return mods;
    }

    await requireScope();
    final response = await _client.mobileMods();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('AI 员工同步失败'));
    }
    final mods = _parseModInfos(response.data ?? const <String, Object?>{});
    await cache(mods);
    return mods;
  }

  Future<List<ModInfo>> _loadModInfosOrCache({required bool adminMode}) async {
    try {
      return await loadModInfos(adminMode: adminMode);
    } on MobileApiException catch (error) {
      if (error.statusCode == 401 ||
          error.statusCode == 403 ||
          error.statusCode == 409) {
        rethrow;
      }
      return _loadCachedModInfos(adminMode: adminMode);
    } catch (_) {
      return _loadCachedModInfos(adminMode: adminMode);
    }
  }

  Future<List<ModInfo>> _loadCachedModInfos({required bool adminMode}) async {
    final generation = _client.authGeneration;
    final session = await _client.loadSession();
    final base = await _client.resolveSessionBaseUrl();
    if (generation != _client.authGeneration) return const [];
    final mods = session.cachedModInfos
        .where((mod) => mod['_mobile_cache_base_url'] == base)
        .map(ModInfo.fromJson)
        .where((mod) => mod.id.trim().isNotEmpty || mod.name.trim().isNotEmpty)
        .toList(growable: false);
    if (adminMode) {
      return mods.map(_normalizeAdminDutyMod).toList(growable: false);
    }
    return mods;
  }
}

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../models/conversation.dart';
import '../policy/android_runtime_policy.dart';
import '../policy/avatar_policy.dart';
import '../policy/pinned_ids.dart';
import 'ai_employee_profile.dart';
import 'duty_roster_ssot.dart';
import 'employee_pending_question.dart';
import '../im/im_websocket_client.dart';

const _badgeInstalledColor = 0xFF3370FF;
const _xcmaxDefaultWorkspaceRoot = '/Users/a4243342/Desktop/XCMAX';

class MobileRepository {
  MobileRepository({MobileApiClient? client, ImWebSocketClient? imWebSocket})
      : _client = client ?? MobileApiClient(),
        _imWebSocket = imWebSocket ?? ImWebSocketClient();

  static const customerServiceRequestType = 'mobile_ai_customer_service';

  final MobileApiClient _client;
  final ImWebSocketClient _imWebSocket;
  StreamSubscription<Map<String, Object?>>? _imWebSocketSubscription;

  MobileApiClient get client => _client;
  bool get imWebSocketConnected => _imWebSocket.connected;
  Stream<Map<String, Object?>> get imWebSocketEvents => _imWebSocket.events;

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
      return MobileMeData.adminFallback(
        avatarUrl: session.localAvatarSource,
      );
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
        throw MobileRepositoryException(
          response.message.ifEmpty('移动数据加载失败'),
        );
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
      // Match Android: cache write failure must not block the live UI.
    }
  }

  Future<List<AiGroupConversation>> loadAiGroups() async {
    final response = await _client.aiGroups();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('AI 群聊加载失败'));
    }
    return _parseAiGroups(response.data);
  }

  Future<List<AiGroupCandidate>> loadGroupMemberCandidates() async {
    final response = await _client.aiGroupCandidates();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('群成员加载失败'));
    }
    return _parseAiGroupCandidates(response.data);
  }

  Future<AiGroupConversation?> createAiGroup(String name) async {
    final text = name.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('群名称不能为空');
    }
    final response = await _client.createAiGroup(text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('建群失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> createGroupWithMembers({
    required String name,
    required List<AiGroupCandidate> members,
  }) async {
    final group = await createAiGroup(name);
    if (group == null) return null;
    var current = group;
    for (final member in members) {
      final updated = await addAiGroupMember(
        groupId: group.id,
        employeeId: member.employeeId,
        modId: member.modId,
        name: member.name,
        avatar: member.avatarUrl ?? '',
        summary: member.summary,
      );
      if (updated != null) current = updated;
    }
    return current;
  }

  Future<List<AiGroupMessage>> loadAiGroupMessages(String groupId) async {
    if (groupId.trim().isEmpty) return const <AiGroupMessage>[];
    final response = await _client.aiGroupMessages(groupId.trim());
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('群消息加载失败'));
    }
    return _parseAiGroupMessages(response.data);
  }

  Future<List<GitBranchInfo>> loadGitBranches() async {
    final response = await _client.gitBranches();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('工作分支加载失败'));
    }
    return _parseGitBranches(response.data);
  }

  Future<AiGroupPostResult> postAiGroupMessage({
    required String groupId,
    required String message,
    List<String> mentions = const [],
    String branchContext = '',
    bool forceDispatch = false,
    Map<String, String> context = const {},
  }) async {
    final text = message.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }
    final branch = branchContext.trim();
    final response = await _client.postAiGroupMessage(
      groupId: groupId,
      message: text,
      mentions: mentions,
      dispatch:
          forceDispatch || branch.isNotEmpty || _shouldDispatchGroupTask(text),
      branchContext: branch,
      context: context,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('发送失败'));
    }
    return _parseAiGroupPostResult(response.data);
  }

  Future<AiGroupConversation?> addAiGroupMember({
    required String groupId,
    required String employeeId,
    required String modId,
    required String name,
    required String avatar,
    required String summary,
  }) async {
    final response = await _client.addAiGroupMember(
      groupId: groupId,
      employeeId: employeeId,
      modId: modId,
      name: name,
      avatar: avatar,
      summary: summary,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('添加成员失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> removeAiGroupMember({
    required String groupId,
    required String employeeId,
  }) async {
    final response = await _client.removeAiGroupMember(
      groupId: groupId,
      employeeId: employeeId,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('移除成员失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupPin(String groupId) async {
    final response = await _client.toggleAiGroupPin(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> markAiGroupUnread(String groupId) async {
    final response = await _client.markAiGroupUnread(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> markAiGroupRead(String groupId) async {
    final response = await _client.markAiGroupRead(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupFollowed(String groupId) async {
    final response = await _client.toggleAiGroupFollowed(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupHidden(String groupId) async {
    final response = await _client.toggleAiGroupHidden(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<void> deleteAiGroup(String groupId) async {
    final response = await _client.deleteAiGroup(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('删除失败'));
    }
  }

  Future<void> toggleConversationPin(String conversationId) async {
    final response = await _client.toggleConversationPin(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> markConversationUnread(String conversationId) async {
    final response = await _client.markConversationUnread(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> markConversationRead(String conversationId) async {
    final response = await _client.markConversationRead(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> toggleConversationUnread(ConversationItem item) async {
    if (item.unreadCount > 0) {
      await markConversationRead(item.id);
      return;
    }
    await markConversationUnread(item.id);
  }

  Future<void> toggleConversationFollowed(String conversationId) async {
    final response = await _client.toggleConversationFollowed(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> toggleConversationHidden(String conversationId) async {
    final response = await _client.toggleConversationHidden(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> deleteConversation(String conversationId) async {
    final response = await _client.deleteConversation(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('删除失败'));
    }
  }

  Future<CsInfo> loadCsInfo() async {
    final response = await _client.csInfo();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客服信息加载失败'));
    }
    return _parseCsInfo(response.data);
  }

  Future<List<CsMessage>> loadCsMessages({String? since}) async {
    final response = await _client.csMessages(since: since);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客服消息加载失败'));
    }
    return _parseCsMessages(response.data);
  }

  Future<CsMessageResponse> sendCsMessage(String body) async {
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }
    final response = await _client.postCsMessage(text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客服消息发送失败'));
    }
    return _parseCsMessageResponse(response.data);
  }

  Future<List<AdminCsInboxItem>> loadAdminCsInbox() async {
    final response = await _client.adminCsInbox();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('加载客服收件箱失败'));
    }
    return _parseAdminCsInbox(response.data);
  }

  Future<List<AdminCsMessage>> loadAdminCsMessages(int conversationId) async {
    if (conversationId <= 0) return const [];
    final response = await _client.adminCsMessages(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('加载客服消息失败'));
    }
    return _parseAdminCsMessages(response.data);
  }

  Future<void> replyAdminCs({
    required int conversationId,
    required String body,
  }) async {
    final text = body.trim();
    if (conversationId <= 0 || text.isEmpty) return;
    final response = await _client.replyAdminCs(id: conversationId, body: text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客服回复失败'));
    }
  }

  Future<List<MobileNavMenuItem>> loadNavMenu() async {
    final response = await _client.navMenu();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('侧栏菜单加载失败'));
    }
    return response.data?.items ?? const <MobileNavMenuItem>[];
  }

  Future<List<AiCirclePost>> loadAiCirclePosts() async {
    final response = await _client.circlePosts();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('交流圈加载失败'));
    }
    return response.data?.items ?? const <AiCirclePost>[];
  }

  Future<List<PendingNotification>> loadPendingNotifications() async {
    final response = await _client.pendingNotifications();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('通知加载失败'));
    }
    return response.data?.notifications ?? const <PendingNotification>[];
  }

  Future<void> exchangePairingCode(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('无法识别配对码');
    }
    final parsed = parsePairingPayload(text);
    if (parsed != null && parsed.version >= 3 && parsed.relayId.isNotEmpty) {
      throw const MobileRepositoryException(
        '云中继绑定请先登录账号，登录后将自动完成绑定',
      );
    }

    final code = _pairingExchangeCode(parsed, text);
    final nonce = _pairingExchangeNonce(parsed, text, code);
    if (code.isEmpty && nonce.isEmpty) {
      throw const MobileRepositoryException('无法识别配对码，请刷新电脑端二维码');
    }

    final baseUrl = await _resolvePairingExchangeBaseUrl(parsed, text);
    if (baseUrl.isEmpty) {
      throw const MobileRepositoryException(
        '未找到电脑，请确认手机与电脑在同一 WiFi，并在管理端刷新设备码后重试',
      );
    }

    await _primePairingLanSession(baseUrl);
    final response = await _client.exchangePairing(
      nonce: nonce,
      code: code,
      baseUrl: baseUrl,
    );
    if (!response.success) {
      throw MobileRepositoryException('设备配对失败[${response.message}]');
    }
    final hostWithPort = _hostPortFromApiBaseUrl(
      _readStringMap(response.data, const ['api_base_url', 'base_url']),
    ).ifEmpty(parsed?.hostWithPort ?? '');
    await _client.persistPairingSession(
      response.data,
      hostWithPort: hostWithPort,
      clearRelayDesktop: true,
      setupComplete: true,
      preserveActiveAuth: true,
    );
    final relayId = _relayIdFromBindingData(response.data);
    if (relayId.isNotEmpty) {
      try {
        await _client.relayBindAccount(relayId);
      } catch (_) {
        // Android leaves relay binding cleared when account relay bind fails.
      }
    }
  }

  Future<void> _primePairingLanSession(String baseUrl) async {
    final hostWithPort = _hostPortFromApiBaseUrl(baseUrl);
    if (hostWithPort.isEmpty) return;
    final session = await _client.loadSession();
    await _client.saveSession(
      session.copyWith(
        fhdHost: hostWithPort,
        serverMode: 'lan',
      ),
    );
  }

  Future<String> _resolvePairingExchangeBaseUrl(
    PairingPayload? parsed,
    String raw,
  ) async {
    if (parsed != null) {
      final fromPayload = parsed.apiBaseUrl.isNotEmpty
          ? _ensureTrailingSlash(parsed.apiBaseUrl)
          : _pairingLanBaseUrl(parsed.host, parsed.port);
      if (fromPayload.isNotEmpty) return fromPayload;
    }

    final session = await _client.loadSession();
    final fromSession = _pairingLanBaseUrlFromHostPort(session.fhdHost);
    if (fromSession.isNotEmpty) return fromSession;

    final shortCode = _pairingExchangeCode(parsed, raw);
    if (RegExp(r'^\d{6}$').hasMatch(shortCode)) {
      return _discoverLanBaseUrlForShortCode(shortCode);
    }
    if (raw.startsWith('{')) {
      throw const MobileRepositoryException(
        '二维码内容无法识别，请在电脑端刷新二维码后重试',
      );
    }
    return '';
  }

  static const _lanPairingProbeTimeout = Duration(milliseconds: 900);

  Future<String> _discoverLanBaseUrlForShortCode(String code) async {
    final cleanCode = code.trim();
    if (!RegExp(r'^\d{6}$').hasMatch(cleanCode)) return '';
    final session = await _client.loadSession();
    final candidates = await _lanPairingCandidateBaseUrls(session.fhdHost);
    for (final baseUrl in candidates) {
      try {
        final lookup = await _client
            .pairingLookup(
              code: cleanCode,
              baseUrl: baseUrl,
            )
            .timeout(_lanPairingProbeTimeout);
        if (lookup.success) return baseUrl;
      } on TimeoutException {
        // 继续尝试下一个候选
      } catch (_) {
        // 继续尝试下一个候选
      }
    }
    return '';
  }

  Future<List<String>> _lanPairingCandidateBaseUrls(String configuredHost) async {
    const lanPorts = [5011, 5100, 17500, 5001, 5000];
    final hostPorts = <String>[];
    final configured = _normalizePairingHost(configuredHost);
    if (configured.isNotEmpty) {
      if (configured.contains(':')) {
        hostPorts.add(configured);
      } else {
        for (final port in lanPorts) {
          hostPorts.add('$configured:$port');
        }
      }
    }

    try {
      final ifaces = await NetworkInterface.list(type: InternetAddressType.IPv4);
      for (final iface in ifaces) {
        for (final addr in iface.addresses) {
          final ip = addr.address;
          if (ip.startsWith('127.') || ip.startsWith('169.254.')) continue;
          final parts = ip.split('.');
          if (parts.length != 4) continue;
          final prefix = '${parts[0]}.${parts[1]}.${parts[2]}';
          for (final hostOctet in ['1', '2', '100']) {
            for (final port in lanPorts) {
              hostPorts.add('$prefix.$hostOctet:$port');
            }
          }
        }
      }
    } catch (_) {
      // 网络接口枚举失败时忽略，仅依赖已配置 host
    }

    final seen = <String>{};
    final bases = <String>[];
    for (final hostPort in hostPorts) {
      final base = _pairingLanBaseUrlFromHostPort(hostPort);
      if (base.isNotEmpty && seen.add(base)) {
        bases.add(base);
      }
    }
    return bases;
  }

  String _pairingExchangeCode(PairingPayload? parsed, String raw) {
    if (parsed != null) return parsed.code.trim();
    if (RegExp(r'^\d{6}$').hasMatch(raw)) return raw;
    return '';
  }

  String _pairingExchangeNonce(PairingPayload? parsed, String raw, String code) {
    if (parsed != null) {
      if (parsed.version >= 2 && code.isEmpty) {
        return parsed.nonce.ifEmpty(parsed.token);
      }
      return parsed.nonce;
    }
    if (code.isNotEmpty) return '';
    if (raw.length >= 8) return raw;
    return '';
  }

  Future<void> confirmAuthQr({
    required String qrId,
    required String username,
    required String password,
    required String accountKind,
  }) async {
    if (qrId.trim().isEmpty) {
      throw const MobileRepositoryException('扫码登录二维码缺少 qr_id');
    }
    final response = await _client.confirmAuthQr(
      qrId: qrId,
      username: username,
      password: password,
      accountKind: accountKind,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('扫码登录确认失败'));
    }
  }

  Future<void> login({
    required String username,
    required String password,
    required bool adminMode,
    bool rememberPass = false,
    bool autoLogin = false,
  }) async {
    if (username.trim().isEmpty || password.isEmpty) {
      throw const MobileRepositoryException('用户名和密码不能为空');
    }
    final response = await _client.login(
      username: username,
      password: password,
      accountKind: adminMode ? 'admin' : 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(
        response.message.ifEmpty(adminMode ? '账号或密码错误' : '用户名或密码错误'),
      );
    }
    await _client.persistLoginSession(
      response.data,
      fallbackUsername: username,
      fallbackAccountKind: adminMode ? 'admin' : 'enterprise',
    );
    await _client.saveLoginPreferences(
      username: username,
      password: password,
      rememberPassword: rememberPass,
      autoLogin: autoLogin,
    );
  }

  Future<void> register({
    required String username,
    required String password,
    required String email,
    required String industryId,
    required String budgetRange,
  }) async {
    if (username.trim().isEmpty || password.isEmpty) {
      throw const MobileRepositoryException('用户名和密码不能为空');
    }
    final response = await _client.register(
      username: username,
      password: password,
      email: email,
      industryId: industryId,
      budgetRange: budgetRange,
      accountKind: 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('注册失败，请稍后重试'));
    }
  }

  Future<void> sendPhoneCode(String phone) async {
    if (phone.trim().length != 11) {
      throw const MobileRepositoryException('请输入 11 位手机号');
    }
    final response = await _client.sendPhoneCode(phone);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('验证码发送失败'));
    }
  }

  Future<void> loginWithPhoneCode({
    required String phone,
    required String code,
  }) async {
    final response = await _client.loginWithPhoneCode(
      phone: phone,
      code: code,
      accountKind: 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('验证码错误或已过期'));
    }
    await _client.persistLoginSession(
      response.data,
      fallbackUsername: phone,
      fallbackAccountKind: 'enterprise',
    );
  }

  Future<void> toggleAiCircleLike(int postId) async {
    final response = await _client.toggleCircleLike(postId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('点赞失败'));
    }
  }

  Future<void> addAiCircleComment(int postId, String body) async {
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('评论不能为空');
    }
    final response = await _client.addCircleComment(postId, text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('评论失败'));
    }
  }

  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    var accountKind = '';
    try {
      accountKind = (await _client.loadSession()).accountKind;
    } catch (_) {
      accountKind = '';
    }
    final mods = await _loadModInfosOrCache(
      adminMode: AndroidConversationRuntimePolicy.isAdminAccountKind(
        accountKind,
      ),
    );
    return aiEmployeeProfilesFromMods(mods);
  }

  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    final cached = await _loadCachedChat(conversation.id);
    if (cached.isNotEmpty) return cached;

    final tool = conversation.type.superTool;
    if (tool == null) return const [];

    final response = await _client.superEmployeeMessages(tool);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工消息加载失败'));
    }
    final messages = response.data ?? const <SuperEmployeeMessage>[];
    return messages
        .map((message) => message.toChatMessage(conversation.id))
        .toList(growable: false);
  }

  Future<ChatMessage> sendMessage({
    required ConversationItem conversation,
    required String body,
  }) async {
    final tool = conversation.type.superTool;
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }

    if (tool != null) {
      final reply = await streamMessage(
        conversation: conversation,
        body: text,
      );
      return _assistantMessage(conversation.id, reply);
    }

    final employeeRef = _employeeConversationRef(conversation.id);
    if (employeeRef != null) {
      final reply = await _client.streamEmployeeChat(
        message: text,
        employeeId: employeeRef.employeeId,
        modId: employeeRef.modId,
        conversationId: conversation.id,
        userId: await _loadCurrentUserId(),
      );
      return _assistantMessage(conversation.id, reply.ifEmpty('已收到。'));
    }

    final response = await _client.chat(
      text,
      sessionId: conversation.id,
    );
    final reply = _assistantReplyFromMap(response).ifEmpty('已收到。');
    return _assistantMessage(conversation.id, reply);
  }

  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final tool = conversation.type.superTool;
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }

    if (tool != null) {
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.user,
        body: text,
      );
      final localBaseUrl = await _superEmployeeLanBaseUrl();
      if (localBaseUrl.isNotEmpty) {
        // 第 1 级：LAN SSE（逐 token / status，避免整段 POST 挡住流式进度）。
        try {
          final reply = await _client.streamSuperEmployeeMessage(
            tool,
            text,
            baseUrl: localBaseUrl,
            onToken: (token) {
              if (isCancelled != null && isCancelled()) return;
              onToken?.call(token);
            },
            onStatus: (status) {
              if (isCancelled != null && isCancelled()) return;
              onToken?.call('\n$status\n');
            },
            isCancelled: isCancelled,
          );
          _throwIfCancelled(isCancelled);
          await _cacheChatMessage(
            conversation.id,
            role: ChatRole.assistant,
            body: reply,
          );
          return reply;
        } catch (_) {
          _throwIfCancelled(isCancelled);
          // 第 2 级：旧后端无 stream 时回落 LAN POST；再失败才走云中继。
          try {
            final reply = await _postSuperEmployeeMessage(
              tool,
              text,
              baseUrl: localBaseUrl,
            );
            _throwIfCancelled(isCancelled);
            onToken?.call(reply);
            await _cacheChatMessage(
              conversation.id,
              role: ChatRole.assistant,
              body: reply,
            );
            return reply;
          } catch (_) {
            // 直连失败静默回落云中继，不在气泡里刷「局域网连接失败」。
            _throwIfCancelled(isCancelled);
          }
        }
      }
      final relayKind = relayKindForConversation(conversation.id);
      String relayId = '';
      try {
        relayId = await _relayIdForSuperEmployeeDispatch();
      } on MobileRepositoryException catch (e) {
        _throwIfCancelled(isCancelled);
        final guidance = e.message.trim().ifEmpty(
          '当前没有在线的电脑执行端。请打开本机 XCAGI 并保持云中继运行后再试。',
        );
        onToken?.call(guidance);
        await _cacheChatMessage(
          conversation.id,
          role: ChatRole.assistant,
          body: guidance,
        );
        return guidance;
      }
      if (relayKind != null && relayId.isNotEmpty) {
        // 第 3 级：relay 中继轮询（跨网络，状态轮询模拟流式）
        final reply = await _streamRelaySuperEmployeeTask(
          relayId: relayId,
          relayKind: relayKind,
          conversationId: conversation.id,
          message: text,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
        );
        _throwIfCancelled(isCancelled);
        if (reply.trim().isNotEmpty) {
          await _cacheChatMessage(
            conversation.id,
            role: ChatRole.assistant,
            body: reply,
          );
        }
        return reply.ifEmpty('已收到，我会继续处理。');
      }
      // 无 LAN、无在线电脑中继时，禁止误打云端 POST（云端通常无本机 CLI，
      // 只会得到「请确认本机已登录」类误导文案）。引导用户绑定执行端。
      _throwIfCancelled(isCancelled);
      final toolLabel = conversation.title.trim().isEmpty
          ? '超级员工'
          : conversation.title.trim();
      final guidance = localBaseUrl.isEmpty
          ? '当前是云端模式，且没有在线的电脑执行端。'
              '请到「我 → 扫码绑定」连接本机 XCAGI，或同一 WiFi 下开启局域网直连后再调用 $toolLabel。'
              '（部分工具失败是账号额度不足，与 XCAGI 钱包无关；请在电脑端该工具里核对用量。）'
          : '局域网与云端中继均不可用，无法调用 $toolLabel。'
              '请确认电脑 FHD 在线，或重新扫码绑定后再试。';
      onToken?.call(guidance);
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.assistant,
        body: guidance,
      );
      return guidance;
    }

    final employeeRef = _employeeConversationRef(conversation.id);
    if (employeeRef != null) {
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.user,
        body: text,
      );
      final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
      final reply = await _client.streamEmployeeChat(
        message: text,
        employeeId: employeeRef.employeeId,
        modId: employeeRef.modId,
        conversationId: conversation.id,
        userId: effectiveUserId,
        onToken: onToken,
      );
      _throwIfCancelled(isCancelled);
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.assistant,
        body: reply,
      );
      return reply;
    }

    await _cacheChatMessage(
      conversation.id,
      role: ChatRole.user,
      body: text,
    );
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    final reply = await _client.streamChat(
      text,
      sessionId: conversation.id,
      userId: effectiveUserId,
      recentMessages: _recentChatContext(recentMessages),
      onToken: onToken,
    );
    _throwIfCancelled(isCancelled);
    await _cacheChatMessage(
      conversation.id,
      role: ChatRole.assistant,
      body: reply,
    );
    return reply;
  }

  Future<bool> hasInflightRelay(String conversationId) async {
    return _inflightRelayTask(conversationId).then((value) => value.isNotEmpty);
  }

  Future<String?> resumeRelayTask({
    required String conversationId,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final taskId = await _inflightRelayTask(conversationId);
    if (taskId.isEmpty) return null;
    if (await _clearInflightIfRelayChanged(conversationId, taskId)) {
      return null;
    }
    final kind = relayKindForConversation(conversationId);
    final toolLabel = toolLabelForRelayKind(kind ?? 'codex.invoke');
    onStatus?.call(RelayTaskProgress(
      taskId: taskId,
      status: 'resuming',
      toolLabel: toolLabel,
    ));
    onToken?.call('思考中...');
    final reply = await _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabel,
      conversationId: conversationId,
      onToken: onToken,
      onStatus: onStatus,
      isCancelled: isCancelled,
    );
    _throwIfCancelled(isCancelled);
    if (reply.trim().isNotEmpty) {
      await _cacheChatMessage(
        conversationId,
        role: ChatRole.assistant,
        body: reply,
      );
    }
    return reply;
  }

  Future<void> deleteCachedChatMessage({
    required String conversationId,
    required ChatMessage message,
  }) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final targetTs = message.cacheTimestampMs;
    if (targetTs <= 0) return;
    final session = await _client.loadSession();
    final rows = [
      ...(session.cachedChatMessages[id] ?? const <Map<String, Object?>>[]),
    ];
    if (rows.isEmpty) return;

    final index =
        rows.indexWhere((row) => _cachedChatTimestampMs(row) == targetTs);
    if (index < 0) return;
    rows.removeAt(index);

    final cache = Map<String, List<Map<String, Object?>>>.of(
      session.cachedChatMessages,
    );
    if (rows.isEmpty) {
      cache.remove(id);
    } else {
      cache[id] = rows;
    }
    await _client.saveSession(session.copyWith(cachedChatMessages: cache));
  }

  Future<int> _loadCurrentUserId() async {
    try {
      return (await loadMe()).user?.id ?? 0;
    } catch (_) {
      return 0;
    }
  }

  Future<String> runGitOperation({
    required String branch,
    required String op,
  }) async {
    final cleanBranch = branch.trim();
    final cleanOp = op.trim();
    if (cleanBranch.isEmpty) {
      throw const MobileRepositoryException('缺少分支名');
    }
    if (!const {
      'git.merge',
      'git.diff',
      'git.discard',
      'git.diff.structured',
      'git.log',
      'git.cancel',
    }.contains(cleanOp)) {
      throw MobileRepositoryException('未知 git 操作：$cleanOp');
    }

    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw MobileRepositoryException('未绑定电脑工具，无法执行 $cleanOp');
    }

    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: cleanOp,
      payload: {
        'branch': cleanBranch,
        'workspace_root': _xcmaxDefaultWorkspaceRoot,
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }

    var lastStatus = '';
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      lastStatus = currentStatus.ifEmpty(lastStatus);
      if (currentStatus == 'done' || currentStatus == 'completed') {
        return _relayTaskResultText(current).ifEmpty('电脑工具已完成任务。');
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('电脑工具执行失败'),
        );
      }
    }
    throw MobileRepositoryException(
      lastStatus.isEmpty
          ? '电脑工具暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。'
          : '电脑工具仍处于 $lastStatus，任务仍在后台运行，可稍后回到此会话查看。',
    );
  }

  /// 结构化 diff：返回 {files, base, branch, total_additions, total_deletions}。
  Future<Map<String, Object?>> runGitDiffStructured({
    required String branch,
  }) async {
    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw const MobileRepositoryException('未绑定电脑工具，无法查看改动');
    }
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: 'git.diff.structured',
      payload: {
        'branch': branch.trim(),
        'workspace_root': _xcmaxDefaultWorkspaceRoot,
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      if (currentStatus == 'done' || currentStatus == 'completed') {
        final result = _objectMap(current['result']);
        final structured = _objectMap(result['structured']);
        if (structured.isNotEmpty) return structured;
        return {
          'files': <Map<String, Object?>>[],
          'base': '',
          'branch': branch.trim(),
        };
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('查看改动失败'),
        );
      }
    }
    throw const MobileRepositoryException('查看改动超时，请稍后重试');
  }

  /// 分支 commit 列表：返回 {commits, base, branch}。
  Future<Map<String, Object?>> runGitLog({
    required String branch,
    int limit = 10,
  }) async {
    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw const MobileRepositoryException('未绑定电脑工具，无法查看提交');
    }
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: 'git.log',
      payload: {
        'branch': branch.trim(),
        'limit': limit,
        'workspace_root': _xcmaxDefaultWorkspaceRoot,
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      if (currentStatus == 'done' || currentStatus == 'completed') {
        final result = _objectMap(current['result']);
        final commits = result['commits'];
        return {
          'commits': commits is List ? commits : <Map<String, Object?>>[],
          'base': _stringField(result, 'base'),
          'branch': _stringField(result, 'branch').ifEmpty(branch.trim()),
        };
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('查看提交失败'),
        );
      }
    }
    throw const MobileRepositoryException('查看提交超时，请稍后重试');
  }

  /// 取消正在执行的 relay 任务。
  Future<bool> cancelRelayTask(String taskId) async {
    if (taskId.trim().isEmpty) return false;
    final response = await _client.relayCancelTask(taskId.trim());
    if (!response.success) return false;
    final task = _objectMap(response.data?['task']);
    return _stringField(task, 'status') == 'cancelled';
  }

  /// 从 relay task result 读取工具调用记录（dev-loop 时间线）。
  Future<List<Map<String, Object?>>> loadToolCalls(String taskId) async {
    if (taskId.trim().isEmpty) return const <Map<String, Object?>>[];
    final status = await _client.relayTaskStatus(taskId.trim());
    final taskMap = _objectMap(status.data?['task']);
    if (taskMap.isEmpty) return const <Map<String, Object?>>[];
    final result = _objectMap(taskMap['result']);
    final codex = _objectMap(result['codex']);
    final raw = codex['tool_calls'] ?? result['tool_calls'];
    if (raw is! List) return const <Map<String, Object?>>[];
    return raw
        .whereType<Map<String, Object?>>()
        .map((e) => Map<String, Object?>.from(e))
        .toList(growable: false);
  }

  /// 从 assistant 消息正文解析 dev-loop 工具调用记录。
  /// 与后端 `_extract_tool_calls` 的正则保持一致，避免无 task_id 时无法回顾。
  List<Map<String, Object?>> parseToolCallsFromBody(
    String body, {
    String toolLabel = '超级员工',
  }) {
    final text = body.trim();
    if (text.isEmpty || !text.contains('闭环结果')) {
      return const <Map<String, Object?>>[];
    }
    final calls = <Map<String, Object?>>[];
    final branchMatch = RegExp(r'分支[：:]\s*(\S+)').firstMatch(text);
    if (branchMatch != null) {
      final branch = branchMatch.group(1) ?? '';
      calls.add({
        'action': 'create_branch',
        'icon': 'branch',
        'label': '创建分支 $branch',
        'detail': branch,
      });
    }
    final verifyMatch =
        RegExp(r'验证[：:]\s*(通过|未通过)[（(]([^)）]*)').firstMatch(text);
    if (verifyMatch != null) {
      final ok = verifyMatch.group(1) == '通过';
      final detail = verifyMatch.group(2) ?? '';
      calls.add({
        'action': 'verify',
        'icon': 'check',
        'label': '验证${ok ? '通过' : '未通过'}',
        'detail': detail.length > 200 ? detail.substring(0, 200) : detail,
        'success': ok,
      });
    }
    final pushMatch = RegExp(r'推送[：:]\s*(.+?)(?:\n|$)').firstMatch(text);
    if (pushMatch != null) {
      final raw = (pushMatch.group(1) ?? '').trim();
      final pushText = raw.length > 200 ? raw.substring(0, 200) : raw;
      calls.add({
        'action': 'push',
        'icon': 'upload',
        'label': '推送分支',
        'detail': pushText,
        'success': pushText.contains('成功') || pushText.contains('已推送'),
      });
    }
    if (calls.isNotEmpty) {
      calls.insert(0, {
        'action': 'cli_run',
        'icon': 'terminal',
        'label': '$toolLabel CLI 执行',
        'detail': '调用无头 agent 修改代码',
      });
    }
    return calls;
  }

  Future<String> _postSuperEmployeeMessage(
    String tool,
    String text, {
    String baseUrl = '',
  }) async {
    final response = await _client.postSuperEmployeeMessage(
      tool,
      text,
      baseUrl: baseUrl,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工回复失败'));
    }
    return _assistantReplyFromMap(response.data ?? response.raw)
        .ifEmpty('已收到，我会继续处理。');
  }

  Future<String> _superEmployeeLanBaseUrl() async {
    final session = await _client.loadSession();
    if (session.serverMode.trim().toLowerCase() != 'lan') {
      return '';
    }
    // 无本机配对 JWT 时不要硬打局域网：云端 token 本机验签必 401，
    // 只会刷「局域网连接失败」再回落云中继。先走云中继，扫码一次后再直连。
    if (session.lanAccessToken.trim().isEmpty) {
      return '';
    }
    // 有缓存绑定就先用；仅缺地址时才向云端拉一次桌面 local_base_url（失效才刷新）。
    if (session.localBaseUrl.trim().isEmpty && session.fhdHost.trim().isEmpty) {
      await _refreshLanBindingFromRelayDesktops();
    }
    final refreshed = await _client.loadSession();
    final localBase = refreshed.localBaseUrl.trim();
    if (localBase.isNotEmpty) {
      return _lanReachableBaseFromStored(localBase);
    }
    final host = refreshed.fhdHost.trim();
    if (host.isEmpty) return '';
    // 后端 loopback 监听 17500 时手机不可达，需改用 vite proxy 端口 5011。
    // 若桌面已对局域网开放 17500，保留原端口（forceProxyPort=false）。
    return AndroidServerRouter(
      fhdHost: host,
      mode: AndroidServerMode.lan,
    ).lanReachableBaseUrl(forceProxyPort: false);
  }

  /// 把会话里存的局域网基址改写成手机可达地址。
  /// - 去掉云端路径前缀 `/fhd-api`（本机 Vite/FHD 无此前缀）
  /// - 保留已声明的局域网端口（含 17500）；仅当调用方显式要求时才改写到 Vite 代理
  String _lanReachableBaseFromStored(String rawBase) {
    final clean = rawBase.trim();
    if (clean.isEmpty) return '';
    final uri = Uri.tryParse(clean);
    if (uri == null || uri.host.isEmpty) {
      return _ensureTrailingSlash(clean);
    }
    final host = uri.host;
    final port =
        uri.hasPort ? uri.port : XcagiMobileTopology.desktopFhdListenPort;
    // 桌面已对局域网开放 17500 时不要强改 5011（Vite 常挂掉会导致「手机答不了」）。
    final usePort = port;
    var path = uri.path.trim();
    if (path == '/fhd-api' || path.startsWith('/fhd-api/')) {
      path = '';
    }
    final base = 'http://$host:$usePort';
    if (path.isEmpty || path == '/') return _ensureTrailingSlash(base);
    final suffix = path.startsWith('/') ? path : '/$path';
    return _ensureTrailingSlash('$base$suffix');
  }

  Future<void> _refreshLanBindingFromRelayDesktops() async {
    try {
      final response = await _client.relayDesktops();
      if (!response.success) return;
      final rows = _relayDesktopRows(response.data)
          .where(_relayDesktopIsDispatchable)
          .toList(growable: false);
      if (rows.isEmpty) return;
      rows.sort((a, b) => _relayDesktopSortKey(a).compareTo(
            _relayDesktopSortKey(b),
          ));
      final latest = rows.last;
      final relayId = _stringField(latest, 'relay_id');
      if (relayId.isEmpty) return;
      await _client.persistRelayBindingMeta(relayId, latest);
      final localBase = _stringField(latest, 'local_base_url');
      if (localBase.isEmpty) return;
      final hostPort = _hostPortFromApiBaseUrl(localBase);
      if (hostPort.isEmpty) return;
      final session = await _client.loadSession();
      if (session.fhdHost.trim() == hostPort &&
          session.localBaseUrl.trim() == localBase) {
        return;
      }
      await _client.saveSession(
        session.copyWith(
          fhdHost: hostPort,
          localBaseUrl: localBase,
        ),
      );
    } catch (_) {
      // 刷新失败仍用本地缓存地址尝试直连。
    }
  }

  Future<String> _streamRelaySuperEmployeeTask({
    required String relayId,
    required String relayKind,
    required String conversationId,
    required String message,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: relayKind,
      payload: {
        'message': message,
        'workspace_root': _xcmaxDefaultWorkspaceRoot,
        'context': _superEmployeeRelayContext(conversationId: conversationId),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('中继任务创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('中继任务缺少 task_id');
    }
    await _setInflightRelayTask(conversationId, taskId);
    final toolLabel = toolLabelForRelayKind(relayKind);
    onStatus?.call(RelayTaskProgress(
      taskId: taskId,
      status: 'queued',
      toolLabel: toolLabel,
    ));
    onToken?.call('思考中...');
    return _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabel,
      conversationId: conversationId,
      onToken: onToken,
      onStatus: onStatus,
      isCancelled: isCancelled,
    );
  }

  Future<String> _pollRelayTask({
    required String taskId,
    required String toolLabel,
    required String conversationId,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    var lastStatus = '';
    for (var attempt = 0; attempt < 150; attempt += 1) {
      _throwIfCancelled(isCancelled);
      await Future<void>.delayed(const Duration(seconds: 2));
      _throwIfCancelled(isCancelled);
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      _throwIfCancelled(isCancelled);
      if (currentStatus.isNotEmpty && currentStatus != lastStatus) {
        onStatus?.call(RelayTaskProgress(
          taskId: taskId,
          status: currentStatus,
          toolLabel: toolLabel,
        ));
        switch (currentStatus) {
          case 'running':
          case 'assigned':
            onToken?.call('\n电脑工具正在运行 $toolLabel。');
            break;
          case 'queued':
            onToken?.call('\n任务仍在服务器队列中。');
            break;
        }
        lastStatus = currentStatus;
      }
      if (currentStatus == 'done' || currentStatus == 'completed') {
        await _setInflightRelayTask(conversationId, '');
        onStatus?.call(RelayTaskProgress(
          taskId: taskId,
          status: 'completed',
          toolLabel: toolLabel,
        ));
        return _relayTaskResultText(current).ifEmpty('电脑工具已完成任务。');
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        await _setInflightRelayTask(conversationId, '');
        onStatus?.call(RelayTaskProgress(
          taskId: taskId,
          status: currentStatus,
          toolLabel: toolLabel,
        ));
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('电脑工具执行失败'),
        );
      }
    }
    throw const MobileRepositoryException(
      '电脑工具暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。',
    );
  }

  Future<List<OnboardingIndustry>> loadOnboardingIndustries() async {
    final response = await _client.onboardingIndustries();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('行业目录加载失败'));
    }
    final data = _nestedDataMap(response.data ?? const <String, Object?>{});
    final packages = _objectList(data['open_packages']);
    final items = packages
        .map(_onboardingIndustryFromPackage)
        .whereType<OnboardingIndustry>()
        .toList(growable: false);
    if (items.isNotEmpty) return items;
    return _stringList(data['open_industry_ids'])
        .map(
          (id) => OnboardingIndustry(
            id: id,
            title: id,
            subtitle: '可选行业',
          ),
        )
        .toList(growable: false);
  }

  Future<Map<String, Object?>> loadIndustryBaseline(String industryId) async {
    final response = await _client.industryBaseline(industryId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('行业基线加载失败'));
    }
    return _nestedDataMap(response.data ?? const <String, Object?>{});
  }

  Future<void> selectOnboardingIndustry(String industryId) async {
    final response = await _client.selectOnboardingIndustry(industryId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('行业绑定失败'));
    }
  }

  Future<String> bootstrapIndustry(String industryId) async {
    final industry = industryId.trim().isEmpty ? '通用' : industryId.trim();
    await selectOnboardingIndustry(industry);
    final host = await _client.installHostFoundation();
    if (!host.success) {
      throw MobileRepositoryException(host.message.ifEmpty('宿主基础包安装失败'));
    }
    final baseline = await loadIndustryBaseline(industry);
    if (_stringList(baseline['missing_industry_mod_ids']).isNotEmpty) {
      final seed = await _client.installIndustrySeed(industry);
      if (!seed.success) {
        throw MobileRepositoryException(seed.message.ifEmpty('行业包安装失败'));
      }
    }
    for (final modId
        in _stringList(baseline['missing_account_custom_mod_ids'])) {
      final install =
          await _client.installMod(modId: modId, industryId: industry);
      if (!install.success) {
        throw MobileRepositoryException(install.message.ifEmpty('$modId 安装失败'));
      }
    }
    for (final modId in _stringList(baseline['account_custom_mod_ids'])) {
      final seed = await _client.installCustomerDeliverySeed(
        modId: modId,
        industryId: industry,
      );
      if (!seed.success) {
        throw MobileRepositoryException(
            seed.message.ifEmpty('$modId 交付数据安装失败'));
      }
    }
    final after = await loadIndustryBaseline(industry);
    final ready = _boolField(after, 'full_stack_ready') ||
        _boolField(after, 'baseline_ready');
    return ready ? '行业能力已装齐' : '基础能力已安装，请刷新查看剩余项';
  }

  Future<List<MarketCapability>> loadMarketCapabilities() async {
    final response = await _client.mobileMods();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('市场能力加载失败'));
    }
    final data = _nestedDataMap(response.data ?? const <String, Object?>{});
    final rows = _firstObjectList([
      data['items'],
      data['mods'],
      data['installed'],
      data['results'],
      data['data'],
    ]);
    return rows
        .map(MarketCapability.fromJson)
        .where((item) => item.id.trim().isNotEmpty)
        .toList(growable: false);
  }

  Future<List<PaymentPlan>> loadPaymentPlans() async {
    final response = await _client.paymentPlans();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('套餐加载失败'));
    }
    final data = _nestedDataMap(response.data ?? const <String, Object?>{});
    final rows = _firstObjectList([
      data['plans'],
      data['items'],
      data['results'],
      data['data'],
    ]);
    return rows
        .map(PaymentPlan.fromJson)
        .where((plan) => plan.id.trim().isNotEmpty)
        .toList(growable: false);
  }

  Future<String> checkoutPaymentPlan({
    required String planId,
    String channel = 'mobile_h5',
  }) async {
    if (planId.trim().isEmpty) {
      throw const MobileRepositoryException('缺少套餐 ID');
    }
    final response = await _client.paymentCheckout({
      'channel': channel.trim().ifEmpty('mobile_h5'),
      'client': 'android',
      'return_url': 'xcagi://payment/complete',
      'plan_id': planId.trim(),
    });
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('支付下单失败'));
    }
    return _checkoutResultText(response.data ?? response.raw);
  }

  Future<String> checkoutWalletRecharge({
    String amountYuan = '50',
    String channel = 'mobile_h5',
  }) async {
    final amount = double.tryParse(amountYuan.trim()) ?? 0;
    if (amount <= 0) {
      throw const MobileRepositoryException('请输入有效充值金额');
    }
    final response = await _client.paymentCheckout({
      'channel': channel.trim().ifEmpty('mobile_h5'),
      'client': 'android',
      'return_url': 'xcagi://payment/complete',
      'wallet_recharge': true,
      'total_amount': amount,
      'subject': '手机钱包充值',
    });
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('充值下单失败'));
    }
    return _checkoutResultText(response.data ?? response.raw);
  }

  Future<void> installMarketMod(String modId,
      {String industryId = '通用'}) async {
    if (modId.trim().isEmpty) {
      throw const MobileRepositoryException('缺少 Mod ID');
    }
    final response = await _client.installMod(
      modId: modId,
      industryId: industryId,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('$modId 安装失败'));
    }
  }

  Future<List<ApprovalRequest>> loadApprovals() async {
    final response = await _client.approvals();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('审批加载失败'));
    }
    final data = _nestedDataMap(response.data ?? const <String, Object?>{});
    final rows = _firstObjectList([
      data['items'],
      data['requests'],
      data['results'],
      data['data'],
    ]);
    return rows
        .map(ApprovalRequest.fromJson)
        .where((item) => item.id > 0 || item.title.trim().isNotEmpty)
        .toList(growable: false);
  }

  Future<ApprovalDetail> loadApprovalDetail(int id) async {
    final body = await _client.approvalDetail(id);
    final data = _nestedDataMap(body);
    final request = _objectMap(data['request']);
    final row = request.isNotEmpty ? request : data;
    return ApprovalDetail.fromJson(row, fallbackId: id);
  }

  Future<void> approveApproval(int id, String opinion) async {
    await _client.approveApproval(id: id, approverId: 0, opinion: opinion);
  }

  Future<void> rejectApproval(int id, String reason) async {
    await _client.rejectApproval(id: id, approverId: 0, reason: reason);
  }

  Future<List<EmployeePendingQuestion>> loadEmployeePendingQuestions({
    int limit = 100,
    bool includeHistory = false,
    String? employeeId,
  }) async {
    final response = await _client.employeePendingQuestions(
      limit: limit,
      includeHistory: includeHistory,
      employeeId: employeeId,
    );
    if (!response.success) {
      throw MobileRepositoryException(
        response.message.ifEmpty('加载员工提问失败'),
      );
    }
    final data = response.data ?? const <String, Object?>{};
    final rows = _firstObjectList([data['items']]);
    return rows.map(EmployeePendingQuestion.fromJson).toList(growable: false);
  }

  Future<void> answerEmployeePendingQuestion({
    required int questionId,
    required String answer,
  }) async {
    final text = answer.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('回答不能为空');
    }
    final response = await _client.answerEmployeePendingQuestion(
      questionId: questionId,
      answer: text,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('回答失败'));
    }
  }

  Future<void> connectImWebSocket() async {
    final session = await _client.loadSession();
    final sessionId = session.sessionId.trim();
    if (sessionId.isEmpty) return;
    final url = await _imWebSocketUrl(sessionId);
    _imWebSocketSubscription ??= _imWebSocket.events.listen((_) {});
    _imWebSocket.connect(sessionId: sessionId, url: url);
  }

  void disconnectImWebSocket() {
    _imWebSocket.disconnect();
  }

  Future<String> _imWebSocketUrl(String sessionId) async {
    final session = await _client.loadSession();
    final host = session.fhdHost.trim();
    final mode = session.serverMode.trim().toLowerCase() == 'lan'
        ? AndroidServerMode.lan
        : AndroidServerMode.cloud;
    return AndroidServerRouter(
      fhdHost: host.isNotEmpty ? host : '127.0.0.1',
      mode: mode,
      enterpriseFhdBaseUrlRaw: MobileAndroidBuild.enterpriseFhdBaseUrl,
      modstoreBaseUrlRaw: MobileAndroidBuild.modstoreBaseUrl,
    ).fhdImWebSocketUrl(sessionId);
  }

  Future<int> openImDirect(int peerUserId) async {
    if (peerUserId <= 0) {
      throw const MobileRepositoryException('请输入有效用户 ID');
    }
    final body = await _client.imCreateDirect(peerUserId);
    final data = _nestedDataMap(body);
    final conversation = _objectMap(data['conversation']);
    final id = _intField(conversation.isNotEmpty ? conversation : data, 'id');
    if (id <= 0) {
      throw const MobileRepositoryException('会话创建成功但缺少会话 ID');
    }
    return id;
  }

  Future<List<ImMessage>> loadImMessages(int conversationId) async {
    if (conversationId <= 0) return const <ImMessage>[];
    final body = await _client.imListMessages(conversationId);
    final data = _nestedDataMap(body);
    final rows = _firstObjectList([
      data['messages'],
      data['items'],
      data['results'],
      data['data'],
    ]);
    return rows.map(ImMessage.fromJson).toList(growable: false);
  }

  Future<ImMessage> sendImMessage({
    required int conversationId,
    required String body,
  }) async {
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }
    final response = await _client.imSendMessage(
      conversationId: conversationId,
      body: text,
    );
    final data = _nestedDataMap(response);
    final message = _objectMap(data['message']);
    if (message.isNotEmpty) return ImMessage.fromJson(message);
    return ImMessage(
      id: DateTime.now().microsecondsSinceEpoch,
      senderUserId: 0,
      body: text,
      createdAt: '刚刚',
    );
  }

  Future<List<BusinessListItem>> loadCustomers() async {
    final response = await _client.customers();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('客户加载失败'));
    }
    return _businessItemsFromData(response.data);
  }

  Future<List<BusinessListItem>> loadShipments() async {
    final response = await _client.shipments();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('发货加载失败'));
    }
    return _businessItemsFromData(response.data);
  }

  Future<List<BusinessListItem>> loadInventory() async {
    final body = await _client.inventoryItems();
    final data = _nestedDataMap(body);
    final rows = _firstObjectList([
      data['items'],
      data['data'],
      data['results'],
    ]);
    if (rows.isNotEmpty) {
      return rows.map(BusinessListItem.fromJson).toList(growable: false);
    }
    final raw = data['items'] ?? data['data'];
    if (raw is List) {
      return raw
          .map((item) => BusinessListItem(
                id: item.toString(),
                title: item.toString(),
                subtitle: '',
              ))
          .toList(growable: false);
    }
    return const <BusinessListItem>[];
  }

  Future<List<BusinessListItem>> loadBridgeRequests({
    String? status,
    String? requestType,
  }) async {
    try {
      final response = await _client.bridgeRequests(
        status: status,
        requestType: requestType,
      );
      if (!response.success) {
        throw MobileRepositoryException(
          response.message.ifEmpty('移动端服务桥接请求列表加载失败'),
        );
      }
      return _bridgeItemsFromData(response.data);
    } on MobileApiException catch (error) {
      if (error.statusCode != 404) rethrow;
      final legacy = await _client.legacyBridgeRequests(
        status: status,
        requestType: requestType,
      );
      return _bridgeItemsFromData(_nestedDataMap(legacy));
    }
  }

  Future<void> respondBridgeRequest({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) async {
    final text = response.trim();
    if (id <= 0) {
      throw const MobileRepositoryException('请先选择工单');
    }
    if (text.isEmpty) {
      throw const MobileRepositoryException('回复不能为空');
    }
    try {
      final result = await _client.bridgeRespond(
        id: id,
        response: text,
        respondedBy: respondedBy,
      );
      if (!result.success) {
        throw MobileRepositoryException(result.message.ifEmpty('回复失败'));
      }
    } on MobileApiException catch (error) {
      if (error.statusCode != 404) rethrow;
      await _client.legacyBridgeRespond(
        id: id,
        response: text,
        respondedBy: respondedBy,
      );
    }
  }

  Future<String> loadFinanceSummary() async {
    final body = await _client.financeSummary();
    return body.toString();
  }

  List<ConversationItem> fallbackConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) {
    return _sortConversationItems([
      ..._fixedConversationItems(
        showCodex: enterpriseMode || adminMode,
        showCursor: enterpriseMode || adminMode,
        showClaude: enterpriseMode || adminMode,
        showTrae: enterpriseMode || adminMode,
        showCustomerService: enterpriseMode && !adminMode,
        states: _emptyConversationStates,
      ),
      if (adminMode) ...adminDutyRosterConversationItems(),
    ]);
  }

  Future<String> _relayIdForSuperEmployeeDispatch() async {
    final session = await _client.loadSession();
    final storedRelayId = session.relayDesktopId.trim();
    try {
      final response = await _client.relayDesktops();
      if (!response.success) return storedRelayId;
      final rows = _relayDesktopRows(response.data)
          .where(_relayDesktopIsDispatchable)
          .toList(growable: false);
      // API 正常但账号下尚无 paired 桌面：不要误用 build 注入/历史 relay_id 去排队。
      if (rows.isEmpty) return '';

      // 与 Android 对齐：status=paired 即可派工；last_seen 只影响排序。
      if (storedRelayId.isNotEmpty) {
        for (final row in rows) {
          if (_stringField(row, 'relay_id') == storedRelayId) {
            return storedRelayId;
          }
        }
      }

      rows.sort((a, b) => _relayDesktopSortKey(a).compareTo(
            _relayDesktopSortKey(b),
          ));
      final latest = rows.last;
      final latestRelayId = _stringField(latest, 'relay_id');
      if (latestRelayId.isEmpty) return '';
      if (latestRelayId != storedRelayId) {
        await _client.persistRelayBindingMeta(latestRelayId, latest);
      }
      return latestRelayId;
    } on MobileRepositoryException {
      rethrow;
    } catch (_) {
      return storedRelayId;
    }
  }

  Future<String> _inflightRelayTask(String conversationId) async {
    final session = await _client.loadSession();
    return session.inflightRelayTasks[conversationId.trim()]?.trim() ?? '';
  }

  Future<void> _setInflightRelayTask(
    String conversationId,
    String taskId,
  ) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final session = await _client.loadSession();
    final tasks = Map<String, String>.of(session.inflightRelayTasks);
    final cleanTaskId = taskId.trim();
    if (cleanTaskId.isEmpty) {
      tasks.remove(id);
    } else {
      tasks[id] = cleanTaskId;
    }
    await _client.saveSession(session.copyWith(inflightRelayTasks: tasks));
  }

  Future<bool> _clearInflightIfRelayChanged(
    String conversationId,
    String taskId,
  ) async {
    final currentRelayId = await _relayIdForSuperEmployeeDispatch();
    if (currentRelayId.isEmpty) {
      await _setInflightRelayTask(conversationId, '');
      return true;
    }
    final status = await _client.relayTaskStatus(taskId);
    final taskMap = _objectMap(status.data?['task']);
    final current =
        taskMap.isNotEmpty ? taskMap : status.data ?? const <String, Object?>{};
    final taskRelayId = _stringField(current, 'relay_id');
    if (taskRelayId.isEmpty || taskRelayId == currentRelayId) return false;
    await _setInflightRelayTask(conversationId, '');
    return true;
  }

  Future<List<ChatMessage>> _loadCachedChat(String conversationId) async {
    final session = await _client.loadSession();
    final rows = session.cachedChatMessages[conversationId.trim()];
    if (rows == null || rows.isEmpty) return const [];
    return rows.map(_chatMessageFromCache).whereType<ChatMessage>().toList();
  }

  Future<void> _cacheChatMessage(
    String conversationId, {
    required ChatRole role,
    required String body,
  }) async {
    final id = conversationId.trim();
    final text = body.trim();
    if (id.isEmpty || text.isEmpty) return;
    final session = await _client.loadSession();
    final cache = Map<String, List<Map<String, Object?>>>.of(
      session.cachedChatMessages,
    );
    final rows = [...(cache[id] ?? const <Map<String, Object?>>[])];
    final now = DateTime.now();
    final timestampMs = now.millisecondsSinceEpoch;
    rows.add({
      'id': 'cache-$timestampMs',
      'conversation_id': id,
      'role': role.name,
      'body': text,
      'time_text': now.toIso8601String(),
      'ts': timestampMs,
      'has_employee_profile': role == ChatRole.assistant,
      'status': ChatDeliveryStatus.sent.name,
    });
    cache[id] = rows.length > 80
        ? rows.sublist(rows.length - 80).toList(growable: false)
        : rows;
    final states = Map<String, Map<String, Object?>>.of(
      session.conversationListStates,
    );
    states[id] = _ConversationListState(
      preview: _conversationPreviewForRole(role, text),
      timestampMs: timestampMs,
    ).toJson();
    await _client.saveSession(
      session.copyWith(
        cachedChatMessages: cache,
        conversationListStates: states,
      ),
    );
  }
}

Map<String, Object?> _superEmployeeRelayContext({
  String conversationId = '',
}) {
  return {
    'source': 'mobile_chat',
    'client_surface': 'mobile',
    'workspace_root': _xcmaxDefaultWorkspaceRoot,
    if (conversationId.trim().isNotEmpty)
      'conversation_id': conversationId.trim(),
  };
}

PairingPayload? parsePairingPayload(String raw) {
  final text = raw.trim();
  if (text.isEmpty || text.toLowerCase().contains('auth-qr')) {
    return null;
  }
  if (text.length == 6 && int.tryParse(text) != null) {
    return PairingPayload(code: text, token: text, version: 2);
  }

  final uri = Uri.tryParse(text);
  if (uri != null && uri.scheme.toLowerCase() == 'xcagi') {
    final route = '${uri.host}${uri.path}';
    if (!route.toLowerCase().contains('pair')) {
      return null;
    }
    final code = _firstNonBlank([
      uri.queryParameters['code'] ?? '',
      uri.queryParameters['shortCode'] ?? '',
      uri.queryParameters['short_code'] ?? '',
      uri.queryParameters['token'] ?? '',
    ]);
    final apiBaseUrl = _firstNonBlank([
      uri.queryParameters['api_base_url'] ?? '',
      uri.queryParameters['api_base'] ?? '',
      uri.queryParameters['base_url'] ?? '',
    ]);
    final fromBase = _pairingHostPortFromApiBase(apiBaseUrl);
    final host = _normalizePairingHost(
      (uri.queryParameters['host'] ?? '').ifEmpty(fromBase.$1),
    );
    final port =
        (int.tryParse(uri.queryParameters['port'] ?? '') ?? fromBase.$2)
            .takeIfValidPort();
    final relayId = _firstNonBlank([
      uri.queryParameters['relay_id'] ?? '',
      uri.queryParameters['relayId'] ?? '',
    ]);
    final relayBaseUrl = _firstNonBlank([
      uri.queryParameters['relay_base_url'] ?? '',
      uri.queryParameters['relayBaseUrl'] ?? '',
    ]);
    if (relayId.isNotEmpty && code.isNotEmpty) {
      return PairingPayload(
        code: code,
        token: code,
        relayId: relayId,
        relayBaseUrl: relayBaseUrl,
        version: 3,
      );
    }
    if (code.isNotEmpty) {
      return PairingPayload(
        nonce: uri.queryParameters['nonce']?.trim() ?? '',
        code: code,
        token: code,
        host: host,
        port: port,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    final nonce = uri.queryParameters['nonce']?.trim() ?? '';
    if (nonce.length >= 8 && host.isNotEmpty && port > 0) {
      return PairingPayload(
        nonce: nonce,
        host: host,
        port: port,
        apiBaseUrl: apiBaseUrl,
        version: 1,
      );
    }
    return null;
  }

  final jsonLike = _tryDecodeObject(text);
  if (jsonLike.isNotEmpty) {
    final version = _intField(jsonLike, 'v').ifZero(1);
    final kind = _stringField(jsonLike, 'kind').toLowerCase();
    final relayId = _firstNonBlank([
      _stringField(jsonLike, 'relay_id'),
      _stringField(jsonLike, 'relayId'),
    ]);
    final relayBaseUrl = _firstNonBlank([
      _stringField(jsonLike, 'relay_base_url'),
      _stringField(jsonLike, 'relayBaseUrl'),
    ]);
    final code = _firstNonBlank([
      _stringField(jsonLike, 't'),
      _stringField(jsonLike, 'code'),
      _stringField(jsonLike, 'shortCode'),
      _stringField(jsonLike, 'short_code'),
      _stringField(jsonLike, 'token'),
    ]);
    if ((version >= 3 || kind.contains('relay')) &&
        relayId.isNotEmpty &&
        code.isNotEmpty) {
      return PairingPayload(
        code: code,
        token: code,
        relayId: relayId,
        relayBaseUrl: relayBaseUrl,
        version: 3,
      );
    }
    final apiBaseUrl = _firstNonBlank([
      _stringField(jsonLike, 'api_base_url'),
      _stringField(jsonLike, 'base_url'),
      _stringField(jsonLike, 'apiBaseUrl'),
    ]);
    final fromBase = _pairingHostPortFromApiBase(apiBaseUrl);
    final host = _normalizePairingHost(
      _stringField(jsonLike, 'host').ifEmpty(fromBase.$1),
    );
    final port = _pairingPort(jsonLike, host).ifZero(fromBase.$2);
    final bareHost = host.split(':').first.trim();
    final hasHostPort = bareHost.isNotEmpty && port.takeIfValidPort() > 0;
    if ((version >= 2 || kind.contains('pairing')) && code.isNotEmpty) {
      return PairingPayload(
        nonce: _stringField(jsonLike, 'nonce'),
        code: code,
        token: code,
        host: hasHostPort ? bareHost : '',
        port: hasHostPort ? port.takeIfValidPort() : 0,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    final nonce = _stringField(jsonLike, 'nonce');
    if (version >= 2 || kind.contains('pairing')) {
      if (nonce.isEmpty) return null;
      return PairingPayload(
        nonce: nonce,
        token: nonce,
        host: hasHostPort ? bareHost : '',
        port: hasHostPort ? port.takeIfValidPort() : 0,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    if (nonce.length >= 8 && hasHostPort) {
      return PairingPayload(
        nonce: nonce,
        host: bareHost,
        port: port.takeIfValidPort(),
        version: 1,
      );
    }
  }

  return null;
}

AuthQrPayload? parseAuthQrPayload(String raw) {
  final text = raw.trim();
  if (!text.contains('auth-qr')) return null;
  final uri = Uri.tryParse(text);
  if (uri == null) return null;
  final qrId = uri.queryParameters['qr_id']?.trim() ?? '';
  if (qrId.isEmpty) return null;
  return AuthQrPayload(
    qrId: qrId,
    accountKind:
        (uri.queryParameters['account_kind'] ?? '').trim().toLowerCase(),
  );
}

List<Map<String, Object?>> _relayDesktopRows(Map<String, Object?>? data) {
  final raw = data?['items'] ?? data?['desktops'] ?? data?['results'];
  return _objectList(raw);
}

List<ModInfo> _parseModInfos(Map<String, Object?> body) {
  final data = _nestedDataMap(body);
  final nestedData = _objectMap(data['data']);
  final rows = _firstObjectList([
    nestedData['items'],
    nestedData['mods'],
    nestedData['installed'],
    data['items'],
    data['mods'],
    data['installed'],
  ]);
  return rows.map(ModInfo.fromJson).toList(growable: false);
}

/// Session cache only needs list-row fields; avoid bloating xcagi_session.json.
Map<String, Object?> _modInfoToCacheJson(ModInfo mod) {
  return {
    'id': mod.id,
    'name': mod.name,
    'version': mod.version,
    'description': mod.description,
    'author': mod.author,
    'primary': mod.primary,
    'industry': mod.industry == null
        ? null
        : {
            'id': mod.industry!.id,
            'name': mod.industry!.name,
          },
    'workflow_employees': mod.workflowEmployees
        .map(
          (employee) => {
            'id': employee.id,
            'label': employee.label,
            'panel_title': employee.panelTitle,
            'panel_summary': employee.panelSummary,
            'api_base_path': employee.apiBasePath,
            'phone_channel': employee.phoneChannel,
            'profile_source': employee.profileSource,
          },
        )
        .toList(growable: false),
  }..removeWhere((_, value) => value == null);
}

bool _relayDesktopIsDispatchable(Map<String, Object?> row) {
  final relayId = _stringField(row, 'relay_id');
  final status = _stringField(row, 'status').toLowerCase();
  // 与 Kotlin 一致：账号下 status=paired 即可派工；last_seen 只影响排序，不阻断中继。
  // 否则桌面轮询稍停就会误走云端 /admin/*-super-employee（服务器 CLI），而非 cursor.invoke 本机执行。
  return relayId.isNotEmpty && status == 'paired';
}

bool _relayDesktopIsFresh(Map<String, Object?> row) {
  final lastSeen = _firstNonBlank([
    _stringField(row, 'last_seen_at'),
    _stringField(row, 'updated_at'),
  ]);
  if (lastSeen.isEmpty) return false;
  final parsed = DateTime.tryParse(lastSeen)?.toUtc();
  if (parsed == null) return false;
  final age = DateTime.now().toUtc().difference(parsed);
  if (age.isNegative) return true;
  return age <= const Duration(minutes: 5);
}

String _relayDesktopSortKey(Map<String, Object?> row) {
  return _firstNonBlank([
    _stringField(row, 'last_seen_at'),
    _stringField(row, 'updated_at'),
    _stringField(row, 'paired_at'),
  ]);
}

String _relayTaskResultText(Map<String, Object?> task) {
  final result = _objectMap(task['result']);
  if (result.isEmpty) return '';
  final error = _stringField(result, 'error');
  if (error.isNotEmpty) return error;
  final codex = _objectMap(result['codex']);
  final assistant = _objectMap(codex['assistant_message']);
  final body = _stringField(assistant, 'body');
  if (body.isNotEmpty) return body;
  return _stringField(result, 'reply');
}

class AuthQrPayload {
  const AuthQrPayload({
    required this.qrId,
    required this.accountKind,
  });

  final String qrId;
  final String accountKind;
}

class OnboardingIndustry {
  const OnboardingIndustry({
    required this.id,
    required this.title,
    required this.subtitle,
  });

  final String id;
  final String title;
  final String subtitle;
}

class MarketCapability {
  const MarketCapability({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory MarketCapability.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'mod_id'),
      _stringField(json, 'pkg_id'),
      _stringField(json, 'slug'),
    ]);
    return MarketCapability(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'name'),
        _stringField(json, 'title'),
        _stringField(json, 'label'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'description'),
        _stringField(json, 'summary'),
        _stringField(json, 'subtitle'),
        _stringField(json, 'version'),
        '从企业端同步的能力包',
      ]),
      payload: json,
    );
  }
}

class PaymentPlan {
  const PaymentPlan({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory PaymentPlan.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'plan_id'),
      _stringField(json, 'sku'),
    ]);
    final cents = _firstNonBlank([
      _stringField(json, 'amount_cents'),
      _stringField(json, 'price_cents'),
    ]);
    return PaymentPlan(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'name'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'description'),
        cents.isNotEmpty ? _formatCents(cents) : '',
        '模型服务套餐',
      ]),
      payload: json,
    );
  }
}

class ApprovalRequest {
  const ApprovalRequest({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.status,
    required this.applicantName,
    this.payload = const <String, Object?>{},
  });

  final int id;
  final String title;
  final String subtitle;
  final String status;
  final String applicantName;
  final Map<String, Object?> payload;

  factory ApprovalRequest.fromJson(Map<String, Object?> json) {
    final id = _intField(json, 'id');
    final status = _firstNonBlank([
      _stringField(json, 'status'),
      _stringField(json, 'state'),
    ]);
    final applicant = _firstNonBlank([
      _stringField(json, 'applicant_name'),
      _stringField(json, 'applicant'),
      _stringField(json, 'requester_name'),
    ]);
    return ApprovalRequest(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'flow_name'),
        _stringField(json, 'request_no'),
        id > 0 ? '#$id' : '',
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'subtitle'),
        applicant,
        _stringField(json, 'description'),
      ]),
      status: status,
      applicantName: applicant,
      payload: json,
    );
  }
}

class ApprovalDetail {
  const ApprovalDetail({
    required this.id,
    required this.requestNo,
    required this.title,
    required this.status,
    required this.applicantName,
    required this.flowName,
    required this.currentNodeName,
    required this.submittedAt,
    required this.description,
    this.payload = const <String, Object?>{},
  });

  final int id;
  final String requestNo;
  final String title;
  final String status;
  final String applicantName;
  final String flowName;
  final String currentNodeName;
  final String submittedAt;
  final String description;
  final Map<String, Object?> payload;

  bool get canAct {
    final normalized = status.trim().toLowerCase();
    return normalized.contains('pending') ||
        normalized.contains('wait') ||
        status.contains('待');
  }

  factory ApprovalDetail.fromJson(
    Map<String, Object?> json, {
    int fallbackId = 0,
  }) {
    final id = _intField(json, 'id');
    final resolvedId = id > 0 ? id : fallbackId;
    final requestNo = _firstNonBlank([
      _stringField(json, 'request_no'),
      _stringField(json, 'no'),
      resolvedId > 0 ? '#$resolvedId' : '',
    ]);
    final flowName = _firstNonBlank([
      _stringField(json, 'flow_name'),
      _stringField(json, 'flow'),
    ]);
    return ApprovalDetail(
      id: resolvedId,
      requestNo: requestNo,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        flowName,
        requestNo,
        '审批详情',
      ]),
      status: _firstNonBlank([
        _stringField(json, 'status'),
        _stringField(json, 'state'),
      ]),
      applicantName: _firstNonBlank([
        _stringField(json, 'applicant_name'),
        _stringField(json, 'applicant'),
        _stringField(json, 'requester_name'),
      ]),
      flowName: flowName,
      currentNodeName: _firstNonBlank([
        _stringField(json, 'current_node_name'),
        _stringField(json, 'node_name'),
      ]),
      submittedAt: _firstNonBlank([
        _stringField(json, 'submitted_at'),
        _stringField(json, 'created_at'),
        _stringField(json, 'updated_at'),
      ]),
      description: _firstNonBlank([
        _stringField(json, 'description'),
        _stringField(json, 'remark'),
        _stringField(json, 'summary'),
        _stringField(json, 'reason'),
      ]),
      payload: json,
    );
  }
}

class ImMessage {
  const ImMessage({
    required this.id,
    required this.senderUserId,
    required this.body,
    required this.createdAt,
  });

  final int id;
  final int senderUserId;
  final String body;
  final String createdAt;

  bool get mine => senderUserId <= 0;

  factory ImMessage.fromJson(Map<String, Object?> json) {
    return ImMessage(
      id: _intField(json, 'id').ifZero(_intField(json, 'message_id')),
      senderUserId: _intField(json, 'sender_user_id'),
      body: _firstNonBlank([
        _stringField(json, 'body'),
        _stringField(json, 'content'),
        _stringField(json, 'text'),
      ]),
      createdAt: _firstNonBlank([
        _stringField(json, 'created_at'),
        _stringField(json, 'timestamp'),
        '刚刚',
      ]),
    );
  }
}

class BusinessListItem {
  const BusinessListItem({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory BusinessListItem.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'uuid'),
      _stringField(json, 'order_number'),
      _stringField(json, 'sku'),
    ]);
    return BusinessListItem(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'name'),
        _stringField(json, 'order_number'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'status'),
        _stringField(json, 'subtitle'),
        _stringField(json, 'description'),
      ]),
      payload: json,
    );
  }
}

class PairingPayload {
  const PairingPayload({
    this.host = '',
    this.port = 0,
    this.nonce = '',
    this.code = '',
    this.token = '',
    this.apiBaseUrl = '',
    this.relayId = '',
    this.relayBaseUrl = '',
    this.version = 1,
  });

  final String host;
  final int port;
  final String nonce;
  final String code;
  final String token;
  final String apiBaseUrl;
  final String relayId;
  final String relayBaseUrl;
  final int version;

  String get hostWithPort => _compactPairingHostPort(host, port);
}

Map<String, Object?> _tryDecodeObject(String text) {
  try {
    final decoded = jsonDecode(text);
    return _objectMap(decoded);
  } catch (_) {
    return const <String, Object?>{};
  }
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) return trimmed;
  }
  return '';
}

String _pairingLanBaseUrl(String host, int port) {
  final hostWithPort = _compactPairingHostPort(host, port);
  if (hostWithPort.isEmpty) return '';
  return 'http://$hostWithPort/';
}

String _pairingLanBaseUrlFromHostPort(String hostWithPort) {
  final normalized = _normalizePairingHost(hostWithPort);
  if (normalized.isEmpty) return '';
  final parts = normalized.split(':');
  final host = parts.first.trim();
  if (host.isEmpty) return '';
  int port = 0;
  if (parts.length > 1) {
    port = (int.tryParse(parts.last.trim()) ?? 0).takeIfValidPort();
  }
  final cleanPort = port > 0 ? port : MobileAndroidBuild.fhdDefaultPort;
  return 'http://$host:$cleanPort/';
}

String _hostPortFromApiBaseUrl(String raw) {
  final (host, port) = _pairingHostPortFromApiBase(raw);
  return _compactPairingHostPort(host, port);
}

String _readStringMap(Map<String, Object?>? data, List<String> keys) {
  if (data == null || data.isEmpty) return '';
  for (final key in keys) {
    final value = data[key]?.toString().trim() ?? '';
    if (value.isNotEmpty) return value;
  }
  return '';
}

String _compactPairingHostPort(String host, int port) {
  final bare = _normalizePairingHost(host).split(':').first.trim();
  final cleanPort = port.takeIfValidPort();
  if (bare.isEmpty) return '';
  if (cleanPort == 0) return bare;
  return '$bare:$cleanPort';
}

String _normalizePairingHost(String host) {
  return host
      .trim()
      .replaceFirst(RegExp(r'^https?://'), '')
      .split('/')
      .first
      .trim();
}

int _pairingPort(Map<String, Object?> json, String host) {
  final explicit = _intField(json, 'port').takeIfValidPort();
  if (explicit > 0) return explicit;
  if (!host.contains(':')) return 0;
  return (int.tryParse(host.split(':').last.trim()) ?? 0).takeIfValidPort();
}

(String, int) _pairingHostPortFromApiBase(String raw) {
  if (raw.trim().isEmpty) return ('', 0);
  final normalized = raw.contains('://') ? raw.trim() : 'http://${raw.trim()}';
  final uri = Uri.tryParse(normalized);
  if (uri == null) return ('', 0);
  final host = uri.host.trim();
  if (host.isEmpty) return ('', 0);
  final port = uri.hasPort
      ? uri.port.takeIfValidPort()
      : switch (uri.scheme.toLowerCase()) {
          'https' => 443,
          'http' => 80,
          _ => 0,
        };
  return (host, port);
}

String _relayIdFromBindingData(Map<String, Object?>? data) {
  final payload = data ?? const <String, Object?>{};
  return _firstNonBlank([
    _stringField(payload, 'relay_id'),
    _stringField(_objectMap(payload['relay']), 'relay_id'),
    _stringField(_objectMap(payload['desktop']), 'relay_id'),
  ]);
}

List<AiGroupConversation> _parseAiGroups(Object? value) {
  final data = _objectMap(value);
  final rawGroups = data['groups'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(rawGroups)
      .map(_aiGroupFromJson)
      .where((group) => group.id.trim().isNotEmpty)
      .toList(growable: false);
}

AiGroupConversation _aiGroupFromJson(Map<String, Object?> json) {
  final lastMessageAt = _stringField(json, 'last_message_at');
  return AiGroupConversation(
    id: _stringField(json, 'id'),
    name: _stringField(json, 'name'),
    memberCount: _intField(json, 'member_count'),
    preview: _aiGroupPreview(_stringField(json, 'last_message_preview')),
    timestampText: _friendlyGroupTimestamp(lastMessageAt),
    timestampMs: _timestampMsFromValue(json['last_message_at']),
    unreadCount: _intField(json, 'unread_count'),
    isPinned: _boolField(json, 'is_pinned'),
    isHidden: _boolField(json, 'is_hidden'),
    isFollowed: _boolField(json, 'is_followed', fallback: true),
    members: _objectList(json['members'])
        .map(
          (member) => AiGroupMember(
            employeeId: _stringField(member, 'employee_id'),
            modId: _stringField(member, 'mod_id'),
            name: _stringField(member, 'name'),
            summary: _stringField(member, 'summary'),
            avatarUrl: _stringField(member, 'avatar').ifEmpty(''),
            avatarKey: _stringField(member, 'avatar_key'),
          ),
        )
        .toList(growable: false),
  );
}

int _timestampMsFromValue(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return 0;
    final numeric = int.tryParse(trimmed);
    if (numeric != null) return numeric;
    final parsed = DateTime.tryParse(trimmed);
    if (parsed != null) return parsed.toLocal().millisecondsSinceEpoch;
  }
  return 0;
}

String _aiGroupPreview(String raw) {
  final text = raw.trim();
  if (text.isEmpty) return '';
  if (text.contains('服务器队列') ||
      text.contains('任务仍在后台运行') ||
      (text.contains('状态：排队中') && text.contains('任务号'))) {
    return '';
  }
  return text;
}

AiGroupConversation? _groupFromWrap(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final group = _objectMap(data['group']);
  if (group.isNotEmpty) return _aiGroupFromJson(group);
  if (data['id'] != null) return _aiGroupFromJson(data);
  return null;
}

List<AiGroupMessage> _parseAiGroupMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(_aiGroupMessageFromJson)
      .where((message) =>
          message.id.trim().isNotEmpty || message.body.trim().isNotEmpty)
      .toList(growable: false);
}

AiGroupPostResult _parseAiGroupPostResult(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  return AiGroupPostResult(
    group: _groupFromWrap(data),
    messages: _parseAiGroupMessages(data),
  );
}

AiGroupMessage _aiGroupMessageFromJson(Map<String, Object?> json) {
  final role = _stringField(json, 'role').trim().toLowerCase();
  return AiGroupMessage(
    id: _stringField(json, 'id'),
    groupId: _stringField(json, 'group_id'),
    role: role == 'user'
        ? AiGroupMessageRole.user
        : role == 'system'
            ? AiGroupMessageRole.system
            : AiGroupMessageRole.ai,
    senderId: _stringField(json, 'sender_id'),
    senderName: _stringField(json, 'sender_name').ifEmpty('AI员工'),
    senderAvatar: _nullableStringField(json, 'sender_avatar'),
    body: _firstNonBlank([
      _stringField(json, 'body'),
      _stringField(json, 'message'),
      _stringField(json, 'content'),
    ]),
    createdAt: _firstNonBlank([
      _stringField(json, 'created_at'),
      _stringField(json, 'timestamp'),
      '刚刚',
    ]),
    kind: _stringField(json, 'kind'),
    status: _stringField(json, 'status'),
    workOrderId: _stringField(json, 'work_order_id'),
  );
}

List<AiGroupCandidate> _parseAiGroupCandidates(Object? value) {
  final data = _objectMap(value);
  final raw = data['candidates'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AiGroupCandidate(
          employeeId: _stringField(json, 'employee_id'),
          modId: _stringField(json, 'mod_id'),
          name: _stringField(json, 'name').ifEmpty('AI员工'),
          avatarUrl: _nullableStringField(json, 'avatar'),
          summary: _stringField(json, 'summary'),
          departmentKey: _stringField(json, 'department_key'),
          isSuper: _boolField(json, 'is_super'),
        ),
      )
      .where((candidate) => candidate.employeeId.trim().isNotEmpty)
      .toList(growable: false);
}

List<GitBranchInfo> _parseGitBranches(Object? value) {
  final data = _objectMap(value);
  final raw = data['branches'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => GitBranchInfo(
          name: _stringField(json, 'name'),
          current: _boolField(json, 'current'),
          remote: _boolField(json, 'remote'),
        ),
      )
      .where((branch) => branch.name.trim().isNotEmpty)
      .toList(growable: false);
}

CsInfo _parseCsInfo(Object? value) {
  final data = _objectMap(value);
  return CsInfo(
    available: _boolField(data, 'cs_available'),
    name: _stringField(data, 'cs_name').ifEmpty('专属客服'),
    avatar: _nullableStringField(data, 'cs_avatar'),
    online: _boolField(data, 'cs_online'),
  );
}

List<CsMessage> _parseCsMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => CsMessage(
          messageId: _stringField(json, 'message_id').ifEmpty(
            _stringField(json, 'id'),
          ),
          sender: _stringField(json, 'sender'),
          body: _firstNonBlank([
            _stringField(json, 'body'),
            _stringField(json, 'content'),
            _stringField(json, 'text'),
          ]),
          timestamp: _firstNonBlank([
            _stringField(json, 'timestamp'),
            _stringField(json, 'created_at'),
            '刚刚',
          ]),
          msgType: _stringField(json, 'msg_type').ifEmpty('text'),
        ),
      )
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

CsMessageResponse _parseCsMessageResponse(Object? value) {
  final data = _objectMap(value);
  return CsMessageResponse(
    messageId: _stringField(data, 'message_id'),
    requestId: _intField(data, 'request_id'),
    reply: _stringField(data, 'reply'),
    backend: _stringField(data, 'backend'),
    timestamp: _firstNonBlank([
      _stringField(data, 'timestamp'),
      _stringField(data, 'created_at'),
      '刚刚',
    ]),
  );
}

List<AdminCsInboxItem> _parseAdminCsInbox(Object? value) {
  final data = _objectMap(value);
  final raw = data['conversations'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AdminCsInboxItem(
          conversationId: _intField(json, 'conversationId').ifZero(
            _intField(json, 'conversation_id').ifZero(_intField(json, 'id')),
          ),
          customerName: _firstNonBlank([
            _stringField(json, 'customerName'),
            _stringField(json, 'customer_name'),
            _stringField(json, 'name'),
            '客户',
          ]),
          lastMessageAt: _firstNonBlank([
            _stringField(json, 'lastMessageAt'),
            _stringField(json, 'last_message_at'),
            _stringField(json, 'updated_at'),
            _stringField(json, 'created_at'),
          ]),
          unreadCount: _intField(json, 'unreadCount').ifZero(
            _intField(json, 'unread_count'),
          ),
        ),
      )
      .where((item) => item.conversationId > 0)
      .toList(growable: false);
}

List<AdminCsMessage> _parseAdminCsMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AdminCsMessage(
          messageId: _firstNonBlank([
            _stringField(json, 'messageId'),
            _stringField(json, 'message_id'),
            _stringField(json, 'id'),
          ]),
          fromCustomer: _boolField(json, 'fromCustomer') ||
              _boolField(json, 'from_customer'),
          senderName: _firstNonBlank([
            _stringField(json, 'senderName'),
            _stringField(json, 'sender_name'),
            _stringField(json, 'sender'),
          ]),
          body: _firstNonBlank([
            _stringField(json, 'body'),
            _stringField(json, 'content'),
            _stringField(json, 'text'),
          ]),
          timestamp: _firstNonBlank([
            _stringField(json, 'timestamp'),
            _stringField(json, 'created_at'),
            _stringField(json, 'updated_at'),
          ]),
        ),
      )
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

bool _shouldDispatchGroupTask(String text) {
  final body = text.trim();
  if (body.isEmpty) return false;
  const keywords = [
    '派工',
    '任务',
    '修复',
    'bug',
    '部署',
    '发布',
    '验收',
    '回访',
    '检查',
    '测试',
    '执行',
    '处理',
  ];
  return keywords.any((keyword) => body.contains(keyword));
}

Map<String, Object?> _objectMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

List<Map<String, Object?>> _objectList(Object? value) {
  if (value is List) {
    return value.map(_objectMap).where((item) => item.isNotEmpty).toList();
  }
  return const <Map<String, Object?>>[];
}

List<Map<String, Object?>> _firstObjectList(List<Object?> values) {
  for (final value in values) {
    final rows = _objectList(value);
    if (rows.isNotEmpty) return rows;
  }
  return const <Map<String, Object?>>[];
}

List<String> _stringList(Object? value) {
  if (value is List) {
    return value
        .map((item) => item?.toString().trim() ?? '')
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
  }
  return const <String>[];
}

Map<String, Object?> _nestedDataMap(Map<String, Object?> data) {
  final nested = _objectMap(data['data']);
  return nested.isNotEmpty ? nested : data;
}

List<BusinessListItem> _businessItemsFromData(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final rows = _firstObjectList([
    data['items'],
    data['results'],
    data['data'],
  ]);
  return rows
      .map(BusinessListItem.fromJson)
      .where((item) => item.title.trim().isNotEmpty)
      .toList(growable: false);
}

List<BusinessListItem> _bridgeItemsFromData(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final rows = _firstObjectList([
    data['items'],
    data['requests'],
    data['results'],
    data['data'],
  ]);
  return rows
      .map(BusinessListItem.fromJson)
      .where(
          (item) => item.id.trim().isNotEmpty || item.title.trim().isNotEmpty)
      .toList(growable: false);
}

OnboardingIndustry? _onboardingIndustryFromPackage(
  Map<String, Object?> json,
) {
  final industryId = _stringField(json, 'industry_id');
  if (industryId.isEmpty) return null;
  return OnboardingIndustry(
    id: industryId,
    title: _firstNonBlank([
      _stringField(json, 'name'),
      _stringField(json, 'product_name'),
      industryId,
    ]),
    subtitle: _firstNonBlank([
      _stringField(json, 'scenario'),
      _stringField(json, 'mod_id'),
    ]),
  );
}

String _stringField(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value == null) return '';
  return value.toString().trim();
}

String? _nullableStringField(Map<String, Object?> json, String key) {
  final value = _stringField(json, key);
  return value.isEmpty ? null : value;
}

String _formatCents(String cents) {
  final parsed = double.tryParse(cents.trim());
  if (parsed == null) return cents;
  return '¥${(parsed / 100).toStringAsFixed(2)}';
}

String _checkoutResultText(Map<String, Object?> json) {
  final data = _nestedDataMap(json);
  return _firstNonBlank([
    _stringField(data, 'payment_url'),
    _stringField(data, 'pay_url'),
    _stringField(data, 'checkout_url'),
    _stringField(data, 'h5_url'),
    _stringField(data, 'url'),
    _stringField(data, 'out_trade_no'),
    _stringField(data, 'message'),
    '订单已创建',
  ]);
}

int _intField(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value.trim()) ?? 0;
  return 0;
}

bool _boolField(
  Map<String, Object?> json,
  String key, {
  bool fallback = false,
}) {
  final value = json[key];
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) {
    final normalized = value.trim().toLowerCase();
    if (const ['1', 'true', 'yes', 'ok'].contains(normalized)) return true;
    if (const ['0', 'false', 'no'].contains(normalized)) return false;
  }
  return fallback;
}

String _ensureTrailingSlash(String value) {
  final clean = value.trim();
  if (clean.isEmpty) return '';
  return clean.endsWith('/') ? clean : '$clean/';
}

String _friendlyGroupTimestamp(String value) {
  final parsed = DateTime.tryParse(value.trim());
  if (parsed == null) return '';
  return _friendlyTimestampFromMillis(parsed.toLocal().millisecondsSinceEpoch);
}

String _friendlyTimestampFromMillis(int timestampMs) {
  if (timestampMs <= 0) return '';
  final local = DateTime.fromMillisecondsSinceEpoch(timestampMs);
  final now = DateTime.now();
  final diff = now.difference(local);
  if (diff.isNegative) return '刚刚';
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inHours < 1) return '${diff.inMinutes}分钟前';
  if (diff.inHours < 24) return '${diff.inHours}小时前';
  if (diff.inHours < 48) return '昨天';
  if (local.year != now.year) {
    final shortYear = (local.year % 100).toString().padLeft(2, '0');
    return '$shortYear/${local.month}/${local.day}';
  }
  return '${local.month}/${local.day}';
}

ModInfo _normalizeAdminDutyMod(ModInfo mod) {
  if (mod.id != adminDutyModId && mod.id != 'admin-duty') return mod;

  final remoteById = <String, WorkflowEmployeeInfo>{};
  for (final employee in mod.workflowEmployees) {
    final id = employee.id.trim();
    if (id.isEmpty || remoteById.containsKey(id)) continue;
    remoteById[id] = employee;
  }

  final employees = adminDutyRosterEmployees.map((fallback) {
    final remote = remoteById[fallback.id];
    final label = _adminDutyEmployeeLabel(fallback, remote);
    final apiBasePath = '/api/admin/employees/${fallback.id}';
    return WorkflowEmployeeInfo(
      id: fallback.id,
      label: label.ifEmpty(fallback.label),
      panelTitle: fallback.id == 'user-customer-service-officer'
          ? label
          : remote == null
              ? fallback.label
              : remote.panelTitle.ifEmpty(label),
      panelSummary: fallback.id == 'user-customer-service-officer'
          ? fallback.summary
          : remote == null
              ? fallback.summary
              : remote.panelSummary.ifEmpty(fallback.summary),
      apiBasePath: remote == null
          ? apiBasePath
          : remote.apiBasePath.ifEmpty(apiBasePath),
      phoneChannel: remote == null
          ? 'admin-duty'
          : remote.phoneChannel.ifEmpty('admin-duty'),
      workflowPlaceholder: false,
      profileSource: remote == null
          ? 'duty_roster'
          : remote.profileSource.ifEmpty('duty_roster'),
      marketConnected: remote?.marketConnected ?? false,
      marketPkgId: remote?.marketPkgId ?? '',
      marketName: remote?.marketName ?? '',
      marketDescription: remote?.marketDescription ?? '',
      marketVersion: remote?.marketVersion ?? '',
      marketAuthor: remote?.marketAuthor ?? '',
      marketIndustry: remote?.marketIndustry ?? '',
      marketMaterialCategory: remote?.marketMaterialCategory ?? '',
      marketLicenseScope: remote?.marketLicenseScope ?? '',
      marketSecurityLevel: remote?.marketSecurityLevel ?? '',
      marketAvatar: remote?.marketAvatar,
    );
  }).toList(growable: false);

  return ModInfo(
    id: adminDutyModId,
    name: mod.name,
    version: mod.version,
    description:
        '$plannedAdminEmployeeCount 位系统 AI 员工与 ${mod.frontendMenu.length} 个管理功能入口',
    author: mod.author,
    primary: mod.primary,
    industry: mod.industry,
    avatarUrl: mod.avatarUrl,
    frontendMenu: mod.frontendMenu,
    workflowEmployees: employees,
  );
}

String _adminDutyEmployeeLabel(
  DutyRosterEmployee fallback,
  WorkflowEmployeeInfo? remote,
) {
  if (fallback.id == 'user-customer-service-officer') {
    return fallback.label;
  }
  return remote == null
      ? fallback.label
      : remote.label.ifEmpty(remote.panelTitle).ifEmpty(fallback.label);
}

List<ConversationItem> _employeeConversationItems(
  List<ModInfo> mods, {
  required String? badgeText,
  required int? badgeColor,
  required Map<String, _ConversationListState> states,
}) {
  final seenIds = <String>{};
  final items = <ConversationItem>[];

  for (final mod in mods) {
    for (final employee in mod.workflowEmployees) {
      final employeeId = employee.id.trim();
      final title = employee.label
          .ifEmpty(employee.panelTitle)
          .ifEmpty(employeeId)
          .trim();
      if (employeeId.isEmpty || title.isEmpty) continue;

      final source = mod.name.ifEmpty(mod.id).trim();
      final conversationId = 'employee:${mod.id}:$employeeId';
      if (!seenIds.add(conversationId)) continue;
      final state = states[conversationId];

      items.add(
        ConversationItem(
          id: conversationId,
          type: ConversationType.aiTask,
          title: title,
          subtitle: state?.preview.ifEmpty(employee.contactSubtitle(source)) ??
              employee.contactSubtitle(source),
          timestampText: state?.timestampText ?? '',
          timestampMs: state?.timestampMs ?? 0,
          avatarUrl: employee.marketAvatar ?? mod.avatarUrl,
          badgeText: badgeText,
          badgeColor: badgeColor,
        ),
      );
    }
  }

  return items;
}

List<ConversationItem> _sortConversationItems(List<ConversationItem> items) {
  final entries = <_IndexedConversationItem>[
    for (var i = 0; i < items.length; i++)
      _IndexedConversationItem(index: i, item: items[i]),
  ];
  entries.sort((a, b) {
    if (a.item.isPinned != b.item.isPinned) {
      return a.item.isPinned ? -1 : 1;
    }
    final timestampOrder = b.item.timestampMs.compareTo(a.item.timestampMs);
    if (timestampOrder != 0) return timestampOrder;
    return a.index.compareTo(b.index);
  });
  return entries.map((entry) => entry.item).toList(growable: false);
}

class _IndexedConversationItem {
  const _IndexedConversationItem({
    required this.index,
    required this.item,
  });

  final int index;
  final ConversationItem item;
}

class _EmployeeConversationRef {
  const _EmployeeConversationRef({
    required this.modId,
    required this.employeeId,
  });

  final String modId;
  final String employeeId;
}

_EmployeeConversationRef? _employeeConversationRef(String raw) {
  final value = raw.trim();
  if (!value.startsWith('employee:')) return null;
  final parts = value.split(':');
  if (parts.length < 3) return null;
  final modId = parts[1].trim();
  final employeeId = parts[2].trim();
  if (modId.isEmpty || employeeId.isEmpty) return null;
  return _EmployeeConversationRef(modId: modId, employeeId: employeeId);
}

List<ConversationItem> _fixedConversationItems({
  required bool showCodex,
  required bool showCursor,
  required bool showClaude,
  required bool showTrae,
  required bool showCustomerService,
  required Map<String, _ConversationListState> states,
}) {
  final items = <ConversationItem>[
    ConversationItem(
      id: PinnedIds.assistant,
      type: ConversationType.pinnedAssistant,
      title: '小C助理',
      subtitle: states[PinnedIds.assistant]?.preview.ifEmpty('有什么可以帮您？') ??
          '有什么可以帮您？',
      timestampText: states[PinnedIds.assistant]?.timestampText ?? '',
      timestampMs: states[PinnedIds.assistant]?.timestampMs ?? 0,
      isPinned: true,
    ),
  ];

  if (showCodex) {
    final state = states[PinnedIds.codex];
    items.add(
      ConversationItem(
        id: PinnedIds.codex,
        type: ConversationType.pinnedCodex,
        title: '超级员工-Codex',
        subtitle: state?.preview.ifEmpty('全设备协同') ?? '全设备协同',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showCursor) {
    final state = states[PinnedIds.cursor];
    items.add(
      ConversationItem(
        id: PinnedIds.cursor,
        type: ConversationType.pinnedCursor,
        title: '超级员工-Cursor',
        subtitle: state?.preview.ifEmpty('全设备协同 · Agent') ?? '全设备协同 · Agent',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showClaude) {
    final state = states[PinnedIds.claude];
    items.add(
      ConversationItem(
        id: PinnedIds.claude,
        type: ConversationType.pinnedClaude,
        title: '超级员工-Claude',
        subtitle: state?.preview.ifEmpty('全设备协同 · 排比派工') ?? '全设备协同 · 排比派工',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showTrae) {
    final state = states[PinnedIds.trae];
    items.add(
      ConversationItem(
        id: PinnedIds.trae,
        type: ConversationType.pinnedTrae,
        title: '超级员工-Trae',
        subtitle: state?.preview.ifEmpty('全设备协同 · Trae') ?? '全设备协同 · Trae',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showCustomerService) {
    final state = states[PinnedIds.cs];
    items.add(
      ConversationItem(
        id: PinnedIds.cs,
        type: ConversationType.pinnedCs,
        title: '专属客服',
        subtitle: state?.preview.ifEmpty('您好，我是您的专属客服') ?? '您好，我是您的专属客服',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }

  return items;
}

class _ConversationListState {
  const _ConversationListState({
    required this.preview,
    required this.timestampMs,
  });

  final String preview;
  final int timestampMs;

  String get timestampText => _friendlyTimestampFromMillis(timestampMs);

  Map<String, Object?> toJson() => {
        'last_message_preview': preview,
        'last_message_at': timestampMs,
      };

  static _ConversationListState? fromJson(Map<String, Object?> json) {
    final timestamp = _firstPositiveInt([
      json['last_message_at'],
      json['timestamp_ms'],
      json['timestamp'],
      json['ts'],
    ]);
    final preview = _firstNonBlank([
      _stringField(json, 'last_message_preview'),
      _stringField(json, 'preview'),
      _stringField(json, 'body'),
    ]);
    if (timestamp <= 0 && preview.isEmpty) return null;
    return _ConversationListState(
      preview: preview,
      timestampMs: timestamp,
    );
  }
}

Future<Map<String, _ConversationListState>> _loadConversationListStates(
  MobileApiClient client,
) async {
  final session = await client.loadSession();
  final result = <String, _ConversationListState>{};
  for (final entry in session.conversationListStates.entries) {
    final key = entry.key.trim();
    if (key.isEmpty) continue;
    final state = _ConversationListState.fromJson(entry.value);
    if (state != null) result[key] = state;
  }
  return result;
}

String _conversationPreviewForRole(ChatRole role, String text) {
  final normalized = text.trim().replaceAll('\n', ' ').replaceAll('\r', ' ');
  if (normalized.isEmpty) return '';
  switch (role) {
    case ChatRole.user:
      return '我: $normalized';
    case ChatRole.assistant:
    case ChatRole.system:
      return normalized;
  }
}

int _firstPositiveInt(List<Object?> values) {
  for (final value in values) {
    if (value is int && value > 0) return value;
    if (value is num && value > 0) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null && parsed > 0) return parsed;
    }
  }
  return 0;
}

const _emptyConversationStates = <String, _ConversationListState>{};

extension on WorkflowEmployeeInfo {
  String contactSubtitle(String source) {
    final summary = panelSummary.trim();
    if (summary.isNotEmpty) return summary;
    if (source.trim().isNotEmpty) return '来自 ${source.trim()}';
    return phoneChannel.contactChannelLabel();
  }
}

extension on String {
  String contactChannelLabel() {
    switch (trim()) {
      case 'admin-duty':
        return '服务器后台';
      case 'mobile':
      case 'mobile-chat':
        return '手机端会话';
      case '':
        return '';
      default:
        return trim();
    }
  }
}

extension on int {
  int ifZero(int fallback) => this == 0 ? fallback : this;

  int takeIfValidPort() => this > 0 && this <= 65535 ? this : 0;
}

extension on SuperEmployeeMessage {
  ChatMessage toChatMessage(String conversationId) {
    final normalizedRole = role.trim().toLowerCase();
    final chatRole = normalizedRole == 'user' || normalizedRole == 'human'
        ? ChatRole.user
        : ChatRole.assistant;

    return ChatMessage(
      id: id.ifEmpty('remote-${createdAt.hashCode}-${body.hashCode}'),
      conversationId: conversationId,
      role: chatRole,
      body: body,
      timeText: createdAt,
      hasEmployeeProfile: chatRole == ChatRole.assistant,
    );
  }
}

ChatMessage? _chatMessageFromCache(Map<String, Object?> json) {
  final body = _stringField(json, 'body').ifEmpty(_stringField(json, 'text'));
  if (body.trim().isEmpty) return null;
  final normalizedRole = _stringField(json, 'role').toLowerCase();
  final role = normalizedRole == 'user' || normalizedRole == 'human'
      ? ChatRole.user
      : normalizedRole == 'system'
          ? ChatRole.system
          : ChatRole.assistant;
  final statusText = _stringField(json, 'status').toLowerCase();
  final status = statusText == 'failed'
      ? ChatDeliveryStatus.failed
      : statusText == 'sending'
          ? ChatDeliveryStatus.sending
          : ChatDeliveryStatus.sent;
  final conversationId = _stringField(json, 'conversation_id');
  return ChatMessage(
    id: _stringField(json, 'id').ifEmpty(
      'cache-${conversationId.hashCode}-${body.hashCode}',
    ),
    conversationId: conversationId,
    role: role,
    body: body,
    timeText: _stringField(json, 'time_text').ifEmpty(
      _stringField(json, 'created_at'),
    ),
    hasEmployeeProfile: _boolField(
      json,
      'has_employee_profile',
      fallback: role == ChatRole.assistant,
    ),
    status: status,
    quote: _stringField(json, 'quote'),
    cacheTimestampMs: _cachedChatTimestampMs(json),
  );
}

int _cachedChatTimestampMs(Map<String, Object?> json) {
  final direct = _intField(json, 'ts');
  if (direct > 0) return direct;
  final timestampMs = _intField(json, 'timestamp_ms');
  if (timestampMs > 0) return timestampMs;
  final createdMs = _intField(json, 'created_at_ms');
  if (createdMs > 0) return createdMs;
  return _parseTimestampMs(
    _stringField(json, 'time_text').ifEmpty(_stringField(json, 'created_at')),
  );
}

int _parseTimestampMs(String value) {
  final text = value.trim();
  if (text.isEmpty || text == '刚刚') return 0;
  final numeric = int.tryParse(text);
  if (numeric != null) return numeric;
  return DateTime.tryParse(text)?.millisecondsSinceEpoch ?? 0;
}

ChatMessage _assistantMessage(String conversationId, String body) {
  return ChatMessage(
    id: 'remote-${DateTime.now().microsecondsSinceEpoch}',
    conversationId: conversationId,
    role: ChatRole.assistant,
    body: body,
    timeText: '刚刚',
    hasEmployeeProfile: true,
  );
}

List<Map<String, String>> _recentChatContext(List<ChatMessage> messages) {
  final rows = messages
      .where((message) => message.role != ChatRole.system)
      .where((message) => message.body.trim().isNotEmpty)
      .map(
        (message) => {
          'role': message.role == ChatRole.user ? 'user' : 'assistant',
          'content': _take(message.body, 500),
        },
      )
      .toList(growable: false);
  if (rows.length <= 6) return rows;
  return rows.sublist(rows.length - 6);
}

String _take(String value, int maxLength) {
  final text = value.trim();
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength);
}

String _assistantReplyFromMap(Map<String, Object?> json) {
  final assistant = _firstNestedReply(json, const [
    'assistant_message',
    'assistantMessage',
    'assistant',
  ]);
  if (assistant.isNotEmpty) return assistant;

  final direct = _firstString(json, const [
    'reply',
    'answer',
    'response',
    'body',
    'content',
    'text',
    'message',
  ]);
  if (direct.isNotEmpty) return direct;

  return _firstNestedReply(json, const ['data', 'result', 'codex']);
}

String _firstNestedReply(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is String) {
      final text = value.trim();
      if (text.isNotEmpty) return text;
    }
    if (value is Map<String, Object?>) {
      final text = _assistantReplyFromMap(value);
      if (text.isNotEmpty) return text;
    }
    if (value is Map) {
      final text = _assistantReplyFromMap(
        value.map((key, value) => MapEntry(key.toString(), value)),
      );
      if (text.isNotEmpty) return text;
    }
  }
  return '';
}

String _firstString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is! String) continue;
    final text = value.trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

class MobileRepositoryException implements Exception {
  const MobileRepositoryException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Relay 任务进度快照，供 UI 显示长任务状态。
class RelayTaskProgress {
  const RelayTaskProgress({
    required this.taskId,
    required this.status,
    required this.toolLabel,
  });

  final String taskId;
  final String status;
  final String toolLabel;
}

class _MobileRepositoryCancelled implements Exception {
  const _MobileRepositoryCancelled();

  @override
  String toString() => 'cancelled';
}

void _throwIfCancelled(bool Function()? isCancelled) {
  if (isCancelled?.call() == true) {
    throw const _MobileRepositoryCancelled();
  }
}

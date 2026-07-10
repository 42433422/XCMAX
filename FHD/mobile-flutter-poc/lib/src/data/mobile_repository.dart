import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../models/conversation.dart';
import '../policy/android_runtime_policy.dart';
import '../policy/avatar_policy.dart';
import '../policy/pinned_ids.dart';
import 'ai_employee_profile.dart';
import 'assistant_assets.dart';
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
  static final Set<String> _activeLocalRunIds = <String>{};
  static final Set<String> _stopRequestedLocalRunIds = <String>{};
  static final Set<String> _cancelledLocalRunIds = <String>{};
  static final Map<String, Future<bool>> _localCancellationRequests =
      <String, Future<bool>>{};

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

  Future<List<String>> _lanPairingCandidateBaseUrls(
      String configuredHost) async {
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
      final ifaces =
          await NetworkInterface.list(type: InternetAddressType.IPv4);
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

  String _pairingExchangeNonce(
      PairingPayload? parsed, String raw, String code) {
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
    final usesPersistentThread = conversation.type.superTool != null ||
        conversation.id == PinnedIds.assistant;
    final threadId = usesPersistentThread
        ? await activeSuperEmployeeThreadId(conversation.id)
        : '';
    final cacheId = _superEmployeeCacheId(conversation.id, threadId);
    final cached = await _loadCachedChat(cacheId);
    if (cached.isNotEmpty) return cached;

    final tool = conversation.type.superTool;
    if (tool == null) return const [];
    // A real thread owns its own local transcript; never mix the legacy global
    // employee message feed into a newly created conversation.
    if (threadId.isNotEmpty) return const [];

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

  Future<String> streamAssistantMessage({
    required String body,
    bool deepAnalysis = false,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    void Function(String token)? onToken,
    bool Function()? isCancelled,
  }) async {
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }
    final threadId = await activeSuperEmployeeThreadId(PinnedIds.assistant);
    final cacheId = _superEmployeeCacheId(PinnedIds.assistant, threadId);
    await _cacheChatMessage(cacheId, role: ChatRole.user, body: text);
    final prompt = deepAnalysis
        ? '请进入深度分析模式：先明确问题与假设，再给出有依据的分析、风险和可执行建议。\n\n用户问题：$text'
        : text;
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    final memoryContext = await _assistantMemoryPromptContext();
    final reply = await _client.streamChat(
      prompt,
      sessionId: cacheId,
      userId: effectiveUserId,
      recentMessages: _recentChatContext(recentMessages),
      context: {
        'source': 'mobile_assistant',
        'client_surface': 'mobile',
        if (memoryContext.isNotEmpty) 'assistant_memory': memoryContext,
      },
      onToken: onToken,
    );
    _throwIfCancelled(isCancelled);
    await _cacheChatMessage(
      cacheId,
      role: ChatRole.assistant,
      body: reply,
    );
    return reply;
  }

  Future<AssistantSearchResult> searchAssistantMessage({
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
  }) async {
    final text = body.trim();
    if (text.isEmpty) throw const MobileRepositoryException('搜索内容不能为空');
    final threadId = await activeSuperEmployeeThreadId(PinnedIds.assistant);
    final cacheId = _superEmployeeCacheId(PinnedIds.assistant, threadId);
    await _cacheChatMessage(cacheId, role: ChatRole.user, body: text);
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    final memoryContext = await _assistantMemoryPromptContext();
    final context = <String, Object?>{
      'source': 'mobile_assistant_search',
      'client_surface': 'mobile',
      'kitten_analyzer': true,
      'kitten_web_search': true,
      'kitten_session_id': cacheId,
      if (effectiveUserId > 0) 'user_id': '$effectiveUserId',
      if (recentMessages.isNotEmpty)
        'recent_messages': _recentChatContext(recentMessages),
      if (memoryContext.isNotEmpty) 'assistant_memory': memoryContext,
    };
    Map<String, Object?> response = const {};
    Object? serverError;
    try {
      response = await _client.chat(
        text,
        sessionId: cacheId,
        context: context,
      );
    } catch (error) {
      serverError = error;
    }
    var answer = _assistantReplyFromMap(response);
    var sources = _assistantSourcesFromRows(
      _deepObjectListForKey(response, 'web_search_results'),
    );
    final meta = _deepObjectMapForKey(response, 'web_search_meta');
    var provider = _stringField(meta, 'provider');
    var warning = _deepStringForKey(response, 'web_search_error');

    // Compatibility fallback: an already-installed app can be connected to a
    // cloud/desktop node that has not yet received the new search endpoint.
    // Fetch real sources directly, then use the existing streaming chat path
    // to produce a grounded answer instead of showing "离线同步不可用".
    if (sources.isEmpty) {
      try {
        final rows = await _client.keylessWebSearch(text);
        sources = _assistantSourcesFromRows(rows);
        if (sources.isNotEmpty) {
          provider = 'bing_rss';
          final groundedPrompt = _groundedSearchPrompt(text, sources);
          try {
            answer = await _client.streamChat(
              groundedPrompt,
              sessionId: cacheId,
              userId: effectiveUserId,
              recentMessages: _recentChatContext(recentMessages),
              context: {
                ...context,
                'kitten_web_search': false,
                'mobile_search_sources': rows,
              },
            );
          } catch (_) {
            // Keep a valid answer returned by an older non-stream endpoint.
          }
        }
      } catch (error) {
        warning = error.toString();
      }
    }
    if (answer.trim().isEmpty && sources.isNotEmpty) {
      answer = '已找到 ${sources.length} 条实时来源，请先查看下方来源卡片；回答服务恢复后可继续追问。';
      warning = warning.ifEmpty(serverError?.toString() ?? '');
    } else if (answer.trim().isEmpty && serverError != null) {
      throw MobileRepositoryException(serverError.toString());
    }
    answer = answer.ifEmpty('没有获得有效回答。');
    await _cacheChatMessage(
      cacheId,
      role: ChatRole.assistant,
      body: answer,
      sources: sources,
    );
    return AssistantSearchResult(
      answer: answer,
      sources: sources,
      provider: provider,
      query: _stringField(meta, 'query').ifEmpty(text),
      warning: warning,
    );
  }

  Future<bool> assistantMemoryEnabled() async {
    final session = await _client.loadSession();
    final settings = session.conversationListStates['__assistant_settings__'];
    final raw = settings?['memory_enabled'];
    return raw is bool ? raw : true;
  }

  Future<void> setAssistantMemoryEnabled(bool enabled) async {
    final session = await _client.loadSession();
    final states = Map<String, Map<String, Object?>>.of(
      session.conversationListStates,
    );
    states['__assistant_settings__'] = {
      ...?states['__assistant_settings__'],
      'memory_enabled': enabled,
    };
    await _client.saveSession(session.copyWith(conversationListStates: states));
  }

  Future<List<AssistantMemoryRecord>> loadAssistantMemories({
    String status = '',
  }) async {
    final local = await _loadLocalAssistantMemories();
    final userId = await _assistantMemoryUserId();
    try {
      final response = await _client.memoryV2List(userId: userId);
      final remote = _deepObjectListForKey(response, 'memories')
          .map(_assistantMemoryFromMap)
          .where((record) => record.id.isNotEmpty)
          .toList(growable: false);
      final merged = _mergeAssistantMemories(local, remote);
      await _saveLocalAssistantMemories(merged);
      return _filterAssistantMemories(merged, status);
    } catch (_) {
      return _filterAssistantMemories(local, status);
    }
  }

  Future<AssistantMemoryRecord> addAssistantMemory({
    required String key,
    required String value,
    String memoryType = 'preference',
  }) async {
    final cleanKey = key.trim();
    final cleanValue = value.trim();
    if (cleanKey.isEmpty || cleanValue.isEmpty) {
      throw const MobileRepositoryException('记忆名称和内容不能为空');
    }
    final userId = await _assistantMemoryUserId();
    try {
      final created = await _client.memoryV2Create(
        userId: userId,
        key: cleanKey,
        value: cleanValue,
        memoryType: memoryType,
      );
      var memory = _deepObjectMapForKey(created, 'memory');
      if (memory.isEmpty) {
        memory = _deepObjectMapForKey(created, 'candidate');
      }
      var memoryId = _stringField(memory, 'memory_id');
      if (memoryId.isEmpty) {
        final pending = await loadAssistantMemories(status: 'pending');
        for (final item in pending) {
          if (item.key == cleanKey && item.value == cleanValue) {
            memoryId = item.id;
            break;
          }
        }
      }
      if (memoryId.isEmpty) {
        throw const MobileRepositoryException(
          '记忆已提交，但没有返回可确认的记录',
        );
      }
      final confirmed = await _client.memoryV2Confirm(
        userId: userId,
        memoryId: memoryId,
      );
      memory = _deepObjectMapForKey(confirmed, 'memory');
      final record = memory.isNotEmpty
          ? _assistantMemoryFromMap(memory)
          : AssistantMemoryRecord(
              id: memoryId,
              type: memoryType,
              key: cleanKey,
              value: cleanValue,
              status: 'active',
            );
      await _upsertLocalAssistantMemory(record);
      return record;
    } catch (_) {
      final record = AssistantMemoryRecord(
        id: 'local_${DateTime.now().microsecondsSinceEpoch}',
        type: memoryType,
        key: cleanKey,
        value: cleanValue,
        status: 'active',
        updatedAt: DateTime.now().toUtc().toIso8601String(),
      );
      await _upsertLocalAssistantMemory(record);
      return record;
    }
  }

  Future<void> updateAssistantMemory(AssistantMemoryRecord record) async {
    if (!record.id.startsWith('local_')) {
      try {
        await _client.memoryV2Correct(
          userId: await _assistantMemoryUserId(),
          memoryId: record.id,
          key: record.key,
          value: record.value,
        );
      } catch (_) {
        // Keep the device copy usable until the server is upgraded.
      }
    }
    await _upsertLocalAssistantMemory(
      AssistantMemoryRecord(
        id: record.id,
        type: record.type,
        key: record.key,
        value: record.value,
        status: record.status,
        updatedAt: DateTime.now().toUtc().toIso8601String(),
      ),
    );
  }

  Future<void> deleteAssistantMemory(String memoryId) async {
    if (!memoryId.startsWith('local_')) {
      try {
        await _client.memoryV2Delete(
          userId: await _assistantMemoryUserId(),
          memoryId: memoryId,
        );
      } catch (_) {
        // Removing the local copy must not depend on server rollout timing.
      }
    }
    final local = await _loadLocalAssistantMemories();
    await _saveLocalAssistantMemories(
      local.where((record) => record.id != memoryId).toList(growable: false),
    );
  }

  Future<List<AssistantMemoryRecord>> _loadLocalAssistantMemories() async {
    final session = await _client.loadSession();
    final settings = session.conversationListStates['__assistant_settings__'];
    return _objectList(settings?['local_memories'])
        .map(_assistantMemoryFromMap)
        .where((record) => record.id.isNotEmpty)
        .toList(growable: false);
  }

  Future<void> _saveLocalAssistantMemories(
    List<AssistantMemoryRecord> records,
  ) async {
    final session = await _client.loadSession();
    final states = Map<String, Map<String, Object?>>.of(
      session.conversationListStates,
    );
    states['__assistant_settings__'] = {
      ...?states['__assistant_settings__'],
      'local_memories': records
          .where((record) => record.status != 'deleted')
          .take(100)
          .map(_assistantMemoryToMap)
          .toList(growable: false),
    };
    await _client.saveSession(session.copyWith(conversationListStates: states));
  }

  Future<void> _upsertLocalAssistantMemory(
    AssistantMemoryRecord record,
  ) async {
    final local = await _loadLocalAssistantMemories();
    final updated = <AssistantMemoryRecord>[record];
    for (final item in local) {
      if (item.id != record.id) updated.add(item);
    }
    await _saveLocalAssistantMemories(updated);
  }

  List<AssistantMemoryRecord> _mergeAssistantMemories(
    List<AssistantMemoryRecord> local,
    List<AssistantMemoryRecord> remote,
  ) {
    final merged = <String, AssistantMemoryRecord>{};
    for (final item in local) {
      merged[item.id] = item;
    }
    for (final item in remote) {
      merged[item.id] = item;
    }
    return merged.values
        .where((item) => item.status != 'deleted')
        .toList(growable: false);
  }

  List<AssistantMemoryRecord> _filterAssistantMemories(
    List<AssistantMemoryRecord> records,
    String status,
  ) {
    final selected = status.trim();
    if (selected.isEmpty) return records;
    return records
        .where((record) => record.status == selected)
        .toList(growable: false);
  }

  Future<String> synthesizeAssistantSpeech(String text) async {
    final response = await _client.synthesizeSpeech(_take(text.trim(), 1600));
    final data = _deepObjectMapForKey(response, 'data');
    final audio = _stringField(data, 'audioBase64');
    if (audio.isEmpty) {
      throw MobileRepositoryException(
        _deepStringForKey(response, 'message').ifEmpty('在线语音暂不可用'),
      );
    }
    return audio;
  }

  Future<AssistantFileAnalysis> analyzeAssistantOfficeFile({
    required String filename,
    required List<int> bytes,
    String contentType = 'application/octet-stream',
  }) async {
    final employeeId = _officeEmployeeForFilename(filename);
    if (employeeId.isEmpty) {
      throw const MobileRepositoryException(
        '支持 PDF、Word、Excel、CSV 和 PowerPoint 文件',
      );
    }
    final localPreview = _localOfficeText(filename, bytes);
    final uploaded = await _client.uploadOfficeFile(
      filename: filename,
      bytes: bytes,
      contentType: contentType,
    );
    final uploadData = _deepObjectMapForKey(uploaded, 'data');
    final filePath = _stringField(uploadData, 'file_path');
    final workspaceRoot = _stringField(uploadData, 'workspace_root');
    if (filePath.isEmpty || workspaceRoot.isEmpty) {
      throw const MobileRepositoryException('文件上传成功，但服务器没有返回工作区路径');
    }
    final result = await _client.runOfficeEmployee(
      employeeId: employeeId,
      filePath: filePath,
      workspaceRoot: workspaceRoot,
    );
    final serverSummary = _officeAnalysisSummary(result);
    final summary = localPreview.isNotEmpty &&
            (serverSummary.isEmpty || _looksLikeOfficeMetadata(serverSummary))
        ? localPreview
        : serverSummary;
    return AssistantFileAnalysis(
      filename: filename,
      employeeId: employeeId,
      summary: summary.ifEmpty('文件已读取，但没有提取到可展示的文字。'),
      filePath: filePath,
    );
  }

  Future<String> recognizeAssistantImage({
    required String filename,
    required List<int> bytes,
    String contentType = 'image/jpeg',
  }) async {
    final response = await _client.recognizeImage(
      filename: filename,
      bytes: bytes,
      contentType: contentType,
    );
    return _firstNonBlank([
      _deepStringForKey(response, 'text'),
      _deepStringForKey(response, 'message'),
    ]);
  }

  Future<AssistantEmployeeAvailability>
      loadAssistantEmployeeAvailability() async {
    final response = await _client.relayDesktops();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('执行端状态加载失败'));
    }
    final rows = _relayDesktopRows(response.data)
        .where(_relayDesktopIsDispatchable)
        .where(_relayDesktopIsFresh)
        .toList(growable: false);
    final online = <String>{};
    var label = '';
    var checkedAt = '';
    for (final row in rows) {
      label = label.ifEmpty(_stringField(row, 'label'));
      final capabilities = _objectMap(row['capabilities']);
      checkedAt = _firstNonBlank([
        checkedAt,
        _stringField(capabilities, 'checked_at'),
        _stringField(row, 'last_seen_at'),
      ]);
      if (_boolField(capabilities, 'codex_cli')) online.add(PinnedIds.codex);
      if (_boolField(capabilities, 'claude_cli')) online.add(PinnedIds.claude);
      if (_boolField(capabilities, 'cursor_cli')) online.add(PinnedIds.cursor);
      if (_boolField(capabilities, 'trae_cli')) online.add(PinnedIds.trae);
    }
    return AssistantEmployeeAvailability(
      onlineConversationIds: Set.unmodifiable(online),
      desktopLabel: label,
      checkedAt: checkedAt,
    );
  }

  Future<String> _assistantMemoryPromptContext() async {
    if (!await assistantMemoryEnabled()) return '';
    try {
      final rows = await loadAssistantMemories(status: 'active');
      if (rows.isEmpty) return '';
      return rows
          .take(20)
          .map((item) => '${item.key}：${item.value}')
          .join('\n');
    } catch (_) {
      return '';
    }
  }

  Future<String> _assistantMemoryUserId() async {
    final id = await _loadCurrentUserId();
    if (id > 0) return '$id';
    final session = await _client.loadSession();
    return session.username.trim().ifEmpty('default');
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
      var threadId = await _ensureActiveSuperEmployeeThread(conversation);
      var cacheId = _superEmployeeCacheId(conversation.id, threadId);
      await _cacheChatMessage(
        cacheId,
        role: ChatRole.user,
        body: text,
      );
      final localBaseUrl = await _superEmployeeLanBaseUrl();
      if (localBaseUrl.isNotEmpty) {
        final reply = await _tryLanSuperEmployeeTask(
          conversation: conversation,
          tool: tool,
          text: text,
          threadId: threadId,
          cacheId: cacheId,
          baseUrl: localBaseUrl,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
        );
        if (reply != null) {
          return reply;
        }
      }
      final relayKind = relayKindForConversation(conversation.id);
      final relayId = await _relayIdForSuperEmployeeDispatch();
      if (relayKind != null && relayId.isNotEmpty) {
        if (threadId.isEmpty || threadId.startsWith('local-')) {
          try {
            final thread = await _createSuperEmployeeThread(
              conversation,
              relayId: relayId,
            );
            threadId = thread.threadId;
            cacheId = _superEmployeeCacheId(conversation.id, threadId);
          } catch (_) {
            // Older relay servers can execute tasks but do not expose the
            // optional thread API yet. Keep the local transcript and dispatch
            // a threadless task instead of blocking Send with 404/405.
          }
        }
        // 第 3 级：relay 中继轮询（跨网络，状态轮询模拟流式）
        final reply = await _streamRelaySuperEmployeeTask(
          relayId: relayId,
          relayKind: relayKind,
          conversationId: conversation.id,
          threadId: threadId.startsWith('local-') ? '' : threadId,
          cacheId: cacheId,
          message: text,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
        );
        _throwIfCancelled(isCancelled);
        if (reply.trim().isNotEmpty) {
          await _cacheChatMessage(
            cacheId,
            role: ChatRole.assistant,
            body: reply,
          );
        }
        return reply.ifEmpty('已收到，我会继续处理。');
      }
      final reply = await _postSuperEmployeeMessage(
        tool,
        text,
        threadId: threadId,
      );
      _throwIfCancelled(isCancelled);
      await _cacheChatMessage(
        cacheId,
        role: ChatRole.assistant,
        body: reply,
      );
      return reply;
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

    final cacheId = conversation.id == PinnedIds.assistant
        ? _superEmployeeCacheId(
            conversation.id,
            await activeSuperEmployeeThreadId(conversation.id),
          )
        : conversation.id;
    await _cacheChatMessage(
      cacheId,
      role: ChatRole.user,
      body: text,
    );
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    final reply = await _client.streamChat(
      text,
      sessionId: cacheId,
      userId: effectiveUserId,
      recentMessages: _recentChatContext(recentMessages),
      onToken: onToken,
    );
    _throwIfCancelled(isCancelled);
    await _cacheChatMessage(
      cacheId,
      role: ChatRole.assistant,
      body: reply,
    );
    return reply;
  }

  Future<bool> hasInflightRelay(String conversationId) async {
    final threadId = await activeSuperEmployeeThreadId(conversationId);
    final cacheId = _superEmployeeCacheId(conversationId, threadId);
    return _inflightRelayTask(cacheId).then((value) => value.isNotEmpty);
  }

  Future<String?> resumeRelayTask({
    required String conversationId,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final threadId = await activeSuperEmployeeThreadId(conversationId);
    final cacheId = _superEmployeeCacheId(conversationId, threadId);
    final taskId = await _inflightRelayTask(cacheId);
    if (taskId.isEmpty) return null;
    if (await _clearInflightIfRelayChanged(cacheId, taskId)) {
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
      conversationId: cacheId,
      onToken: onToken,
      onStatus: onStatus,
      isCancelled: isCancelled,
    );
    _throwIfCancelled(isCancelled);
    if (reply.trim().isNotEmpty) {
      await _cacheChatMessage(
        cacheId,
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
    if (taskId.trim().startsWith('local-run-')) {
      return _cancelLocalSuperEmployeeRun(taskId.trim());
    }
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
    String threadId = '',
    String clientTaskId = '',
  }) async {
    final response = await _client.postSuperEmployeeMessage(
      tool,
      text,
      baseUrl: baseUrl,
      context: {
        ..._superEmployeeThreadContext(threadId),
        if (clientTaskId.trim().isNotEmpty)
          'client_task_id': clientTaskId.trim(),
      },
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工回复失败'));
    }
    return _assistantReplyFromMap(response.data ?? response.raw)
        .ifEmpty('已收到，我会继续处理。');
  }

  String _superEmployeeExecutionErrorCode(MobileApiException error) {
    final nested = _objectMap(error.body['data']);
    return _firstNonBlank([
      _stringField(error.body, 'error_code'),
      _stringField(nested, 'error_code'),
      error.statusCode == 429 ? 'usage_limit' : '',
    ]);
  }

  bool _isSuperEmployeeExecutionFailure(MobileApiException error) {
    if (_superEmployeeExecutionErrorCode(error).isNotEmpty) return true;
    return error.statusCode >= 200 &&
        error.statusCode < 300 &&
        _stringField(error.body, 'type') == 'error';
  }

  Future<String> _superEmployeeLanBaseUrl() async {
    final session = await _client.loadSession();
    if (session.serverMode.trim().toLowerCase() != 'lan') {
      return '';
    }
    // Cloud and desktop JWTs are signed independently. A legacy session may
    // know the LAN address but not have completed a desktop credential
    // exchange yet; in that case skip the guaranteed-401 direct attempt and
    // continue through the already paired cloud relay.
    if (session.localAccessToken.trim().isEmpty) return '';
    final localBase = session.localBaseUrl.trim();
    if (localBase.isNotEmpty) return _ensureTrailingSlash(localBase);
    final host = session.fhdHost.trim();
    if (host.isEmpty) return '';
    // 后端 loopback 监听 17500 时手机不可达，需改用 vite proxy 端口 5011。
    return AndroidServerRouter(
      fhdHost: host,
      mode: AndroidServerMode.lan,
    ).lanReachableBaseUrl();
  }

  Future<String?> _tryLanSuperEmployeeTask({
    required ConversationItem conversation,
    required String tool,
    required String text,
    required String threadId,
    required String cacheId,
    required String baseUrl,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final run = await _beginLocalSuperEmployeeRun(
      conversation: conversation,
      tool: tool,
      threadId: threadId,
      message: text,
    );
    try {
      final stopwatch = Stopwatch()..start();
      final toolLabel = toolLabelForRelayKind('${tool.toLowerCase()}.invoke');
      bool cancelled() =>
          _stopRequestedLocalRunIds.contains(run.taskId) ||
          _cancelledLocalRunIds.contains(run.taskId) ||
          (isCancelled?.call() ?? false);
      onStatus?.call(
        RelayTaskProgress(
          taskId: run.taskId,
          status: 'running',
          toolLabel: toolLabel,
          source: 'lan',
        ),
      );

      Future<Never> finishExecutionFailure(MobileApiException error) async {
        final message = error.message.trim().ifEmpty('超级员工执行失败，请在电脑端重试');
        await _finishLocalSuperEmployeeRun(
          run.taskId,
          status: 'failed',
          resultText: message,
          elapsedSeconds: stopwatch.elapsedMilliseconds / 1000,
        );
        onStatus?.call(
          RelayTaskProgress(
            taskId: run.taskId,
            status: 'failed',
            toolLabel: toolLabel,
            source: 'lan',
          ),
        );
        throw MobileRepositoryException(message);
      }

      Future<String> finishSuccess(String reply) async {
        if (cancelled()) {
          await _cancelLocalSuperEmployeeRun(run.taskId);
          throw const _MobileRepositoryCancelled();
        }
        await _finishLocalSuperEmployeeRun(
          run.taskId,
          status: 'completed',
          resultText: reply,
          elapsedSeconds: stopwatch.elapsedMilliseconds / 1000,
        );
        await _cacheChatMessage(
          cacheId,
          role: ChatRole.assistant,
          body: reply,
        );
        onStatus?.call(
          RelayTaskProgress(
            taskId: run.taskId,
            status: 'completed',
            toolLabel: toolLabel,
            source: 'lan',
          ),
        );
        return reply;
      }

      try {
        // 第 1 级：LAN SSE 流式（逐 token 输出，体验最佳）。
        final reply = await _client.streamSuperEmployeeMessage(
          tool,
          text,
          baseUrl: baseUrl,
          onToken: (token) {
            if (!cancelled()) onToken?.call(token);
          },
          onStatus: (status) {
            if (!cancelled()) onToken?.call('\n$status\n');
          },
          isCancelled: cancelled,
          context: {
            ..._superEmployeeThreadContext(threadId),
            'client_task_id': run.taskId,
          },
        );
        return finishSuccess(reply);
      } on _MobileRepositoryCancelled {
        rethrow;
      } on MobileApiException catch (error) {
        if (_isSuperEmployeeExecutionFailure(error)) {
          await finishExecutionFailure(error);
        }
        if (cancelled()) {
          await _cancelLocalSuperEmployeeRun(run.taskId);
          throw const _MobileRepositoryCancelled();
        }
      } catch (_) {
        if (cancelled()) {
          await _cancelLocalSuperEmployeeRun(run.taskId);
          throw const _MobileRepositoryCancelled();
        }
      }

      try {
        // 第 2 级：LAN 直答。SSE 不可用时仍在同一条真实 local-run 中收口。
        final reply = await _postSuperEmployeeMessage(
          tool,
          text,
          baseUrl: baseUrl,
          threadId: threadId,
          clientTaskId: run.taskId,
        );
        return finishSuccess(reply);
      } on _MobileRepositoryCancelled {
        rethrow;
      } on MobileApiException catch (error) {
        if (_isSuperEmployeeExecutionFailure(error)) {
          await finishExecutionFailure(error);
        }
        if (cancelled()) {
          await _cancelLocalSuperEmployeeRun(run.taskId);
          throw const _MobileRepositoryCancelled();
        }
        await _finishLocalSuperEmployeeRun(
          run.taskId,
          status: 'failed',
          resultText: '局域网执行失败，已尝试切换云中继：${_take(error.toString(), 240)}',
          elapsedSeconds: stopwatch.elapsedMilliseconds / 1000,
        );
        onStatus?.call(
          RelayTaskProgress(
            taskId: run.taskId,
            status: 'failed',
            toolLabel: toolLabel,
            source: 'lan',
          ),
        );
        onToken?.call('〔局域网连接失败，正在切换到云端中继〕\n');
        return null;
      } catch (error) {
        if (cancelled()) {
          await _cancelLocalSuperEmployeeRun(run.taskId);
          throw const _MobileRepositoryCancelled();
        }
        await _finishLocalSuperEmployeeRun(
          run.taskId,
          status: 'failed',
          resultText: '局域网执行失败，已尝试切换云中继：${_take(error.toString(), 240)}',
          elapsedSeconds: stopwatch.elapsedMilliseconds / 1000,
        );
        onStatus?.call(
          RelayTaskProgress(
            taskId: run.taskId,
            status: 'failed',
            toolLabel: toolLabel,
            source: 'lan',
          ),
        );
        onToken?.call('〔局域网连接失败，正在切换到云端中继〕\n');
        return null;
      }
    } finally {
      _activeLocalRunIds.remove(run.taskId);
      _stopRequestedLocalRunIds.remove(run.taskId);
      _cancelledLocalRunIds.remove(run.taskId);
    }
  }

  Future<RelayRunSummary> _beginLocalSuperEmployeeRun({
    required ConversationItem conversation,
    required String tool,
    required String threadId,
    required String message,
  }) async {
    final now = DateTime.now().toUtc();
    final taskId = 'local-run-${now.microsecondsSinceEpoch}';
    final session = await _client.loadSession();
    final runs = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeRuns,
    );
    final attemptNo = runs.values
            .where((row) =>
                _stringField(row, 'thread_id') == threadId &&
                _stringField(row, 'kind') == '${tool.toLowerCase()}.invoke')
            .length +
        1;
    final row = <String, Object?>{
      'task_id': taskId,
      'thread_id': threadId,
      'conversation_id': conversation.id,
      'work_item_id': 'local-work-${now.microsecondsSinceEpoch}',
      'employee_id': _superEmployeeIdForConversation(conversation.id) ??
          '${tool.toLowerCase()}-super-employee',
      'kind': '${tool.toLowerCase()}.invoke',
      'status': 'running',
      'attempt_no': attemptNo,
      'created_at': now.toIso8601String(),
      'updated_at': now.toIso8601String(),
      'source': 'lan',
      'payload': {'message': message},
      'result': const <String, Object?>{},
    };
    runs[taskId] = row;
    final threads = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeThreads,
    );
    if (threadId.startsWith('local-') || threads.containsKey(threadId)) {
      final existing = threads[threadId] ?? const <String, Object?>{};
      final existingTitle = _stringField(existing, 'title');
      threads[threadId] = {
        ...existing,
        'thread_id': threadId,
        'conversation_id': conversation.id,
        'employee_id': row['employee_id'],
        'tool': tool.toLowerCase(),
        'title': existingTitle.isEmpty || existingTitle.endsWith('· 新对话')
            ? _localSuperEmployeeThreadTitle(message)
            : existingTitle,
        'status': 'active',
        'source': 'lan',
        'created_at':
            _stringField(existing, 'created_at').ifEmpty(now.toIso8601String()),
        'updated_at': now.toIso8601String(),
        'last_task_id': taskId,
      };
    }
    await _client.saveSession(
      session.copyWith(
        localSuperEmployeeRuns: _trimLocalRecordMap(runs, 240),
        localSuperEmployeeThreads: _trimLocalRecordMap(threads, 80),
      ),
    );
    _activeLocalRunIds.add(taskId);
    _stopRequestedLocalRunIds.remove(taskId);
    _cancelledLocalRunIds.remove(taskId);
    return RelayRunSummary.fromMap(row);
  }

  Future<void> _finishLocalSuperEmployeeRun(
    String taskId, {
    required String status,
    required String resultText,
    required double elapsedSeconds,
  }) async {
    final session = await _client.loadSession();
    final runs = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeRuns,
    );
    final current = runs[taskId];
    if (current == null) return;
    final now = DateTime.now().toUtc().toIso8601String();
    final cancelled = _cancelledLocalRunIds.contains(taskId) ||
        _stringField(current, 'status') == 'cancelled';
    final effectiveStatus = cancelled ? 'cancelled' : status;
    runs[taskId] = {
      ...current,
      'status': effectiveStatus,
      'updated_at': now,
      if (!const {'running', 'queued'}.contains(effectiveStatus))
        'completed_at': now,
      'result': {
        if (const {'failed', 'blocked'}.contains(effectiveStatus))
          'error': resultText
        else
          'reply': resultText,
        'elapsed_seconds': elapsedSeconds,
        'execution_source': 'lan',
      },
    };
    final threads = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeThreads,
    );
    final threadId = _stringField(current, 'thread_id');
    if (threads.containsKey(threadId)) {
      threads[threadId] = {
        ...threads[threadId]!,
        'status': 'idle',
        'updated_at': now,
        'last_task_id': taskId,
      };
    }
    await _client.saveSession(
      session.copyWith(
        localSuperEmployeeRuns: runs,
        localSuperEmployeeThreads: threads,
      ),
    );
    _activeLocalRunIds.remove(taskId);
  }

  Future<String> _streamRelaySuperEmployeeTask({
    required String relayId,
    required String relayKind,
    required String conversationId,
    required String threadId,
    required String cacheId,
    required String message,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: relayKind,
      threadId: threadId,
      payload: {
        'message': message,
        'workspace_root': _xcmaxDefaultWorkspaceRoot,
        'context': _superEmployeeRelayContext(
          conversationId: threadId.ifEmpty(conversationId),
        ),
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
    await _setInflightRelayTask(cacheId, taskId);
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
      conversationId: cacheId,
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
    final uri = Uri.tryParse(url);
    if (uri == null || !AndroidTransportSecurityPolicy.permits(uri)) {
      throw const MobileRepositoryException('已阻止不安全的非局域网消息连接');
    }
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

  Future<String> activeSuperEmployeeThreadId(String conversationId) async {
    final session = await _client.loadSession();
    return session.activeSuperEmployeeThreads[conversationId.trim()]?.trim() ??
        '';
  }

  Future<SuperEmployeeThread> startNewAssistantConversation() async {
    final threadId = 'assistant-${DateTime.now().microsecondsSinceEpoch}';
    await switchSuperEmployeeThread(PinnedIds.assistant, threadId);
    return SuperEmployeeThread(
      threadId: threadId,
      employeeId: 'xcagi-assistant',
      tool: 'assistant',
      title: '小C助理 · 新对话',
      status: 'active',
      updatedAt: DateTime.now().toUtc().toIso8601String(),
    );
  }

  Future<List<SuperEmployeeThread>> loadAssistantConversations() async {
    final session = await _client.loadSession();
    final activeId =
        session.activeSuperEmployeeThreads[PinnedIds.assistant]?.trim() ?? '';
    const prefix = '${PinnedIds.assistant}::';
    final threads = <SuperEmployeeThread>[];

    void addThread(
      String threadId,
      List<Map<String, Object?>> rows,
    ) {
      final title = _assistantThreadTitle(rows);
      final latestTs = rows.fold<int>(
        0,
        (value, row) =>
            _intField(row, 'ts') > value ? _intField(row, 'ts') : value,
      );
      threads.add(SuperEmployeeThread(
        threadId: threadId,
        employeeId: 'xcagi-assistant',
        tool: 'assistant',
        title: title,
        status:
            threadId == activeId || (threadId == 'legacy' && activeId.isEmpty)
                ? 'active'
                : 'idle',
        updatedAt: latestTs > 0
            ? DateTime.fromMillisecondsSinceEpoch(latestTs)
                .toUtc()
                .toIso8601String()
            : '',
      ));
    }

    final legacyRows = session.cachedChatMessages[PinnedIds.assistant];
    if (legacyRows != null && legacyRows.isNotEmpty) {
      addThread('legacy', legacyRows);
    }
    for (final entry in session.cachedChatMessages.entries) {
      if (!entry.key.startsWith(prefix) || entry.value.isEmpty) continue;
      final threadId = entry.key.substring(prefix.length).trim();
      if (threadId.isEmpty) continue;
      addThread(threadId, entry.value);
    }
    if (activeId.isNotEmpty &&
        !threads.any((thread) => thread.threadId == activeId)) {
      addThread(activeId, const []);
    }
    threads.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List<SuperEmployeeThread>.unmodifiable(threads);
  }

  Future<List<ChatMessage>> switchAssistantConversation(
    String threadId,
  ) async {
    final clean = threadId.trim();
    final persisted = clean == 'legacy' ? '' : clean;
    await switchSuperEmployeeThread(PinnedIds.assistant, persisted);
    return _loadCachedChat(
      _superEmployeeCacheId(PinnedIds.assistant, persisted),
    );
  }

  Future<void> cacheAssistantExchange({
    required String userMessage,
    required String assistantMessage,
  }) async {
    final threadId = await activeSuperEmployeeThreadId(PinnedIds.assistant);
    final cacheId = _superEmployeeCacheId(PinnedIds.assistant, threadId);
    if (userMessage.trim().isNotEmpty) {
      await _cacheChatMessage(
        cacheId,
        role: ChatRole.user,
        body: userMessage.trim(),
      );
    }
    if (assistantMessage.trim().isNotEmpty) {
      await _cacheChatMessage(
        cacheId,
        role: ChatRole.assistant,
        body: assistantMessage.trim(),
      );
    }
  }

  Future<String> summarizeMeetingMinutes({
    required String title,
    required String transcript,
    String participants = '',
  }) async {
    final cleanTranscript = transcript.trim();
    if (cleanTranscript.isEmpty) {
      throw const MobileRepositoryException('会议转写内容为空');
    }
    final prompt = '''
请把下面的会议转写整理成专业、简洁、忠于原文的会议纪要。
只能使用以下纯文本结构，不要使用 Markdown 代码块：
【会议摘要】
一段不超过 180 字的摘要
【讨论要点】
- 要点
【决策事项】
- 决策；没有则写“无”
【待办事项】
- 事项｜负责人｜截止时间；信息缺失写“待确认”

会议主题：${title.trim()}
参会人员：${participants.trim().isEmpty ? '未填写' : participants.trim()}
原始转写：
$cleanTranscript
''';
    final response = await _client.chat(
      prompt,
      sessionId: 'meeting-minutes-${DateTime.now().millisecondsSinceEpoch}',
      context: const {
        'source': 'mobile_meeting_minutes',
        'client_surface': 'mobile',
      },
    );
    return _assistantReplyFromMap(response).trim();
  }

  Future<SuperEmployeeThread> startNewSuperEmployeeConversation(
    ConversationItem conversation,
  ) async {
    final localBaseUrl = await _superEmployeeLanBaseUrl();
    var relayId = '';
    if (localBaseUrl.isEmpty) {
      try {
        relayId = await _relayIdForSuperEmployeeDispatch();
      } catch (_) {
        // A local persistent conversation remains available while offline.
      }
    }
    if (relayId.isEmpty) {
      final employeeId = _superEmployeeIdForConversation(conversation.id);
      if (employeeId == null) {
        throw const MobileRepositoryException('当前会话不是超级员工。');
      }
      final threadId = 'local-${DateTime.now().microsecondsSinceEpoch}';
      final now = DateTime.now().toUtc().toIso8601String();
      final thread = SuperEmployeeThread(
        threadId: threadId,
        employeeId: employeeId,
        tool: conversation.type.superTool?.toLowerCase() ?? '',
        title: '${conversation.title} · 新对话',
        status: 'idle',
        updatedAt: now,
        cliSessionId: '',
        workspaceRoot: '',
        branch: '',
        lastTaskId: '',
        archived: false,
        source: localBaseUrl.isNotEmpty ? 'lan' : 'cloud',
      );
      await _persistLocalSuperEmployeeThread(
        thread,
        conversationId: conversation.id,
        createdAt: now,
      );
      await switchSuperEmployeeThread(conversation.id, threadId);
      return thread;
    }
    return _createSuperEmployeeThread(conversation, relayId: relayId);
  }

  Future<SuperEmployeeThread> _createSuperEmployeeThread(
    ConversationItem conversation, {
    required String relayId,
  }) async {
    final employeeId = _superEmployeeIdForConversation(conversation.id);
    if (employeeId == null) {
      throw const MobileRepositoryException('当前会话不是超级员工。');
    }
    final response = await _client.relayCreateThread(
      relayId: relayId,
      employeeId: employeeId,
      title: '${conversation.title} · 新对话',
      context: const {'workspace_root': _xcmaxDefaultWorkspaceRoot},
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('新建对话失败'));
    }
    final row = _objectMap(response.data?['thread']);
    final thread = SuperEmployeeThread.fromMap(row);
    if (thread.threadId.isEmpty) {
      throw const MobileRepositoryException('新建对话缺少 thread_id');
    }
    await switchSuperEmployeeThread(conversation.id, thread.threadId);
    return thread;
  }

  Future<String> _ensureActiveSuperEmployeeThread(
    ConversationItem conversation,
  ) async {
    final active = await activeSuperEmployeeThreadId(conversation.id);
    if (active.isNotEmpty) return active;
    try {
      return (await startNewSuperEmployeeConversation(conversation)).threadId;
    } catch (_) {
      // LAN-only development still receives an isolated conversation key. When
      // a cloud relay becomes available the send path upgrades it to a server thread.
      final local = 'local-${DateTime.now().microsecondsSinceEpoch}';
      await switchSuperEmployeeThread(conversation.id, local);
      return local;
    }
  }

  Future<void> switchSuperEmployeeThread(
    String conversationId,
    String threadId,
  ) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final session = await _client.loadSession();
    final active = Map<String, String>.of(session.activeSuperEmployeeThreads);
    final cleanThread = threadId.trim();
    if (cleanThread.isEmpty) {
      active.remove(id);
    } else {
      active[id] = cleanThread;
    }
    await _client.saveSession(
      session.copyWith(activeSuperEmployeeThreads: active),
    );
  }

  Future<List<SuperEmployeeThread>> loadSuperEmployeeThreads(
    ConversationItem conversation, {
    bool includeArchived = false,
  }) async {
    final employeeId = _superEmployeeIdForConversation(conversation.id);
    if (employeeId == null) return const [];
    final local = await _loadLocalSuperEmployeeThreads(
      conversation.id,
      includeArchived: includeArchived,
    );
    List<SuperEmployeeThread> remote = const [];
    try {
      final response = await _client.relayThreads(
        employeeId: employeeId,
        includeArchived: includeArchived,
      );
      if (!response.success) {
        throw MobileRepositoryException(response.message.ifEmpty('对话列表加载失败'));
      }
      remote = _objectList(response.data?['items'])
          .map(SuperEmployeeThread.fromMap)
          .where((item) => item.threadId.isNotEmpty)
          .toList(growable: false);
    } catch (_) {
      if (local.isEmpty) rethrow;
    }
    final merged = <String, SuperEmployeeThread>{
      for (final thread in remote) thread.threadId: thread,
      for (final thread in local) thread.threadId: thread,
    }.values.toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List<SuperEmployeeThread>.unmodifiable(merged);
  }

  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
  }) async {
    final local = await _loadLocalSuperEmployeeRuns(
      threadId: threadId,
      activeOnly: activeOnly,
    );
    List<RelayRunSummary> remote = const [];
    try {
      final response = await _client.relayTasks(
        threadId: threadId,
        activeOnly: activeOnly,
        limit: limit,
      );
      if (!response.success) {
        throw MobileRepositoryException(response.message.ifEmpty('执行记录加载失败'));
      }
      remote = _objectList(response.data?['items'])
          .map(RelayRunSummary.fromMap)
          .where((item) => item.taskId.isNotEmpty)
          .toList(growable: false);
    } catch (_) {
      if (local.isEmpty) rethrow;
    }
    final merged = <String, RelayRunSummary>{
      for (final run in remote) run.taskId: run,
      for (final run in local) run.taskId: run,
    }.values.toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List<RelayRunSummary>.unmodifiable(merged.take(limit));
  }

  Future<RelayRunSummary> retryRelayRun(String taskId) async {
    if (taskId.trim().startsWith('local-run-')) {
      return _retryLocalSuperEmployeeRun(taskId.trim());
    }
    final response = await _client.relayRetryTask(taskId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('重试任务失败'));
    }
    return RelayRunSummary.fromMap(_objectMap(response.data?['task']));
  }

  Future<void> archiveSuperEmployeeThread(
    String conversationId,
    String threadId,
  ) async {
    final cleanThreadId = threadId.trim();
    final session = await _client.loadSession();
    if (session.localSuperEmployeeThreads.containsKey(cleanThreadId)) {
      final threads = Map<String, Map<String, Object?>>.of(
        session.localSuperEmployeeThreads,
      );
      final now = DateTime.now().toUtc().toIso8601String();
      threads[cleanThreadId] = {
        ...threads[cleanThreadId]!,
        'status': 'archived',
        'archived_at': now,
        'updated_at': now,
      };
      final active = Map<String, String>.of(
        session.activeSuperEmployeeThreads,
      );
      if (active[conversationId.trim()] == cleanThreadId) {
        active.remove(conversationId.trim());
      }
      await _client.saveSession(
        session.copyWith(
          localSuperEmployeeThreads: threads,
          activeSuperEmployeeThreads: active,
        ),
      );
      return;
    }
    final response = await _client.relayArchiveThread(threadId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('归档对话失败'));
    }
    if (await activeSuperEmployeeThreadId(conversationId) == cleanThreadId) {
      await switchSuperEmployeeThread(conversationId, '');
    }
  }

  Future<void> _persistLocalSuperEmployeeThread(
    SuperEmployeeThread thread, {
    required String conversationId,
    required String createdAt,
  }) async {
    final session = await _client.loadSession();
    final threads = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeThreads,
    );
    threads[thread.threadId] = {
      'thread_id': thread.threadId,
      'conversation_id': conversationId,
      'employee_id': thread.employeeId,
      'tool': thread.tool,
      'title': thread.title,
      'status': thread.status,
      'source': thread.source,
      'created_at': createdAt,
      'updated_at': thread.updatedAt,
      'last_task_id': thread.lastTaskId,
    };
    await _client.saveSession(
      session.copyWith(
        localSuperEmployeeThreads: _trimLocalRecordMap(threads, 80),
      ),
    );
  }

  Future<List<SuperEmployeeThread>> _loadLocalSuperEmployeeThreads(
    String conversationId, {
    required bool includeArchived,
  }) async {
    final session = await _client.loadSession();
    final rows = session.localSuperEmployeeThreads.values
        .where((row) =>
            _stringField(row, 'conversation_id') == conversationId.trim())
        .where((row) =>
            includeArchived || _stringField(row, 'archived_at').isEmpty)
        .map(SuperEmployeeThread.fromMap)
        .where((thread) => thread.threadId.isNotEmpty)
        .toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List<SuperEmployeeThread>.unmodifiable(rows);
  }

  Future<List<RelayRunSummary>> _loadLocalSuperEmployeeRuns({
    String threadId = '',
    bool activeOnly = false,
  }) async {
    var session = await _client.loadSession();
    final stored = Map<String, Map<String, Object?>>.of(
      session.localSuperEmployeeRuns,
    );
    var reconciled = false;
    final now = DateTime.now().toUtc().toIso8601String();
    for (final entry in stored.entries.toList(growable: false)) {
      final status = _stringField(entry.value, 'status');
      if (!const {'queued', 'running', 'assigned', 'processing', 'in_progress'}
              .contains(status) ||
          _activeLocalRunIds.contains(entry.key)) {
        continue;
      }
      stored[entry.key] = {
        ...entry.value,
        'status': 'blocked',
        'updated_at': now,
        'completed_at': now,
        'result': const {
          'error': '应用重启前未获得局域网任务的最终结果，可重新执行',
          'execution_source': 'lan',
        },
      };
      reconciled = true;
    }
    if (reconciled) {
      session = session.copyWith(localSuperEmployeeRuns: stored);
      await _client.saveSession(session);
    }
    final selectedThread = threadId.trim();
    final rows = stored.values
        .where((row) =>
            selectedThread.isEmpty ||
            _stringField(row, 'thread_id') == selectedThread)
        .map(RelayRunSummary.fromMap)
        .where((run) => run.taskId.isNotEmpty)
        .where((run) => !activeOnly || run.active)
        .toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List<RelayRunSummary>.unmodifiable(rows);
  }

  Future<bool> _cancelLocalSuperEmployeeRun(String taskId) async {
    final existing = _localCancellationRequests[taskId];
    if (existing != null) return existing;
    final request = _cancelLocalSuperEmployeeRunImpl(taskId);
    _localCancellationRequests[taskId] = request;
    try {
      return await request;
    } finally {
      if (identical(_localCancellationRequests[taskId], request)) {
        _localCancellationRequests.remove(taskId);
      }
    }
  }

  Future<bool> _cancelLocalSuperEmployeeRunImpl(String taskId) async {
    final session = await _client.loadSession();
    final current = session.localSuperEmployeeRuns[taskId];
    if (current == null) return false;
    final currentStatus = _stringField(current, 'status');
    if (currentStatus == 'cancelled') return true;
    if (!const {
      'queued',
      'running',
      'assigned',
      'processing',
      'in_progress',
    }.contains(currentStatus)) {
      return false;
    }

    _stopRequestedLocalRunIds.add(taskId);
    final baseUrl = await _superEmployeeLanBaseUrl();
    var acknowledged = false;
    if (baseUrl.isNotEmpty) {
      try {
        final response = await _client.postJson(
          'api/mobile/v1/admin/super-employee/tasks/'
          '${Uri.encodeComponent(taskId)}/cancel',
          const <String, Object?>{},
          baseUrl: baseUrl,
        );
        final data = _objectMap(response['data']);
        acknowledged = _boolField(data, 'ack') ||
            _boolField(response, 'ack') ||
            _boolField(_objectMap(data['task']), 'ack');
      } catch (_) {
        acknowledged = false;
      }
    }

    if (acknowledged) {
      _cancelledLocalRunIds.add(taskId);
      await _finishLocalSuperEmployeeRun(
        taskId,
        status: 'cancelled',
        resultText: '电脑已确认停止本次局域网执行',
        elapsedSeconds: 0,
      );
      return true;
    }

    // Closing the mobile SSE only stops waiting on the phone. Without an
    // authenticated server acknowledgement the CLI may still be changing
    // files, so keep the record explicitly unconfirmed instead of pretending
    // that the task was cancelled.
    await _finishLocalSuperEmployeeRun(
      taskId,
      status: 'blocked',
      resultText: '只能停止等待，电脑任务可能继续',
      elapsedSeconds: 0,
    );
    return false;
  }

  Future<RelayRunSummary> _retryLocalSuperEmployeeRun(String taskId) async {
    final session = await _client.loadSession();
    final row = session.localSuperEmployeeRuns[taskId];
    if (row == null) {
      throw const MobileRepositoryException('没有找到这条局域网执行记录');
    }
    final baseUrl = await _superEmployeeLanBaseUrl();
    if (baseUrl.isEmpty) {
      throw const MobileRepositoryException('局域网执行电脑当前不可用，无法重试本地任务');
    }
    final conversationId = _stringField(row, 'conversation_id');
    final conversation = _superEmployeeConversationForId(conversationId);
    if (conversation == null) {
      throw const MobileRepositoryException('局域网执行记录缺少员工信息');
    }
    final kind = _stringField(row, 'kind');
    final tool = kind.split('.').first.ifEmpty(
          conversation.type.superTool?.toLowerCase() ?? '',
        );
    final message = _firstString(
      _objectMap(row['payload']),
      const ['message', 'body', 'prompt'],
    );
    if (message.isEmpty) {
      throw const MobileRepositoryException('局域网执行记录缺少原任务内容');
    }
    final threadId = _stringField(row, 'thread_id');
    final reply = await _tryLanSuperEmployeeTask(
      conversation: conversation,
      tool: tool,
      text: message,
      threadId: threadId,
      cacheId: _superEmployeeCacheId(conversationId, threadId),
      baseUrl: baseUrl,
    );
    if (reply == null) {
      throw const MobileRepositoryException('局域网重试失败，请检查电脑服务后再试');
    }
    final refreshed = await _loadLocalSuperEmployeeRuns(threadId: threadId);
    return refreshed.firstWhere(
      (run) => run.taskId != taskId && run.message == message,
      orElse: () => throw const MobileRepositoryException('局域网重试完成但记录未写入'),
    );
  }

  Future<List<ChatMessage>> loadActiveSuperEmployeeMessages(
    String conversationId,
  ) async {
    final threadId = await activeSuperEmployeeThreadId(conversationId);
    return _loadCachedChat(_superEmployeeCacheId(conversationId, threadId));
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

      // 账号下可能累积大量历史 paired 桌面；只派给近期在线（last_seen≤5min）的执行端，
      // 避免任务进死队列后误回落云端 CLI。
      if (storedRelayId.isNotEmpty) {
        for (final row in rows) {
          if (_stringField(row, 'relay_id') == storedRelayId &&
              _relayDesktopIsFresh(row)) {
            return storedRelayId;
          }
        }
      }

      final freshRows =
          rows.where(_relayDesktopIsFresh).toList(growable: false);
      if (freshRows.isEmpty) {
        throw const MobileRepositoryException(
          '当前没有在线的电脑执行端。请在本机 Mac 打开 XCAGI 并保持桌面云中继运行后再试。',
        );
      }

      freshRows.sort((a, b) => _relayDesktopSortKey(a).compareTo(
            _relayDesktopSortKey(b),
          ));
      final latest = freshRows.last;
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
    List<ChatSource> sources = const [],
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
      if (sources.isNotEmpty)
        'sources': sources
            .map(
              (source) => {
                'title': source.title,
                'url': source.url,
                'snippet': source.snippet,
              },
            )
            .toList(growable: false),
    });
    cache[id] = rows.length > 80
        ? rows.sublist(rows.length - 80).toList(growable: false)
        : rows;
    final states = Map<String, Map<String, Object?>>.of(
      session.conversationListStates,
    );
    final listState = _ConversationListState(
      preview: _conversationPreviewForRole(role, text),
      timestampMs: timestampMs,
    ).toJson();
    states[id] = listState;
    if (id.contains('::')) {
      states[id.split('::').first] = listState;
    }
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

Map<String, Object?> _superEmployeeThreadContext(String threadId) {
  final id = threadId.trim();
  return {
    'source': 'mobile_chat',
    'client_surface': 'mobile',
    'workspace_root': _xcmaxDefaultWorkspaceRoot,
    if (id.isNotEmpty) ...{
      'thread_id': id,
      'conversation_id': id,
      'persistent_conversation': true,
    },
  };
}

String _superEmployeeCacheId(String conversationId, String threadId) {
  final base = conversationId.trim();
  final thread = threadId.trim();
  return thread.isEmpty ? base : '$base::$thread';
}

String _assistantThreadTitle(List<Map<String, Object?>> rows) {
  for (final row in rows) {
    if (_stringField(row, 'role') != ChatRole.user.name) continue;
    final body = _stringField(row, 'body').replaceAll(RegExp(r'\s+'), ' ');
    if (body.isEmpty) continue;
    return body.length > 22 ? '${body.substring(0, 22)}…' : body;
  }
  return '小C助理 · 新对话';
}

String? _superEmployeeIdForConversation(String conversationId) {
  switch (conversationId.trim()) {
    case PinnedIds.codex:
      return AiGroupMemberIds.codexSuperEmployee;
    case PinnedIds.claude:
      return AiGroupMemberIds.claudeSuperEmployee;
    case PinnedIds.cursor:
      return AiGroupMemberIds.cursorSuperEmployee;
    case PinnedIds.trae:
      return AiGroupMemberIds.traeSuperEmployee;
    default:
      return null;
  }
}

ConversationItem? _superEmployeeConversationForId(String conversationId) {
  return switch (conversationId.trim()) {
    PinnedIds.codex => const ConversationItem(
        id: PinnedIds.codex,
        type: ConversationType.pinnedCodex,
        title: '超级员工-Codex',
        subtitle: '',
        timestampText: '',
      ),
    PinnedIds.claude => const ConversationItem(
        id: PinnedIds.claude,
        type: ConversationType.pinnedClaude,
        title: '超级员工-Claude',
        subtitle: '',
        timestampText: '',
      ),
    PinnedIds.cursor => const ConversationItem(
        id: PinnedIds.cursor,
        type: ConversationType.pinnedCursor,
        title: '超级员工-Cursor',
        subtitle: '',
        timestampText: '',
      ),
    PinnedIds.trae => const ConversationItem(
        id: PinnedIds.trae,
        type: ConversationType.pinnedTrae,
        title: '超级员工-Trae',
        subtitle: '',
        timestampText: '',
      ),
    _ => null,
  };
}

String _localSuperEmployeeThreadTitle(String message) {
  final clean = message.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (clean.isEmpty) return '局域网新对话';
  return clean.length > 22 ? '${clean.substring(0, 22)}…' : clean;
}

Map<String, Map<String, Object?>> _trimLocalRecordMap(
  Map<String, Map<String, Object?>> source,
  int limit,
) {
  if (source.length <= limit) return source;
  final entries = source.entries.toList()
    ..sort((a, b) => _stringField(b.value, 'updated_at')
        .compareTo(_stringField(a.value, 'updated_at')));
  return {
    for (final entry in entries.take(limit)) entry.key: entry.value,
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

List<Map<String, Object?>> _deepObjectListForKey(Object? value, String key) {
  if (value is Map) {
    final map = _objectMap(value);
    final direct = _objectList(map[key]);
    if (direct.isNotEmpty) return direct;
    for (final nested in map.values) {
      final found = _deepObjectListForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  } else if (value is List) {
    for (final nested in value) {
      final found = _deepObjectListForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  }
  return const <Map<String, Object?>>[];
}

Map<String, Object?> _deepObjectMapForKey(Object? value, String key) {
  if (value is Map) {
    final map = _objectMap(value);
    final direct = _objectMap(map[key]);
    if (direct.isNotEmpty) return direct;
    for (final nested in map.values) {
      final found = _deepObjectMapForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  } else if (value is List) {
    for (final nested in value) {
      final found = _deepObjectMapForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  }
  return const <String, Object?>{};
}

String _deepStringForKey(Object? value, String key) {
  if (value is Map) {
    final map = _objectMap(value);
    final direct = map[key];
    if (direct is String && direct.trim().isNotEmpty) return direct.trim();
    for (final nested in map.values) {
      final found = _deepStringForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  } else if (value is List) {
    for (final nested in value) {
      final found = _deepStringForKey(nested, key);
      if (found.isNotEmpty) return found;
    }
  }
  return '';
}

List<ChatSource> _assistantSourcesFromRows(
  List<Map<String, Object?>> rows,
) {
  return rows
      .map(
        (row) => ChatSource(
          title: _stringField(row, 'title').ifEmpty(
            _stringField(row, 'url'),
          ),
          url: _stringField(row, 'url'),
          snippet: _stringField(row, 'snippet'),
        ),
      )
      .where((source) => source.url.isNotEmpty)
      .toList(growable: false);
}

String _groundedSearchPrompt(String query, List<ChatSource> sources) {
  final evidence = sources
      .take(5)
      .toList(growable: false)
      .asMap()
      .entries
      .map(
        (entry) =>
            '[${entry.key + 1}] ${entry.value.title}\n${entry.value.snippet}\n${entry.value.url}',
      )
      .join('\n\n');
  return '请基于下面的实时联网来源回答用户问题。先给结论，再给关键依据；不要编造来源中没有的信息。\n\n'
      '用户问题：$query\n\n联网来源：\n$evidence';
}

AssistantMemoryRecord _assistantMemoryFromMap(Map<String, Object?> row) {
  final value = row['value'];
  final valueText = value is String
      ? value.trim()
      : value == null
          ? ''
          : jsonEncode(value);
  return AssistantMemoryRecord(
    id: _stringField(row, 'memory_id').ifEmpty(_stringField(row, 'id')),
    type: _stringField(row, 'memory_type').ifEmpty('preference'),
    key: _stringField(row, 'key'),
    value: valueText,
    status: _stringField(row, 'status').ifEmpty('pending'),
    updatedAt: _stringField(row, 'updated_at'),
  );
}

Map<String, Object?> _assistantMemoryToMap(AssistantMemoryRecord record) => {
      'memory_id': record.id,
      'memory_type': record.type,
      'key': record.key,
      'value': record.value,
      'status': record.status,
      if (record.updatedAt.isNotEmpty) 'updated_at': record.updatedAt,
    };

String _officeEmployeeForFilename(String filename) {
  final clean = filename.toLowerCase().trim();
  if (clean.endsWith('.xlsx') ||
      clean.endsWith('.xlsm') ||
      clean.endsWith('.xls')) {
    return 'excel-full-read-employee';
  }
  if (clean.endsWith('.csv')) return 'csv-full-read-employee';
  if (clean.endsWith('.docx') || clean.endsWith('.doc')) {
    return 'word-full-read-employee';
  }
  if (clean.endsWith('.pdf')) return 'pdf-full-read-employee';
  if (clean.endsWith('.pptx') || clean.endsWith('.ppt')) {
    return 'ppt-full-read-employee';
  }
  return '';
}

String _localOfficeText(String filename, List<int> bytes) {
  final clean = filename.toLowerCase().trim();
  if (clean.endsWith('.csv')) {
    try {
      return _take(utf8.decode(bytes, allowMalformed: true).trim(), 12000);
    } catch (_) {
      return '';
    }
  }
  if (!clean.endsWith('.docx') &&
      !clean.endsWith('.pptx') &&
      !clean.endsWith('.xlsx')) {
    return '';
  }
  try {
    final archive = ZipDecoder().decodeBytes(bytes, verify: true);
    if (clean.endsWith('.docx')) {
      final document = archive.findFile('word/document.xml');
      if (document == null) return '';
      return _take(_officeXmlText(utf8.decode(document.content)), 12000);
    }
    if (clean.endsWith('.pptx')) {
      final slides = archive.files
          .where(
            (file) =>
                file.isFile &&
                RegExp(r'^ppt/slides/slide\d+\.xml$').hasMatch(file.name),
          )
          .toList()
        ..sort((left, right) => left.name.compareTo(right.name));
      return _take(
        slides
            .asMap()
            .entries
            .map((entry) {
              final text = _officeXmlText(utf8.decode(entry.value.content));
              return text.isEmpty ? '' : '第 ${entry.key + 1} 页\n$text';
            })
            .where((text) => text.isNotEmpty)
            .join('\n\n'),
        12000,
      );
    }
    final sharedStrings = archive.findFile('xl/sharedStrings.xml');
    if (sharedStrings == null) return '';
    final xml = utf8.decode(sharedStrings.content);
    final rows = RegExp(r'<si\b[^>]*>([\s\S]*?)</si>')
        .allMatches(xml)
        .map((match) => _officeXmlText(match.group(1) ?? ''))
        .where((text) => text.isNotEmpty)
        .toList(growable: false);
    return _take(rows.join('\n'), 12000);
  } catch (_) {
    return '';
  }
}

String _officeXmlText(String xml) {
  var text = xml
      .replaceAll(RegExp(r'</(?:w:p|a:p|row|si)>'), '\n')
      .replaceAll(RegExp(r'<(?:w:tab|w:br|a:br)\b[^>]*/>'), '\n')
      .replaceAll(RegExp(r'<[^>]+>'), ' ')
      .replaceAll('&amp;', '&')
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&apos;', "'")
      .replaceAll('&#39;', "'");
  text = text.replaceAllMapped(
    RegExp(r'&#(x[0-9a-fA-F]+|[0-9]+);'),
    (match) {
      final raw = match.group(1) ?? '';
      final radix = raw.toLowerCase().startsWith('x') ? 16 : 10;
      final digits = radix == 16 ? raw.substring(1) : raw;
      final codePoint = int.tryParse(digits, radix: radix);
      return codePoint == null
          ? match.group(0)!
          : String.fromCharCode(codePoint);
    },
  );
  return text
      .split('\n')
      .map((line) => line.replaceAll(RegExp(r'[ \t]+'), ' ').trim())
      .where((line) => line.isNotEmpty)
      .join('\n');
}

bool _looksLikeOfficeMetadata(String text) {
  final value = text.toLowerCase();
  return value.contains('output_path') &&
      (value.contains('text_output_path') || value.contains('output_schema'));
}

String _officeAnalysisSummary(Map<String, Object?> response) {
  for (final key in const ['summary', 'markdown', 'text', 'content']) {
    final value = _deepStringForKey(response, key);
    if (value.isNotEmpty) return _take(value, 12000);
  }
  try {
    final data = _nestedDataMap(response);
    return _take(jsonEncode(data), 12000);
  } catch (_) {
    return '';
  }
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

double _doubleField(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value.trim()) ?? 0;
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
    sources: _objectList(json['sources'])
        .map(
          (source) => ChatSource(
            title: _stringField(source, 'title'),
            url: _stringField(source, 'url'),
            snippet: _stringField(source, 'snippet'),
          ),
        )
        .where((source) => source.url.isNotEmpty)
        .toList(growable: false),
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
    this.source = 'cloud',
  });

  final String taskId;
  final String status;
  final String toolLabel;
  final String source;

  String get sourceLabel => source == 'lan' ? '局域网' : '云中继';
}

class SuperEmployeeThread {
  const SuperEmployeeThread({
    required this.threadId,
    required this.employeeId,
    required this.tool,
    required this.title,
    required this.status,
    required this.updatedAt,
    this.cliSessionId = '',
    this.workspaceRoot = '',
    this.branch = '',
    this.lastTaskId = '',
    this.archived = false,
    this.source = 'cloud',
  });

  factory SuperEmployeeThread.fromMap(Map<String, Object?> json) {
    return SuperEmployeeThread(
      threadId: _stringField(json, 'thread_id'),
      employeeId: _stringField(json, 'employee_id'),
      tool: _stringField(json, 'tool'),
      title: _stringField(json, 'title').ifEmpty('未命名对话'),
      status: _stringField(json, 'status').ifEmpty('idle'),
      updatedAt: _stringField(json, 'updated_at'),
      cliSessionId: _stringField(json, 'cli_session_id'),
      workspaceRoot: _stringField(json, 'workspace_root'),
      branch: _stringField(json, 'branch'),
      lastTaskId: _stringField(json, 'last_task_id'),
      archived: _stringField(json, 'archived_at').isNotEmpty,
      source: _stringField(json, 'source').ifEmpty('cloud'),
    );
  }

  final String threadId;
  final String employeeId;
  final String tool;
  final String title;
  final String status;
  final String updatedAt;
  final String cliSessionId;
  final String workspaceRoot;
  final String branch;
  final String lastTaskId;
  final bool archived;
  final String source;

  String get sourceLabel => source == 'lan' ? '局域网' : '云中继';
}

class RelayRunSummary {
  const RelayRunSummary({
    required this.taskId,
    required this.threadId,
    required this.workItemId,
    required this.employeeId,
    required this.kind,
    required this.status,
    required this.attemptNo,
    required this.createdAt,
    required this.updatedAt,
    this.completedAt = '',
    this.message = '',
    this.resultText = '',
    this.branch = '',
    this.elapsedSeconds = 0,
    this.source = 'cloud',
  });

  factory RelayRunSummary.fromMap(Map<String, Object?> json) {
    final payload = _objectMap(json['payload']);
    final result = _objectMap(json['result']);
    final nested = _objectMap(result['codex']);
    final session = _objectMap(result['session']).isNotEmpty
        ? _objectMap(result['session'])
        : _objectMap(nested['session']);
    return RelayRunSummary(
      taskId: _stringField(json, 'task_id'),
      threadId: _stringField(json, 'thread_id'),
      workItemId: _stringField(json, 'work_item_id'),
      employeeId: _stringField(json, 'employee_id'),
      kind: _stringField(json, 'kind'),
      status: _stringField(json, 'status'),
      attemptNo: _intField(json, 'attempt_no') <= 0
          ? 1
          : _intField(json, 'attempt_no'),
      createdAt: _stringField(json, 'created_at'),
      updatedAt: _stringField(json, 'updated_at'),
      completedAt: _stringField(json, 'completed_at'),
      message: _firstString(payload, const ['message', 'body', 'prompt']),
      resultText: _relayTaskResultText(json),
      branch: _firstString(session, const ['branch']),
      elapsedSeconds: _doubleField(result, 'elapsed_seconds'),
      source: _stringField(json, 'source').ifEmpty('cloud'),
    );
  }

  final String taskId;
  final String threadId;
  final String workItemId;
  final String employeeId;
  final String kind;
  final String status;
  final int attemptNo;
  final String createdAt;
  final String updatedAt;
  final String completedAt;
  final String message;
  final String resultText;
  final String branch;
  final double elapsedSeconds;
  final String source;

  String get sourceLabel => source == 'lan' ? '局域网' : '云中继';

  bool get active => const {
        'queued',
        'running',
        'assigned',
        'processing',
        'in_progress',
      }.contains(status);
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

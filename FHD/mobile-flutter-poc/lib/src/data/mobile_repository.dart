import 'dart:async';
import 'dart:convert';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../models/conversation.dart';
import '../policy/android_runtime_policy.dart';
import '../policy/avatar_policy.dart';
import '../policy/pinned_ids.dart';
import 'ai_employee_profile.dart';
import 'duty_roster_ssot.dart';

const _badgeAdminColor = 0xFFED7B2F;
const _badgeInstalledColor = 0xFF3370FF;

class MobileRepository {
  MobileRepository({MobileApiClient? client})
      : _client = client ?? MobileApiClient();

  static const customerServiceRequestType = 'mobile_ai_customer_service';

  final MobileApiClient _client;

  MobileApiClient get client => _client;

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

    if (!adminMode && !enterpriseMode) return fixed;

    final mods = await _loadModInfosOrCache(adminMode: adminMode);
    return [
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: adminMode ? '管理端' : '已安装',
        badgeColor: adminMode ? _badgeAdminColor : _badgeInstalledColor,
        states: conversationStates,
      ),
    ];
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

    if (!adminMode && !enterpriseMode) return fixed;

    final mods = await _loadCachedModInfos(adminMode: adminMode);
    return [
      ...fixed,
      ..._employeeConversationItems(
        mods,
        badgeText: adminMode ? '管理端' : '已安装',
        badgeColor: adminMode ? _badgeAdminColor : _badgeInstalledColor,
        states: conversationStates,
      ),
    ];
  }

  Future<List<ModInfo>> loadModInfos({bool adminMode = false}) async {
    if (adminMode) {
      final response = await _client.adminHome();
      if (!response.success) {
        throw MobileRepositoryException(
          response.message.ifEmpty('管理端移动数据加载失败'),
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
      final session = await _client.loadSession();
      await _client.sessionStore.save(
        session.copyWith(
          cachedModInfos: mods.map(_modInfoToJson).toList(growable: false),
        ),
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
    final parsed = parsePairingPayload(raw);
    if (parsed != null && parsed.version >= 3 && parsed.relayId.isNotEmpty) {
      throw const MobileRepositoryException(
        '云中继绑定已改为账号鉴权，请刷新电脑端内网二维码后绑定',
      );
    }
    final baseUrl = parsed == null
        ? ''
        : parsed.apiBaseUrl.isNotEmpty
            ? parsed.apiBaseUrl
            : _pairingBaseUrl(parsed.host, parsed.port);
    final code = parsed?.code.trim() ?? '';
    final nonce = parsed == null
        ? raw.trim()
        : parsed.version >= 2 && code.isEmpty
            ? parsed.nonce.ifEmpty(parsed.token)
            : parsed.nonce;
    final response = await _client.exchangePairing(
      nonce: nonce,
      code: code,
      baseUrl: baseUrl,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('设备配对失败'));
    }
    await _client.persistPairingSession(
      response.data,
      hostWithPort: parsed?.hostWithPort ?? '',
      clearRelayDesktop: true,
      setupComplete: true,
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
        response.message.ifEmpty(adminMode ? '服务器后台账号或密码错误' : '用户名或密码错误'),
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
      final response = await _client.postSuperEmployeeMessage(tool, text);
      if (!response.success) {
        throw MobileRepositoryException(response.message.ifEmpty('超级员工回复失败'));
      }
      final reply = _assistantReplyFromMap(
        response.data ?? response.raw,
      ).ifEmpty('已收到，我会继续处理。');
      return _assistantMessage(conversation.id, reply);
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
      final relayKind = relayKindForConversation(conversation.id);
      final relayId = await _relayIdForSuperEmployeeDispatch();
      if (relayKind != null && relayId.isNotEmpty) {
        final reply = await _streamRelaySuperEmployeeTask(
          relayId: relayId,
          relayKind: relayKind,
          conversationId: conversation.id,
          message: text,
          onToken: onToken,
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
      final reply = await _postSuperEmployeeMessage(tool, text);
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
    bool Function()? isCancelled,
  }) async {
    final taskId = await _inflightRelayTask(conversationId);
    if (taskId.isEmpty) return null;
    if (await _clearInflightIfRelayChanged(conversationId, taskId)) {
      return null;
    }
    final kind = relayKindForConversation(conversationId);
    onToken?.call('思考中...');
    final reply = await _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabelForRelayKind(kind ?? 'codex.invoke'),
      conversationId: conversationId,
      onToken: onToken,
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
    await _client.sessionStore
        .save(session.copyWith(cachedChatMessages: cache));
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
    if (!const {'git.merge', 'git.diff', 'git.discard'}.contains(cleanOp)) {
      throw MobileRepositoryException('未知 git 操作：$cleanOp');
    }

    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw MobileRepositoryException('未绑定电脑执行端，无法执行 $cleanOp');
    }

    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: cleanOp,
      payload: {
        'branch': cleanBranch,
        'context': const {
          'source': 'mobile_chat',
          'client_surface': 'mobile',
        },
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
        return _relayTaskResultText(current).ifEmpty('电脑执行端已完成任务。');
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('电脑执行端执行失败'),
        );
      }
    }
    throw MobileRepositoryException(
      lastStatus.isEmpty
          ? '电脑执行端暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。'
          : '电脑执行端仍处于 $lastStatus，任务仍在后台运行，可稍后回到此会话查看。',
    );
  }

  Future<String> _postSuperEmployeeMessage(String tool, String text) async {
    final response = await _client.postSuperEmployeeMessage(tool, text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工回复失败'));
    }
    return _assistantReplyFromMap(response.data ?? response.raw)
        .ifEmpty('已收到，我会继续处理。');
  }

  Future<String> _streamRelaySuperEmployeeTask({
    required String relayId,
    required String relayKind,
    required String conversationId,
    required String message,
    void Function(String token)? onToken,
    bool Function()? isCancelled,
  }) async {
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: relayKind,
      payload: {
        'message': message,
        'context': {
          'source': 'mobile_chat',
          'client_surface': 'mobile',
          'conversation_id': conversationId,
        },
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
    onToken?.call('思考中...');
    return _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabelForRelayKind(relayKind),
      conversationId: conversationId,
      onToken: onToken,
      isCancelled: isCancelled,
    );
  }

  Future<String> _pollRelayTask({
    required String taskId,
    required String toolLabel,
    required String conversationId,
    void Function(String token)? onToken,
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
        switch (currentStatus) {
          case 'running':
          case 'assigned':
            onToken?.call('\n电脑执行端正在运行 $toolLabel。');
            break;
          case 'queued':
            onToken?.call('\n任务仍在服务器队列中。');
            break;
        }
        lastStatus = currentStatus;
      }
      if (currentStatus == 'done' || currentStatus == 'completed') {
        await _setInflightRelayTask(conversationId, '');
        return _relayTaskResultText(current).ifEmpty('电脑执行端已完成任务。');
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        await _setInflightRelayTask(conversationId, '');
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('电脑执行端执行失败'),
        );
      }
    }
    throw const MobileRepositoryException(
      '电脑执行端暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。',
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
    return [
      ..._fixedConversationItems(
        showCodex: enterpriseMode || adminMode,
        showCursor: enterpriseMode || adminMode,
        showClaude: enterpriseMode || adminMode,
        showTrae: enterpriseMode || adminMode,
        showCustomerService: enterpriseMode && !adminMode,
        states: _emptyConversationStates,
      ),
      if (adminMode) ...adminDutyRosterConversationItems(),
    ];
  }

  Future<String> _relayIdForSuperEmployeeDispatch() async {
    final configured = _client.configuredRelayId;
    try {
      final response = await _client.relayDesktops();
      if (!response.success) return configured;
      final rows = _relayDesktopRows(response.data)
          .where(_relayDesktopIsDispatchable)
          .toList(growable: false);
      if (rows.isEmpty) return configured;
      rows.sort((a, b) => _relayDesktopSortKey(a).compareTo(
            _relayDesktopSortKey(b),
          ));
      return _stringField(rows.last, 'relay_id').ifEmpty(configured);
    } catch (_) {
      return configured;
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
    await _client.sessionStore
        .save(session.copyWith(inflightRelayTasks: tasks));
  }

  Future<bool> _clearInflightIfRelayChanged(
    String conversationId,
    String taskId,
  ) async {
    final currentRelayId = await _relayIdForSuperEmployeeDispatch();
    if (currentRelayId.isEmpty) return false;
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
    await _client.sessionStore.save(
      session.copyWith(
        cachedChatMessages: cache,
        conversationListStates: states,
      ),
    );
  }
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

Map<String, Object?> _modInfoToJson(ModInfo mod) {
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
    'avatar_url': mod.avatarUrl,
    'frontend_menu': mod.frontendMenu.map(_modMenuItemToJson).toList(
          growable: false,
        ),
    'workflow_employees':
        mod.workflowEmployees.map(_workflowEmployeeToJson).toList(
              growable: false,
            ),
  }..removeWhere((_, value) => value == null);
}

Map<String, Object?> _modMenuItemToJson(ModMenuItem item) {
  return {
    'id': item.id,
    'label': item.label,
    'icon': item.icon,
    'path': item.path,
  };
}

Map<String, Object?> _workflowEmployeeToJson(WorkflowEmployeeInfo employee) {
  return {
    'id': employee.id,
    'label': employee.label,
    'panel_title': employee.panelTitle,
    'panel_summary': employee.panelSummary,
    'api_base_path': employee.apiBasePath,
    'phone_channel': employee.phoneChannel,
    'workflow_placeholder': employee.workflowPlaceholder,
    'profile_source': employee.profileSource,
    'market_connected': employee.marketConnected,
    'market_pkg_id': employee.marketPkgId,
    'market_name': employee.marketName,
    'market_description': employee.marketDescription,
    'market_version': employee.marketVersion,
    'market_author': employee.marketAuthor,
    'market_industry': employee.marketIndustry,
    'market_material_category': employee.marketMaterialCategory,
    'market_license_scope': employee.marketLicenseScope,
    'market_security_level': employee.marketSecurityLevel,
    'market_avatar': employee.marketAvatar,
  }..removeWhere((_, value) => value == null);
}

bool _relayDesktopIsDispatchable(Map<String, Object?> row) {
  final relayId = _stringField(row, 'relay_id');
  final status = _stringField(row, 'status').toLowerCase();
  return relayId.isNotEmpty && status == 'paired';
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

String _pairingBaseUrl(String host, int port) {
  final hostWithPort = _compactPairingHostPort(host, port);
  if (hostWithPort.isEmpty) return '';
  return 'http://$hostWithPort/fhd-api';
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
  return AiGroupConversation(
    id: _stringField(json, 'id'),
    name: _stringField(json, 'name'),
    memberCount: _intField(json, 'member_count'),
    preview: _stringField(json, 'last_message_preview'),
    timestampText: _friendlyGroupTimestamp(
      _stringField(json, 'last_message_at'),
    ),
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
        '$plannedAdminEmployeeCount 位管理端 duty AI 员工与 ${mod.frontendMenu.length} 个管理功能入口',
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
  required String badgeText,
  required int badgeColor,
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
        return '管理端工作台';
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
  final direct = _firstString(json, const [
    'reply',
    'answer',
    'response',
    'message',
    'body',
    'content',
    'text',
  ]);
  if (direct.isNotEmpty) return direct;

  final data = json['data'];
  if (data is Map<String, Object?>) return _assistantReplyFromMap(data);
  if (data is Map) {
    return _assistantReplyFromMap(
      data.map((key, value) => MapEntry(key.toString(), value)),
    );
  }
  return '';
}

String _firstString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value == null) continue;
    final text = value.toString().trim();
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

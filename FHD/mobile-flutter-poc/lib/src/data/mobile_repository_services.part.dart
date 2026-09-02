part of 'mobile_repository.dart';

abstract class _RepoServicesBase extends _RepoChatBase {
  _RepoServicesBase({
    MobileApiClient? client,
    ImWebSocketClient? imWebSocket,
  }) : super(client: client, imWebSocket: imWebSocket);

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
        .map((id) => OnboardingIndustry(id: id, title: id, subtitle: '可选行业'))
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
    for (final modId in _stringList(
      baseline['missing_account_custom_mod_ids'],
    )) {
      final install = await _client.installMod(
        modId: modId,
        industryId: industry,
      );
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
          seed.message.ifEmpty('$modId 交付数据安装失败'),
        );
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

  Future<void> installMarketMod(
    String modId, {
    String industryId = '通用',
  }) async {
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
      throw MobileRepositoryException(response.message.ifEmpty('加载员工提问失败'));
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
        ? MobileServerMode.lan
        : MobileServerMode.cloud;
    return MobileServerRouter(
      fhdHost: host.isNotEmpty ? host : '127.0.0.1',
      mode: mode,
      enterpriseFhdBaseUrlRaw: MobileBuildConfig.enterpriseFhdBaseUrl,
      modstoreBaseUrlRaw: MobileBuildConfig.modstoreBaseUrl,
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

}

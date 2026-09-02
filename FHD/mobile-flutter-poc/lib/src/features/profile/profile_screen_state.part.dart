part of 'profile_screen.dart';

// 个人资料页状态类。
class _ProfileScreenState extends State<ProfileScreen> {
  late final MobileApiClient _api;
  late final ImagePicker _imagePicker;
  late Future<WalletBalanceData> _walletFuture;
  var _displayName = '未登录';
  var _avatarPath = '';
  var _accountKindLabel = '账号';
  var _serverModeLabel = '远程同步可用';
  var _profilePage = const MobileProfilePageConfig.disabled();
  var _syncing = false;
  var _hasLocalDisplayName = false;
  var _hasLocalAvatar = false;
  var _hasLocalAccountKind = false;

  @override
  void initState() {
    super.initState();
    _api = widget.api ??
        MobileRepositoryScope.maybeRead(context)?.client ??
        MobileApiClient();
    _imagePicker = ImagePicker();
    _walletFuture = _loadWallet();
    _loadCachedProfile();
    _refreshMe();
    _refreshAppConfig();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      color: colors.surface,
      child: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const WeTopBar(title: '个人'),
            Expanded(
              child: FutureBuilder<WalletBalanceData>(
                future: _walletFuture,
                builder: (context, snapshot) {
                  final wallet = snapshot.data ??
                      WalletBalanceData.mobileCurrentFallback();
                  return ListView(
                    padding: EdgeInsets.zero,
                    children: [
                      _ProfileHeroCard(
                        displayName: _displayName,
                        avatarPath: _avatarPath,
                        accountKindLabel: _accountKindLabel,
                        serverModeLabel: _serverModeLabel,
                        profilePage: _profilePage.enabled ? _profilePage : null,
                        syncing: _syncing,
                        onEdit: _showProfileEditor,
                        onSync: _refreshProfileState,
                      ),
                      const SizedBox(height: 8),
                      _WalletBalanceCard(
                        wallet: wallet,
                        onRefresh: _refreshWallet,
                      ),
                      const SizedBox(height: 8),
                      WeCellGroup(
                        children: [
                          WeCell(
                            title: '扫码绑定',
                            subtitle: '绑定服务器后台、企业工作台或电脑执行端',
                            icon: Icons.qr_code_2,
                            iconColor: Theme.of(context).colorScheme.secondary,
                            iconBg: Theme.of(
                              context,
                            ).colorScheme.secondaryContainer,
                            onTap: _openConnectPc,
                          ),
                          WeCell(
                            title: '服务',
                            subtitle: _serverModeLabel,
                            icon: Icons.verified,
                            iconColor: Theme.of(context).colorScheme.secondary,
                            iconBg: Theme.of(
                              context,
                            ).colorScheme.secondaryContainer,
                            showDivider: false,
                            onTap: _openSettings,
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      WeCellGroup(
                        children: [
                          WeCell(
                            title: '设置',
                            icon: Icons.settings,
                            iconColor: colors.brand,
                            iconBg: colors.brandContainer,
                            onTap: _openSettings,
                          ),
                          WeCell(
                            title: '关于',
                            subtitle: '成都修茈科技有限公司',
                            icon: Icons.account_balance_wallet,
                            iconColor: colors.warning,
                            iconBg: Theme.of(
                              context,
                            ).colorScheme.primaryContainer,
                            showDivider: false,
                            onTap: _openAbout,
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      const WeSectionCaption('账号管理'),
                      WeCellGroup(
                        children: [
                          WeRedActionCell(text: '退出登录', onTap: _logout),
                        ],
                      ),
                      const SizedBox(height: 8),
                      WeCellGroup(
                        children: [
                          WeRedActionCell(
                            text: '注销账号',
                            onTap: _showDeleteAccountDialog,
                          ),
                        ],
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                        child: Text(
                          MobileBuildConfig.profileVersionText,
                          style: TextStyle(
                            color: colors.textTertiary,
                            fontSize: 11,
                            height: 1.27,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                        child: Center(
                          child: Text(
                            '蜀ICP备2026014056号-3A',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: colors.textTertiary,
                              fontSize: 11,
                              height: 1.27,
                              letterSpacing: 0,
                            ),
                          ),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<WalletBalanceData> _loadWallet() async {
    final cached = await _loadCachedWallet();
    if (cached != null) {
      unawaited(_refreshWalletFromNetwork());
      return cached;
    }
    return _loadWalletFromNetworkOrFallback();
  }

  Future<WalletBalanceData?> _loadCachedWallet() async {
    try {
      final session = await _api.loadSession();
      final raw = session.walletBalanceJson.trim();
      if (raw.isEmpty) return null;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      return WalletBalanceData.fromJson(Map<String, Object?>.from(decoded));
    } catch (_) {
      return null;
    }
  }

  Future<WalletBalanceData> _loadWalletFromNetworkOrFallback() async {
    try {
      final envelope = await _api.walletBalance();
      final wallet = envelope.data ?? WalletBalanceData.mobileCurrentFallback();
      unawaited(_api.saveWalletBalanceJson(_walletBalanceCacheJson(wallet)));
      return wallet;
    } catch (_) {
      return await _loadCachedWallet() ??
          WalletBalanceData.mobileCurrentFallback();
    }
  }

  void _refreshWallet() {
    setState(() {
      _walletFuture = _loadWalletFromNetworkOrFallback();
    });
  }

  Future<void> _refreshWalletFromNetwork() async {
    final wallet = await _loadWalletFromNetworkOrFallback();
    if (!mounted) return;
    setState(() {
      _walletFuture = Future.value(wallet);
    });
  }

  Future<void> _loadCachedProfile() async {
    try {
      final session = await _api.loadSession();
      if (!mounted) return;
      setState(() {
        _serverModeLabel = session.mobileServerModeLabel;
        if (!session.hasIdentity) return;
        if (session.username.trim().isNotEmpty) {
          _displayName = session.username.trim();
          _hasLocalDisplayName = true;
        }
        if (session.accountKind.trim().isNotEmpty) {
          _accountKindLabel = _profileAccountKindLabel(
            session.accountKind,
            _accountKindLabel,
          );
          _hasLocalAccountKind = true;
        }
        final localAvatar = session.localAvatarSource.trim();
        if (localAvatar.isNotEmpty) {
          _avatarPath = localAvatar;
          _hasLocalAvatar = true;
        }
      });
    } catch (_) {
      // Keep the last visible state if local profile storage is unavailable.
    }
  }

  Future<void> _refreshAppConfig() async {
    try {
      final config = await _api.appConfig();
      if (!mounted) return;
      setState(() {
        _profilePage = config.profilePage;
      });
    } catch (_) {
      // Keep the mobile defaults when the market config endpoint is offline.
    }
  }

  Future<void> _refreshMe() async {
    try {
      final envelope = await _api.me();
      if (!envelope.success || !mounted) return;
      final me = MobileMeData.fromJson(
        envelope.data ?? const <String, Object?>{},
      );
      setState(() {
        if (!_hasLocalDisplayName) {
          _displayName = me.displayName.ifEmpty(_displayName).ifEmpty('未登录');
        }
        if (!_hasLocalAccountKind) {
          _accountKindLabel = me.accountKindLabel;
        }
        if (me.avatarSource.isNotEmpty && !_hasLocalAvatar) {
          _avatarPath = me.avatarSource;
        }
      });
    } catch (_) {
      // Keep locally edited profile fields when account sync is unavailable.
    }
  }

  Future<void> _refreshProfileState() async {
    if (_syncing) return;
    setState(() {
      _syncing = true;
      _walletFuture = _loadWallet();
    });
    try {
      await Future.wait<void>([
        _loadCachedProfile(),
        _refreshAppConfig(),
        _refreshMe(),
      ]);
    } finally {
      if (mounted) {
        setState(() => _syncing = false);
      }
    }
  }

  void _openConnectPc() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const ConnectScreen(fromProfile: true)),
    );
  }

  void _openSettings() {
    Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (_) => SettingsScreen(api: _api)));
  }

  void _openAbout() {
    Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (_) => AboutScreen(api: _api)));
  }

  Future<void> _logout() async {
    final before = await _api.loadSession().catchError(
          (_) => MobileSessionData.empty,
        );
    await _api.clearActiveAuth();
    if (!mounted) return;
    _replaceWithMobileLogoutDestination(before);
  }

  void _replaceWithMobileLogoutDestination(MobileSessionData before) {
    final setupComplete =
        before.setupComplete || before.fhdHost.trim().isNotEmpty;
    final Widget destination = setupComplete
        ? const AuthScreen()
        : const ConnectScreen(fromProfile: true);
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => destination),
      (_) => false,
    );
  }

  Future<void> _showProfileEditor() async {
    final result = await showDialog<_ProfileEditResult>(
      context: context,
      builder: (_) => _ProfileEditorDialog(
        displayName: _displayName,
        avatarPath: _avatarPath,
        onPickAvatar: _pickAvatar,
      ),
    );
    if (result == null) return;
    final previousName = _displayName;
    final previousAvatar = _avatarPath;
    setState(() {
      _displayName = result.displayName;
      _avatarPath = result.avatarPath;
      _hasLocalDisplayName = true;
      _hasLocalAvatar = result.avatarPath.trim().isNotEmpty;
    });
    await _api.saveLocalProfile(
      displayName: result.displayName,
      avatarSource: result.avatarPath,
    );
    if (!mounted) return;
    final nameChanged = result.displayName != previousName;
    final avatarChanged = result.avatarPath != previousAvatar;
    final message = avatarChanged && !nameChanged
        ? (result.avatarPath.isEmpty ? '头像已移除' : '头像已更新')
        : '资料已保存';
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<String?> _pickAvatar() async {
    final image = await _imagePicker.pickImage(source: ImageSource.gallery);
    return image?.path;
  }

  Future<void> _showDeleteAccountDialog() async {
    final password = await showDialog<String>(
      context: context,
      builder: (_) => const _DeleteAccountDialog(),
    );
    if (password == null) return;
    try {
      await _api.deleteAccount(password);
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('账号已成功注销')));
      _replaceWithAuth();
    } catch (error) {
      if (!mounted) return;
      final message = error is MobileApiException
          ? error.message
          : error.toString().replaceFirst('Exception: ', '');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message.isEmpty ? '注销失败，请检查网络后重试' : message)),
      );
    }
  }

  void _replaceWithAuth() {
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const AuthScreen()),
      (_) => false,
    );
  }
}

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_models.dart';
import '../../api/mobile_session_store.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../about/about_screen.dart';
import '../auth/auth_screen.dart';
import '../connect/connect_screen.dart';
import '../settings/settings_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, this.api});

  final MobileApiClient? api;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late final MobileApiClient _api;
  late final ImagePicker _imagePicker;
  late Future<WalletBalanceData> _walletFuture;
  var _displayName = 'admin';
  var _avatarPath = '';
  var _accountKindLabel = '管理员账号';
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
                      WalletBalanceData.androidCurrentFallback();
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
                            iconBg: Theme.of(context)
                                .colorScheme
                                .secondaryContainer,
                            onTap: _openConnectPc,
                          ),
                          WeCell(
                            title: '服务',
                            subtitle: _serverModeLabel,
                            icon: Icons.verified,
                            iconColor: Theme.of(context).colorScheme.secondary,
                            iconBg: Theme.of(context)
                                .colorScheme
                                .secondaryContainer,
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
                            iconBg: colors.warning.withValues(alpha: 0.12),
                            showDivider: false,
                            onTap: _openAbout,
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      const WeSectionCaption('账号管理'),
                      WeCellGroup(
                        children: [
                          WeRedActionCell(
                            text: '退出登录',
                            onTap: _logout,
                          ),
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
                          MobileAndroidBuild.profileVersionText,
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
      final wallet =
          envelope.data ?? WalletBalanceData.androidCurrentFallback();
      unawaited(_api.saveWalletBalanceJson(_walletBalanceCacheJson(wallet)));
      return wallet;
    } catch (_) {
      return await _loadCachedWallet() ??
          WalletBalanceData.androidCurrentFallback();
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
        _serverModeLabel = session.androidServerModeLabel;
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
      // Android keeps the last visible state if local profile storage is unavailable.
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
      // Keep the Android defaults when the market config endpoint is offline.
    }
  }

  Future<void> _refreshMe() async {
    try {
      final envelope = await _api.me();
      if (!envelope.success || !mounted) return;
      final me =
          MobileMeData.fromJson(envelope.data ?? const <String, Object?>{});
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
      MaterialPageRoute(
        builder: (_) => const ConnectScreen(fromProfile: true),
      ),
    );
  }

  void _openSettings() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => SettingsScreen(api: _api)),
    );
  }

  void _openAbout() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => AboutScreen(api: _api)),
    );
  }

  Future<void> _logout() async {
    final before = await _api.loadSession().catchError(
          (_) => MobileSessionData.empty,
        );
    await _api.clearActiveAuth();
    if (!mounted) return;
    _replaceWithAndroidLogoutDestination(before);
  }

  void _replaceWithAndroidLogoutDestination(MobileSessionData before) {
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
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('账号已成功注销')),
      );
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

String _profileAccountKindLabel(String accountKind, String fallback) {
  switch (accountKind.trim().toLowerCase()) {
    case 'admin':
    case 'admin_portal':
      return '管理员账号';
    case 'enterprise':
      return '企业账号';
    case 'personal':
      return '个人账号';
    default:
      return fallback;
  }
}

String _walletBalanceCacheJson(WalletBalanceData wallet) {
  return jsonEncode({
    'balance': wallet.balance,
    'currency': wallet.currency,
    'membership_level': wallet.membershipLevel,
    'experience': wallet.experience,
    'byok_configured': wallet.byokConfigured,
    'byok_count': wallet.byokCount,
    'synced': wallet.synced,
    'message': wallet.message,
  });
}

class _ProfileEditResult {
  const _ProfileEditResult({
    required this.displayName,
    required this.avatarPath,
  });

  final String displayName;
  final String avatarPath;
}

class _ProfileEditorDialog extends StatefulWidget {
  const _ProfileEditorDialog({
    required this.displayName,
    required this.avatarPath,
    required this.onPickAvatar,
  });

  final String displayName;
  final String avatarPath;
  final Future<String?> Function() onPickAvatar;

  @override
  State<_ProfileEditorDialog> createState() => _ProfileEditorDialogState();
}

class _ProfileEditorDialogState extends State<_ProfileEditorDialog> {
  late final TextEditingController _controller;
  late String _avatarPath;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.displayName);
    _avatarPath = widget.avatarPath;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final draft = _controller.text.trim();
    final colors = AppTheme.colors(context);
    return AlertDialog(
      title: const Text('个人资料'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _ProfileAvatarPreview(avatarPath: _avatarPath, size: 76),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              TextButton(
                onPressed: _pickAvatar,
                child: const Text('更换头像'),
              ),
              TextButton(
                onPressed: _avatarPath.isEmpty
                    ? null
                    : () => setState(() => _avatarPath = ''),
                child: const Text('移除'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          WeField(
            controller: _controller,
            placeholder: '昵称',
            maxLength: 32,
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              '${_controller.text.length}/32',
              style: TextStyle(
                color: colors.textTertiary,
                fontSize: 11,
                height: 1.27,
                letterSpacing: 0,
              ),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: draft.isEmpty ? null : _save,
          child: const Text('保存'),
        ),
      ],
    );
  }

  Future<void> _pickAvatar() async {
    final path = await widget.onPickAvatar();
    if (path == null || !mounted) return;
    setState(() => _avatarPath = path);
  }

  void _save() {
    final name = _controller.text.trim();
    if (name.isEmpty) return;
    Navigator.of(context).pop(
      _ProfileEditResult(
        displayName: name.length > 32 ? name.substring(0, 32) : name,
        avatarPath: _avatarPath,
      ),
    );
  }
}

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final password = _controller.text;
    return AlertDialog(
      title: const Text('注销账号'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('注销后无法恢复，请确认密码。'),
          const SizedBox(height: 16),
          WeField(
            controller: _controller,
            placeholder: '密码',
            obscureText: true,
            singleLine: true,
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(password),
          child: const Text('确认注销'),
        ),
      ],
    );
  }
}

class _ProfileHeroCard extends StatelessWidget {
  const _ProfileHeroCard({
    required this.displayName,
    required this.avatarPath,
    required this.accountKindLabel,
    required this.serverModeLabel,
    required this.profilePage,
    required this.syncing,
    required this.onEdit,
    required this.onSync,
  });

  final String displayName;
  final String avatarPath;
  final String accountKindLabel;
  final String serverModeLabel;
  final MobileProfilePageConfig? profilePage;
  final bool syncing;
  final VoidCallback onEdit;
  final VoidCallback onSync;

  @override
  Widget build(BuildContext context) {
    final page = profilePage;
    final colors = AppTheme.colors(context);
    final accent = _profileAccentColor(context, page?.accent);
    final solidHero = page?.heroVariant.toLowerCase() == 'solid';
    final headline = page?.headline.trim() ?? '';
    final subtitle = (page?.subtitle ?? '').ifEmpty('个人资料与工作身份');
    final readyStatus = (page?.statusReady ?? '').ifEmpty('资料、头像和工作台状态已就绪');
    final syncingStatus = (page?.statusSyncing ?? '').ifEmpty('正在同步你的资料与工作台状态');
    final primaryChip = (page?.primaryChip ?? '').ifEmpty(accountKindLabel);
    final secondaryChip = (page?.secondaryChip ?? '').ifEmpty(serverModeLabel);
    final titleColor =
        solidHero ? colors.chatUserBubbleText : colors.textPrimary;
    final bodyColor = solidHero
        ? colors.chatUserBubbleText.withValues(alpha: 0.78)
        : colors.textSecondary;
    final cardBorder = solidHero
        ? colors.chatUserBubbleText.withValues(alpha: 0.24)
        : colors.divider.withValues(alpha: 0.72);
    final glassAccent = Color.alphaBlend(accent.withAlpha(31), colors.surface);
    final glassTail = Color.alphaBlend(
      Theme.of(context).colorScheme.secondaryContainer.withAlpha(70),
      colors.surface,
    );

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onEdit,
        borderRadius: BorderRadius.circular(22),
        child: Container(
          key: const ValueKey('profile_hero_card'),
          margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: cardBorder),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: solidHero
                  ? [
                      accent,
                      accent.withValues(alpha: 0.82),
                      Theme.of(context).colorScheme.tertiary,
                    ]
                  : [
                      colors.surface,
                      glassAccent,
                      glassTail,
                    ],
              stops: solidHero ? null : const [0, 0.7, 1],
            ),
          ),
          child: Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  _EditableAvatar(
                    avatarPath: avatarPath,
                    accent: accent,
                    solidHero: solidHero,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (headline.isNotEmpty) ...[
                          Text(
                            headline,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: bodyColor,
                              fontSize: 11,
                              height: 1.27,
                              fontWeight: FontWeight.w500,
                              letterSpacing: 0,
                            ),
                          ),
                          const SizedBox(height: 2),
                        ],
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                displayName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: titleColor,
                                  fontSize: 18,
                                  height: 1.44,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                            Icon(
                              key: const ValueKey('profile_hero_chevron'),
                              Icons.chevron_right,
                              size: 20,
                              color: bodyColor,
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          subtitle,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: bodyColor,
                            fontSize: 13,
                            height: 1.31,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _InfoChip(
                              icon: Icons.verified,
                              label: primaryChip,
                              accent: accent,
                              solidHero: solidHero,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _InfoChip(
                                icon: Icons.tag,
                                label: secondaryChip,
                                accent: accent,
                                solidHero: solidHero,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 9),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      syncing ? syncingStatus : readyStatus,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: bodyColor,
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  _StatusPill(
                    label: syncing ? '同步中…' : '同步',
                    selected: syncing,
                    onTap: onSync,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EditableAvatar extends StatelessWidget {
  const _EditableAvatar({
    required this.avatarPath,
    required this.accent,
    required this.solidHero,
  });

  final String avatarPath;
  final Color accent;
  final bool solidHero;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      width: 72,
      height: 72,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            left: 0,
            top: 0,
            child: Container(
              key: const ValueKey('profile_avatar_frame'),
              width: 72,
              height: 72,
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.92)
                    : colors.surface,
                shape: BoxShape.circle,
              ),
              child: _ProfileAvatarPreview(avatarPath: avatarPath, size: 66),
            ),
          ),
          Positioned(
            right: -3,
            bottom: -3,
            child: Container(
              key: const ValueKey('profile_avatar_badge_shell'),
              width: 22,
              height: 22,
              padding: const EdgeInsets.all(2),
              decoration: BoxDecoration(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.92)
                    : colors.surface,
                shape: BoxShape.circle,
              ),
              child: Container(
                key: const ValueKey('profile_avatar_badge_accent'),
                decoration: BoxDecoration(
                  color: accent,
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.photo,
                  size: 13,
                  color: Colors.white,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfileAvatarPreview extends StatelessWidget {
  const _ProfileAvatarPreview({
    required this.avatarPath,
    required this.size,
  });

  final String avatarPath;
  final double size;

  @override
  Widget build(BuildContext context) {
    return AppAvatar(
      imageSource: avatarPath,
      fallback: AppAvatarFallback.user,
      size: size,
      borderRadius: BorderRadius.circular(size / 2),
      contentDescription: '头像',
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({
    required this.icon,
    required this.label,
    required this.accent,
    required this.solidHero,
  });

  final IconData icon;
  final String label;
  final Color accent;
  final bool solidHero;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 28),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: solidHero
            ? colors.chatUserBubbleText.withValues(alpha: 0.18)
            : colors.surface.withValues(alpha: 0.74),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: solidHero
              ? colors.chatUserBubbleText.withValues(alpha: 0.26)
              : colors.divider.withValues(alpha: 0.62),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            icon,
            size: 14,
            color: solidHero ? colors.chatUserBubbleText : accent,
          ),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.9)
                    : colors.textSecondary,
                fontSize: 11,
                height: 1.27,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: colors.divider),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.refresh_outlined,
                size: 14,
                color: colors.textTertiary,
              ),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(
                  color: selected ? colors.brand : colors.textSecondary,
                  fontSize: 11,
                  height: 1.27,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Color _profileAccentColor(BuildContext context, String? accent) {
  final colors = AppTheme.colors(context);
  switch (accent?.trim().toLowerCase()) {
    case 'emerald':
    case 'green':
    case 'success':
      return colors.success;
    case 'amber':
    case 'yellow':
    case 'warning':
      return colors.warning;
    case 'red':
    case 'danger':
      return colors.danger;
    case 'violet':
    case 'purple':
      return colors.brandGradientEnd;
    default:
      return colors.brand;
  }
}

class _WalletBalanceCard extends StatelessWidget {
  const _WalletBalanceCard({
    required this.wallet,
    required this.onRefresh,
  });

  final WalletBalanceData wallet;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final balanceText =
        wallet.balance == null ? '—' : _formatBalance(wallet.balance!);
    final currency = wallet.currency.trim().isEmpty ? 'CNY' : wallet.currency;
    final membership =
        wallet.membershipLevel.trim().isEmpty ? '未开通' : wallet.membershipLevel;
    final experience = wallet.experience?.toString() ?? '—';
    final byok = wallet.byokConfigured ? '已开通' : '未开通';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onRefresh,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          key: const ValueKey('profile_wallet_card'),
          margin: const EdgeInsets.symmetric(horizontal: 16),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(
              colors: [colors.brand, colors.brandGradientEnd],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '账户余额',
                      style: TextStyle(
                        color:
                            colors.chatUserBubbleText.withValues(alpha: 0.85),
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  Icon(
                    Icons.refresh_outlined,
                    size: 16,
                    color: Colors.white.withValues(alpha: 0.85),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    balanceText,
                    style: TextStyle(
                      color: colors.chatUserBubbleText,
                      fontSize: 20,
                      height: 1.4,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      currency,
                      style: TextStyle(
                        color:
                            colors.chatUserBubbleText.withValues(alpha: 0.85),
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _BalanceMetric(label: '会员等级', value: membership),
                  _BalanceMetric(label: '经验值', value: experience),
                  _BalanceMetric(label: 'BYOK', value: byok),
                ],
              ),
              if (!wallet.synced && wallet.message.trim().isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  wallet.message,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.chatUserBubbleText.withValues(alpha: 0.7),
                    fontSize: 11,
                    height: 1.27,
                    letterSpacing: 0,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _BalanceMetric extends StatelessWidget {
  const _BalanceMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          label,
          style: TextStyle(
            color: colors.chatUserBubbleText.withValues(alpha: 0.7),
            fontSize: 11,
            height: 1.27,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            color: colors.chatUserBubbleText,
            fontSize: 15,
            height: 1.4,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
      ],
    );
  }
}

String _formatBalance(double value) {
  final fixed = value.toStringAsFixed(2);
  final parts = fixed.split('.');
  final integer = parts.first;
  final buffer = StringBuffer();
  for (var i = 0; i < integer.length; i++) {
    final remaining = integer.length - i;
    buffer.write(integer[i]);
    if (remaining > 1 && remaining % 3 == 1) {
      buffer.write(',');
    }
  }
  return '${buffer.toString()}.${parts.last}';
}

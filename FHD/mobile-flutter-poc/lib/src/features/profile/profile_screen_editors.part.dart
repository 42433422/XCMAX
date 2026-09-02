part of 'profile_screen.dart';

// 资料编辑弹窗、注销账号弹窗及辅助函数。
String _profileAccountKindLabel(String accountKind, String fallback) {
  switch (accountKind.trim().toLowerCase()) {
    case 'admin':
    case 'admin_portal':
      return '账号';
    case 'enterprise':
      return '账号';
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
              TextButton(onPressed: _pickAvatar, child: const Text('更换头像')),
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

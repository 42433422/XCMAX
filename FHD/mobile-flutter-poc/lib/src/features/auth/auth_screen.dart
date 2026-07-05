import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/android_runtime_policy.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';
import '../scan/scan_qr_screen.dart';
import 'register_screen.dart';

enum AuthLoginMode { password, phone }

class AuthScreen extends StatefulWidget {
  const AuthScreen({
    super.key,
    this.repository,
    this.onDone,
    this.openExternalUrl,
  });

  final MobileRepository? repository;
  final VoidCallback? onDone;
  final ExternalUrlLauncher? openExternalUrl;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  late final MobileRepository _repository;
  late final ExternalUrlLauncher _openExternalUrl;
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _phoneController = TextEditingController();
  final _otpController = TextEditingController();
  var _mode = AuthLoginMode.password;
  var _passwordVisible = false;
  var _agreed = true;
  var _adminMode = false;
  var _rememberPass = false;
  var _autoLogin = false;
  var _loggingIn = false;
  var _sendingCode = false;
  var _codeCooldown = 0;
  String? _error;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _openExternalUrl = widget.openExternalUrl ?? launchExternalUrl;
    _loadCachedAuthState();
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _phoneController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final canLogin = _canLogin;
    final colors = AppTheme.colors(context);
    final isEnterprise = AndroidProductSkuConfig.isEnterprise(
      buildSku: MobileAndroidBuild.productSku,
    );
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 26, 24, 28),
          children: [
            const Center(child: _AuthLogo()),
            const SizedBox(height: 12),
            Text(
              isEnterprise ? 'XCAGI 手机控制端' : 'XCAGI 个人版',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 22,
                height: 1.27,
                fontWeight: FontWeight.w600,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              isEnterprise
                  ? '连接服务器后台、企业工作台和电脑执行端'
                  : '与官网 MODstore 同一账号，登录后可同步能力。',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.31,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _LoginTab(
                    label: '密码登录',
                    selected: _mode == AuthLoginMode.password,
                    onTap: () => setState(() => _mode = AuthLoginMode.password),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: _LoginTab(
                    label: '手机号登录',
                    selected: _mode == AuthLoginMode.phone,
                    onTap: () => setState(() => _mode = AuthLoginMode.phone),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            if (_mode == AuthLoginMode.password) ...[
              if (isEnterprise) ...[
                _AccountKindSegment(
                  adminMode: _adminMode,
                  onChanged: (value) => setState(() => _adminMode = value),
                ),
                const SizedBox(height: 14),
              ],
              _AuthTextField(
                controller: _usernameController,
                hintText: _adminMode
                    ? '管理员账号'
                    : isEnterprise
                        ? '账号或邮箱'
                        : '请输入用户名',
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 14),
              _AuthTextField(
                controller: _passwordController,
                hintText: '密码',
                obscureText: !_passwordVisible,
                onChanged: (_) => setState(() {}),
                suffix: IconButton(
                  onPressed: () =>
                      setState(() => _passwordVisible = !_passwordVisible),
                  constraints:
                      const BoxConstraints.tightFor(width: 40, height: 40),
                  padding: EdgeInsets.zero,
                  icon: Icon(
                    _passwordVisible ? Icons.visibility_off : Icons.visibility,
                    size: 22,
                  ),
                  tooltip: _passwordVisible ? '隐藏密码' : '显示密码',
                ),
              ),
            ] else ...[
              _AuthTextField(
                controller: _phoneController,
                hintText: '请输入手机号',
                keyboardType: TextInputType.phone,
                onChanged: (value) {
                  final digits = value.replaceAll(RegExp(r'\D'), '');
                  if (digits != value) {
                    _phoneController.text = digits.substring(
                      0,
                      digits.length > 11 ? 11 : digits.length,
                    );
                    _phoneController.selection = TextSelection.collapsed(
                      offset: _phoneController.text.length,
                    );
                  }
                  setState(() {});
                },
              ),
              const SizedBox(height: 8),
              _OtpCodeField(
                controller: _otpController,
                actionLabel: _codeButtonText,
                actionEnabled: _canSendCode,
                onAction: _sendCode,
                onChanged: (_) => setState(() {}),
              ),
            ],
            const SizedBox(height: 18),
            if (_error != null) ...[
              Text(
                _error!,
                style: TextStyle(
                  color: colors.danger,
                  fontSize: 13,
                  height: 1.31,
                  letterSpacing: 0,
                ),
              ),
              const SizedBox(height: 8),
            ],
            SizedBox(
              height: 48,
              child: FilledButton(
                onPressed: canLogin ? _login : null,
                style: FilledButton.styleFrom(
                  backgroundColor: colors.brand,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: colors.divider,
                  disabledForegroundColor: colors.textSecondary,
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(24),
                  ),
                  textStyle: const TextStyle(
                    fontSize: 16,
                    height: 1.38,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
                child: Text(_loginButtonText),
              ),
            ),
            const SizedBox(height: 12),
            _ScanButton(onTap: _openScan),
            const SizedBox(height: 10),
            _RegisterLink(onTap: _openRegister),
            if (_mode == AuthLoginMode.password) ...[
              const SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  _LoginCheckbox(
                    checked: _rememberPass,
                    label: '记住密码',
                    onTap: () => setState(() => _rememberPass = !_rememberPass),
                  ),
                  const SizedBox(width: 20),
                  _LoginCheckbox(
                    checked: _autoLogin,
                    label: '免登录',
                    onTap: () => setState(() => _autoLogin = !_autoLogin),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 18),
            _AgreementRow(
              agreed: _agreed,
              onToggle: () => setState(() => _agreed = !_agreed),
              openExternalUrl: _openExternalUrl,
            ),
          ],
        ),
      ),
    );
  }

  bool get _canSendCode {
    return _phoneController.text.trim().length == 11 &&
        _codeCooldown == 0 &&
        !_sendingCode;
  }

  String get _codeButtonText {
    if (_sendingCode) return '发送中…';
    if (_codeCooldown > 0) return '${_codeCooldown}s 后重发';
    return '获取验证码';
  }

  bool get _canLogin {
    if (!_agreed || _loggingIn) return false;
    if (_mode == AuthLoginMode.password) {
      return _usernameController.text.trim().isNotEmpty &&
          _passwordController.text.isNotEmpty;
    }
    return _phoneController.text.trim().length == 11 &&
        _otpController.text.trim().length >= 4;
  }

  String get _loginButtonText {
    if (_loggingIn) return '登录中…';
    if (_mode == AuthLoginMode.password && _adminMode) return '进入服务器后台';
    if (_mode == AuthLoginMode.password) return '进入企业工作台';
    return '登录';
  }

  Future<void> _login() async {
    setState(() {
      _loggingIn = true;
      _error = null;
    });
    try {
      if (_mode == AuthLoginMode.password) {
        await _repository.login(
          username: _usernameController.text,
          password: _passwordController.text,
          adminMode: _adminMode,
          rememberPass: _rememberPass,
          autoLogin: _autoLogin,
        );
      } else {
        await _repository.loginWithPhoneCode(
          phone: _phoneController.text,
          code: _otpController.text,
        );
      }
      if (!mounted) return;
      widget.onDone?.call();
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loggingIn = false);
    }
  }

  Future<void> _loadCachedAuthState() async {
    try {
      final session = await _repository.client.loadSession();
      if (!mounted) return;
      setState(() {
        _rememberPass = session.rememberPassword;
        _autoLogin = session.autoLogin;
        if (session.rememberPassword) {
          _usernameController.text = session.savedUsername;
          _passwordController.text = session.savedPassword;
        }
      });
    } catch (_) {
      // Android keeps the login form usable when local credential storage fails.
    }
  }

  Future<void> _sendCode() async {
    setState(() {
      _sendingCode = true;
      _error = null;
    });
    try {
      await _repository.sendPhoneCode(_phoneController.text);
      if (!mounted) return;
      setState(() => _codeCooldown = 60);
      _tickCooldown();
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _sendingCode = false);
    }
  }

  Future<void> _tickCooldown() async {
    while (mounted && _codeCooldown > 0) {
      await Future<void>.delayed(const Duration(seconds: 1));
      if (mounted) setState(() => _codeCooldown -= 1);
    }
  }

  void _openScan() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ScanQrScreen(repository: _repository)),
    );
  }

  void _openRegister() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => RegisterScreen(
          onLogin: () =>
              Navigator.of(context).popUntil((route) => route.isFirst),
        ),
      ),
    );
  }
}

const _termsUrl = 'https://xiu-ci.com/legal/terms';
const _privacyUrl = 'https://xiu-ci.com/legal/privacy';

class _AuthLogo extends StatelessWidget {
  const _AuthLogo();

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        width: 72,
        height: 72,
        child: Center(
          child: Image.asset(
            appLauncherForegroundAsset,
            width: 50,
            height: 50,
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }
}

class _LoginTab extends StatelessWidget {
  const _LoginTab({
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
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(4),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: TextStyle(
                color: selected ? colors.textPrimary : colors.textSecondary,
                fontSize: 16,
                height: 1.38,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 6),
            Container(
              height: 2.5,
              decoration: BoxDecoration(
                color: selected ? colors.brand : Colors.transparent,
                borderRadius: BorderRadius.circular(1.25),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AccountKindSegment extends StatelessWidget {
  const _AccountKindSegment({
    required this.adminMode,
    required this.onChanged,
  });

  final bool adminMode;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: colors.divider, width: 0.5),
      ),
      padding: const EdgeInsets.all(4),
      child: Row(
        children: [
          Expanded(
            child: _AccountKindSegmentItem(
              label: '服务器后台',
              selected: adminMode,
              onTap: () => onChanged(true),
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _AccountKindSegmentItem(
              label: '企业工作台',
              selected: !adminMode,
              onTap: () => onChanged(false),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccountKindSegmentItem extends StatelessWidget {
  const _AccountKindSegmentItem({
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
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? colors.brand : Colors.transparent,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? Colors.white : colors.textSecondary,
            fontSize: 14,
            height: 1.29,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
      ),
    );
  }
}

class _AuthTextField extends StatefulWidget {
  const _AuthTextField({
    required this.controller,
    required this.hintText,
    this.obscureText = false,
    this.keyboardType,
    this.suffix,
    this.onChanged,
  });

  final TextEditingController controller;
  final String hintText;
  final bool obscureText;
  final TextInputType? keyboardType;
  final Widget? suffix;
  final ValueChanged<String>? onChanged;

  @override
  State<_AuthTextField> createState() => _AuthTextFieldState();
}

class _AuthTextFieldState extends State<_AuthTextField> {
  final _focusNode = FocusNode();
  var _focused = false;

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_handleFocusChanged);
  }

  @override
  void dispose() {
    _focusNode
      ..removeListener(_handleFocusChanged)
      ..dispose();
    super.dispose();
  }

  void _handleFocusChanged() {
    if (_focused == _focusNode.hasFocus) return;
    setState(() => _focused = _focusNode.hasFocus);
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 46,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: _focused ? colors.brand : colors.divider,
          width: 1,
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: widget.controller,
              focusNode: _focusNode,
              obscureText: widget.obscureText,
              keyboardType: widget.keyboardType,
              onChanged: widget.onChanged,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 15,
                height: 1.4,
                letterSpacing: 0,
              ),
              decoration: InputDecoration(
                isDense: true,
                hintText: widget.hintText,
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                hintStyle: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 15,
                  height: 1.4,
                  letterSpacing: 0,
                ),
              ),
            ),
          ),
          if (widget.suffix != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: widget.suffix!,
            ),
        ],
      ),
    );
  }
}

class _OtpCodeField extends StatefulWidget {
  const _OtpCodeField({
    required this.controller,
    required this.actionLabel,
    required this.actionEnabled,
    required this.onAction,
    required this.onChanged,
  });

  final TextEditingController controller;
  final String actionLabel;
  final bool actionEnabled;
  final VoidCallback onAction;
  final ValueChanged<String> onChanged;

  @override
  State<_OtpCodeField> createState() => _OtpCodeFieldState();
}

class _OtpCodeFieldState extends State<_OtpCodeField> {
  final _focusNode = FocusNode();

  @override
  void dispose() {
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final digits = widget.controller.text.replaceAll(RegExp(r'\D'), '');
    final cleanDigits = digits.length > 6 ? digits.substring(0, 6) : digits;
    if (cleanDigits != widget.controller.text) {
      widget.controller.value = TextEditingValue(
        text: cleanDigits,
        selection: TextSelection.collapsed(offset: cleanDigits.length),
      );
    }
    final focusedIndex = cleanDigits.length.clamp(0, 5);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '验证码',
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 16,
                  height: 1.38,
                  letterSpacing: 0,
                ),
              ),
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: widget.actionEnabled ? widget.onAction : null,
                child: Text(
                  widget.actionLabel,
                  style: TextStyle(
                    color: widget.actionEnabled
                        ? colors.brand
                        : colors.textSecondary,
                    fontSize: 14,
                    height: 1.36,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ],
          ),
        ),
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => _focusNode.requestFocus(),
          child: Stack(
            children: [
              Row(
                children: [
                  for (var index = 0; index < 6; index++) ...[
                    Expanded(
                      child: _OtpCell(
                        char: index < cleanDigits.length
                            ? cleanDigits[index]
                            : '',
                        focused: focusedIndex == index,
                      ),
                    ),
                    if (index != 5) const SizedBox(width: 8),
                  ],
                ],
              ),
              Positioned(
                left: 0,
                top: 0,
                child: Opacity(
                  opacity: 0,
                  child: SizedBox(
                    width: 1,
                    height: 1,
                    child: TextField(
                      controller: widget.controller,
                      focusNode: _focusNode,
                      keyboardType: TextInputType.number,
                      maxLength: 6,
                      onChanged: (value) {
                        final normalized = value.replaceAll(RegExp(r'\D'), '');
                        final next = normalized.length > 6
                            ? normalized.substring(0, 6)
                            : normalized;
                        if (next != value) {
                          widget.controller.value = TextEditingValue(
                            text: next,
                            selection:
                                TextSelection.collapsed(offset: next.length),
                          );
                        }
                        setState(() {});
                        widget.onChanged(next);
                      },
                      decoration: const InputDecoration(
                        border: InputBorder.none,
                        counterText: '',
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _OtpCell extends StatelessWidget {
  const _OtpCell({
    required this.char,
    required this.focused,
  });

  final String char;
  final bool focused;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 48,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: focused ? colors.brand : colors.divider,
          width: focused ? 1.5 : 1,
        ),
      ),
      child: Text(
        char,
        textAlign: TextAlign.center,
        style: TextStyle(
          color: colors.textPrimary,
          fontSize: 18,
          height: 1.44,
          fontWeight: FontWeight.w500,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _ScanButton extends StatelessWidget {
  const _ScanButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(22),
      child: Container(
        height: 44,
        decoration: BoxDecoration(
          color: colors.brand.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(
            color: colors.brand.withValues(alpha: 0.35),
            width: 0.5,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.qr_code_scanner,
              size: 18,
              color: colors.brand,
            ),
            const SizedBox(width: 8),
            Text(
              '扫码绑定/登录',
              style: TextStyle(
                color: colors.brand,
                fontSize: 15,
                height: 1.4,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RegisterLink extends StatelessWidget {
  const _RegisterLink({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: InkWell(
        key: const ValueKey('android-register-link'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(4),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Text(
            '账号注册',
            style: TextStyle(
              color: colors.brand,
              fontSize: 13,
              height: 1.31,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
        ),
      ),
    );
  }
}

class _LoginCheckbox extends StatelessWidget {
  const _LoginCheckbox({
    required this.checked,
    required this.label,
    required this.onTap,
  });

  final bool checked;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _CheckBoxMark(
            checked: checked,
            size: 18,
            radius: 3,
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 13,
              height: 1.31,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }
}

class _AgreementRow extends StatelessWidget {
  const _AgreementRow({
    required this.agreed,
    required this.onToggle,
    required this.openExternalUrl,
  });

  final bool agreed;
  final VoidCallback onToggle;
  final ExternalUrlLauncher openExternalUrl;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Row(
        children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onToggle,
            child: _CheckBoxMark(
              checked: agreed,
              size: 20,
              radius: 4,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '已阅读并同意 ',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          _AgreementLink(
            label: '服务协议',
            url: _termsUrl,
            openExternalUrl: openExternalUrl,
          ),
          Text(
            ' 和 ',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          _AgreementLink(
            label: '隐私政策',
            url: _privacyUrl,
            openExternalUrl: openExternalUrl,
          ),
        ],
      ),
    );
  }
}

class _CheckBoxMark extends StatelessWidget {
  const _CheckBoxMark({
    required this.checked,
    required this.size,
    required this.radius,
  });

  final bool checked;
  final double size;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: checked ? colors.brand : colors.divider,
        borderRadius: BorderRadius.circular(radius),
        border: checked ? null : Border.all(color: colors.divider, width: 0.5),
      ),
      alignment: Alignment.center,
      child: checked
          ? Icon(
              Icons.check,
              size: size == 20 ? 13 : 12,
              color: Colors.white,
            )
          : null,
    );
  }
}

class _AgreementLink extends StatelessWidget {
  const _AgreementLink({
    required this.label,
    required this.url,
    required this.openExternalUrl,
  });

  final String label;
  final String url;
  final ExternalUrlLauncher openExternalUrl;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () async {
        final opened = await openExternalUrl(Uri.parse(url));
        if (!context.mounted || opened) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('无法打开$label')),
        );
      },
      child: Text(
        label,
        style: TextStyle(
          color: colors.brand,
          fontSize: 11,
          height: 1.27,
          fontWeight: FontWeight.w500,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

// part 文件：登录页主状态（_AuthScreenState）。

part of 'auth_screen.dart';

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
    final isEnterprise = MobileProductSkuConfig.isEnterprise(
      buildSku: MobileBuildConfig.productSku,
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
                  constraints: const BoxConstraints.tightFor(
                    width: 40,
                    height: 40,
                  ),
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
      // Keep the login form usable when local credential storage fails.
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

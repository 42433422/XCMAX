// part 文件：登录页主状态（_AuthScreenState）。

part of 'auth_screen.dart';

class _AuthScreenState extends State<AuthScreen> {
  late final MobileRepository _repository;
  late final ExternalUrlLauncher _openExternalUrl;
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  var _passwordVisible = false;
  var _agreed = true;
  var _adminMode = false;
  var _rememberPass = false;
  var _autoLogin = false;
  var _loggingIn = false;
  var _modeTapCount = 0;
  var _lastModeTapAt = DateTime.fromMillisecondsSinceEpoch(0);
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
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(24, 26, 24, 12),
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
                  const SizedBox(height: 16),
                  Text(
                    '密码登录',
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 14),
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
                        _passwordVisible
                            ? Icons.visibility_off
                            : Icons.visibility,
                        size: 22,
                      ),
                      tooltip: _passwordVisible ? '隐藏密码' : '显示密码',
                    ),
                  ),
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
                  const SizedBox(height: 10),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      _LoginCheckbox(
                        checked: _rememberPass,
                        label: '记住密码',
                        onTap: () =>
                            setState(() => _rememberPass = !_rememberPass),
                      ),
                      const SizedBox(width: 20),
                      _LoginCheckbox(
                        checked: _autoLogin,
                        label: '免登录',
                        onTap: () => setState(() => _autoLogin = !_autoLogin),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  _AgreementRow(
                    agreed: _agreed,
                    onToggle: () => setState(() => _agreed = !_agreed),
                    openExternalUrl: _openExternalUrl,
                  ),
                ],
              ),
            ),
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _handleVersionTap,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
                alignment: Alignment.center,
                child: Text(
                  MobileBuildConfig.profileVersionText,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: colors.textTertiary,
                    fontSize: 11,
                    height: 1.27,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // 连点系统版本号 5 下在企业工作台与服务器后台之间切换。
  void _handleVersionTap() {
    final now = DateTime.now();
    if (now.difference(_lastModeTapAt) > const Duration(seconds: 2)) {
      _modeTapCount = 0;
    }
    _lastModeTapAt = now;
    _modeTapCount += 1;
    if (_modeTapCount < 5) return;
    _modeTapCount = 0;
    setState(() => _adminMode = !_adminMode);
  }

  bool get _canLogin =>
      _agreed &&
      !_loggingIn &&
      _usernameController.text.trim().isNotEmpty &&
      _passwordController.text.isNotEmpty;

  String get _loginButtonText {
    if (_loggingIn) return '登录中…';
    return _adminMode ? '进入服务器后台' : '进入企业工作台';
  }

  Future<void> _login() async {
    final requestedRemember = _rememberPass;
    setState(() {
      _loggingIn = true;
      _error = null;
    });
    try {
      await _repository.login(
        username: _usernameController.text,
        password: _passwordController.text,
        adminMode: _adminMode,
        rememberPass: _rememberPass,
        autoLogin: _autoLogin,
      );
      if (!mounted) return;
      if (requestedRemember) {
        final session = await _repository.client.loadSession();
        if (!mounted) return;
        if (!session.rememberPassword) {
          setState(() {
            _rememberPass = false;
            _autoLogin = false;
          });
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('已登录，但当前设备无法安全保存密码，下次请手动输入。'),
          ));
        }
      }
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

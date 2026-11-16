import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_session_store.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

typedef MobileWebUrlOverride = bool Function(String nextUrl);

class DesktopToolWebViewScreen extends StatefulWidget {
  const DesktopToolWebViewScreen({
    super.key,
    required this.title,
    required this.path,
    this.config = const MobileApiConfig(),
    this.api,
    this.onUrlOverride,
    this.externalUrlLauncher = launchExternalUrl,
  });

  final String title;
  final String path;
  final MobileApiConfig config;
  final MobileApiClient? api;
  final MobileWebUrlOverride? onUrlOverride;
  final ExternalUrlLauncher externalUrlLauncher;

  @override
  State<DesktopToolWebViewScreen> createState() =>
      _DesktopToolWebViewScreenState();
}

class _DesktopToolWebViewScreenState extends State<DesktopToolWebViewScreen> {
  WebViewController? _controller;
  late final MobileApiClient _api;
  String? _error;
  var _loading = true;
  var _loadId = 0;
  int? _pageGeneration;
  String? _pageConnection;
  StreamSubscription<MobileSessionData>? _sessionSubscription;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? MobileApiClient(config: widget.config);
    _sessionSubscription = _api.sessionChanges.listen((session) {
      if (mounted &&
          _pageGeneration != null &&
          (_pageGeneration != _api.authGeneration ||
              (_pageConnection != null &&
                  _pageConnection != _connectionKey(session)))) {
        ++_loadId;
        setState(() {
          _controller = null;
          _loading = false;
          _error = _pageGeneration != _api.authGeneration
              ? '账号已切换，请重新打开页面'
              : '连接已切换，请重新打开页面';
        });
      }
    });
    unawaited(_load());
  }

  @override
  void dispose() {
    _sessionSubscription?.cancel();
    if (widget.api == null) _api.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final loadId = ++_loadId;
    setState(() {
      _error = null;
      _loading = true;
      _controller = null;
      _pageConnection = null;
    });
    try {
      final generation = _api.authGeneration;
      _pageGeneration = generation;
      final initialSession = await _api.loadSession();
      _pageConnection = _connectionKey(initialSession);
      final base = await _api.resolveSessionBaseUrl();
      final config = MobileApiConfig(
          baseUrl: base, modstoreBaseUrl: widget.config.modstoreBaseUrl);
      final uri = _resolveDesktopUri(widget.path, config: config);
      final session = await _api.loadSession();
      if (!mounted || loadId != _loadId) return;
      if (generation != _api.authGeneration) throw StateError('账号已切换，请重新打开');
      if (_pageConnection != _connectionKey(session)) {
        throw StateError('连接已切换，请重新打开');
      }
      final fhd = _isFhdTarget(uri, config);
      final publicRegistration = fhd &&
          uri.path == _normalizedBaseUri(base).resolve('login/register').path;
      final token = fhd
          ? _firstNonBlank([session.accessToken, session.sessionId])
          : session.marketAccessToken.trim();
      if (!publicRegistration && token.isEmpty) throw StateError('请先登录再打开业务页面');
      bool allowed(Uri next) => publicRegistration
          ? _sameOrigin(next, uri) && next.path == uri.path
          : fhd
              ? _isFhdTarget(next, config)
              : _isMarketTarget(next, config) && !_isFhdTarget(next, config);
      if (!allowed(uri)) throw StateError('该链接不属于当前连接，请返回后重新选择');
      final controller = WebViewController();
      var bootstrapping = true;
      await controller.setJavaScriptMode(JavaScriptMode.unrestricted);
      await controller.setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (request) {
          final next = Uri.tryParse(request.url);
          if (loadId != _loadId || generation != _api.authGeneration) {
            return NavigationDecision.prevent;
          }
          if (next != null &&
              _sameOrigin(next, uri) &&
              (widget.onUrlOverride?.call(request.url) ?? false)) {
            return NavigationDecision.prevent;
          }
          if (next != null &&
              allowed(next) &&
              generation == _api.authGeneration) {
            return NavigationDecision.navigate;
          }
          if (next != null &&
              (next.scheme == 'https' || next.scheme == 'http')) {
            unawaited(widget.externalUrlLauncher(next));
          }
          return NavigationDecision.prevent;
        },
        onPageFinished: (url) async {
          if (!mounted ||
              loadId != _loadId ||
              generation != _api.authGeneration) {
            return;
          }
          if (bootstrapping) {
            try {
              final ready = await _injectMobileWebTokens(
                  controller, uri, config, _api, generation,
                  publicRegistration: publicRegistration);
              if (!mounted ||
                  loadId != _loadId ||
                  generation != _api.authGeneration) {
                return;
              }
              if (!ready) throw StateError('登录同步失败');
              bootstrapping = false;
              await controller.loadRequest(uri,
                  headers: publicRegistration
                      ? const {}
                      : _mobileWebHeaders(config, uri, session: session));
            } catch (_) {
              if (mounted && loadId == _loadId) {
                setState(() {
                  _loading = false;
                  _error = '登录状态同步失败，请重试';
                });
              }
            }
            return;
          }
          final current = Uri.tryParse(await controller.currentUrl() ?? '');
          final finished = Uri.tryParse(url);
          if (current == null || current != finished || !allowed(current)) {
            return;
          }
          try {
            if (!publicRegistration) {
              await _injectMobileWebTokens(
                  controller, current, config, _api, generation);
            }
          } catch (_) {
            if (mounted && loadId == _loadId) {
              setState(() => _error = '登录状态同步失败，请重试');
            }
          }
          if (mounted && loadId == _loadId) setState(() => _loading = false);
        },
        onWebResourceError: (error) {
          if (error.isForMainFrame == false || !mounted || loadId != _loadId) {
            return;
          }
          setState(() {
            _loading = false;
            _error = '页面加载失败，请检查当前连接后重试';
          });
        },
      ));
      await controller.setUserAgent(_mobileUserAgent);
      if (_isFhdTarget(uri, config)) {
        await WebViewCookieManager().setCookie(WebViewCookie(
          name: 'session_id',
          value: publicRegistration ? '' : token,
          domain: uri.host,
          path: _normalizedBaseUri(base).path,
        ));
      }
      if (!mounted || loadId != _loadId || generation != _api.authGeneration) {
        return;
      }
      setState(() => _controller = controller);
      // Prepare only this origin's auth state before any application script runs.
      await controller.loadHtmlString(
          '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>',
          baseUrl: uri.toString());
    } catch (_) {
      if (mounted && loadId == _loadId) {
        setState(() {
          _loading = false;
          _error = '无法打开页面，请检查登录与当前连接后重试';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
          bottom: false,
          child: Column(children: [
            WeTopBar(
                title: widget.title,
                showBack: true,
                onBack: () => Navigator.of(context).maybePop(),
                actions: [
                  IconButton(
                      onPressed: _load,
                      icon: const Icon(Icons.refresh, size: 22),
                      tooltip: '刷新')
                ]),
            if (_loading) const LinearProgressIndicator(),
            Expanded(
                child: _error != null
                    ? Center(
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(_error!, textAlign: TextAlign.center),
                        TextButton(onPressed: _load, child: const Text('重试')),
                      ]))
                    : _controller == null
                        ? const SizedBox.shrink()
                        : WebViewWidget(controller: _controller!)),
          ])),
    );
  }
}

class ModWebViewScreen extends StatelessWidget {
  const ModWebViewScreen(
      {super.key,
      required this.modId,
      this.title,
      this.config = const MobileApiConfig(),
      this.api});
  final String modId;
  final String? title;
  final MobileApiConfig config;
  final MobileApiClient? api;

  @override
  Widget build(BuildContext context) => DesktopToolWebViewScreen(
      title: title ?? 'Mod',
      path: '/mod/${Uri.encodeComponent(modId.trim())}/',
      config: config,
      api: api);
}

Uri _resolveDesktopUri(
  String path, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  final trimmed = path.trim();
  final parsed = Uri.tryParse(trimmed);
  if (parsed != null && parsed.hasScheme) return _withMobileShell(parsed);

  final base = _normalizedBaseUri(config.baseUrl);
  if (trimmed.isEmpty) return _withMobileShell(base);
  final normalized = trimmed.startsWith('/') ? trimmed : '/$trimmed';
  return _withMobileShell(base.resolve(normalized.substring(1)));
}

Uri _resolveModUri(
  String modId, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  final clean = Uri.encodeComponent(modId.trim());
  final fhdBase = _normalizedBaseUri(config.baseUrl);
  if (clean.isEmpty) return _withMobileShell(fhdBase);
  return _withMobileShell(fhdBase.resolve('mod/$clean/'));
}

Uri _normalizedBaseUri(String rawBase) {
  final value = rawBase.trim();
  final base = Uri.parse(value.endsWith('/') ? value : '$value/');
  return base;
}

Uri _withMobileShell(Uri uri) {
  final params = Map<String, String>.of(uri.queryParameters);
  params.putIfAbsent('shell', () => '1');
  return uri.replace(queryParameters: params);
}

Map<String, String> _mobileWebHeaders(
  MobileApiConfig config,
  Uri uri, {
  MobileSessionData session = MobileSessionData.empty,
}) {
  final headers = <String, String>{'X-XCAGI-Client': 'android'};
  final bearer = _firstNonBlank([config.accessToken, session.accessToken]);
  if (bearer.isNotEmpty && _isFhdTarget(uri, config)) {
    headers['Authorization'] = 'Bearer $bearer';
  }
  return headers;
}

Future<bool> _injectMobileWebTokens(
  WebViewController controller,
  Uri uri,
  MobileApiConfig config,
  MobileApiClient api,
  int generation, {
  bool publicRegistration = false,
}) async {
  final session = await api.loadSession();
  if (generation != api.authGeneration ||
      await api.resolveSessionBaseUrl() != config.baseUrl ||
      generation != api.authGeneration) {
    return false;
  }
  final injectMarket = !_isFhdTarget(uri, config) &&
      _isMarketTarget(uri, config) &&
      _firstNonBlank([
        config.marketAccessToken,
        session.marketAccessToken,
      ]).isNotEmpty;
  final injectFhd = !publicRegistration &&
      _isFhdTarget(uri, config) &&
      _firstNonBlank([
        config.accessToken,
        config.sessionId,
        session.accessToken,
        session.sessionId,
      ]).isNotEmpty;
  if (!publicRegistration && !injectMarket && !injectFhd) return false;
  final result = await controller.runJavaScriptReturningResult(
    _buildTokenInjectScript(
      origin: uri.origin,
      pathPrefix: _isFhdTarget(uri, config)
          ? _normalizedBaseUri(config.baseUrl).path
          : '/',
      accessToken: injectMarket
          ? _firstNonBlank([
              config.marketAccessToken,
              session.marketAccessToken,
            ])
          : '',
      refreshToken: injectMarket
          ? _firstNonBlank([
              config.marketRefreshToken,
              session.marketRefreshToken,
            ])
          : '',
      prepareFhd: _isFhdTarget(uri, config),
      fhdRefreshToken: injectFhd ? session.refreshToken : '',
      fhdAccessToken: injectFhd
          ? _firstNonBlank([
              config.accessToken,
              config.sessionId,
              session.accessToken,
              session.sessionId,
            ])
          : '',
    ),
  );
  return result == true || result == 'true';
}

String _buildTokenInjectScript({
  required String accessToken,
  required String refreshToken,
  required String fhdAccessToken,
  String? origin,
  String pathPrefix = '/',
  bool prepareFhd = false,
  String fhdRefreshToken = '',
}) {
  String esc(String value) {
    return value
        .replaceAll(r'\', r'\\')
        .replaceAll("'", r"\'")
        .replaceAll('\n', r'\n')
        .replaceAll('\r', r'\r')
        .replaceAll('\u2028', r'\u2028')
        .replaceAll('\u2029', r'\u2029');
  }

  final refreshLine = refreshToken.trim().isEmpty
      ? (accessToken.isEmpty
          ? ''
          : "localStorage.removeItem('modstore_refresh_token');")
      : "localStorage.setItem('modstore_refresh_token','${esc(refreshToken)}');";
  final fhdLine = fhdAccessToken.trim().isEmpty && !prepareFhd
      ? ''
      : "document.cookie = 'session_id=${esc(fhdAccessToken)}; path=${esc(pathPrefix)}; SameSite=Lax';";
  return """
    (function() {
      try {
        ${origin == null ? '' : "if (location.origin !== '${esc(origin)}' || !location.pathname.startsWith('${esc(pathPrefix)}')) return false;"}
        ${accessToken.isEmpty ? '' : "localStorage.setItem('modstore_token','${esc(accessToken)}');"}
        $refreshLine
        $fhdLine
        ${!prepareFhd ? '' : fhdRefreshToken.isEmpty ? "localStorage.removeItem('xcagi_stability_refresh');" : "localStorage.setItem('xcagi_stability_refresh','${esc(fhdRefreshToken)}');"}
        window.__XCAGI_CLIENT__ = 'android';
        document.documentElement.classList.add('xcagi-client-android');
        window.dispatchEvent(new Event('xcagi-client-ready'));
        return true;
      } catch (e) { return false; }
    })();
  """;
}

String _connectionKey(MobileSessionData session) =>
    '${session.serverMode}|${session.fhdHost}|${session.localBaseUrl}';

bool _sameOrigin(Uri a, Uri b) =>
    (a.scheme == 'http' || a.scheme == 'https') &&
    a.userInfo.isEmpty &&
    a.scheme == b.scheme &&
    a.host == b.host &&
    a.port == b.port;

bool _isFhdTarget(Uri uri, MobileApiConfig config) {
  final base = _normalizedBaseUri(config.baseUrl);
  return _sameOrigin(uri, base) &&
      (uri.path == base.path.replaceFirst(RegExp(r'/$'), '') ||
          uri.path.startsWith(base.path));
}

bool _isMarketTarget(Uri uri, MobileApiConfig config) =>
    _sameOrigin(uri, Uri.parse(config.modstoreBaseUrl));

bool _shouldInjectMarketTokens(Uri uri) =>
    _isMarketTarget(uri, const MobileApiConfig()) &&
    !_isFhdTarget(uri, const MobileApiConfig());

const _mobileWebViewAllowedHosts = {'xiu-ci.com', 'www.xiu-ci.com'};

bool _isMobileWebViewUrlAllowed(String rawUrl, {String? extraLanHost}) {
  final uri = Uri.tryParse(rawUrl);
  if (uri == null ||
      uri.userInfo.isNotEmpty ||
      (uri.scheme != 'http' && uri.scheme != 'https')) {
    return false;
  }
  if (uri.scheme == 'https' && _mobileWebViewAllowedHosts.contains(uri.host)) {
    return true;
  }
  if (extraLanHost == null) return false;
  final base = Uri.tryParse(
      extraLanHost.contains('://') ? extraLanHost : 'http://$extraLanHost');
  return base != null && _sameOrigin(uri, base);
}

bool _shouldInjectFhdSession(Uri uri) =>
    _isFhdTarget(uri, const MobileApiConfig());

bool isMobileRegisterCompleteUrl(String rawUrl) {
  final uri = Uri.tryParse(rawUrl);
  if (uri == null) return false;
  return uri.path == '/app/mobile-register-complete';
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) return trimmed;
  }
  return '';
}

const _mobileUserAgent =
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36';

@visibleForTesting
Uri resolveMobileDesktopWebUriForTest(
  String path, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  return _resolveDesktopUri(path, config: config);
}

@visibleForTesting
Uri resolveMobileModWebUriForTest(
  String modId, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  return _resolveModUri(modId, config: config);
}

@visibleForTesting
String buildMobileTokenInjectScriptForTest({
  required String accessToken,
  required String refreshToken,
  required String fhdAccessToken,
}) {
  return _buildTokenInjectScript(
    accessToken: accessToken,
    refreshToken: refreshToken,
    fhdAccessToken: fhdAccessToken,
  );
}

@visibleForTesting
Set<String> mobileWebViewAllowedHostsForTest() {
  return Set.unmodifiable(_mobileWebViewAllowedHosts);
}

@visibleForTesting
bool isMobileWebViewUrlAllowedForTest(String rawUrl, {String? extraLanHost}) {
  return _isMobileWebViewUrlAllowed(rawUrl, extraLanHost: extraLanHost);
}

@visibleForTesting
bool shouldInjectMarketTokensForTest(String rawUrl) {
  final uri = Uri.tryParse(rawUrl);
  return uri != null && _shouldInjectMarketTokens(uri);
}

@visibleForTesting
bool shouldInjectFhdSessionForTest(String rawUrl) {
  final uri = Uri.tryParse(rawUrl);
  return uri != null && _shouldInjectFhdSession(uri);
}

@visibleForTesting
bool isMobileRegisterCompleteUrlForTest(String rawUrl) {
  return isMobileRegisterCompleteUrl(rawUrl);
}

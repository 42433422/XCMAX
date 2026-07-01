import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_session_store.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

typedef AndroidWebUrlOverride = bool Function(String nextUrl);

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
  final AndroidWebUrlOverride? onUrlOverride;
  final ExternalUrlLauncher externalUrlLauncher;

  @override
  State<DesktopToolWebViewScreen> createState() =>
      _DesktopToolWebViewScreenState();
}

class _DesktopToolWebViewScreenState extends State<DesktopToolWebViewScreen> {
  late final WebViewController _controller;
  late final MobileApiClient _api;
  var _loadingProgress = 0;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? MobileApiClient(config: widget.config);
    final uri = _resolveDesktopUri(widget.path, config: widget.config);
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (request) {
            final handled = widget.onUrlOverride?.call(request.url) ?? false;
            if (handled) return NavigationDecision.prevent;
            if (_isAndroidWebViewUrlAllowed(request.url)) {
              return NavigationDecision.navigate;
            }
            final uri = Uri.tryParse(request.url);
            if (uri != null) {
              unawaited(widget.externalUrlLauncher(uri));
            }
            return NavigationDecision.prevent;
          },
          onProgress: (progress) {
            if (mounted) setState(() => _loadingProgress = progress);
          },
          onPageFinished: (_) =>
              _injectAndroidWebTokens(_controller, uri, widget.config, _api),
        ),
      )
      ..setUserAgent(_androidUserAgent);
    _loadRequest(uri);
  }

  Future<void> _loadRequest(Uri uri) async {
    final session = await _api.loadSession();
    await _controller.loadRequest(
      uri,
      headers: _androidWebHeaders(widget.config, uri, session: session),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: widget.title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: () => _controller.reload(),
                  icon: const Icon(Icons.refresh, size: 22),
                  tooltip: '刷新',
                  color: colors.textPrimary,
                ),
              ],
            ),
            _WebLoadingProgress(progress: _loadingProgress),
            Expanded(child: WebViewWidget(controller: _controller)),
          ],
        ),
      ),
    );
  }
}

class ModWebViewScreen extends StatefulWidget {
  const ModWebViewScreen({
    super.key,
    required this.modId,
    this.title,
    this.config = const MobileApiConfig(),
    this.api,
  });

  final String modId;
  final String? title;
  final MobileApiConfig config;
  final MobileApiClient? api;

  @override
  State<ModWebViewScreen> createState() => _ModWebViewScreenState();
}

class _ModWebViewScreenState extends State<ModWebViewScreen> {
  late final WebViewController _controller;
  late final MobileApiClient _api;
  late final Uri _uri;
  var _loadingProgress = 0;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? MobileApiClient(config: widget.config);
    _uri = _resolveModUri(widget.modId, config: widget.config);
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (progress) {
            if (mounted) setState(() => _loadingProgress = progress);
          },
          onPageFinished: (_) =>
              _injectAndroidWebTokens(_controller, _uri, widget.config, _api),
        ),
      )
      ..setUserAgent(_androidUserAgent);
    _loadRequest();
  }

  Future<void> _loadRequest() async {
    final session = await _api.loadSession();
    await _controller.loadRequest(
      _uri,
      headers: _androidWebHeaders(widget.config, _uri, session: session),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: widget.title ?? 'Mod',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: () => _controller.reload(),
                  icon: const Icon(Icons.refresh, size: 22),
                  tooltip: '刷新',
                  color: colors.textPrimary,
                ),
              ],
            ),
            _WebLoadingProgress(progress: _loadingProgress),
            Expanded(child: WebViewWidget(controller: _controller)),
          ],
        ),
      ),
    );
  }
}

class _WebLoadingProgress extends StatelessWidget {
  const _WebLoadingProgress({required this.progress});

  final int progress;

  @override
  Widget build(BuildContext context) {
    if (progress >= 100) return const SizedBox.shrink();
    final colors = AppTheme.colors(context);
    return LinearProgressIndicator(
      minHeight: 2,
      value: progress / 100,
      color: colors.brand,
      backgroundColor: colors.surfaceHigh,
    );
  }
}

Uri _resolveDesktopUri(
  String path, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  final trimmed = path.trim();
  final parsed = Uri.tryParse(trimmed);
  if (parsed != null && parsed.hasScheme) return _withAndroidShell(parsed);

  final base = _normalizedBaseUri(config.baseUrl);
  if (trimmed.isEmpty) return _withAndroidShell(base);
  final normalized = trimmed.startsWith('/') ? trimmed : '/$trimmed';
  return _withAndroidShell(base.resolve(normalized.substring(1)));
}

Uri _resolveModUri(
  String modId, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  final clean = Uri.encodeComponent(modId.trim());
  final fhdBase = _normalizedBaseUri(config.baseUrl);
  if (clean.isEmpty) return _withAndroidShell(fhdBase);
  return _withAndroidShell(fhdBase.resolve('mod/$clean/'));
}

Uri _normalizedBaseUri(String rawBase) {
  final value = rawBase.trim();
  final base = Uri.parse(value.endsWith('/') ? value : '$value/');
  return base;
}

Uri _withAndroidShell(Uri uri) {
  final params = Map<String, String>.of(uri.queryParameters);
  params.putIfAbsent('shell', () => '1');
  return uri.replace(queryParameters: params);
}

Map<String, String> _androidWebHeaders(
  MobileApiConfig config,
  Uri uri, {
  MobileSessionData session = MobileSessionData.empty,
}) {
  final headers = <String, String>{'X-XCAGI-Client': 'android'};
  final bearer = _firstNonBlank([config.accessToken, session.accessToken]);
  if (bearer.isNotEmpty && !_shouldInjectMarketTokens(uri)) {
    headers['Authorization'] = 'Bearer $bearer';
  }
  return headers;
}

Future<void> _injectAndroidWebTokens(
  WebViewController controller,
  Uri uri,
  MobileApiConfig config,
  MobileApiClient api,
) async {
  final session = await api.loadSession();
  final injectMarket = _shouldInjectMarketTokens(uri) &&
      _firstNonBlank([config.marketAccessToken, session.marketAccessToken])
          .isNotEmpty;
  final injectFhd = _shouldInjectFhdSession(uri) &&
      _firstNonBlank([
        config.accessToken,
        config.sessionId,
        session.accessToken,
        session.sessionId,
      ]).isNotEmpty;
  if (!injectMarket && !injectFhd) return;
  await controller.runJavaScript(
    _buildTokenInjectScript(
      accessToken: injectMarket
          ? _firstNonBlank(
              [config.marketAccessToken, session.marketAccessToken])
          : '',
      refreshToken: injectMarket
          ? _firstNonBlank(
              [config.marketRefreshToken, session.marketRefreshToken],
            )
          : '',
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
}

String _buildTokenInjectScript({
  required String accessToken,
  required String refreshToken,
  required String fhdAccessToken,
}) {
  String esc(String value) {
    return value.replaceAll(r'\', r'\\').replaceAll("'", r"\'");
  }

  final refreshLine = refreshToken.trim().isEmpty
      ? ''
      : "localStorage.setItem('modstore_refresh_token','${esc(refreshToken)}');";
  final fhdLine = fhdAccessToken.trim().isEmpty
      ? ''
      : "document.cookie = 'session_id=${esc(fhdAccessToken)}; path=/; SameSite=Lax';";
  return """
    (function() {
      try {
        localStorage.setItem('modstore_token','${esc(accessToken)}');
        $refreshLine
        $fhdLine
        window.__XCAGI_CLIENT__ = 'android';
        document.documentElement.classList.add('xcagi-client-android');
        window.dispatchEvent(new Event('xcagi-client-ready'));
      } catch (e) {}
    })();
  """;
}

bool _shouldInjectMarketTokens(Uri uri) {
  return uri.toString().toLowerCase().contains('xiu-ci.com');
}

const _androidWebViewAllowedHosts = {
  'xiu-ci.com',
  'www.xiu-ci.com',
};

bool _isAndroidWebViewUrlAllowed(String rawUrl, {String? extraLanHost}) {
  final uri = Uri.tryParse(rawUrl);
  final host = uri?.host.toLowerCase();
  if (host == null || host.isEmpty) return false;
  for (final allowed in _androidWebViewAllowedHosts) {
    if (host == allowed || host.endsWith('.$allowed')) return true;
  }
  final lan = extraLanHost?.split(':').first.trim().toLowerCase();
  if (lan != null && lan.isNotEmpty && host == lan) return true;
  return host == '127.0.0.1' || host.startsWith('192.168.');
}

bool _shouldInjectFhdSession(Uri uri) {
  if (_shouldInjectMarketTokens(uri)) return false;
  final lower = uri.toString().toLowerCase();
  return lower.startsWith('http://') &&
      (lower.contains('127.0.0.1') ||
          lower.contains('192.168.') ||
          lower.contains('10.') ||
          lower.contains('localhost'));
}

bool isAndroidRegisterCompleteUrl(String rawUrl) {
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

const _androidUserAgent =
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36';

@visibleForTesting
Uri resolveAndroidDesktopWebUriForTest(
  String path, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  return _resolveDesktopUri(path, config: config);
}

@visibleForTesting
Uri resolveAndroidModWebUriForTest(
  String modId, {
  MobileApiConfig config = const MobileApiConfig(),
}) {
  return _resolveModUri(modId, config: config);
}

@visibleForTesting
String buildAndroidTokenInjectScriptForTest({
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
Set<String> androidWebViewAllowedHostsForTest() {
  return Set.unmodifiable(_androidWebViewAllowedHosts);
}

@visibleForTesting
bool isAndroidWebViewUrlAllowedForTest(String rawUrl, {String? extraLanHost}) {
  return _isAndroidWebViewUrlAllowed(rawUrl, extraLanHost: extraLanHost);
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
bool isAndroidRegisterCompleteUrlForTest(String rawUrl) {
  return isAndroidRegisterCompleteUrl(rawUrl);
}

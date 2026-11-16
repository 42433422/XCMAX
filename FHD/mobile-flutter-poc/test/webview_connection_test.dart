import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

void main() {
  for (final host in ['10.0.0.9', '172.20.1.4']) {
    testWidgets('selected LAN $host keeps session and guarded redirects',
        (tester) async {
      final platform = _Platform();
      WebViewPlatform.instance = platform;
      final api = MobileApiClient(
          sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
              .copyWith(
                  serverMode: 'lan',
                  fhdHost: '$host:5011',
                  localBaseUrl: 'http://$host:5011/',
                  accessToken: 'account-a')));
      await tester.pumpWidget(MaterialApp(
          home: DesktopToolWebViewScreen(
              title: '工作台',
              path: '/workflow-employee-space',
              api: api,
              externalUrlLauncher: (_) async => true)));
      await tester.pump();
      final controller = platform.controller!;
      expect(controller.request!.uri.host, host);
      expect(controller.request!.uri.path, '/workflow-employee-space');
      expect(controller.request!.headers['Authorization'], 'Bearer account-a');
      expect(platform.cookie!.domain, host);
      expect(platform.cookie!.value, 'account-a');
      expect(
          await platform.delegate!.navigate!(NavigationRequest(
              url: 'http://$host:5011/customers', isMainFrame: true)),
          NavigationDecision.navigate);
      for (final url in [
        'http://foo10.evil.com/',
        'http://attacker.localhost.evil.com/',
        'https://example.com/?next=xiu-ci.com',
        'http://$host:5012/'
      ]) {
        expect(
            await platform.delegate!
                .navigate!(NavigationRequest(url: url, isMainFrame: true)),
            NavigationDecision.prevent);
      }
      controller.scripts.clear();
      controller.current = 'https://example.com/?next=xiu-ci.com';
      platform.delegate!.finished!(controller.current!);
      await tester.pump();
      expect(controller.scripts, isEmpty);
      controller.current = controller.request!.uri.toString();
      platform.delegate!.finished!(controller.current!);
      await tester.pump();
      expect(controller.scripts.single,
          contains("location.origin !== 'http://$host:5011'"));
      expect(controller.scripts.single, contains('session_id=account-a'));
      await api.clearActiveAuth();
      await tester.pump();
      expect(find.text('账号已切换，请重新打开页面'), findsOneWidget);
      expect(find.byKey(const ValueKey('mock-webview')), findsNothing);
    });
  }
  testWidgets(
      'account switch while session loads prevents late credential injection',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    final api = _DelayedSessionApi();
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '客户', path: '/customers', api: api)));
    await tester.pump();
    platform.controller!.scripts.clear();
    api.pending = Completer<MobileSessionData>();
    platform.delegate!.finished!(platform.controller!.current!);
    await tester.pump();
    api.beginLoginAttempt();
    api.pending!.complete(
        MobileSessionData.empty.copyWith(accessToken: 'new-account-secret'));
    await tester.pump();
    expect(platform.controller!.scripts, isEmpty);
  });
  testWidgets('market auth is prepared before the first business request',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '市场',
            path: 'https://xiu-ci.com/market',
            api: MobileApiClient(
                sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                    .copyWith(marketAccessToken: 'market-b'))))));
    await tester.pump();
    expect(platform.loads, 1);
    expect(platform.controller!.scripts.single,
        contains("localStorage.setItem('modstore_token','market-b')"));
    expect(platform.controller!.scripts.single,
        contains("localStorage.removeItem('modstore_refresh_token')"));
    expect(platform.authPreparedBeforeRequest, isTrue);
  });
  testWidgets('untrusted bootstrap origin fails closed before business request',
      (tester) async {
    final platform = _Platform()..scriptResult = false;
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '客户',
            path: '/customers',
            api: MobileApiClient(
                sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                    .copyWith(accessToken: 'account-b'))))));
    await tester.pump();
    expect(platform.loads, 0);
    expect(find.text('登录状态同步失败，请重试'), findsOneWidget);
  });
  testWidgets('public registration clears only scoped auth before opening',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '注册',
            path: '/login/register',
            api: MobileApiClient(sessionStore: MemoryMobileSessionStore()))));
    await tester.pump();
    expect(platform.loads, 1);
    expect(platform.controller!.request!.headers, isEmpty);
    expect(platform.cookie!.value, isEmpty);
    expect(platform.controller!.scripts.single,
        contains("localStorage.removeItem('xcagi_stability_refresh')"));
    expect(platform.controller!.scripts.single,
        isNot(contains('localStorage.clear')));
    expect(
        await platform.delegate!.navigate!(const NavigationRequest(
            url: 'https://xiu-ci.com/fhd-api/customers', isMainFrame: true)),
        NavigationDecision.prevent);
  });
  testWidgets('logged out cannot open protected page or reuse web cookies',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '客户',
            path: '/customers',
            api: MobileApiClient(sessionStore: MemoryMobileSessionStore()))));
    await tester.pump();
    expect(platform.loads, 0);
    expect(find.text('重试'), findsOneWidget);
  });
  testWidgets('selected backend change removes the old web page',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    final api = MobileApiClient(
        sessionStore: MemoryMobileSessionStore(MobileSessionData.empty.copyWith(
            accessToken: 'account-a',
            serverMode: 'lan',
            fhdHost: '10.0.0.9:5011',
            localBaseUrl: 'http://10.0.0.9:5011/')));
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '客户', path: '/customers', api: api)));
    await tester.pump();
    await api.saveLocalSettings(serverMode: 'cloud');
    await tester.pump();
    expect(find.text('连接已切换，请重新打开页面'), findsOneWidget);
    expect(find.byKey(const ValueKey('mock-webview')), findsNothing);
  });
  testWidgets('failed page offers retry on the selected backend',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '客户',
            path: '/customers',
            api: MobileApiClient(
                sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                    .copyWith(accessToken: 'account-a'))))));
    await tester.pump();
    platform.delegate!.error!(const WebResourceError(
        errorCode: -1, description: 'offline', isForMainFrame: true));
    await tester.pump();
    expect(find.text('重试'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pump();
    expect(platform.loads, 2);
  });
}

class _Platform extends WebViewPlatform {
  _Controller? controller;
  _Delegate? delegate;
  WebViewCookie? cookie;
  int loads = 0;
  bool scriptResult = true;
  bool authPreparedBeforeRequest = false;
  @override
  PlatformWebViewController createPlatformWebViewController(
          PlatformWebViewControllerCreationParams params) =>
      controller = _Controller(params, this);
  @override
  PlatformNavigationDelegate createPlatformNavigationDelegate(
          PlatformNavigationDelegateCreationParams params) =>
      delegate = _Delegate(params);
  @override
  PlatformWebViewCookieManager createPlatformCookieManager(
          PlatformWebViewCookieManagerCreationParams params) =>
      _Cookies(params, this);
  @override
  PlatformWebViewWidget createPlatformWebViewWidget(
          PlatformWebViewWidgetCreationParams params) =>
      _WebWidget(params);
}

class _Controller extends PlatformWebViewController {
  _Controller(super.params, this.owner) : super.implementation();
  final _Platform owner;
  LoadRequestParams? request;
  String? current;
  final scripts = <String>[];
  @override
  Future<void> setJavaScriptMode(JavaScriptMode mode) async {}
  @override
  Future<void> setUserAgent(String? userAgent) async {}
  @override
  Future<void> setPlatformNavigationDelegate(
      PlatformNavigationDelegate handler) async {}
  @override
  Future<void> loadRequest(LoadRequestParams params) async {
    request = params;
    current = params.uri.toString();
    owner.authPreparedBeforeRequest = scripts.isNotEmpty;
    owner.loads++;
  }

  @override
  Future<void> loadHtmlString(String html, {String? baseUrl}) async {
    current = baseUrl;
    owner.delegate!.finished!(baseUrl!);
  }

  @override
  Future<Object> runJavaScriptReturningResult(String script) async {
    scripts.add(script);
    return owner.scriptResult;
  }

  @override
  Future<String?> currentUrl() async => current;
  @override
  Future<void> runJavaScript(String script) async {
    scripts.add(script);
  }
}

class _Delegate extends PlatformNavigationDelegate {
  _Delegate(super.params) : super.implementation();
  NavigationRequestCallback? navigate;
  PageEventCallback? finished;
  WebResourceErrorCallback? error;
  @override
  Future<void> setOnNavigationRequest(
      NavigationRequestCallback callback) async {
    navigate = callback;
  }

  @override
  Future<void> setOnPageFinished(PageEventCallback callback) async {
    finished = callback;
  }

  @override
  Future<void> setOnWebResourceError(WebResourceErrorCallback callback) async {
    error = callback;
  }
}

class _Cookies extends PlatformWebViewCookieManager {
  _Cookies(super.params, this.owner) : super.implementation();
  final _Platform owner;
  @override
  Future<void> setCookie(WebViewCookie cookie) async {
    owner.cookie = cookie;
  }
}

class _WebWidget extends PlatformWebViewWidget {
  _WebWidget(super.params) : super.implementation();
  @override
  Widget build(BuildContext context) =>
      const SizedBox(key: ValueKey('mock-webview'));
}

class _DelayedSessionApi extends MobileApiClient {
  _DelayedSessionApi()
      : super(
            sessionStore: MemoryMobileSessionStore(
                MobileSessionData.empty.copyWith(accessToken: 'account-a')));
  Completer<MobileSessionData>? pending;
  @override
  Future<MobileSessionData> loadSession({bool forceReload = false}) =>
      pending?.future ?? super.loadSession(forceReload: forceReload);
}

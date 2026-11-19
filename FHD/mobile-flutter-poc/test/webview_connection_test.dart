import 'dart:async';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
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
  testWidgets('retired registration cannot bypass WebView authentication',
      (tester) async {
    final platform = _Platform();
    WebViewPlatform.instance = platform;
    await tester.pumpWidget(MaterialApp(
        home: DesktopToolWebViewScreen(
            title: '注册',
            path: '/login/register',
            api: MobileApiClient(sessionStore: MemoryMobileSessionStore()))));
    await tester.pump();
    expect(platform.loads, 0);
    expect(platform.controller, isNull);
    expect(platform.cookie, isNull);
    expect(find.text('无法打开页面，请检查登录与当前连接后重试'), findsOneWidget);
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
  testWidgets(
      'Android chooser preserves accept types, multiple files and URI paths',
      (tester) async {
    final platform = await _showFileChooser(tester, filePicker: ({
      required acceptedTypeGroups,
      required multiple,
    }) async {
      expect(multiple, isTrue);
      expect(acceptedTypeGroups.single.extensions, ['xlsx']);
      expect(acceptedTypeGroups.single.mimeTypes, ['text/csv', 'image/*']);
      return [XFile('/cache/客户 数据.xlsx'), XFile('content://documents/report')];
    });
    final selected = await platform.selectFiles!(const FileSelectorParams(
        isCaptureEnabled: false,
        acceptTypes: ['.xlsx, text/csv', 'image/*'],
        mode: FileSelectorMode.openMultiple));
    expect(selected, [
      Uri.file('/cache/客户 数据.xlsx').toString(),
      'content://documents/report'
    ]);
  });
  testWidgets(
      'Android chooser cancellation and picker failure return empty selections',
      (tester) async {
    var calls = 0;
    final platform = await _showFileChooser(tester, filePicker: ({
      required acceptedTypeGroups,
      required multiple,
    }) async {
      expect(multiple, isFalse);
      expect(acceptedTypeGroups, isEmpty);
      if (++calls == 2) throw StateError('Picker unavailable');
      return [];
    });
    expect(await platform.selectFiles!(_singleFile), isEmpty);
    expect(await platform.selectFiles!(_singleFile), isEmpty);
    expect(await platform.selectFiles!(_singleFile), isEmpty);
    expect(calls, 3);
  });
  testWidgets(
      'Android chooser rejects untrusted pages before opening native picker',
      (tester) async {
    var calls = 0;
    final platform = await _showFileChooser(tester, filePicker: ({
      required acceptedTypeGroups,
      required multiple,
    }) async {
      calls++;
      return [XFile('/cache/report.csv')];
    });
    for (final url in [
      'https://example.com/',
      'https://xiu-ci.com/market',
      'https://xiu-ci.com/fhd-api-other/'
    ]) {
      platform.current = url;
      expect(await platform.selectFiles!(_singleFile), isEmpty);
    }
    expect(calls, 0);
  });
  for (final change in ['account', 'backend', 'page', 'refresh', 'unmount']) {
    testWidgets('Android chooser discards selection after $change changes',
        (tester) async {
      final api = _chooserApi();
      addTearDown(api.dispose);
      final pending = Completer<List<XFile>>();
      var calls = 0;
      final platform = await _showFileChooser(tester, api: api, filePicker: ({
        required acceptedTypeGroups,
        required multiple,
      }) {
        calls++;
        return pending.future;
      });
      final selection = platform.selectFiles!(_singleFile);
      await tester.pump();
      expect(calls, 1);
      expect(await platform.selectFiles!(_singleFile), isEmpty);
      switch (change) {
        case 'account':
          api.beginLoginAttempt();
        case 'backend':
          await api.saveSession((await api.loadSession()).copyWith(
              serverMode: 'lan',
              fhdHost: '10.0.0.8:5000',
              localBaseUrl: 'http://10.0.0.8:5000/'));
        case 'page':
          platform.current = 'https://xiu-ci.com/fhd-api/customers';
        case 'refresh':
          await tester.tap(find.byTooltip('刷新'));
          await tester.pump();
        case 'unmount':
          await tester.pumpWidget(const SizedBox());
      }
      pending.complete([XFile('/cache/private.csv')]);
      expect(await selection, isEmpty);
    });
  }
}

class _Platform extends WebViewPlatform {
  _Platform({this.android = false});
  final bool android;
  _Controller? controller;
  _Delegate? delegate;
  WebViewCookie? cookie;
  int loads = 0;
  bool scriptResult = true;
  bool authPreparedBeforeRequest = false;
  @override
  PlatformWebViewController createPlatformWebViewController(
          PlatformWebViewControllerCreationParams params) =>
      controller = android
          ? _AndroidController(params, this)
          : _Controller(params, this);
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

const _singleFile = FileSelectorParams(
    isCaptureEnabled: false, acceptTypes: ['*/*'], mode: FileSelectorMode.open);

MobileApiClient _chooserApi() => MobileApiClient(
    sessionStore: MemoryMobileSessionStore(
        MobileSessionData.empty.copyWith(accessToken: 'account-a')));

Future<_AndroidController> _showFileChooser(
  WidgetTester tester, {
  required MobileWebFilePicker filePicker,
  MobileApiClient? api,
}) async {
  final client = api ?? _chooserApi();
  if (api == null) addTearDown(client.dispose);
  final platform = _Platform(android: true);
  WebViewPlatform.instance = platform;
  await tester.pumpWidget(MaterialApp(
      home: DesktopToolWebViewScreen(
          title: '数据对接',
          path: '/data-integration',
          api: client,
          filePicker: filePicker)));
  await tester.pump();
  return platform.controller! as _AndroidController;
}

class _AndroidController extends _Controller
    implements AndroidWebViewController {
  _AndroidController(super.params, super.owner);
  Future<List<String>> Function(FileSelectorParams)? selectFiles;
  @override
  Future<void> setOnShowFileSelector(
      Future<List<String>> Function(FileSelectorParams)? callback) async {
    selectFiles = callback;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

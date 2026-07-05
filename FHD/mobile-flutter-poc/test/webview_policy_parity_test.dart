import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

void main() {
  test('WebView allowed hosts mirror Android WebViewUrlPolicy', () {
    expect(
      androidWebViewAllowedHostsForTest(),
      _androidWebViewAllowedHosts(),
      reason: 'Flutter WebView host allowlist must mirror Android.',
    );
  });

  test('WebView URL allow decision follows Android policy branches', () {
    expect(isAndroidWebViewUrlAllowedForTest('https://xiu-ci.com/a'), isTrue);
    expect(
      isAndroidWebViewUrlAllowedForTest('https://market.xiu-ci.com/a'),
      isTrue,
    );
    expect(isAndroidWebViewUrlAllowedForTest('http://127.0.0.1:5100'), isTrue);
    expect(
        isAndroidWebViewUrlAllowedForTest('http://192.168.1.8:5100'), isTrue);
    expect(
      isAndroidWebViewUrlAllowedForTest(
        'http://10.0.0.9:5100',
        extraLanHost: '10.0.0.9:5100',
      ),
      isTrue,
    );
    expect(isAndroidWebViewUrlAllowedForTest('http://10.0.0.9:5100'), isFalse);
    expect(isAndroidWebViewUrlAllowedForTest('https://example.com'), isFalse);
  });

  test('Web token injection predicates follow Android WebViewTokenScript', () {
    expect(
      shouldInjectMarketTokensForTest('https://xiu-ci.com/market'),
      isTrue,
    );
    expect(
      shouldInjectMarketTokensForTest('https://example.com/?next=xiu-ci.com'),
      isTrue,
      reason: 'Android checks the whole URL string for xiu-ci.com.',
    );
    expect(
      shouldInjectMarketTokensForTest('https://example.com/market'),
      isFalse,
    );

    expect(
      shouldInjectFhdSessionForTest('http://127.0.0.1:5100/mod/a'),
      isTrue,
    );
    expect(
      shouldInjectFhdSessionForTest('http://192.168.1.8:5100/mod/a'),
      isTrue,
    );
    expect(
      shouldInjectFhdSessionForTest('http://10.0.0.9:5100/mod/a'),
      isTrue,
    );
    expect(
      shouldInjectFhdSessionForTest('http://localhost:5100/mod/a'),
      isTrue,
    );
    expect(
      shouldInjectFhdSessionForTest('https://127.0.0.1:5100/mod/a'),
      isFalse,
    );
    expect(
      shouldInjectFhdSessionForTest('http://xiu-ci.com/mod/a'),
      isFalse,
      reason: 'Android market token predicate suppresses FHD cookie injection.',
    );
  });
}

Set<String> _androidWebViewAllowedHosts() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/feature/web/WebViewUrlPolicy.kt',
  ).readAsStringSync();
  final block = RegExp(
    r'allowedHosts\s*=\s*setOf\(([\s\S]*?)\)',
  ).firstMatch(source);
  if (block == null) {
    throw StateError('Android WebViewUrlPolicy allowedHosts not found');
  }
  return RegExp(
    r'"([^"]+)"',
  ).allMatches(block.group(1)!).map((match) => match.group(1)!).toSet();
}

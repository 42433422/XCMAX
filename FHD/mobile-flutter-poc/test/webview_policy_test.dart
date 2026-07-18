import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

void main() {
  test('WebView allowed hosts match the Flutter security contract', () {
    expect(mobileWebViewAllowedHostsForTest(), {
      'xiu-ci.com',
      'www.xiu-ci.com',
    });
  });

  test('WebView URL allow decision follows the mobile policy branches', () {
    expect(isMobileWebViewUrlAllowedForTest('https://xiu-ci.com/a'), isTrue);
    expect(
      isMobileWebViewUrlAllowedForTest('https://market.xiu-ci.com/a'),
      isTrue,
    );
    expect(isMobileWebViewUrlAllowedForTest('http://127.0.0.1:5100'), isTrue);
    expect(isMobileWebViewUrlAllowedForTest('http://192.168.1.8:5100'), isTrue);
    expect(
      isMobileWebViewUrlAllowedForTest(
        'http://10.0.0.9:5100',
        extraLanHost: '10.0.0.9:5100',
      ),
      isTrue,
    );
    expect(isMobileWebViewUrlAllowedForTest('http://10.0.0.9:5100'), isFalse);
    expect(isMobileWebViewUrlAllowedForTest('https://example.com'), isFalse);
  });

  test('Web token injection predicates follow the Flutter contract', () {
    expect(
      shouldInjectMarketTokensForTest('https://xiu-ci.com/market'),
      isTrue,
    );
    expect(
      shouldInjectMarketTokensForTest('https://example.com/?next=xiu-ci.com'),
      isTrue,
      reason: 'The policy checks the whole URL string for xiu-ci.com.',
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
    expect(shouldInjectFhdSessionForTest('http://10.0.0.9:5100/mod/a'), isTrue);
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
      reason: 'The market token predicate suppresses FHD cookie injection.',
    );
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/legal/legal_consent_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  testWidgets('first-run legal labels open the configured HTTPS document', (
    tester,
  ) async {
    final opened = <Uri>[];
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1000);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: LegalConsentScreen(
          termsUrl: 'https://xiu-ci.com/privacy.html',
          privacyUrl: 'https://xiu-ci.com/privacy.html',
          openExternalUrl: (uri) async {
            opened.add(uri);
            return true;
          },
        ),
      ),
    );

    await tester.tap(find.text('《用户协议》'));
    await tester.pump();
    await tester.tap(find.text('《隐私政策》'));
    await tester.pump();

    expect(opened, [
      Uri.parse('https://xiu-ci.com/privacy.html'),
      Uri.parse('https://xiu-ci.com/privacy.html'),
    ]);
  });

  testWidgets('first-run legal screen rejects cleartext policy URLs', (
    tester,
  ) async {
    var calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: LegalConsentScreen(
          termsUrl: 'http://example.com/terms',
          openExternalUrl: (_) async {
            calls += 1;
            return true;
          },
        ),
      ),
    );

    await tester.tap(find.text('《用户协议》'));
    await tester.pump();

    expect(calls, 0);
    expect(find.text('协议地址不可用，请稍后重试'), findsOneWidget);
  });
}

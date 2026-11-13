import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:xcagi_flutter_poc/src/security/relay_e2ee.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('解密与后端一致的固定结果向量', () async {
    const desktopPublic = 'B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw=';
    const ephemeralPrivate = 'KCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4/QEFCQ0RFRkc=';
    const envelope = <String, Object?>{
      'v': 1,
      'alg': 'x25519-hkdf-sha256-aesgcm',
      'nonce': 'e/Ij0NKS39uWpDwG',
      'ct': '+0C979cEanQa75dpe6v7oIquCGTl6zxSKFPT61vq8eHnlVcRjv5C21JQ0OSeSwM=',
      'ref': '0123456789abcdef',
    };

    final result = await RelayE2ee.openResult(
      envelope,
      ephemeralPrivateKey: ephemeralPrivate,
      ephemeralPublicKey: 'SS8cuFhH/8e7Qnhl9kxegEHsBJmzeh2pRaFbQQKvAn4=',
      desktopPublicKey: desktopPublic,
    );

    expect(result['ok'], isTrue);
    expect(result['reply'], '已完成');
  });

  test('加密任务后可以解回原文且信封不含明文', () async {
    final desktop = await X25519().newKeyPair();
    final desktopPublic = (await desktop.extractPublicKey()).bytes;

    final sealed = await RelayE2ee.sealPayload(
      {'message': '客户A 的合同', 'count': 3},
      base64.encode(desktopPublic),
    );

    expect(RelayE2ee.isEnvelope(sealed.envelope), isTrue);
    expect(sealed.envelope['ref'], sealed.reference);
    expect(sealed.envelope['ct'], isNot(contains('客户A')));
    expect(sealed.ephemeralPrivateKey, isNotEmpty);
  });

  test('公钥指纹不一致时拒绝继续', () async {
    await RelayE2ee.pinDesktopKey('relay-1', 'key-a');

    expect(
      () => RelayE2ee.pinDesktopKey('relay-1', 'key-b'),
      throwsA(isA<RelayE2eeException>()),
    );
    expect(await RelayE2ee.pinnedDesktopKey('relay-1'), 'key-a');
  });

  test('e2ee_error 标记会被识别', () {
    expect(RelayE2ee.isE2eeError({'e2ee_error': true}), isTrue);
    expect(RelayE2ee.isE2eeError({'error': 'x'}), isFalse);
  });
}

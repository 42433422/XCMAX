import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/widgets/app_avatar.dart';

void main() {
  test('avatar decode targets are bounded and quantized by physical size', () {
    expect(avatarDecodeSize(36, 2), 128);
    expect(avatarDecodeSize(40, 3), 128);
    expect(avatarDecodeSize(180, 3), 512);
    expect(avatarDecodeSize(double.infinity, 2), 64);
    expect(avatarDecodeSize(0, 1), 64);
  });

  test('AppAvatar resolves local file sources for mobile avatars', () {
    final provider = appAvatarImageProviderForSource('/tmp/xcagi-avatar.png');

    expect(provider, isA<FileImage>());
    expect((provider as FileImage).file.path, '/tmp/xcagi-avatar.png');
  });

  test('AppAvatar keeps http avatars on NetworkImage', () {
    final provider = appAvatarImageProviderForSource(
      'https://xiu-ci.com/avatar.png',
    );

    expect(provider, isA<NetworkImage>());
    expect((provider as NetworkImage).url, 'https://xiu-ci.com/avatar.png');
  });

  test('AppAvatar reads Android content uri through platform provider', () {
    final provider = appAvatarImageProviderForSource(
      'content://com.android.fileexplorer.myprovider/avatar.jpg',
    );

    expect(provider, isA<AndroidContentUriImageProvider>());
    expect(
      (provider as AndroidContentUriImageProvider).uri,
      'content://com.android.fileexplorer.myprovider/avatar.jpg',
    );
  });
}

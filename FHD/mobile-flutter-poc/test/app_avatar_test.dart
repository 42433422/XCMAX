import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/widgets/app_avatar.dart';

void main() {
  test('AppAvatar resolves local file sources like Android local avatar', () {
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

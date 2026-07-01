import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../policy/avatar_policy.dart';
import '../theme/app_theme.dart';

class AppAvatar extends StatelessWidget {
  const AppAvatar({
    super.key,
    this.imageSource,
    required this.fallback,
    required this.size,
    required this.borderRadius,
    this.contentDescription,
  });

  final String? imageSource;
  final AppAvatarFallback fallback;
  final double size;
  final BorderRadius borderRadius;
  final String? contentDescription;

  @override
  Widget build(BuildContext context) {
    final source = imageSource?.trim();
    final effectiveSource = source == null || source.isEmpty ? null : source;

    return Semantics(
      label: contentDescription,
      image: true,
      child: ClipRRect(
        borderRadius: borderRadius,
        child: SizedBox.square(
          dimension: size,
          child: effectiveSource == null
              ? _fallbackImage()
              : _sourceImage(effectiveSource),
        ),
      ),
    );
  }

  Widget _sourceImage(String source) {
    final provider = appAvatarImageProviderForSource(source);
    if (provider == null) return _fallbackImage();
    return Image(
      image: provider,
      fit: BoxFit.cover,
      width: size,
      height: size,
      errorBuilder: (_, __, ___) => _fallbackImage(),
      loadingBuilder: (context, child, loadingProgress) {
        if (loadingProgress == null) return child;
        return _fallbackImage();
      },
    );
  }

  Widget _fallbackImage() {
    return Image.asset(
      fallback.assetPath,
      fit: BoxFit.cover,
      width: size,
      height: size,
    );
  }
}

ImageProvider<Object>? appAvatarImageProviderForSource(String source) {
  final text = source.trim();
  if (text.isEmpty) return null;
  final uri = Uri.tryParse(text);
  final scheme = uri?.scheme.toLowerCase() ?? '';
  if (scheme == 'http' || scheme == 'https') return NetworkImage(text);
  if (scheme == 'content') return AndroidContentUriImageProvider(text);
  if (scheme == 'file' && uri != null) return FileImage(File.fromUri(uri));
  return FileImage(File(text));
}

class AndroidContentUriImageProvider
    extends ImageProvider<AndroidContentUriImageProvider> {
  const AndroidContentUriImageProvider(
    this.uri, {
    this.channel = const MethodChannel('xcagi/content_uri'),
  });

  final String uri;
  final MethodChannel channel;

  @override
  Future<AndroidContentUriImageProvider> obtainKey(
    ImageConfiguration configuration,
  ) {
    return SynchronousFuture<AndroidContentUriImageProvider>(this);
  }

  @override
  ImageStreamCompleter loadImage(
    AndroidContentUriImageProvider key,
    ImageDecoderCallback decode,
  ) {
    return MultiFrameImageStreamCompleter(
      codec: _loadAsync(key, decode),
      scale: 1,
      debugLabel: key.uri,
      informationCollector: () => [
        DiagnosticsProperty<String>('Content URI', key.uri),
      ],
    );
  }

  Future<ui.Codec> _loadAsync(
    AndroidContentUriImageProvider key,
    ImageDecoderCallback decode,
  ) async {
    final bytes = await key.channel.invokeMethod<Uint8List>(
      'readBytes',
      {'uri': key.uri},
    );
    if (bytes == null || bytes.isEmpty) {
      throw StateError('Empty content uri image: ${key.uri}');
    }
    final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
    return decode(buffer);
  }

  @override
  bool operator ==(Object other) {
    return other is AndroidContentUriImageProvider && other.uri == uri;
  }

  @override
  int get hashCode => uri.hashCode;
}

class UnreadBadge extends StatelessWidget {
  const UnreadBadge({super.key, required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    if (count <= 0) return const SizedBox.shrink();

    final colors = AppTheme.colors(context);
    final label = count > 99 ? '99+' : '$count';
    final badgeSize = count > 99 ? 25.0 : 21.0;

    return Container(
      width: badgeSize,
      height: badgeSize,
      decoration: BoxDecoration(
        color: colors.danger,
        shape: BoxShape.circle,
      ),
      alignment: Alignment.center,
      child: Text(
        label,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 10,
          fontWeight: FontWeight.w800,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

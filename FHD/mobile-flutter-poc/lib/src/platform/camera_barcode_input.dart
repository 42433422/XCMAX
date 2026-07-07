import 'dart:io' show Platform;
import 'dart:ui';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:google_mlkit_barcode_scanning/google_mlkit_barcode_scanning.dart';

InputImage? inputImageFromCameraFrame(
  CameraImage image,
  CameraDescription camera,
) {
  if (!Platform.isAndroid && !Platform.isIOS) return null;

  final rotation = InputImageRotationValue.fromRawValue(
    camera.sensorOrientation,
  );
  if (rotation == null) return null;

  if (Platform.isAndroid) {
    if (image.format.group != ImageFormatGroup.yuv420) return null;
    if (image.planes.length != 3) return null;
    final bytes = _concatenatePlanes(image.planes);
    return InputImage.fromBytes(
      bytes: bytes,
      metadata: InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: rotation,
        format: InputImageFormat.yuv420,
        bytesPerRow: image.planes.first.bytesPerRow,
      ),
    );
  }

  if (image.planes.length != 1) return null;
  final plane = image.planes.first;
  return InputImage.fromBytes(
    bytes: plane.bytes,
    metadata: InputImageMetadata(
      size: Size(image.width.toDouble(), image.height.toDouble()),
      rotation: rotation,
      format: InputImageFormat.bgra8888,
      bytesPerRow: plane.bytesPerRow,
    ),
  );
}

Uint8List _concatenatePlanes(List<Plane> planes) {
  final writer = WriteBuffer();
  for (final plane in planes) {
    writer.putUint8List(plane.bytes);
  }
  return writer.done().buffer.asUint8List();
}

import 'dart:io' show Platform;
import 'dart:math' as math;

import 'package:camera/camera.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_barcode_scanning/google_mlkit_barcode_scanning.dart';

InputImage? inputImageFromCameraFrame(
  CameraImage image,
  CameraController controller,
) {
  if (!Platform.isAndroid && !Platform.isIOS) return null;

  final rotation = _rotationFromController(controller);
  if (rotation == null) return null;

  if (Platform.isAndroid) {
    if (image.format.group != ImageFormatGroup.yuv420 ||
        image.planes.length != 3) {
      return null;
    }
    final nv21 = _yuv420ToNv21(image);
    if (nv21 == null) return null;
    return InputImage.fromBytes(
      bytes: nv21,
      metadata: InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: rotation,
        format: InputImageFormat.nv21,
        bytesPerRow: image.width,
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

InputImageRotation? _rotationFromController(CameraController controller) {
  final sensorOrientation = controller.description.sensorOrientation;
  if (Platform.isIOS) {
    return InputImageRotationValue.fromRawValue(sensorOrientation);
  }

  var rotation = switch (controller.value.deviceOrientation) {
    DeviceOrientation.portraitUp => sensorOrientation,
    DeviceOrientation.landscapeLeft => sensorOrientation + 90,
    DeviceOrientation.portraitDown => sensorOrientation + 180,
    DeviceOrientation.landscapeRight => sensorOrientation + 270,
  };
  rotation = rotation % 360;
  return InputImageRotationValue.fromRawValue(rotation);
}

Uint8List? _yuv420ToNv21(CameraImage image) {
  final width = image.width;
  final height = image.height;
  final yPlane = image.planes[0];
  final uPlane = image.planes[1];
  final vPlane = image.planes[2];

  final nv21 = Uint8List(width * height + (width * height) ~/ 2);
  var index = 0;

  if (yPlane.bytesPerRow == width) {
    nv21.setRange(0, width * height, yPlane.bytes);
    index = width * height;
  } else {
    for (var row = 0; row < height; row++) {
      final rowStart = row * yPlane.bytesPerRow;
      nv21.setRange(index, index + width, yPlane.bytes, rowStart);
      index += width;
    }
  }

  final uvRowStride = uPlane.bytesPerRow;
  final uvPixelStride = uPlane.bytesPerPixel ?? 1;
  final uvWidth = math.max(1, width ~/ 2);
  final uvHeight = math.max(1, height ~/ 2);

  for (var row = 0; row < uvHeight; row++) {
    for (var col = 0; col < uvWidth; col++) {
      final uvIndex = row * uvRowStride + col * uvPixelStride;
      if (uvIndex >= vPlane.bytes.length || uvIndex >= uPlane.bytes.length) {
        return null;
      }
      nv21[index++] = vPlane.bytes[uvIndex];
      nv21[index++] = uPlane.bytes[uvIndex];
    }
  }

  return nv21;
}

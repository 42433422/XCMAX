import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_api.dart';
import '../../widgets/we_ui.dart';
import 'android_package_update_installer.dart';

Future<void> runAndroidUpdateCheck(
  BuildContext context,
  MobileApiClient api, {
  AndroidPackageUpdateInstaller installer =
      const MethodChannelAndroidPackageUpdateInstaller(),
}) async {
  try {
    final result = await api.checkForUpdate();
    if (!context.mounted) return;
    if (!result.available) {
      _showSnack(context, '已是最新版本');
      return;
    }
    _showUpdatePrompt(context, result, installer);
  } catch (error) {
    if (!context.mounted) return;
    final message = error is MobileApiException
        ? error.message
        : error.toString().replaceFirst('Exception: ', '');
    _showSnack(context, message.isEmpty ? '检查更新失败，请稍后重试' : message);
  }
}

void _showUpdatePrompt(
  BuildContext context,
  MobileUpdateCheckResult result,
  AndroidPackageUpdateInstaller installer,
) {
  showDialog<void>(
    context: context,
    barrierDismissible: !result.force,
    builder: (dialogContext) {
      var downloading = false;
      var statusMessage = '';

      return StatefulBuilder(
        builder: (dialogContext, setDialogState) {
          final content = StringBuffer(result.androidPromptMessage);
          final status = statusMessage.trim();
          if (status.isNotEmpty) {
            content
              ..write('\n')
              ..write(status);
          }

          return WeDialog(
            onDismiss: () {
              if (!result.force && !downloading) {
                Navigator.of(dialogContext).pop();
              }
            },
            title: result.title,
            message: content.toString(),
            confirmText: downloading ? '下载中' : '去更新',
            dismissText: result.force ? null : '稍后',
            onConfirm: () async {
              if (downloading) return;
              if (result.downloadUrl.trim().isEmpty) {
                setDialogState(() {
                  statusMessage = '安装包下载地址为空';
                });
                if (context.mounted) {
                  _showSnack(context, '安装包下载地址为空');
                }
                return;
              }

              setDialogState(() {
                downloading = true;
                statusMessage = '正在连接下载服务器…';
              });
              try {
                final message = await installer.startPackageUpdate(result);
                if (!dialogContext.mounted || !context.mounted) {
                  return;
                }
                final snack = message.isEmpty ? '系统安装器已打开，请确认安装' : message;
                setDialogState(() {
                  downloading = false;
                  statusMessage =
                      snack.contains('系统安装器已打开') ? '系统安装器已打开' : snack;
                });
                _showSnack(context, snack);
                if (!result.force && snack.contains('系统安装器已打开')) {
                  Navigator.of(dialogContext).pop();
                }
              } catch (error) {
                if (!dialogContext.mounted || !context.mounted) {
                  return;
                }
                setDialogState(() {
                  downloading = false;
                  statusMessage = '安装包更新失败';
                });
                _showSnack(context, _installerErrorMessage(error));
              }
            },
          );
        },
      );
    },
  );
}

void _showSnack(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message)),
  );
}

String _installerErrorMessage(Object error) {
  if (error is PlatformException) {
    final message = error.message?.trim();
    if (message != null && message.isNotEmpty) return message;
  }
  final message = error.toString().replaceFirst('Exception: ', '').trim();
  return message.isEmpty ? '安装包更新失败' : message;
}

import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { FlutterPlugin, FlutterPluginBinding, MethodCall, MethodCallHandler, MethodChannel, MethodResult } from '@ohos/flutter_ohos';

export default class XcagiScanPlugin implements FlutterPlugin, MethodCallHandler {
  private channel?: MethodChannel;

  constructor(private readonly context: common.UIAbilityContext) {}

  getUniqueClassName(): string {
    return 'XcagiScanPlugin';
  }

  onAttachedToEngine(binding: FlutterPluginBinding): void {
    this.channel = new MethodChannel(binding.getBinaryMessenger(), 'xcagi/ohos_scanner');
    this.channel.setMethodCallHandler(this);
  }

  onDetachedFromEngine(_binding: FlutterPluginBinding): void {
    this.channel?.setMethodCallHandler(null);
    this.channel = undefined;
  }

  onMethodCall(call: MethodCall, result: MethodResult): void {
    if (call.method !== 'scanQrCode') {
      result.notImplemented();
      return;
    }
    this.scan(result);
  }

  private async scan(result: MethodResult): Promise<void> {
    const options: scanBarcode.ScanOptions = {
      scanTypes: [scanCore.ScanType.QR_CODE],
      enableMultiMode: false,
      enableAlbum: true,
    };
    try {
      const scanned = await scanBarcode.startScanForResult(this.context, options);
      result.success(scanned.originalValue);
    } catch (error) {
      if ((error as BusinessError).code === 1000500002) {
        result.success(null);
        return;
      }
      result.error('scan_failed', '无法打开系统扫码', null);
    }
  }
}

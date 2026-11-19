import { AbilityConstant, Want, common } from '@kit.AbilityKit';
import { uniformTypeDescriptor } from '@kit.ArkData';
import { url } from '@kit.ArkTS';
import { fileIo, fileUri } from '@kit.CoreFileKit';
import { systemShare } from '@kit.ShareKit';
import { FlutterAbility, FlutterEngine, MethodCall, MethodCallHandler, MethodChannel, MethodResult } from '@ohos/flutter_ohos';
import { GeneratedPluginRegistrant } from '../plugins/GeneratedPluginRegistrant';
import XcagiPlatformPlugin from '../plugins/XcagiPlatformPlugin';
import XcagiScanPlugin from '../plugins/XcagiScanPlugin';

class WorkspaceFiles implements MethodCallHandler {
  private readonly context: common.UIAbilityContext;

  constructor(context: common.UIAbilityContext) {
    this.context = context;
  }

  onMethodCall(call: MethodCall, result: MethodResult): void {
    if (call.method !== 'share') {
      result.notImplemented();
      return;
    }
    this.share(call, result);
  }

  private async share(call: MethodCall, result: MethodResult): Promise<void> {
    try {
      const value: ESObject = call.argument('path');
      if (typeof value !== 'string') throw new Error('Invalid export path');
      const path = value as string;
      const root = this.context.cacheDir + '/workspace_exports';
      if (!path.startsWith(root + '/') || /[\0\r\n\\]/.test(path) || !fileIo.lstatSync(root).isDirectory()) {
        throw new Error('File is outside the export directory');
      }
      const parts = path.slice(root.length + 1).split('/');
      let checked = root;
      // lstat refuses symlinks at every level; dot segments must not escape the root.
      for (let index = 0; index < parts.length; index++) {
        const part = parts[index];
        if (part.length === 0 || part === '.' || part === '..') throw new Error('Invalid export path');
        checked += '/' + part;
        const stat = fileIo.lstatSync(checked);
        if (index === parts.length - 1 ? !stat.isFile() : !stat.isDirectory()) {
          throw new Error('Export file is unavailable');
        }
      }
      const name = parts[parts.length - 1];
      const dot = name.lastIndexOf('.');
      const type = dot > 0 && dot < name.length - 1 ?
        uniformTypeDescriptor.getUniformDataTypeByFilenameExtension(name.slice(dot).toLowerCase()) :
        uniformTypeDescriptor.UniformDataType.FILE;
      const data = new systemShare.SharedData({
        utd: type,
        uri: fileUri.getUriFromPath(path),
        title: name,
      });
      await new systemShare.ShareController(data).show(this.context, {
        previewMode: systemShare.SharePreviewMode.DETAIL,
        selectionMode: systemShare.SelectionMode.SINGLE,
      });
      result.success(null);
    } catch (error) {
      result.error('file_export', '无法打开文件分享，请重试', null);
    }
  }
}

export default class EntryAbility extends FlutterAbility implements MethodCallHandler {
  private deepLinkChannel?: MethodChannel;
  private workspaceChannel?: MethodChannel;
  private pendingRoute?: string;
  private routesReady = false;

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    this.pendingRoute = this.routeFromWant(want);
    super.onCreate(want, launchParam);
  }

  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    super.onNewWant(want, launchParam);
    const route = this.routeFromWant(want);
    if (route === undefined) return;
    if (this.deepLinkChannel !== undefined && this.routesReady) {
      this.deepLinkChannel.invokeMethod('onRoute', route);
    } else {
      this.pendingRoute = route;
    }
  }

  configureFlutterEngine(flutterEngine: FlutterEngine): void {
    super.configureFlutterEngine(flutterEngine)
    GeneratedPluginRegistrant.registerWith(flutterEngine)
    flutterEngine.getPlugins()?.add(new XcagiPlatformPlugin())
    flutterEngine.getPlugins()?.add(new XcagiScanPlugin(this.context))
    const messenger = flutterEngine.getDartExecutor().getBinaryMessenger();
    this.workspaceChannel = new MethodChannel(messenger, 'xcagi/workspace_files');
    this.workspaceChannel.setMethodCallHandler(new WorkspaceFiles(this.context));
    this.deepLinkChannel = new MethodChannel(messenger, 'xcagi/deep_link');
    this.deepLinkChannel.setMethodCallHandler(this);
  }

  cleanUpFlutterEngine(flutterEngine: FlutterEngine): void {
    this.workspaceChannel?.setMethodCallHandler(null);
    this.deepLinkChannel?.setMethodCallHandler(null);
    this.workspaceChannel = undefined;
    this.deepLinkChannel = undefined;
    this.routesReady = false;
    this.pendingRoute = undefined;
    super.cleanUpFlutterEngine(flutterEngine);
  }

  onMethodCall(call: MethodCall, result: MethodResult): void {
    if (call.method !== 'getInitialRoute') {
      result.notImplemented();
      return;
    }
    const route = this.pendingRoute;
    this.pendingRoute = undefined;
    // MobileDeepLinkBridge subscribes to onRoute before requesting the initial route.
    this.routesReady = true;
    result.success(route ?? null);
  }

  private routeFromWant(want: Want): string | undefined {
    if (!want.uri) return undefined;
    try {
      const parsed = url.URL.parseURL(want.uri);
      if (parsed.protocol.toLowerCase() !== 'xcagi:' || !parsed.hostname ||
        parsed.username || parsed.password || parsed.port) return undefined;
      return parsed.hostname + parsed.pathname + parsed.search;
    } catch (error) {
      return undefined;
    }
  }
}

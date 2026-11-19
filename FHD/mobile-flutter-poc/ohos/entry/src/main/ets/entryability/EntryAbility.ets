import { FlutterAbility, FlutterEngine } from '@ohos/flutter_ohos';
import { GeneratedPluginRegistrant } from '../plugins/GeneratedPluginRegistrant';
import XcagiPlatformPlugin from '../plugins/XcagiPlatformPlugin';
import XcagiScanPlugin from '../plugins/XcagiScanPlugin';

export default class EntryAbility extends FlutterAbility {
  configureFlutterEngine(flutterEngine: FlutterEngine) {
    super.configureFlutterEngine(flutterEngine)
    GeneratedPluginRegistrant.registerWith(flutterEngine)
    flutterEngine.getPlugins()?.add(new XcagiPlatformPlugin())
    flutterEngine.getPlugins()?.add(new XcagiScanPlugin(this.context))
  }
}

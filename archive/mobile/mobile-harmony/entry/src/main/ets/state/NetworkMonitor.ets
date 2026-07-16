// 网络状态监测(对标 Android core/connectivity/NetworkMonitor.kt)。
//
// 用 @ohos.net.connection 监听默认网络可用/丢失,回调上层更新在线状态,
// 离线时在主界面顶部显示横幅。

import connection from '@ohos.net.connection';

export class NetworkMonitor {
  private static instance: NetworkMonitor | null = null;
  private netCon: connection.NetConnection | null = null;
  private listener: (online: boolean) => void = () => {};
  private started: boolean = false;

  static getInstance(): NetworkMonitor {
    if (NetworkMonitor.instance === null) {
      NetworkMonitor.instance = new NetworkMonitor();
    }
    return NetworkMonitor.instance;
  }

  /** 开始监听;onChange 在网络可用/丢失时回调。 */
  start(onChange: (online: boolean) => void): void {
    this.listener = onChange;
    // 初始态
    try {
      const has: boolean = connection.hasDefaultNetSync();
      this.listener(has);
    } catch (_err) {
      this.listener(true);
    }
    if (this.started) {
      return;
    }
    try {
      this.netCon = connection.createNetConnection();
      this.netCon.on('netAvailable', () => { this.listener(true); });
      this.netCon.on('netLost', () => { this.listener(false); });
      this.netCon.on('netUnavailable', () => { this.listener(false); });
      this.netCon.register((_err: Object) => {});
      this.started = true;
    } catch (err) {
      console.error('NetworkMonitor start failed: ' + ((err as Error).message));
    }
  }

  stop(): void {
    if (this.netCon !== null && this.started) {
      try {
        this.netCon.unregister((_err: Object) => {});
      } catch (_e) {
        // ignore
      }
      this.started = false;
    }
  }
}

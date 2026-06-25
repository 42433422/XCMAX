import connection from '@ohos.net.connection';
import { BusinessError } from '@ohos.base';

// 网络连接监测，对齐 Android core/connectivity/NetworkMonitor.kt：
// 订阅默认网络可用/丢失事件，向监听者推送在线状态（首次必发 + 仅变化时再发 = distinctUntilChanged）。

export type OnlineListener = (online: boolean) => void;

export class ConnectivityMonitor {
  private netCon: connection.NetConnection | null = null;
  private listener: OnlineListener | null = null;
  private online: boolean = true;
  private hasEmitted: boolean = false;
  private started: boolean = false;

  start(listener: OnlineListener): void {
    if (this.started) {
      return;
    }
    this.started = true;
    this.listener = listener;
    const con = connection.createNetConnection();
    this.netCon = con;
    con.on('netAvailable', (_netHandle: connection.NetHandle) => {
      this.emit(true);
    });
    con.on('netLost', (_netHandle: connection.NetHandle) => {
      this.recheck();
    });
    con.on('netUnavailable', () => {
      this.emit(false);
    });
    con.register((_err: BusinessError) => {});
    // 初始态（异步探测，fire-and-forget）。
    this.recheck();
  }

  stop(): void {
    const con = this.netCon;
    if (con !== null) {
      try {
        con.unregister((_err: BusinessError) => {});
      } catch (e) {
      }
      this.netCon = null;
    }
    this.started = false;
    this.listener = null;
    this.hasEmitted = false;
  }

  isOnline(): Promise<boolean> {
    return connection.hasDefaultNet().then(
      (has: boolean) => has,
      () => false
    );
  }

  private recheck(): void {
    connection.hasDefaultNet().then(
      (has: boolean) => {
        this.emit(has);
      },
      () => {
        this.emit(false);
      }
    );
  }

  private emit(online: boolean): void {
    if (this.hasEmitted && online === this.online) {
      return;
    }
    this.hasEmitted = true;
    this.online = online;
    if (this.listener !== null) {
      this.listener(online);
    }
  }
}

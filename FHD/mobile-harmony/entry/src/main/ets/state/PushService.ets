// 推送注册(对标 Android core/push/PushRegistrar + PushKit)。
//
// 用华为 PushKit 取 push token,POST /api/mobile/v1/devices/register 注册到后端。
// 注意:getToken 真正生效需在华为 AGC 控制台配置应用(agconnect-services.json)并真机运行;
// 本环境/未配置时 getToken 会抛错,这里 best-effort 吞掉,不阻断登录。

import { pushService } from '@kit.PushKit';
import { MobileApiClient } from '../api/MobileApiClient';

export class PushService {
  /** 取 push token 并注册到后端;失败不抛出(返回空串)。 */
  static async registerToken(api: MobileApiClient): Promise<string> {
    try {
      const token: string = await pushService.getToken();
      if (token.length >= 8) {
        await api.registerDevice(token, 'harmony');
        return token;
      }
      return '';
    } catch (err) {
      console.warn('PushService.registerToken 失败(需 AGC 配置/真机): ' + ((err as Error).message));
      return '';
    }
  }
}

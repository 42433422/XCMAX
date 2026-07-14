// 生物识别解锁(对标 Android core/security/BiometricGate.kt)。
//
// 用 @ohos.userIAM.userAuth 在开启「生物识别解锁」后,App 恢复登录态时要求
// 指纹/人脸验证。设备不支持或未录入凭据时放行(graceful),避免把用户锁死。

import userAuth from '@ohos.userIAM.userAuth';

const CHALLENGE: Uint8Array = new Uint8Array([0x58, 0x43, 0x41, 0x47, 0x49, 0x31, 0x30, 0x30]);

export class BiometricGate {
  /** 设备是否支持并已录入指纹或人脸。 */
  static isSupported(): boolean {
    if (BiometricGate.statusOk(userAuth.UserAuthType.FINGERPRINT)) {
      return true;
    }
    return BiometricGate.statusOk(userAuth.UserAuthType.FACE);
  }

  private static statusOk(authType: userAuth.UserAuthType): boolean {
    try {
      userAuth.getAvailableStatus(authType, userAuth.AuthTrustLevel.ATL1);
      return true;
    } catch (_err) {
      return false;
    }
  }

  /** 弹出系统生物识别验证;成功 resolve(true)。不支持时放行 resolve(true)。 */
  static authenticate(title: string): Promise<boolean> {
    return new Promise<boolean>((resolve: (ok: boolean) => void) => {
      if (!BiometricGate.isSupported()) {
        resolve(true);
        return;
      }
      try {
        const authParam: userAuth.AuthParam = {
          challenge: CHALLENGE,
          authType: [userAuth.UserAuthType.FINGERPRINT, userAuth.UserAuthType.FACE],
          authTrustLevel: userAuth.AuthTrustLevel.ATL1
        };
        const widgetParam: userAuth.WidgetParam = { title: title };
        const instance: userAuth.UserAuthInstance = userAuth.getUserAuthInstance(authParam, widgetParam);
        instance.on('result', {
          onResult: (result: userAuth.UserAuthResult) => {
            resolve(result.result === userAuth.UserAuthResultCode.SUCCESS);
          }
        });
        instance.start();
      } catch (_err) {
        // 拉起验证失败(不支持/异常):放行
        resolve(true);
      }
    });
  }
}

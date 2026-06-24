import userAuth from '@ohos.userIAM.userAuth';

// 生物识别门，对齐 Android core/security/BiometricGate.kt：
// - canAuthenticate：设备是否可做指纹/PIN 校验；
// - prompt：拉起系统校验，结果经回调（success: boolean）返回。
// 注：真机行为（指纹/PIN 弹窗）需 HarmonyOS 设备；本类仅保证编译与接口契约。

export type AuthCallback = (success: boolean) => void;

const CHALLENGE: Uint8Array = new Uint8Array([0x58, 0x43, 0x41, 0x47, 0x49]); // 'XCAGI'

export class BiometricGate {
  static canAuthenticate(): boolean {
    if (BiometricGate._statusOk(userAuth.UserAuthType.FINGERPRINT)) {
      return true;
    }
    return BiometricGate._statusOk(userAuth.UserAuthType.PIN);
  }

  static prompt(onResult: AuthCallback): void {
    try {
      const authParam: userAuth.AuthParam = {
        challenge: CHALLENGE,
        authType: [userAuth.UserAuthType.FINGERPRINT, userAuth.UserAuthType.PIN],
        authTrustLevel: userAuth.AuthTrustLevel.ATL1
      };
      const widgetParam: userAuth.WidgetParam = { title: '解锁 XCAGI' };
      const auth = userAuth.getUserAuthInstance(authParam, widgetParam);
      auth.on('result', {
        onResult: (result: userAuth.UserAuthResult) => {
          onResult(result.result === userAuth.UserAuthResultCode.SUCCESS);
        }
      });
      auth.start();
    } catch (e) {
      onResult(false);
    }
  }

  private static _statusOk(authType: userAuth.UserAuthType): boolean {
    try {
      userAuth.getAvailableStatus(authType, userAuth.AuthTrustLevel.ATL1);
      return true;
    } catch (e) {
      return false;
    }
  }
}

import Foundation
import LocalAuthentication

/// 生物识别解锁(对标 mobile-harmony `BiometricGate.ets` / Android 生物识别)。
enum BiometricGate {
    /// 设备是否可用面容/触控 ID。
    static var isAvailable: Bool {
        var error: NSError?
        return LAContext().canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
    }

    /// 发起一次解锁;成功返回 true。失败/取消返回 false。
    static func authenticate(reason: String = "解锁修茈企业") async -> Bool {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            return false
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) { success, _ in
                continuation.resume(returning: success)
            }
        }
    }
}

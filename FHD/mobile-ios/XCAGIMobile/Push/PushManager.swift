import SwiftUI
import UIKit
import UserNotifications

/// 一条已收到的通知(对标 Android `NotificationListScreen` 的本地通知存储)。
struct AppNotification: Identifiable {
    let id = UUID()
    var title: String
    var body: String
    var date: Date
}

/// 已收到通知的内存存储。
@MainActor
final class NotificationStore: ObservableObject {
    static let shared = NotificationStore()
    @Published var items: [AppNotification] = []

    func add(title: String, body: String, date: Date = Date()) {
        items.insert(AppNotification(title: title, body: body, date: date), at: 0)
    }
}

/// 推送管理(对标 Android PushRegistrar / 鸿蒙 `PushService`)。
/// 申请授权 → 注册远程通知 → APNs 回调 device token → 上报 `/devices/register`。
@MainActor
final class PushManager: ObservableObject {
    static let shared = PushManager()

    @Published var deviceToken: String?
    @Published var authorized = false

    func refreshStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        authorized = settings.authorizationStatus == .authorized
    }

    func requestAuthorizationAndRegister() async {
        let center = UNUserNotificationCenter.current()
        let granted = (try? await center.requestAuthorization(options: [.alert, .badge, .sound])) ?? false
        authorized = granted
        if granted {
            UIApplication.shared.registerForRemoteNotifications()
        }
    }

    func setToken(_ data: Data) {
        deviceToken = data.map { String(format: "%02x", $0) }.joined()
    }
}

/// UIKit 应用代理:接 APNs token 与前台通知展示。
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        MobilePerformanceMonitor.shared.start()
        return true
    }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in PushManager.shared.setToken(deviceToken) }
    }

    func application(_ application: UIApplication,
                     didFailToRegisterForRemoteNotificationsWithError error: Error) {
        // 模拟器/未配置证书时会进这里 —— 静默忽略,不阻断 App。
    }

    // 前台收到通知:展示横幅 + 记录到通知中心。
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        let content = notification.request.content
        Task { @MainActor in NotificationStore.shared.add(title: content.title, body: content.body) }
        completionHandler([.banner, .sound, .badge])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let content = response.notification.request.content
        Task { @MainActor in NotificationStore.shared.add(title: content.title, body: content.body) }
        completionHandler()
    }
}

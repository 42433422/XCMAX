import BackgroundTasks
import CryptoKit
import Flutter
import LocalAuthentication
import Security
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var deepLinkChannel: FlutterMethodChannel?
  private var pendingDeepLinkRoute: String?

  private static let backgroundSyncTaskId = "com.xcagi.mobile.sync"

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    BGTaskScheduler.shared.register(
      forTaskWithIdentifier: Self.backgroundSyncTaskId,
      using: nil
    ) { task in
      Self.handleBackgroundSyncTask(task as! BGAppRefreshTask)
    }
    if let url = launchOptions?[.url] as? URL {
      pendingDeepLinkRoute = parseDeepLinkRoute(url)
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    registerXcagiChannels(messenger: engineBridge.applicationRegistrar.messenger())
  }

  func handleDeepLink(_ url: URL) {
    guard let route = parseDeepLinkRoute(url) else {
      return
    }
    if let channel = deepLinkChannel {
      channel.invokeMethod("onRoute", arguments: route)
    } else {
      pendingDeepLinkRoute = route
    }
  }

  private func registerXcagiChannels(messenger: FlutterBinaryMessenger) {
    deepLinkChannel = FlutterMethodChannel(
      name: "xcagi/deep_link",
      binaryMessenger: messenger
    )
    deepLinkChannel?.setMethodCallHandler { [weak self] call, result in
      guard call.method == "getInitialRoute" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(self?.consumePendingDeepLinkRoute())
    }

    FlutterMethodChannel(
      name: "xcagi/session_store",
      binaryMessenger: messenger
    ).setMethodCallHandler { [weak self] call, result in
      guard call.method == "sessionFilePath" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(self?.sessionFilePath())
    }

    FlutterMethodChannel(
      name: "xcagi/credential_cipher",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      switch call.method {
      case "encrypt":
        let args = call.arguments as? [String: Any]
        let plain = args?["plain"] as? String ?? ""
        result(Self.encryptCredential(plain))
      case "decrypt":
        let args = call.arguments as? [String: Any]
        let stored = args?["stored"] as? String ?? ""
        result(Self.decryptCredential(stored))
      default:
        result(FlutterMethodNotImplemented)
      }
    }

    FlutterMethodChannel(
      name: "xcagi/biometric",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      switch call.method {
      case "canAuthenticate":
        result(Self.canAuthenticate())
      case "authenticate":
        Self.authenticate(result: result)
      case "finishApp":
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }

    FlutterMethodChannel(
      name: "xcagi/background_work",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "reconcile" else {
        result(FlutterMethodNotImplemented)
        return
      }
      let args = call.arguments as? [String: Any] ?? [:]
      Self.reconcileBackgroundWork(
        loggedIn: args["loggedIn"] as? Bool ?? false,
        autoSync: args["autoSync"] as? Bool ?? false
      )
      result(["platform": "ios", "available": true])
    }

    FlutterMethodChannel(
      name: "xcagi/update_installer",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "startPackageUpdate" else {
        result(FlutterMethodNotImplemented)
        return
      }
      let args = call.arguments as? [String: Any] ?? [:]
      let urlString = (args["downloadUrl"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
      if !urlString.isEmpty, let url = URL(string: urlString) {
        DispatchQueue.main.async {
          UIApplication.shared.open(url)
        }
        result("已跳转 App Store")
      } else {
        result("请通过 App Store 搜索 XCAGI 更新")
      }
    }

    FlutterMethodChannel(
      name: "xcagi/content_uri",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "readBytes" else {
        result(FlutterMethodNotImplemented)
        return
      }
      let args = call.arguments as? [String: Any]
      let uri = args?["uri"] as? String ?? ""
      Self.readBytes(uri: uri, result: result)
    }
  }

  private func consumePendingDeepLinkRoute() -> String? {
    let route = pendingDeepLinkRoute
    pendingDeepLinkRoute = nil
    return route
  }

  private func sessionFilePath() -> String {
    let manager = FileManager.default
    let base = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
      ?? manager.temporaryDirectory
    let directory = base.appendingPathComponent("XCAGI", isDirectory: true)
    try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory.appendingPathComponent("xcagi_session.json").path
  }

  private func parseDeepLinkRoute(_ url: URL) -> String? {
    if url.scheme?.lowercased() == "xcagi" {
      let host = url.host ?? ""
      let path = url.path
      let route = "\(host)\(path)".trimmingCharacters(in: .whitespacesAndNewlines)
      return route.isEmpty ? nil : route
    }
    if url.host?.contains("xiu-ci.com") == true {
      let route = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
      return route.isEmpty ? "chat" : route
    }
    return nil
  }

  private static func canAuthenticate() -> Bool {
    var error: NSError?
    return LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: &error)
  }

  private static func authenticate(result: @escaping FlutterResult) {
    let context = LAContext()
    var error: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
      result(false)
      return
    }
    context.evaluatePolicy(
      .deviceOwnerAuthentication,
      localizedReason: "Authenticate to unlock XCAGI"
    ) { success, _ in
      DispatchQueue.main.async {
        result(success)
      }
    }
  }

  private static func readBytes(uri: String, result: FlutterResult) {
    let text = uri.trimmingCharacters(in: .whitespacesAndNewlines)
    let url = URL(string: text) ?? URL(fileURLWithPath: text)
    do {
      let data = try Data(contentsOf: url)
      result(FlutterStandardTypedData(bytes: data))
    } catch {
      result(
        FlutterError(
          code: "CONTENT_URI_READ_FAILED",
          message: error.localizedDescription,
          details: nil
        )
      )
    }
  }

  // MARK: - Credential Cipher (AES-GCM + Keychain)

  private static let cipherKeychainService = "com.xcagi.credential"
  private static let cipherKeychainAccount = "xcagi-aes-key"

  private static func encryptCredential(_ plain: String) -> String {
    guard !plain.isEmpty else { return "" }
    do {
      let key = try cipherKey()
      let sealed = try AES.GCM.seal(Data(plain.utf8), using: key)
      guard let combined = sealed.combined else { return plain }
      return combined.base64EncodedString()
    } catch {
      return plain
    }
  }

  private static func decryptCredential(_ stored: String) -> String {
    guard !stored.isEmpty else { return "" }
    do {
      let key = try cipherKey()
      guard let combined = Data(base64Encoded: stored) else { return "" }
      let sealed = try AES.GCM.SealedBox(combined: combined)
      let decrypted = try AES.GCM.open(sealed, using: key)
      return String(data: decrypted, encoding: .utf8) ?? ""
    } catch {
      return ""
    }
  }

  private static func cipherKey() throws -> SymmetricKey {
    if let data = loadCipherKeyData() {
      return SymmetricKey(data: data)
    }
    let newKey = SymmetricKey(size: .bits256)
    let keyData = newKey.withUnsafeBytes { Data($0) }
    saveCipherKeyData(keyData)
    return newKey
  }

  private static func loadCipherKeyData() -> Data? {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: cipherKeychainService,
      kSecAttrAccount as String: cipherKeychainAccount,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    guard status == errSecSuccess else { return nil }
    return item as? Data
  }

  private static func saveCipherKeyData(_ data: Data) {
    let attrs: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: cipherKeychainService,
      kSecAttrAccount as String: cipherKeychainAccount,
      kSecValueData as String: data,
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
    ]
    SecItemAdd(attrs as CFDictionary, nil)
  }

  // MARK: - Background Work (BGTaskScheduler)

  private static func reconcileBackgroundWork(loggedIn: Bool, autoSync: Bool) {
    let scheduler = BGTaskScheduler.shared
    if loggedIn && autoSync {
      let request = BGAppRefreshTaskRequest(identifier: backgroundSyncTaskId)
      request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
      try? scheduler.submit(request)
    } else {
      scheduler.cancel(taskRequestWithIdentifier: backgroundSyncTaskId)
    }
  }

  private static func handleBackgroundSyncTask(_ task: BGAppRefreshTask) {
    task.expirationHandler = {
      task.setTaskCompleted(success: false)
    }
    // 后台同步的最小实现：标记完成。
    // 真实同步逻辑由 Flutter 侧通过 MethodChannel 在前台触发，
    // iOS 后台仅维持调度能力声明，确保 autoSync 可用。
    task.setTaskCompleted(success: true)
  }
}
